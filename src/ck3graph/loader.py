"""Neo4j loader.

Connection settings come from the environment (see ``.env.example``). Every
write is an idempotent ``MERGE`` so the same snapshot can be loaded twice, and
snapshots of one run can be loaded in any order (docs/PLAN.md §4): nothing is
ever deleted, and the writes below are **order independent**, which matters
because saves get loaded across separate runs of the tool, not only oldest
first within one.

Order independence means, concretely:

* ``first_seen`` only ever moves earlier and ``last_seen`` only later, so they
  bracket the snapshots a node was actually seen in;
* a tenure that one snapshot saw still open and another saw closed stays
  closed, whichever order they load in;
* ``VASSAL_OF.as_of`` keeps the latest snapshot that observed the link.

Game dates are written as real ``date`` values, never strings: save dates like
``"99.1.1"`` and ``"948.3.25"`` sort the wrong way round as text.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ck3parser.parser import Block, to_date
from ck3parser.titles import TitleRecord, normalize_history

SCHEMA_PATH = Path(__file__).with_name("schema.cypher")


@dataclass
class Neo4jConfig:
    uri: str
    user: str
    password: str
    database: str | None = None

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Neo4jConfig":
        env = os.environ if env is None else env
        try:
            return cls(
                uri=env["NEO4J_URI"],
                user=env["NEO4J_USER"],
                password=env["NEO4J_PASSWORD"],
                database=env.get("NEO4J_DATABASE") or None,
            )
        except KeyError as e:
            raise RuntimeError(f"missing environment variable {e.args[0]} (see .env.example)") from None


def open_session(cfg: Neo4jConfig):
    from neo4j import GraphDatabase  # imported lazily so tests never need the driver

    driver = GraphDatabase.driver(cfg.uri, auth=(cfg.user, cfg.password))
    return _DriverSession(driver, cfg.database)


class _DriverSession:
    """Context manager that owns both the driver and one session."""

    def __init__(self, driver, database):
        self._driver = driver
        self._session = driver.session(database=database) if database else driver.session()

    def run(self, query: str, **params):
        return self._session.run(query, **params)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._session.close()
        self._driver.close()


class DryRunSession:
    """Records statements instead of executing them (tests, ``--dry-run``)."""

    def __init__(self, echo: bool = True):
        self.statements: list[tuple[str, dict[str, Any]]] = []
        self.echo = echo

    def run(self, query: str, **params):
        self.statements.append((query, params))
        if self.echo:
            print(query.strip(), params)
        return None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def schema_statements(path: Path = SCHEMA_PATH) -> list[str]:
    text = "\n".join(line for line in path.read_text().splitlines() if not line.strip().startswith("//"))
    return [s.strip() for s in text.split(";") if s.strip()]


def apply_schema(session, path: Path = SCHEMA_PATH) -> None:
    for stmt in schema_statements(path):
        session.run(stmt)


# ------------------------------------------------------------ pure helpers


def holder_intervals(
    history: Block | list[tuple[str, int | None, str | None]] | None,
    end_date: str | None,
    current_holder: int | None = None,
    holder_since: str | None = None,
) -> list[dict[str, Any]]:
    """Turn a title history into ``[{holder, from, to, open, reason}]``.

    Takes either a raw ``history`` block or the normalised tuples of a
    :class:`~ck3parser.titles.TitleRecord`. An entry with a holder opens a
    tenure and closes the running one; a terminal entry (``type=destroyed``)
    only closes, because its holder names the outgoing ruler.

    The title's own ``holder`` and ``date`` win over the history for the tenure
    in progress, because they disagree in real saves: 6 079 held titles have no
    history at all, and another 341 (all leased-out baronies) changed hands
    without an entry being appended. So ``holder_since`` opens the final tenure
    whenever the history does not already end with ``current_holder``.

    A tenure with no start date is dropped: it cannot be placed in time, and
    ``Title.holder`` still records who holds the title.
    """
    # NB: Block subclasses list, so it must be tested for first.
    if history is None:
        entries: list[tuple[str, int | None, str | None]] = []
    elif isinstance(history, Block):
        entries = normalize_history(history)
    else:
        entries = list(history)

    intervals: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for date, holder, reason in entries:
        if current is not None:
            current["to"] = date
            intervals.append(current)
            current = None
        if holder is not None:
            current = {"holder": holder, "from": date, "to": None, "open": False, "reason": reason}

    if current is not None and current_holder is not None and current["holder"] != current_holder:
        current["to"] = holder_since or end_date  # the current holder took over here
        intervals.append(current)
        current = None
    if current is not None:
        current["to"] = end_date
        current["open"] = True
        intervals.append(current)
    elif current_holder is not None and holder_since is not None:
        intervals.append(
            {"holder": current_holder, "from": holder_since, "to": end_date, "open": True, "reason": None}
        )
    return [iv for iv in intervals if iv["from"] is not None]


def character_props(char_id: int, char: Block) -> dict[str, Any]:
    """Node properties for one character. Game dates become real ``date`` values.

    Save dates are strings like ``"1364.3.10"``, which sort lexicographically:
    ``"99.1.1"`` would land after ``"948.3.25"``. Everything written to the graph
    that is a game date is converted so that ordering and range queries work.
    """
    dead = char.get("dead_data")
    return {
        "id": char_id,
        "first_name": str(char.get("first_name", "")),
        "birth": to_date(char.get("birth")),
        "death": to_date(dead.get("date")) if isinstance(dead, Block) else None,
        "death_reason": str(dead.get("reason")) if isinstance(dead, Block) and dead.get("reason") else None,
        "female": bool(char.get("female", False)),
        "dynasty_house": char.get("dynasty_house"),
    }


# ------------------------------------------------------------ writers


def load_snapshot(session, fp) -> None:
    session.run(
        """
        MERGE (r:Run {run_id: $run_id})
        SET r.random_seed = $seed, r.bookmark_date = $bookmark
        MERGE (s:Snapshot {run_id: $run_id, date: $date})
        SET s.file = $file, s.random_count = $random_count, s.meta_real_date = $real
        MERGE (s)-[:OF]->(r)
        """,
        run_id=fp.run_id, seed=fp.random_seed, bookmark=to_date(fp.bookmark_date), date=to_date(fp.date),
        file=fp.file, random_count=fp.random_count, real=fp.meta_real_date,
    )


def load_title(
    session,
    fp,
    title: TitleRecord,
    intervals: list[dict[str, Any]],
    characters: dict[int, Block],
) -> None:
    session.run(
        """
        MERGE (t:Title {key: $key})
        SET t.name = $name, t.tier = $tier, t.holder = $holder,
            t.first_seen = CASE WHEN t.first_seen IS NULL OR $date < t.first_seen
                                THEN $date ELSE t.first_seen END,
            t.last_seen = CASE WHEN t.last_seen IS NULL OR $date > t.last_seen
                               THEN $date ELSE t.last_seen END
        """,
        key=title.key, name=title.display_name, tier=title.tier, holder=title.holder, date=to_date(fp.date),
    )
    for cid, char in characters.items():
        props = character_props(cid, char)
        session.run(
            """
            MERGE (c:Character {id: $id})
            SET c += $props,
                c.first_seen = CASE WHEN c.first_seen IS NULL OR $date < c.first_seen
                                    THEN $date ELSE c.first_seen END,
                c.last_seen = CASE WHEN c.last_seen IS NULL OR $date > c.last_seen
                                   THEN $date ELSE c.last_seen END
            """,
            id=cid, props=props, date=to_date(fp.date),
        )
        if props["dynasty_house"] is not None:
            session.run(
                "MERGE (h:House {id: $house}) WITH h MATCH (c:Character {id: $id}) MERGE (c)-[:MEMBER_OF]->(h)",
                house=props["dynasty_house"], id=cid,
            )
    for iv in intervals:
        session.run(
            """
            MATCH (t:Title {key: $key})
            MERGE (c:Character {id: $holder})
            MERGE (t)-[r:HELD_BY {from: $from}]->(c)
            WITH r, coalesce(r.open, true) AND $open AS still_open
            SET r.to = CASE
                    WHEN NOT still_open AND $open THEN r.to
                    WHEN still_open AND r.to IS NOT NULL AND r.to > $to THEN r.to
                    ELSE $to END,
                r.open = still_open,
                r.reason = coalesce($reason, r.reason)
            """,
            key=title.key, holder=iv["holder"], **{"from": to_date(iv["from"])},
            to=to_date(iv["to"]), open=iv["open"], reason=iv.get("reason"),
        )


def load_vassal_edge(session, vassal: TitleRecord, liege: TitleRecord, fp, kind: str = "de_facto") -> None:
    """``(:Title)-[:VASSAL_OF {kind, as_of}]->(:Title)`` for one liege link.

    Names and tiers are set on both ends so that a liege reached only through a
    de jure edge is still an identifiable title rather than a bare key. Only
    ``load_title`` sets ``first_seen``/``last_seen``, which mark the titles whose
    history was actually loaded.
    """
    session.run(
        """
        MERGE (v:Title {key: $vassal})
        SET v.name = $vassal_name, v.tier = $vassal_tier
        MERGE (l:Title {key: $liege})
        SET l.name = $liege_name, l.tier = $liege_tier
        MERGE (v)-[r:VASSAL_OF {kind: $kind}]->(l)
        SET r.as_of = CASE WHEN r.as_of IS NULL OR $date > r.as_of THEN $date ELSE r.as_of END
        """,
        vassal=vassal.key, vassal_name=vassal.display_name, vassal_tier=vassal.tier,
        liege=liege.key, liege_name=liege.display_name, liege_tier=liege.tier,
        kind=kind, date=to_date(fp.date),
    )

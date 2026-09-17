"""Neo4j loader.

Connection settings come from the environment (see ``.env.example``). Every
write is an idempotent ``MERGE`` so the same snapshot can be loaded twice, and
snapshots of one run can be loaded oldest to newest (docs/PLAN.md §4): later
snapshots overwrite scalar properties and never delete.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ck3parser.parser import Block
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
) -> list[dict[str, Any]]:
    """Turn a title history into ``[{holder, from, to, open, reason}]``.

    Takes either a raw ``history`` block or the normalised tuples of a
    :class:`~ck3parser.titles.TitleRecord`. An entry with a holder opens a
    tenure and closes the running one; a terminal entry (``type=destroyed``)
    only closes, because its holder names the outgoing ruler. The last open
    tenure closes at ``end_date`` and is marked ``open``. A title with no
    history but a current holder gets one open interval.
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
    if current is not None:
        current["to"] = end_date
        current["open"] = True
        intervals.append(current)
    elif current_holder is not None and not intervals:
        intervals.append({"holder": current_holder, "from": None, "to": end_date, "open": True, "reason": None})
    return intervals


def character_props(char_id: int, char: Block) -> dict[str, Any]:
    dead = char.get("dead_data")
    return {
        "id": char_id,
        "first_name": str(char.get("first_name", "")),
        "birth": char.get("birth"),
        "death": dead.get("date") if isinstance(dead, Block) else None,
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
        run_id=fp.run_id, seed=fp.random_seed, bookmark=fp.bookmark_date, date=fp.date,
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
            t.first_seen = coalesce(t.first_seen, $date), t.last_seen = $date
        """,
        key=title.key, name=title.display_name, tier=title.tier, holder=title.holder, date=fp.date,
    )
    for cid, char in characters.items():
        props = character_props(cid, char)
        session.run(
            """
            MERGE (c:Character {id: $id})
            SET c += $props, c.first_seen = coalesce(c.first_seen, $date), c.last_seen = $date
            """,
            id=cid, props=props, date=fp.date,
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
            SET r.to = $to, r.open = $open, r.reason = $reason
            """,
            key=title.key, holder=iv["holder"], **{"from": iv["from"]},
            to=iv["to"], open=iv["open"], reason=iv.get("reason"),
        )


def load_vassal_edge(session, vassal: TitleRecord, liege: TitleRecord, fp, kind: str = "de_facto") -> None:
    """``(:Title)-[:VASSAL_OF {kind, as_of}]->(:Title)`` for one liege link."""
    session.run(
        """
        MERGE (v:Title {key: $vassal})
        MERGE (l:Title {key: $liege})
        MERGE (v)-[r:VASSAL_OF {kind: $kind}]->(l)
        SET r.as_of = $date
        """,
        vassal=vassal.key, liege=liege.key, kind=kind, date=fp.date,
    )

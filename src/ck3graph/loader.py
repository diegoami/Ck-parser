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
* a ``VASSAL_OF`` stretch only ever widens the window it was seen in and
  tightens the windows the change is bounded by.

Game dates are written as real ``date`` values, never strings: save dates like
``"99.1.1"`` and ``"948.3.25"`` sort the wrong way round as text.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

from ck3parser.dynasties import house_name
from ck3parser.parser import Block, to_date
from ck3parser.titles import TitleRecord, normalize_history
from ck3parser.vassalage import Vassalage

SCHEMA_PATH = Path(__file__).with_name("schema.cypher")


class Titled(NamedTuple):
    """The three things an edge needs to know about a title.

    :class:`~ck3parser.titles.TitleRecord` satisfies it, and so does a caller
    that kept only the names: a run's title indexes are the expensive thing to
    hold on to, and an edge needs none of the history in them.
    """

    key: str
    display_name: str = ""
    tier: str | None = None

#: How many rows go into one ``UNWIND``. A whole save is 281 916 characters
#: and 201 498 parent links, so they are written in batches rather than one
#: statement each; the pass that produces them streams, and so does this.
BATCH_SIZE = 1000


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


# ------------------------------------------------------------ statements

#: One character, merged so that no snapshot can erase what another established.
#:
#: ``SET c += $props`` would be wrong here: Neo4j *removes* a property that a map
#: sets to null, so loading an older snapshot after a newer one would resurrect
#: the dead by deleting their `death`. Each property is therefore merged by hand,
#: and the ones that can only ever be learnt -- birth, death, the reason -- keep
#: the first non-null answer. The result does not depend on the order snapshots
#: are loaded in, which is the rule this whole module is written to.
MERGE_CHARACTERS = """
UNWIND $rows AS row
MERGE (c:Character {id: row.props.id})
SET c.first_name = CASE WHEN row.props.first_name = '' THEN c.first_name
                        ELSE row.props.first_name END,
    c.birth = coalesce(c.birth, row.props.birth),
    c.death = coalesce(c.death, row.props.death),
    c.death_reason = coalesce(c.death_reason, row.props.death_reason),
    c.female = coalesce(row.props.female, c.female),
    c.dynasty_house = coalesce(row.props.dynasty_house, c.dynasty_house),
    c.first_seen = CASE WHEN c.first_seen IS NULL OR $date < c.first_seen
                        THEN $date ELSE c.first_seen END,
    c.last_seen = CASE WHEN c.last_seen IS NULL OR $date > c.last_seen
                       THEN $date ELSE c.last_seen END
"""

MERGE_MEMBERSHIP = """
UNWIND $rows AS row
MERGE (c:Character {id: row.id})
MERGE (h:House {id: row.house})
MERGE (c)-[:MEMBER_OF]->(h)
"""

#: Parentage, written straight off the parent's own child list.
#:
#: It carries no dates. A tenure and a vassalage link are observations that can
#: change between snapshots; who your father was cannot, so there is nothing to
#: bracket and the edge is a plain fact.
MERGE_PARENTS = """
UNWIND $rows AS row
MERGE (p:Character {id: row.parent})
MERGE (c:Character {id: row.child})
MERGE (p)-[:PARENT_OF]->(c)
"""

#: A bastard's true father, kept apart from `PARENT_OF` exactly as the game and
#: :mod:`ck3parser.family` keep it apart: merging them would quietly rewrite a
#: lineage the save is careful to state twice.
MERGE_REAL_FATHERS = """
UNWIND $rows AS row
MERGE (f:Character {id: row.father})
MERGE (c:Character {id: row.child})
MERGE (f)-[:REAL_FATHER_OF]->(c)
"""

#: Marriage, written once between the pair rather than once per record.
#:
#: Both spouses' records name each other, so the edge is written from the lower
#: id to the higher and queried undirected -- otherwise the same marriage would
#: be two edges pointing opposite ways. `former` is sticky for the same reason a
#: closed tenure stays closed: a marriage one snapshot saw end has ended,
#: whichever order the snapshots load in.
MERGE_SPOUSES = """
UNWIND $rows AS row
MERGE (a:Character {id: row.a})
MERGE (b:Character {id: row.b})
MERGE (a)-[r:SPOUSE_OF]->(b)
SET r.former = coalesce(r.former, false) OR row.former
"""


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
    rows = [{"props": character_props(cid, char)} for cid, char in characters.items()]
    if rows:
        session.run(MERGE_CHARACTERS, rows=rows, date=to_date(fp.date))
        members = [
            {"id": row["props"]["id"], "house": row["props"]["dynasty_house"]}
            for row in rows
            if isinstance(row["props"]["dynasty_house"], int)
        ]
        if members:
            session.run(MERGE_MEMBERSHIP, rows=members)
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


def load_people(session, fp, people, batch_size: int = BATCH_SIZE) -> dict[str, int]:
    """Write a whole save's population and its family edges, in batches.

    `people` is an iterable of :class:`ck3graph.people.Person`, streamed, so
    nothing here holds more than `batch_size` records at a time.

    Nobody is filtered out. The lineage load drops filler characters because a
    page for one would be empty, but a filler is still somebody's parent, and
    dropping them would cut the very paths this exists to make walkable: a
    cousin two hops up and two back down usually leaves the lineage on the way.

    Returns the **rows** written, which is what the CLI reports. Rows are not
    edges: both spouses name each other, so a marriage is written twice and
    `MERGE`d into one edge -- 471 646 spouse rows on the 1364 save are about
    235 800 marriages. The parent rows are claims and each one is its own edge:
    389 639 of them over 201 498 children, most of whom the save gives two
    parents.
    """
    counts = {"characters": 0, "houses": 0, "parent_of": 0, "real_father_of": 0, "spouse_of": 0}
    date = to_date(fp.date)
    nodes: list[dict[str, Any]] = []
    members: list[dict[str, Any]] = []
    parents: list[dict[str, Any]] = []
    fathers: list[dict[str, Any]] = []
    spouses: list[dict[str, Any]] = []

    def flush(force: bool = False) -> None:
        for rows, query, key, params in (
            (nodes, MERGE_CHARACTERS, "characters", {"date": date}),
            (members, MERGE_MEMBERSHIP, "houses", {}),
            (parents, MERGE_PARENTS, "parent_of", {}),
            (fathers, MERGE_REAL_FATHERS, "real_father_of", {}),
            (spouses, MERGE_SPOUSES, "spouse_of", {}),
        ):
            if rows and (force or len(rows) >= batch_size):
                session.run(query, rows=list(rows), **params)
                counts[key] += len(rows)
                rows.clear()

    for person in people:
        nodes.append({"props": person.props})
        if person.house is not None:
            members.append({"id": person.id, "house": person.house})
        parents += [{"parent": person.id, "child": kid} for kid in person.children]
        if person.real_father is not None:
            fathers.append({"father": person.real_father, "child": person.id})
        # the pair is ordered so that both records write the same edge
        spouses += [
            {"a": min(person.id, other), "b": max(person.id, other), "former": former}
            for others, former in ((person.spouses, False), (person.former_spouses, True))
            for other in others
            if other != person.id
        ]
        flush()
    flush(force=True)
    return counts


def load_house(session, house, dynasty=None, arms_file: str | None = None) -> None:
    """A house node with the name the wiki shows it under, and its dynasty.

    :func:`ck3parser.dynasties.house_name` and :func:`~ck3parser.dynasties.arms_id`
    are the one rule each; the graph calls the same ones the wiki and the
    hand-off call, because a page linking one image while the graph names
    another would be two answers to one question.

    `arms_file` is the image name, not the save's ``coat_of_arms_id``: that id
    indexes one save and names no picture at all (docs/PLAN.md §11).
    """
    session.run(
        """
        MERGE (h:House {id: $id})
        SET h.name = $name, h.key = $key, h.motto = $motto, h.founded = $founded,
            h.arms_file = coalesce($arms, h.arms_file)
        """,
        id=house.id, name=house_name(house, dynasty), key=house.key, motto=house.motto,
        founded=to_date(house.founded), arms=arms_file,
    )
    if dynasty is not None:
        session.run(
            """
            MERGE (d:Dynasty {id: $id})
            SET d.name = $name
            WITH d MATCH (h:House {id: $house}) MERGE (h)-[:OF_DYNASTY]->(d)
            """,
            id=dynasty.id, name=dynasty.display_name, house=house.id,
        )
    head = house.head if house.head is not None else (dynasty.head if dynasty else None)
    if head is not None:
        session.run(
            """
            MATCH (h:House {id: $house})
            MERGE (c:Character {id: $head})
            MERGE (h)-[:HEADED_BY]->(c)
            """,
            house=house.id, head=head,
        )


def load_vassalage(session, vassal: Titled, liege: Titled, stretch: Vassalage, kind: str = "de_facto") -> None:
    """``(:Title)-[:VASSAL_OF {kind, first, last, after, before}]->(:Title)``.

    One edge per *stretch* of snapshots that saw the same liege, not one per
    save and not one that keeps only the latest answer. A save carries no
    vassalage history, so a change of liege is only ever known to have happened
    between two snapshots, and the edge says exactly that: `first`/`last` are
    the window it was seen in, `after`/`before` the snapshots that bound the
    change on either side (docs/PLAN.md §9). A tree can then be asked as of any
    date, not only a snapshot's:

        MATCH (t:Title {key: $key})<-[r:VASSAL_OF* {kind: 'de_facto'}]-(v)
        WHERE all(x IN r WHERE x.first <= $on AND $on <= x.last)

    Independence is **not** an edge: a title that answered to nobody has no
    `VASSAL_OF` covering that date. It is told apart from a title we simply did
    not see by the node's own `first_seen`/`last_seen`, because absence from a
    save means destroyed or pruned and never independence.

    Merging keeps the observation window widening and the ignorance window
    tightening: `last` only moves later, `after` only later, `before` only
    earlier, and a stretch one load saw still open stays closed once another
    closes it. `first` is part of the edge's identity, so a later load that
    sees this liege *earlier* writes a second, overlapping stretch rather than
    moving this one -- the price of a loader that never deletes. Loading a run
    whole, which is what the CLI does, never hits it.
    """
    session.run(
        """
        MERGE (v:Title {key: $vassal})
        SET v.name = $vassal_name, v.tier = $vassal_tier
        MERGE (l:Title {key: $liege})
        SET l.name = $liege_name, l.tier = $liege_tier
        MERGE (v)-[r:VASSAL_OF {kind: $kind, first: $first}]->(l)
        SET r.last = CASE WHEN r.last IS NULL OR $last > r.last THEN $last ELSE r.last END,
            r.after = CASE WHEN $after IS NULL THEN r.after
                           WHEN r.after IS NULL OR $after > r.after THEN $after
                           ELSE r.after END,
            r.before = CASE WHEN $before IS NULL THEN r.before
                            WHEN r.before IS NULL OR $before < r.before THEN $before
                            ELSE r.before END
        """,
        vassal=vassal.key, vassal_name=vassal.display_name, vassal_tier=vassal.tier,
        liege=liege.key, liege_name=liege.display_name, liege_tier=liege.tier,
        kind=kind, first=to_date(stretch.first), last=to_date(stretch.last),
        after=to_date(stretch.after), before=to_date(stretch.before),
    )

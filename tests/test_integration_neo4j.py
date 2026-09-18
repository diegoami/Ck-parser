"""End-to-end load against a real Neo4j. Opt in, and it WIPES the target database.

Everything else in this suite runs against `DryRunSession`, which records the
Cypher but never executes it. That proved insufficient: loading for real is what
exposed string dates sorting wrongly and provenance that depended on load order.

Run it against a throwaway database only:

    CK3_TEST_NEO4J_URI=bolt://127.0.0.1:7687 \
    NEO4J_USER=neo4j NEO4J_PASSWORD="$YOUR_TEST_PASSWORD" \
    uv run pytest tests/test_integration_neo4j.py

Both variables are required and neither has a default: a password falling back
to a well-known value is how a "throwaway" run reaches a database that is not
throwaway.

The saves are the tiny synthetic fixtures, so the whole file takes a second.
"""

from __future__ import annotations

import os
from datetime import date

import pytest

from ck3graph.loader import Neo4jConfig, apply_schema, load_people, open_session
from ck3graph.people import stream_people
from ck3parser.pipeline import Observations, gather, load_view
from helpers import SUCCESSION_EDITS, make_save

URI = os.environ.get("CK3_TEST_NEO4J_URI")
PASSWORD = os.environ.get("NEO4J_PASSWORD")
pytestmark = pytest.mark.skipif(
    not (URI and PASSWORD),
    reason="set CK3_TEST_NEO4J_URI and NEO4J_PASSWORD to run (this WIPES that database)",
)


@pytest.fixture
def session():
    config = Neo4jConfig(
        uri=URI,
        user=os.environ.get("NEO4J_USER", "neo4j"),
        password=PASSWORD,
        database=os.environ.get("NEO4J_DATABASE") or None,
    )
    with open_session(config) as s:
        s.run("MATCH (n) DETACH DELETE n")
        apply_schema(s)
        yield s


@pytest.fixture
def saves(tmp_path):
    """One run: 1100, then 1120 after the holder was succeeded."""
    early = make_save(tmp_path / "a_1100.ck3", date="1100.6.1", seed=7, random_count=100)
    late = make_save(
        tmp_path / "b_1120.ck3", date="1120.1.1", seed=7, random_count=200, edits=SUCCESSION_EDITS
    )
    return str(early), str(late)


def rows(session, cypher, **params):
    return [dict(r) for r in session.run(cypher, **params)]


def load(session, *paths, title="k_testland", people=False):
    """One or more snapshots, the way the CLI loads them.

    Vassalage is written only once every snapshot has been read, because a save
    has no vassalage history and a stretch is only known between two of them.
    """
    observed = Observations()
    for path in paths:
        with open(os.devnull, "w") as quiet:
            view = gather(path, title, log=quiet)
        load_view(session, view)
        observed.add(view)
        if people:
            load_people(session, view.fp, stream_people(view.fp.file))
    observed.emit(session)


def tenures(session):
    return rows(
        session,
        """MATCH (t:Title {key:'k_testland'})-[h:HELD_BY]->(c:Character)
           RETURN h.from AS from, h.to AS to, h.open AS open, c.id AS holder
           ORDER BY h.from""",
    )


def test_schema_applies_and_is_idempotent(session):
    apply_schema(session)
    assert rows(session, "SHOW CONSTRAINTS YIELD name RETURN count(*) AS n") == [{"n": 6}]


def test_single_save_writes_the_expected_graph(session, saves):
    load(session, saves[0])
    assert rows(session, "MATCH (n) UNWIND labels(n) AS l RETURN l, count(*) AS n ORDER BY l") == [
        {"l": "Character", "n": 5},
        {"l": "House", "n": 1},
        {"l": "Run", "n": 1},
        {"l": "Snapshot", "n": 1},
        {"l": "Title", "n": 3},
    ]
    assert tenures(session) == [
        {"from": date(867, 1, 1), "to": date(880, 5, 5), "open": False, "holder": 100},
        {"from": date(880, 5, 5), "to": date(900, 1, 1), "open": False, "holder": 101},
        {"from": date(950, 3, 3), "to": date(1090, 2, 1), "open": False, "holder": 102},
        {"from": date(1090, 2, 1), "to": date(1100, 6, 1), "open": True, "holder": 200},
    ]


def test_dates_are_temporal_not_text(session, saves):
    load(session, saves[0])
    # "99.1.1" would sort after "948.3.25" as text; as dates the order is by year
    held = rows(
        session,
        """MATCH (:Title {key:'k_testland'})-[h:HELD_BY]->(c:Character)
           WHERE h.from <= date('0890-01-01') AND h.to > date('0890-01-01')
           RETURN c.id AS holder""",
    )
    assert held == [{"holder": 101}]
    assert rows(
        session,
        """MATCH (:Title {key:'k_testland'})-[h:HELD_BY]->()
           RETURN max(duration.between(h.from, h.to).years) AS longest""",
    ) == [{"longest": 139}]


def test_loading_the_same_save_twice_changes_nothing(session, saves):
    load(session, saves[0])
    before = (tenures(session), rows(session, "MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS n ORDER BY t"))
    load(session, saves[0])
    after = (tenures(session), rows(session, "MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS n ORDER BY t"))
    assert before == after


def test_later_snapshot_closes_the_open_tenure_in_place(session, saves):
    load(session, *saves)
    assert tenures(session)[-2:] == [
        # closed by the later snapshot, still one relationship
        {"from": date(1090, 2, 1), "to": date(1110, 5, 5), "open": False, "holder": 200},
        {"from": date(1110, 5, 5), "to": date(1120, 1, 1), "open": True, "holder": 201},
    ]
    assert rows(session, "MATCH (:Title {key:'k_testland'})-[h:HELD_BY]->() RETURN count(*) AS n") == [{"n": 5}]


def test_load_order_does_not_change_the_result(session, saves):
    load(session, saves[1])  # newest first
    load(session, saves[0])  # then the older one
    assert tenures(session)[-2:] == [
        {"from": date(1090, 2, 1), "to": date(1110, 5, 5), "open": False, "holder": 200},
        {"from": date(1110, 5, 5), "to": date(1120, 1, 1), "open": True, "holder": 201},
    ]
    assert rows(
        session,
        "MATCH (t:Title {key:'k_testland'}) RETURN t.first_seen AS first, t.last_seen AS last",
    ) == [{"first": date(1100, 6, 1), "last": date(1120, 1, 1)}]


def test_provenance_brackets_the_snapshots_a_node_was_seen_in(session, saves):
    load(session, *saves)
    assert rows(
        session,
        "MATCH (t:Title {key:'k_testland'}) RETURN t.first_seen AS first, t.last_seen AS last",
    ) == [{"first": date(1100, 6, 1), "last": date(1120, 1, 1)}]
    # the heir only appears in the later save
    assert rows(session, "MATCH (c:Character {id:201}) RETURN c.first_seen AS first, c.last_seen AS last") == [
        {"first": date(1100, 6, 1), "last": date(1120, 1, 1)}
    ]


def test_a_de_jure_only_liege_is_named_but_not_marked_loaded(session, saves):
    # c_far sits under c_test de facto but under d_empty de jure, so d_empty is
    # reached only through that edge and its history is never loaded
    load(session, saves[0], title="c_test")
    assert rows(
        session,
        "MATCH (t:Title {key:'d_empty'}) RETURN t.name AS name, t.tier AS tier, t.first_seen IS NULL AS unloaded",
    ) == [{"name": "Empty Duchy", "tier": "duchy", "unloaded": True}]


def test_a_vassalage_stretch_spans_the_snapshots_that_saw_it(session, saves):
    load(session, *saves)
    # one stretch, not one edge per save: the liege did not change, so there is
    # nothing between the snapshots to report
    assert rows(
        session,
        """MATCH (:Title {key:'c_test'})-[r:VASSAL_OF {kind:'de_facto'}]->(l:Title)
           RETURN l.key AS liege, r.first AS first, r.last AS last, r.before AS before""",
    ) == [
        {"liege": "k_testland", "first": date(1100, 6, 1), "last": date(1120, 1, 1), "before": None}
    ]


def test_a_tree_can_be_asked_as_of_a_date_between_snapshots(session, saves):
    load(session, *saves)
    # 1110 is in neither save; the stretch covers it, which is the whole point
    # of bounds over an as-of date
    assert rows(
        session,
        """MATCH (t:Title {key:'k_testland'})<-[r:VASSAL_OF {kind:'de_facto'}]-(v:Title)
           WHERE r.first <= date('1110-01-01') AND date('1110-01-01') <= r.last
           RETURN v.key AS vassal ORDER BY vassal""",
    ) == [{"vassal": "c_test"}, {"vassal": "x_mc_0"}]


def test_parentage_is_walkable_upward_without_any_inversion(session, saves):
    load(session, saves[0], people=True)
    # the save never stores a parent; the edge is written off the child list and
    # Cypher reads it backwards
    assert rows(
        session,
        """MATCH (c:Character {id:203})<-[:PARENT_OF]-(p)
           RETURN p.id AS parent ORDER BY parent""",
    ) == [{"parent": 200}, {"parent": 202}]
    # ... and siblings come out of the same two edges, with no sibling edge
    assert rows(
        session,
        """MATCH (c:Character {id:203})<-[:PARENT_OF]-()-[:PARENT_OF]->(s)
           WHERE s <> c RETURN DISTINCT s.id AS sibling""",
    ) == [{"sibling": 204}]


def test_a_marriage_is_one_edge_not_two(session, saves):
    load(session, saves[0], people=True)
    # both spouses' records name each other; ordering the pair is what keeps it
    # from becoming two edges pointing opposite ways
    assert rows(session, "MATCH ()-[r:SPOUSE_OF]->() RETURN count(*) AS n") == [{"n": 1}]


def test_an_older_snapshot_cannot_resurrect_the_dead(session, saves):
    # `SET c += $props` would: Neo4j removes a property a map sets to null
    load(session, saves[1], people=True)  # newest first
    load(session, saves[0], people=True)  # then the older one, where 100 is alive in no sense
    assert rows(session, "MATCH (c:Character {id:100}) RETURN c.death AS death") == [
        {"death": date(880, 5, 5)}
    ]


def test_a_house_carries_the_name_and_the_image_the_wiki_uses(session, saves):
    load(session, *saves)
    got, = rows(
        session,
        """MATCH (h:House {id:500})
           OPTIONAL MATCH (h)-[:OF_DYNASTY]->(d:Dynasty)
           RETURN h.name AS name, h.arms_file AS arms, d.id AS dynasty""",
    )
    assert got["dynasty"] is not None
    # the image is named after the recipe, never after the save's coat_of_arms_id
    assert got["arms"] is None or got["arms"].startswith("arms_")

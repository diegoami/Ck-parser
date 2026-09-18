import pytest
from datetime import date

from ck3graph.loader import (
    DryRunSession,
    Neo4jConfig,
    Titled,
    apply_schema,
    holder_intervals,
    load_house,
    load_people,
    load_snapshot,
    load_title,
    load_vassalage,
    schema_statements,
)
from ck3graph.people import stream_people
from ck3parser.dynasties import find_dynasties, find_houses, house_name
from ck3parser.fingerprint import fingerprint
from ck3parser.parser import parse_text
from ck3parser.titles import build_index
from ck3parser.vassalage import Vassalage
from helpers import fixture_text, make_save


def test_config_from_env():
    cfg = Neo4jConfig.from_env({"NEO4J_URI": "bolt://x:7687", "NEO4J_USER": "u", "NEO4J_PASSWORD": "p"})
    assert cfg.uri == "bolt://x:7687" and cfg.database is None
    with pytest.raises(RuntimeError):
        Neo4jConfig.from_env({})


def test_schema_has_constraints():
    stmts = schema_statements()
    assert len(stmts) == 6 and all(s.startswith("CREATE CONSTRAINT") for s in stmts)
    s = DryRunSession(echo=False)
    apply_schema(s)
    assert len(s.statements) == 6


def test_holder_intervals_from_fixture_history():
    hist = parse_text(fixture_text())["landed_titles"]["landed_titles"]["0"]["history"]
    assert holder_intervals(hist, end_date="1100.6.1") == [
        {"holder": 100, "from": "867.1.1", "to": "880.5.5", "open": False, "reason": None},
        # closed by the destroyed entry, which does NOT open a tenure for its holder
        {"holder": 101, "from": "880.5.5", "to": "900.1.1", "open": False, "reason": None},
        {"holder": 102, "from": "950.3.3", "to": "1090.2.1", "open": False, "reason": "created"},
        {"holder": 200, "from": "1090.2.1", "to": "1100.6.1", "open": True, "reason": None},
    ]


def test_a_title_with_no_history_gets_one_tenure_from_its_date():
    # 6 079 held titles in the sample save have no history at all
    assert holder_intervals(None, "1100.6.1", current_holder=5, holder_since="1080.1.1") == [
        {"holder": 5, "from": "1080.1.1", "to": "1100.6.1", "open": True, "reason": None}
    ]


def test_a_tenure_that_cannot_be_placed_in_time_is_dropped():
    # Neo4j cannot MERGE a relationship on a null property, and Title.holder
    # still records who holds it
    assert holder_intervals(None, "1100.6.1", current_holder=5) == []
    assert holder_intervals(None, "1100.6.1") == []


def test_the_titles_own_holder_wins_over_a_stale_history():
    # leased-out baronies change hands without a history entry being appended
    assert holder_intervals(
        [("900.1.1", 1, "leased_out")], "1100.6.1", current_holder=2, holder_since="1050.1.1"
    ) == [
        {"holder": 1, "from": "900.1.1", "to": "1050.1.1", "open": False, "reason": "leased_out"},
        {"holder": 2, "from": "1050.1.1", "to": "1100.6.1", "open": True, "reason": None},
    ]


def test_a_history_ending_in_a_terminal_entry_leaves_no_open_tenure():
    ended = holder_intervals([("900.1.1", 1, None), ("950.1.1", None, "destroyed")], "1100.6.1", current_holder=1)
    assert ended == [{"holder": 1, "from": "900.1.1", "to": "950.1.1", "open": False, "reason": None}]


def test_load_writes_merges_only(tmp_path):
    p = make_save(tmp_path / "a.ck3")
    fp = fingerprint(p, with_sha256=False)
    top = parse_text(fixture_text())
    title = build_index(p).get("k_testland")
    chars = {200: top["living"]["200"], 100: top["dead_unprunable"]["100"]}
    s = DryRunSession(echo=False)
    load_snapshot(s, fp)
    load_title(s, fp, title, holder_intervals(title.history, fp.date, title.holder), chars)
    queries = [q for q, _ in s.statements]
    assert all("MERGE" in q and "DELETE" not in q for q in queries)
    held = [params for q, params in s.statements if "HELD_BY" in q]
    assert [h["holder"] for h in held] == [100, 101, 102, 200]
    assert [h["reason"] for h in held] == [None, None, "created", None]
    written = [params for q, params in s.statements if "MERGE (c:Character {id: row.props.id})" in q]
    deaths = {row["props"]["death"] for params in written for row in params["rows"]}
    # game dates are stored as real dates, so that "99.1.1" does not sort after "948.3.25"
    assert deaths == {None, date(880, 5, 5)}
    assert [h["from"] for h in held][:2] == [date(867, 1, 1), date(880, 5, 5)]


def test_a_vassalage_edge_carries_the_bounds_and_not_a_date(tmp_path):
    p = make_save(tmp_path / "a.ck3")
    index = build_index(p)
    s = DryRunSession(echo=False)
    stretch = Vassalage(
        liege="k_testland", first="1100.6.1", last="1110.1.1", after="1090.1.1", before="1120.1.1"
    )
    load_vassalage(s, index.get("c_test"), index.get("k_testland"), stretch)
    (query, params), = s.statements
    assert "VASSAL_OF" in query and "DELETE" not in query
    assert params == {
        "vassal": "c_test", "vassal_name": "Test County", "vassal_tier": "county",
        "liege": "k_testland", "liege_name": "Kingdom of Testland", "liege_tier": "kingdom",
        "kind": "de_facto",
        # the window it was seen in, and the two snapshots the change is bounded
        # by: a save has no vassalage history, so there is no date to give
        "first": date(1100, 6, 1), "last": date(1110, 1, 1),
        "after": date(1090, 1, 1), "before": date(1120, 1, 1),
    }
    # merging widens what was observed and tightens what bounds it
    assert "$last > r.last" in query and "$after > r.after" in query and "$before < r.before" in query


def test_a_stretch_is_identified_by_where_it_starts():
    # a title that leaves a liege and comes back is two stretches, not one edge
    # overwriting the other
    s = DryRunSession(echo=False)
    for first, last in (("1100.6.1", "1100.6.1"), ("1120.1.1", "1120.1.1")):
        load_vassalage(
            s, Titled("c_test"), Titled("k_testland"), Vassalage("k_testland", first, last)
        )
    query = s.statements[0][0]
    assert "VASSAL_OF {kind: $kind, first: $first}" in query
    assert [params["first"] for _, params in s.statements] == [date(1100, 6, 1), date(1120, 1, 1)]


def test_a_character_write_cannot_erase_what_another_snapshot_established():
    # `SET c += $props` would: Neo4j removes a property a map sets to null, so
    # loading an older save after a newer one would delete the dead's `death`
    s = DryRunSession(echo=False)
    top = parse_text(fixture_text())
    load_people(s, _Fp("1100.6.1"), [_person(100, top["dead_unprunable"]["100"])])
    query = next(q for q, _ in s.statements if "MERGE (c:Character" in q)
    assert "c +=" not in query
    assert "c.death = coalesce(c.death, row.props.death)" in query
    assert "c.birth = coalesce(c.birth, row.props.birth)" in query


class _Fp:
    """Just the date, which is all the people writer takes off a fingerprint."""

    def __init__(self, date_):
        self.date = date_


def _person(cid, block):
    from ck3graph.people import Person
    from ck3graph.loader import character_props
    from ck3parser.family import own_family
    from ck3parser.parser import Block

    person = Person(id=cid, props=character_props(cid, block))
    family = block.get("family_data")
    if isinstance(family, Block):
        own = own_family(cid, family)
        person.children, person.spouses = own.children, own.spouses
        person.former_spouses, person.real_father = own.former_spouses, own.real_father
    return person


def test_parentage_is_written_downward_and_needs_no_inversion(tmp_path):
    # the save lists children and never parents; a graph walks the edge either
    # way, so nothing is inverted here the way ck3parser.family has to
    p = make_save(tmp_path / "a.ck3")
    s = DryRunSession(echo=False)
    counts = load_people(s, _Fp("1100.6.1"), stream_people(p), batch_size=1)
    parents = [params for q, params in s.statements if "PARENT_OF" in q]
    links = sorted((row["parent"], row["child"]) for params in parents for row in params["rows"])
    # both parents claim both children, and each claim is its own edge
    assert links == [(200, 203), (200, 204), (202, 203), (202, 204)]
    assert counts["parent_of"] == len(links)
    assert all("DELETE" not in q for q, _ in s.statements)


def test_a_marriage_is_one_edge_however_many_records_name_it(tmp_path):
    p = make_save(tmp_path / "a.ck3")
    s = DryRunSession(echo=False)
    load_people(s, _Fp("1100.6.1"), stream_people(p))
    pairs = [
        (row["a"], row["b"])
        for q, params in s.statements if "SPOUSE_OF" in q
        for row in params["rows"]
    ]
    # both spouses name each other, so both records are written; ordering the
    # pair is what makes them the same row, and MERGE one edge rather than two
    assert all(a < b for a, b in pairs)
    assert pairs == [(200, 202), (200, 202)] and set(pairs) == {(200, 202)}


def test_a_house_is_named_the_way_the_wiki_names_it(tmp_path):
    p = make_save(tmp_path / "a.ck3")
    houses = find_houses(p, {501, 502})
    dynasties = find_dynasties(p, {h.dynasty for h in houses.values() if h.dynasty is not None})
    s = DryRunSession(echo=False)
    for house in houses.values():
        load_house(s, house, dynasties.get(house.dynasty), "arms_abc123.png")
    names = {params["id"]: params["name"] for q, params in s.statements if "MERGE (h:House" in q}
    assert names[502] == house_name(houses[502], dynasties.get(houses[502].dynasty))
    # the image name is the recipe's, never the save's coat_of_arms_id
    arms = {params["arms"] for q, params in s.statements if "MERGE (h:House" in q}
    assert arms == {"arms_abc123.png"}
    assert any("OF_DYNASTY" in q for q, _ in s.statements)

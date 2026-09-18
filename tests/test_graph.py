import pytest
from datetime import date

from ck3graph.loader import (
    DryRunSession,
    Neo4jConfig,
    apply_schema,
    holder_intervals,
    load_snapshot,
    load_title,
    load_vassal_edge,
    schema_statements,
)
from ck3parser.fingerprint import fingerprint
from ck3parser.parser import parse_text
from ck3parser.titles import build_index
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
    char_writes = [params for q, params in s.statements if "MERGE (c:Character {id: $id})" in q]
    # game dates are stored as real dates, so that "99.1.1" does not sort after "948.3.25"
    assert {c["props"]["death"] for c in char_writes} == {None, date(880, 5, 5)}
    assert [h["from"] for h in held][:2] == [date(867, 1, 1), date(880, 5, 5)]


def test_load_vassal_edge(tmp_path):
    p = make_save(tmp_path / "a.ck3")
    fp = fingerprint(p, with_sha256=False)
    index = build_index(p)
    s = DryRunSession(echo=False)
    load_vassal_edge(s, index.get("c_test"), index.get("k_testland"), fp)
    (query, params), = s.statements
    assert "VASSAL_OF" in query and "DELETE" not in query
    assert params == {
        "vassal": "c_test", "vassal_name": "Test County", "vassal_tier": "county",
        "liege": "k_testland", "liege_name": "Kingdom of Testland", "liege_tier": "kingdom",
        "kind": "de_facto", "date": date(1100, 6, 1),
    }

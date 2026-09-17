from ck3parser.titles import (
    TitleIndex,
    TitleRecord,
    build_index,
    clean_title_name,
    normalize_history,
    tier_of,
)
from ck3parser.parser import parse_text
from helpers import fixture_text, make_save


def test_tier_and_name_helpers():
    assert tier_of("e_germany") == "empire" and tier_of("c_test") == "county"
    assert tier_of("x_mc_0") is None
    assert tier_of("x_mc_0", {"x_mc_0": "duchy"}) == "duchy"
    assert clean_title_name("e_germania") == "Germania"
    assert clean_title_name("k_papal_state") == "Papal State"


def test_normalize_history_terminal_entry_closes_without_opening():
    history = parse_text(fixture_text())["landed_titles"]["landed_titles"]["0"]["history"]
    assert normalize_history(history) == [
        ("867.1.1", 100, None),
        ("880.5.5", 101, None),
        ("900.1.1", None, "destroyed"),  # holder=101 names the outgoing ruler
        ("950.3.3", 102, "created"),
        ("1090.2.1", 200, None),
    ]


def test_normalize_history_sorts_and_ignores_junk():
    block = parse_text("history={ 900.1.1=5 800.1.1=4 850.1.1={ type=granted holder=9 } }")["history"]
    assert normalize_history(block) == [("800.1.1", 4, None), ("850.1.1", 9, "granted"), ("900.1.1", 5, None)]
    assert normalize_history(None) == []


def test_build_index_from_save(tmp_path):
    index = build_index(make_save(tmp_path / "a.ck3"))
    assert set(index.by_key) == {"k_testland", "d_empty", "c_test", "x_mc_0", "c_far"}
    assert index.templates == {"x_mc_0": "duchy"}
    king = index.get("k_testland")
    assert king.idx == 0 and king.tier == "kingdom" and king.holder == 200
    assert king.display_name == "Kingdom of Testland"
    assert index.get("x_mc_0").tier == "duchy"  # tier came from the dynamic template
    assert index.resolve(index.get("c_test").de_jure_liege) is king
    assert index.resolve(None) is None


def test_immediate_vassals_are_de_facto_and_tier_ordered(tmp_path):
    index = build_index(make_save(tmp_path / "a.ck3"))
    vassals = index.immediate_vassals("k_testland")
    assert [v.key for v in vassals] == ["x_mc_0", "c_test"]  # duchy before county
    # d_empty is de jure only, and c_far sits under c_test, so neither is immediate
    assert [v.key for v in index.immediate_vassals("c_test")] == ["c_far"]
    assert index.immediate_vassals("nope") == []


def test_liege_chain_stops_at_the_top(tmp_path):
    index = build_index(make_save(tmp_path / "a.ck3"))
    assert [r.key for r in index.liege_chain("c_far")] == ["c_far", "c_test", "k_testland"]


def test_liege_chain_survives_a_cycle():
    index = TitleIndex()
    index.add(TitleRecord(idx=1, key="a", de_facto_liege=2))
    index.add(TitleRecord(idx=2, key="b", de_facto_liege=1))
    assert [r.key for r in index.liege_chain("a")] == ["a", "b"]


def test_keep_history_predicate_bounds_what_is_kept(tmp_path):
    save = make_save(tmp_path / "a.ck3")
    index = build_index(save, keep_history=lambda key: key == "k_testland")
    assert index.get("k_testland").history and not index.get("c_test").history
    assert not build_index(save, keep_history=False).get("k_testland").history


def test_holder_ids_span_history_and_current_holder(tmp_path):
    index = build_index(make_save(tmp_path / "a.ck3"))
    assert index.get("k_testland").holder_ids() == {100, 101, 102, 200}

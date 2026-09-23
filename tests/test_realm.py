from ck3parser.realm import changes, realm
from ck3parser.titles import build_index
from helpers import make_save
from test_wiki import LEAVES_AND_PASSES, VANISHES


def index_of(tmp_path, name="a.ck3", **kw):
    return build_index(str(make_save(tmp_path / name, **kw)))


def test_depth_is_vassal_rank_counted_in_holders(tmp_path):
    # 200 holds the kingdom; 201 holds c_test and x_mc_0 under it; 202 holds
    # c_far under c_test -- a vassal's vassal
    r = realm(index_of(tmp_path), 200, "1100.6.1")
    assert r.titles["k_testland"].depth == 0 and r.titles["k_testland"].chain == (200,)
    assert r.titles["c_test"].depth == 1 and r.titles["c_test"].chain == (200, 201)
    assert r.titles["x_mc_0"].depth == 1
    assert r.titles["c_far"].depth == 2 and r.titles["c_far"].chain == (200, 201, 202)
    assert "d_empty" not in r.titles  # unheld and under nobody: not the ruler's
    assert r.by_depth("county") == {1: 1, 2: 1}


def test_a_realm_is_whatever_hangs_under_the_rulers_titles(tmp_path):
    index = index_of(tmp_path)
    # the vassal's own realm is his subtree, not his liege's
    assert set(realm(index, 201).titles) == {"c_test", "x_mc_0", "c_far"}
    assert realm(index, 201).titles["c_far"].depth == 1
    assert realm(index, 999).titles == {}  # holds nothing, rules nothing


def test_a_title_moving_deeper_is_not_a_change_of_realm(tmp_path):
    # x_mc_0 passes from 201 to 205 and moves under c_test: still the realm,
    # now held by a vassal's vassal
    early = realm(index_of(tmp_path, "a.ck3"), 200, "1100.6.1")
    late = realm(index_of(tmp_path, "b.ck3", date="1120.1.1", edits=LEAVES_AND_PASSES), 200, "1120.1.1")
    assert late.titles["x_mc_0"].chain == (200, 201, 205)
    assert changes(early, late, tier=None) == []


def test_a_title_gone_from_the_save_is_gone_not_lost(tmp_path):
    # absence is never an ending the save states: destroyed or pruned, unknown
    early = realm(index_of(tmp_path, "a.ck3"), 200, "1100.6.1")
    late = realm(index_of(tmp_path, "b.ck3", date="1120.1.1", edits=VANISHES), 200, "1120.1.1")
    (change,) = changes(early, late, tier=None)
    assert (change.key, change.kind) == ("x_mc_0", "gone")
    # and it is a window, never a date
    assert (change.after, change.before) == ("1100.6.1", "1120.1.1")


def test_a_title_that_leaves_for_another_realm_has_left(tmp_path):
    # c_far stops answering to c_test and answers to d_empty, which is outside
    edits = (("de_jure_liege=1\n\tde_facto_liege=2", "de_jure_liege=1\n\tde_facto_liege=1"),)
    early = realm(index_of(tmp_path, "a.ck3"), 200, "1100.6.1")
    late = realm(index_of(tmp_path, "b.ck3", date="1120.1.1", edits=edits), 200, "1120.1.1")
    assert [(c.key, c.kind) for c in changes(early, late)] == [("c_far", "left")]
    assert [(c.key, c.kind) for c in changes(late, early)] == [("c_far", "gained")]

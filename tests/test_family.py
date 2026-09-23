from ck3parser.family import Family, read_family
from helpers import make_save


def save(tmp_path):
    return str(make_save(tmp_path / "a.ck3"))


def test_parents_are_found_by_inverting_child_lists(tmp_path):
    # the save has no `father` or `mother` anywhere: verified on all 281 916
    # characters of the 1364 save. A parent is only ever found by reading the
    # record that claims the child.
    family = read_family(save(tmp_path), {203})
    assert family[203].parents == [200, 202]


def test_a_parents_own_record_gives_children_and_spouses(tmp_path):
    parent = read_family(save(tmp_path), {200})[200]
    assert parent.children == [203, 204] and parent.spouses == [202]
    # 102 held the kingdom until 1090 and 103 held nothing; both claim 200 as a
    # child, which is the only way a save ever states a parent (docs/PLAN.md §10)
    assert parent.parents == [102, 103]


def test_siblings_come_from_the_parents_whole_brood(tmp_path):
    family = read_family(save(tmp_path), {203, 204})
    assert family[203].siblings == [204] and family[204].siblings == [203]
    # and never include the character themselves
    assert 203 not in family[203].siblings


def test_only_the_wanted_characters_are_returned(tmp_path):
    assert read_family(save(tmp_path), set()) == {}
    found = read_family(save(tmp_path), {203})
    assert set(found) == {203}


def test_a_character_with_no_family_data_still_gets_a_record(tmp_path):
    # 27 of the 1364 lineage's 666 characters carry no family_data at all
    found = read_family(save(tmp_path), {100})
    assert found[100] == Family(id=100)
    assert not found[100].everyone


def test_everyone_gathers_the_ids_worth_naming():
    f = Family(id=1, parents=[2], children=[3], spouses=[4], former_spouses=[5],
               primary_spouse=4, real_father=6, siblings=[7])
    assert f.everyone == [2, 3, 4, 5, 6, 7]


def test_repeated_and_listed_keys_are_both_read(tmp_path):
    # `spouse` repeats as its own key while `child` arrives as a list; the save
    # uses both shapes and Block keeps repeats, so neither may be read with get()
    parent = read_family(save(tmp_path), {200})[200]
    assert parent.spouses == [202] and parent.children == [203, 204]

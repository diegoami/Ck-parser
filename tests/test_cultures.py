"""Cultures and faiths: what the save names, and what it only keys."""

from ck3parser.cultures import find_cultures
from ck3parser.faiths import find_faiths
from helpers import make_save


def test_a_shipped_culture_is_keyed_and_a_created_one_is_named(tmp_path):
    p = make_save(tmp_path / "a.ck3")
    found = find_cultures(p, {0, 1})

    keyed = found[0]
    # `name` equals `culture_template` for every templated culture (verified:
    # 190 of 190 on the 1364 save), so it is a localization key and is
    # transcribed, never shown raw and never guessed at
    assert keyed.templated and keyed.display_name == "Testish"
    assert keyed.heritage == "Test North" and keyed.language == "Testic"
    # 1.1.1 is a sentinel, not a founding date anyone wants to read
    assert keyed.created == "1.1.1" and keyed.founded is None

    made = found[1]
    # no template: the game had to write the name out, so it is shown as it stands
    assert not made.templated and made.display_name == "Testish-Farrish"
    assert made.founded == "1050.4.4" and made.parents == [0]


def test_a_culture_lookup_asks_for_nothing_it_was_not_given(tmp_path):
    p = make_save(tmp_path / "a.ck3")
    assert find_cultures(p, set()) == {}
    assert set(find_cultures(p, {1, 99999})) == {1}


def test_a_faith_founded_in_the_run_names_its_founder(tmp_path):
    p = make_save(tmp_path / "a.ck3")
    found = find_faiths(p, {0, 1})

    plain = found[0]
    # nobody named it, so the key is transcribed the same way a culture's is
    assert not plain.founded_in_run and plain.display_name == "Test Pagan"
    assert plain.founder is None

    made = found[1]
    # a dynamic_faith_ tag is the save saying this faith was reformed in-run
    assert made.founded_in_run and made.display_name == "Testarianism"
    assert made.founder == 102 and made.template == "test_pagan"
    assert made.adjective == "Testarian"


def test_a_faith_keeps_the_template_it_was_reformed_out_of(tmp_path):
    # the reformed faith and the original share a template; the tag is what
    # tells them apart, and the template is worth keeping to say where it came from
    p = make_save(tmp_path / "a.ck3")
    found = find_faiths(p, {0, 1})
    assert found[0].template == found[1].template == "test_pagan"
    assert found[0].tag != found[1].tag


def test_a_template_does_not_say_when_a_culture_came_into_being(tmp_path):
    # the two questions are separate: 10 of the 1364 save's 190 templated
    # cultures were created during that very run, because CK3 ships templates
    # for the cultures it expects to diverge
    p = make_save(tmp_path / "a.ck3")
    found = find_cultures(p, {0, 1})
    assert found[0].templated and found[0].founded is None
    assert not found[1].templated and found[1].founded == "1050.4.4"

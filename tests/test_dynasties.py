from ck3parser.dynasties import (
    Dynasty,
    arms_id,
    House,
    clean_key,
    find_dynasties,
    find_houses,
    from_house_key,
    house_name,
)
from ck3parser.portraits import CHECKSUM_LENGTH, arms_name, portrait_name, save_checksum
from helpers import make_save


def save(tmp_path):
    return str(make_save(tmp_path / "a_1100.ck3", date="1100.6.1", seed=7, random_count=100))


# ---------------------------------------------------------------- houses


def test_clean_key_strips_the_key_prefix_and_nothing_else():
    assert clean_key("dynn_Strathearn", "dynn_") == "Strathearn"
    assert clean_key("dynnp_of", "dynnp_") == "of"
    assert clean_key("dynn_van_der_Berg", "dynn_") == "van der Berg"
    assert clean_key("Strathearn", "dynn_") == "Strathearn"  # no prefix, unchanged
    assert clean_key(None, "dynn_") == "" and clean_key("", "dynn_") == ""


def test_a_house_carries_its_dynasty_and_reads_its_name_from_the_key(tmp_path):
    houses = find_houses(save(tmp_path), {500})
    house = houses[500]
    assert house.display_name == "of Test" and house.dynasty == 50
    assert house.founded == "1040.3.2"
    # a motto is usually a block whose `key` needs localization to read; only
    # the key is kept, never dressed up as prose
    assert house.motto == "motto_x_under_y_king"


def test_an_unfounded_house_has_no_founding_date(tmp_path):
    # the game dates houses it shipped with 9999.1.1, a sentinel, not a date
    house = find_houses(save(tmp_path), {501})[501]
    assert house.found_date == "9999.1.1" and house.founded is None
    assert house.display_name == ""  # and no name of its own either
    assert house.motto == "motto_plain"  # the plain form is taken as it stands


def test_a_house_with_no_name_falls_back_to_its_key_and_its_own_arms(tmp_path):
    # `house_munso` is the name, unlike a dynasty's `key`, which is a number
    house = find_houses(save(tmp_path), {502})[502]
    assert house.display_name == "Munso" and house.head == 201
    # its own arms win over the dynasty's 900
    assert house.coat_of_arms_id == 901 and house.dynasty == 50


def test_only_the_wanted_houses_are_kept(tmp_path):
    assert find_houses(save(tmp_path), set()) == {}
    assert set(find_houses(save(tmp_path), {500, 999})) == {500}


# ---------------------------------------------------------------- dynasties


def test_a_dynasty_carries_its_arms_and_its_head(tmp_path):
    dynasty = find_dynasties(save(tmp_path), {50})[50]
    assert dynasty.display_name == "Test" and dynasty.coat_of_arms_id == 900
    assert dynasty.head == 200
    assert find_dynasties(save(tmp_path), set()) == {}


def test_a_localized_name_wins_over_the_key():
    # 2 210 dynasties in the 1364 save carry display text already; it is used
    # as it stands, prefix key and all left behind
    assert Dynasty(id=1, name="Danielid").display_name == "Danielid"
    assert Dynasty(id=1, name="Test", prefix="of").display_name == "of Test"
    assert House(id=1).display_name == ""
    assert from_house_key("house_von_habsburg") == "Von Habsburg"


def test_a_house_shows_its_own_arms_and_falls_back_to_its_dynastys():
    # one rule, so the image a wiki page links is the image the companion is
    # asked for; they disagreed once and nobody noticed
    dynasty = Dynasty(id=50, name="Test", coat_of_arms_id=900)
    assert arms_id(House(id=1, coat_of_arms_id=901), dynasty) == 901
    assert arms_id(House(id=1), dynasty) == 900
    assert arms_id(House(id=1), None) is None


def test_a_house_falls_back_to_its_dynastys_name():
    dynasty = Dynasty(id=50, name="Test")
    assert house_name(House(id=1, name="Own"), dynasty) == "Own"
    assert house_name(House(id=1), dynasty) == "Test"
    assert house_name(House(id=1), None) == "House 1"


# ---------------------------------------------------------------- naming


def test_both_projects_derive_the_same_image_name():
    real = "Fylkir_Ludwig_of_Immasonian_Fylkirate_1364_03_10.ck3"
    assert save_checksum(real) == "5a86b836cd32"
    assert len(save_checksum(real)) == CHECKSUM_LENGTH
    assert portrait_name(real, 50544311) == "5a86b836cd32_50544311.png"
    # arms are not keyed on the save at all: the recipe names the picture, so
    # the same arms are one file in every run (docs/PLAN.md §11)
    assert arms_name("4ec4589d5e8a") == "arms_4ec4589d5e8a.png"
    # the base name is what is hashed, so where the save sits cannot matter
    assert save_checksum(f"/wherever/{real}") == save_checksum(real)


def test_a_different_save_means_a_different_portrait():
    assert portrait_name("a.ck3", 7) != portrait_name("b.ck3", 7)
    assert portrait_name("a.ck3", 7) != portrait_name("a.ck3", 8)


# ---------------------------------------------------------------- arms recipes


def test_repeated_emblems_survive_the_json_shape():
    # `colored_emblem` repeats once per emblem, so a dict would keep one of
    # three and two different coats of arms would collapse to one name
    from ck3parser.arms import as_pairs, canonical, digest
    from ck3parser.parser import parse_text

    two = parse_text('colored_emblem={ texture="a.dds" } colored_emblem={ texture="b.dds" }')
    one = parse_text('colored_emblem={ texture="a.dds" }')
    assert len(as_pairs(two)) == 2 and len(as_pairs(one)) == 1
    assert digest(two) != digest(one)

    # order is part of the recipe: emblems are drawn in the order listed
    flipped = parse_text('colored_emblem={ texture="b.dds" } colored_emblem={ texture="a.dds" }')
    assert digest(flipped) != digest(two)
    assert canonical(two).count("colored_emblem") == 2


def test_the_same_recipe_gets_the_same_name_whatever_its_id(tmp_path):
    from ck3parser.arms import digest, read_arms
    from ck3parser.parser import parse_text
    from ck3parser.portraits import arms_name

    found = read_arms(save(tmp_path), {900, 901})
    assert found[900].digest != found[901].digest  # drawn differently
    assert arms_name(found[900].digest).startswith("arms_")

    # an identical recipe under a different id is the same file
    same = parse_text('pattern="pattern_solid.dds" color1=red color2=white'
                      ' colored_emblem={ color1=white texture="ce_lion.dds" }')
    assert digest(same) == found[900].digest


def test_an_unknown_arms_id_simply_is_not_found(tmp_path):
    from ck3parser.arms import read_arms

    assert read_arms(save(tmp_path), set()) == {}
    assert set(read_arms(save(tmp_path), {900, 99999})) == {900}

from ck3parser.dynasties import (
    Dynasty,
    House,
    clean_key,
    find_dynasties,
    find_houses,
    from_house_key,
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


# ---------------------------------------------------------------- naming


def test_both_projects_derive_the_same_image_name():
    real = "Fylkir_Ludwig_of_Immasonian_Fylkirate_1364_03_10.ck3"
    assert save_checksum(real) == "5a86b836cd32"
    assert len(save_checksum(real)) == CHECKSUM_LENGTH
    assert portrait_name(real, 50544311) == "5a86b836cd32_50544311.png"
    assert arms_name(real, 42) == "5a86b836cd32_arms_42.png"
    # the base name is what is hashed, so where the save sits cannot matter
    assert save_checksum(f"/wherever/{real}") == save_checksum(real)


def test_a_different_save_means_a_different_portrait():
    assert portrait_name("a.ck3", 7) != portrait_name("b.ck3", 7)
    assert portrait_name("a.ck3", 7) != portrait_name("a.ck3", 8)

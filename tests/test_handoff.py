import csv
import json

from ck3parser.handoff import (
    COLUMNS,
    HOUSE_COLUMNS,
    HandoffCharacter,
    describe,
    houses_of,
    interesting_ids,
    living_characters,
    main,
    select,
    slug,
)
from ck3parser.portraits import arms_name, portrait_name
from ck3parser.parser import parse_text
from ck3parser.titles import build_index
from helpers import SUCCESSION_EDITS, fixture_text, make_save


def test_interesting_ids_are_everyone_who_ever_held_the_lineage(tmp_path):
    index = build_index(make_save(tmp_path / "a.ck3"))
    lineage = [index.get("k_testland"), *index.immediate_vassals("k_testland")]
    # the kingdom's four holders plus the two vassals' holder
    assert interesting_ids(lineage) == {100, 101, 102, 200, 201}


def test_living_characters_excludes_the_dead(tmp_path):
    save = make_save(tmp_path / "a.ck3")
    # 100/101/102 are in dead_unprunable, 300 in dead_prunable, 200/201 alive
    assert set(living_characters(save, {100, 101, 102, 200, 201, 300})) == {200, 201}
    assert living_characters(save, set()) == {}


def test_a_character_in_living_but_marked_dead_is_not_harvestable(tmp_path):
    # someone who died on the save's own date can still sit in `living`
    save = make_save(
        tmp_path / "a.ck3",
        edits=(('	201={\n\t\tfirst_name="Vassal"', '	201={\n\t\tdead_data={\n\t\t\tdate=1100.6.1\n\t\t}\n\n\t\tfirst_name="Vassal"'),),
    )
    assert set(living_characters(save, {200, 201})) == {200}


def test_describe_reads_the_fields_the_harvester_keeps():
    living = parse_text(fixture_text())["living"]
    assert describe(200, living["200"], "1100.6.1") == HandoffCharacter(
        character_id=200, birth_year=1060, sex="male", dynasty_house=500, save_date="1100.6.1"
    )
    assert describe(202, living["202"], "1100.6.1").sex == "female"
    assert describe(203, living["203"], "1100.6.1").dynasty_house is None


def test_select_returns_only_the_living_lineage(tmp_path, capsys):
    chosen = select(make_save(tmp_path / "a.ck3"), "k_testland")
    assert [c.character_id for c in chosen] == [200, 201]
    assert {c.save_date for c in chosen} == {"1100.6.1"}
    assert "harvestable: 2 of 5 alive at 1100.6.1" in capsys.readouterr().err


def test_row_blanks_missing_values():
    row = HandoffCharacter(1, None, None, None, "1100.6.1").row()
    assert row == {
        "character_id": 1, "birth_year": "", "sex": "", "dynasty_house": "",
        "save_date": "1100.6.1", "portrait_file": "",
    }


def test_the_handoff_carries_the_portrait_name_the_wiki_links(tmp_path):
    save = make_save(tmp_path / "a.ck3")
    chosen = select(str(save), "k_testland")
    assert chosen[0].portrait_file == portrait_name(str(save), 200)


def test_houses_are_handed_off_with_their_arms(tmp_path):
    save = str(make_save(tmp_path / "a.ck3"))
    chosen = select(save, "k_testland")
    houses = houses_of(save, chosen, "1100.6.1")
    assert [h.house_id for h in houses] == [500]
    house = houses[0]
    assert house.dynasty_id == 50 and house.coat_of_arms_id == 900
    assert house.name == "of Test" and house.found_date == "1040.3.2"
    assert house.motto == "motto_x_under_y_king"
    assert house.arms_file == arms_name(save, 900)


def test_slug_makes_a_filename_safe_date():
    assert slug("1364.3.10") == "1364_3_10"


# ---------------------------------------------------------------- the CLI


def _run_dir(tmp_path):
    make_save(tmp_path / "a_1100.ck3", date="1100.6.1", seed=7, random_count=100)
    make_save(tmp_path / "b_1120.ck3", date="1120.1.1", seed=7, random_count=200, edits=SUCCESSION_EDITS)
    return tmp_path


def test_cli_writes_one_file_per_snapshot(tmp_path):
    out = tmp_path / "out"
    assert main([str(_run_dir(tmp_path)), "--title", "k_testland", "--out", str(out)]) == 0
    manifest = json.loads((out / "handoff.json").read_text())
    assert manifest["title"] == "k_testland"
    assert [s["save_date"] for s in manifest["snapshots"]] == ["1100.6.1", "1120.1.1"]
    assert [s["file"] for s in manifest["snapshots"]] == ["characters_1100_6_1.csv", "characters_1120_1_1.csv"]
    rows = list(csv.DictReader((out / "characters_1100_6_1.csv").open()))
    assert list(rows[0]) == list(COLUMNS)
    assert [r["character_id"] for r in rows] == ["200", "201"]
    assert rows[0]["birth_year"] == "1060" and rows[0]["sex"] == "male"


def test_cli_writes_the_houses_beside_the_characters(tmp_path):
    out = tmp_path / "out"
    assert main([str(_run_dir(tmp_path)), "--title", "k_testland", "--out", str(out)]) == 0
    snapshot = json.loads((out / "handoff.json").read_text())["snapshots"][0]
    assert snapshot["houses_file"] == "houses_1100_6_1.csv" and snapshot["houses"] == 1
    rows = list(csv.DictReader((out / "houses_1100_6_1.csv").open()))
    assert list(rows[0]) == list(HOUSE_COLUMNS)
    assert rows[0]["house_id"] == "500" and rows[0]["coat_of_arms_id"] == "900"
    assert rows[0]["arms_file"].endswith("_arms_900.png")


def test_the_list_changes_with_the_snapshot(tmp_path):
    out = tmp_path / "out"
    main([str(_run_dir(tmp_path)), "--title", "k_testland", "--out", str(out)])
    late = list(csv.DictReader((out / "characters_1120_1_1.csv").open()))
    assert {r["save_date"] for r in late} == {"1120.1.1"}


def test_ids_only_writes_the_bare_form(tmp_path):
    out = tmp_path / "out"
    assert main([str(_run_dir(tmp_path)), "--title", "k_testland", "--out", str(out), "--ids-only"]) == 0
    assert (out / "characters_1100_6_1.txt").read_text() == "200\n201\n"
    assert json.loads((out / "handoff.json").read_text())["snapshots"][0]["file"].endswith(".txt")


def test_no_character_names_are_ever_written(tmp_path):
    # a house's name is not a person's name, and the house list keeps it; the
    # character list still carries no name column at all
    out = tmp_path / "out"
    main([str(_run_dir(tmp_path)), "--title", "k_testland", "--out", str(out)])
    text = (out / "characters_1100_6_1.csv").read_text()
    assert "Test" not in text and "name" not in text


def test_unknown_title_is_an_argument_error(tmp_path, capsys):
    assert main([str(make_save(tmp_path / "a.ck3")), "--title", "k_nope", "--out", str(tmp_path / "o")]) == 2
    err = capsys.readouterr().err
    assert "'k_nope' is not in a.ck3, skipped" in err
    assert "no harvestable characters for 'k_nope'" in err


def test_a_lineage_with_nobody_alive_writes_no_file(tmp_path, capsys):
    # d_empty has no holder and no history, so nobody is harvestable
    out = tmp_path / "out"
    assert main([str(make_save(tmp_path / "a.ck3")), "--title", "d_empty", "--out", str(out)]) == 2
    assert "nobody harvestable" in capsys.readouterr().err
    assert not (out / "handoff.json").exists()

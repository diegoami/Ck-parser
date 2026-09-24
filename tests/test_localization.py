import json

import pytest

from ck3parser.localization import SCHEMA, Localization, parse


def test_a_line_is_read_past_version_digits_comments_and_escapes():
    text = (
        "﻿l_english:\n"
        ' A_sa:0 "Åsa"\n'
        ' death_depressed:0 "$death_spindly$" # a trailing comment\n'
        ' quoted: "said \\"hello\\""\n'
        ' # key_in_comment:0 "no"\n'
        ' A_sa:1 "second definition loses"\n'
    )
    assert parse(text) == {
        "A_sa": "Åsa", "death_depressed": "$death_spindly$", "quoted": 'said "hello"',
    }


def test_references_resolve_and_a_missing_one_answers_nothing():
    loc = Localization({"a": "$b$ and $c$", "b": "B", "c": "$b$!", "loop": "$loop$", "bad": "$nope$"})
    assert loc.text("a") == "B and B!"
    assert loc.text("loop") is None and loc.text("bad") is None and loc.text("absent") is None
    assert loc.used == {"a", "b", "c"}  # what answered, references included


def test_a_template_is_filled_or_left_alone():
    loc = Localization({
        "death_drinking_passive": "drank [CHARACTER.GetHerselfHimself] to death",
        "death_murder": "was murdered by [TARGET_CHARACTER.GetUIName]",
        "death_ill": "died of [GetTrait('ill').GetName( CHARACTER.Self )]",
        "trait_ill": "Illness",
        "death_odd": "was [CHARACTER.GetFirstName]'s own undoing",
        "death_bold": "#bold died#!",
    })
    assert loc.render("death_drinking_passive", female=True) == "drank herself to death"
    assert loc.render("death_drinking_passive", female=False) == "drank himself to death"
    assert loc.render("death_murder", killer="Ragnar") == "was murdered by Ragnar"
    assert loc.render("death_ill") == "died of Illness"
    # never guessed: no killer named, an unknown expression, formatting
    assert loc.render("death_murder") is None
    assert loc.render("death_drinking_passive") is None  # no sex to choose a pronoun
    assert loc.render("death_odd", female=True) is None
    assert loc.render("death_bold") is None


def test_the_extract_holds_only_what_was_used(tmp_path):
    loc = Localization({"A_sa": "Åsa", "unused": "x", "k_denmark": "Denmark"})
    loc.text("A_sa")
    path = tmp_path / "localization.json"
    assert loc.write_extract(path) == 1
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {"schema": SCHEMA, "keys": {"A_sa": "Åsa"}}
    assert Localization.from_extract(path).text("A_sa") == "Åsa"
    path.write_text('{"schema": "other"}', encoding="utf-8")
    with pytest.raises(ValueError):
        Localization.from_extract(path)


def test_the_game_folder_is_read_with_its_subfolders(tmp_path):
    names = tmp_path / "game" / "localization" / "english" / "names"
    names.mkdir(parents=True)
    (names / "character_names_l_english.yml").write_text('l_english:\n A_sa:0 "Åsa"\n', encoding="utf-8")
    (names.parent / "titles_l_english.yml").write_text('l_english:\n k_x:0 "Exland"\n', encoding="utf-8")
    loc = Localization.from_game(tmp_path / "game")
    assert loc.text("A_sa") == "Åsa" and loc.text("k_x") == "Exland"

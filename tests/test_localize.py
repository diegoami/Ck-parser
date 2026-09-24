from ck3parser.localization import Localization
from ck3wiki.build import main as build_main
from ck3wiki.localize import main as localize_main
from ck3wiki.model import build_wiki
from helpers import make_save
from test_wiki import views

#: 101 falls in battle to 100; c_test loses its own name, so only the game can name it
EDITS = (
    ('\t\t\treason="death_battle"', '\t\t\treason="death_battle"\n\t\t\tkiller=100'),
    ('\tname="Test County"\n', ""),
)

GAME = {
    "Test": "Tést",
    "Founder": "Fóunder",
    "death_battle": "was slain in battle by [TARGET_CHARACTER.GetUIName]",
    "death_old_age": "died of old age",
    "death_natural_causes": "died of $cause_natural$",
    "cause_natural": "natural causes",
    "testish": "Testish, the game's",
    "test_pagan": "the Test Faith",
    "c_test": "Testshire",
    "heritage_test_north_name": "North Testic",
    "never_used": "stays out of the extract",
}


def game_dir(tmp_path, version="1.6.1.2"):
    (tmp_path / "launcher").mkdir(exist_ok=True)
    (tmp_path / "launcher" / "launcher-settings.json").write_text(
        f'{{"rawVersion": "{version}"}}', encoding="utf-8-sig")
    folder = tmp_path / "game" / "localization" / "english"
    folder.mkdir(parents=True, exist_ok=True)
    lines = "".join(f' {k}:0 "{v}"\n' for k, v in GAME.items())
    (folder / "test_l_english.yml").write_text("l_english:\n" + lines, encoding="utf-8")
    return tmp_path / "game"


def test_names_causes_titles_cultures_and_faiths_in_the_games_words(tmp_path):
    wiki = build_wiki(views(make_save(tmp_path / "a.ck3", edits=EDITS)), "k_testland", loc=Localization(dict(GAME)))
    assert wiki.characters[200].name == "Tést"
    # the killer is named, and the template filled from the save's dead_data
    assert wiki.characters[101].killer == 100
    assert wiki.characters[101].death_text == "was slain in battle by Fóunder"
    assert wiki.characters[102].death_text == "died of old age"
    assert wiki.titles["c_test"].name == "Testshire"
    assert {c.display_name for c in wiki.cultures.values() if c.templated} == {"Testish, the game's"}
    assert "the Test Faith" in {f.display_name for f in wiki.faiths.values()}
    # a faith the player named keeps its own name
    assert "Testarianism" in {f.display_name for f in wiki.faiths.values()}


def test_without_the_game_nothing_changes(tmp_path):
    wiki = build_wiki(views(make_save(tmp_path / "a.ck3", edits=EDITS)), "k_testland")
    assert wiki.characters[200].name == "Test" and wiki.characters[101].death_text is None
    assert wiki.titles["c_test"].name == "Test"  # the key, tidied, as before


def test_the_cache_carries_the_killer(tmp_path):
    # the digest stores dead_data's killer (schema 2): a warm build says the same
    from ck3wiki.build import discover, load_run

    saves = tmp_path / "saves"
    saves.mkdir()
    make_save(saves / "a.ck3", edits=EDITS)
    (run,) = discover(str(saves))
    for _ in range(2):  # cold, then warm
        wiki = load_run(run, "k_testland", cache_dir=tmp_path / "cache", loc=Localization(dict(GAME)))
        assert wiki.characters[101].death_text == "was slain in battle by Fóunder"


def test_the_extract_holds_what_the_chronicles_used_and_builds_the_same(tmp_path):
    saves = tmp_path / "saves"
    saves.mkdir()
    make_save(saves / "a.ck3", edits=EDITS)
    extract = tmp_path / "localization.json"
    assert localize_main([str(saves), "--game", str(game_dir(tmp_path)), "--out", str(extract),
                          "--title", "k_testland", "--cache", str(tmp_path / "cache")]) == 0
    keys = Localization.from_extract(extract, "1.6.1.2").table
    assert "never_used" not in keys and "cause_natural" in keys  # a reference is kept with its user
    assert keys["Test"] == "Tést"

    pages = {}
    for how, flag in (("game", ["--game", str(game_dir(tmp_path))]), ("extract", ["--localization", str(extract)])):
        # its own folder: `tmp_path / "game"` is the fake game, and a site
        # written into it made picking the chronicle depend on listing order
        site = tmp_path / f"site_{how}"
        assert build_main([str(saves), "--title", "k_testland", "--out", str(site),
                           "--cache", str(tmp_path / "cache"), *flag]) == 0
        (chronicle,) = [p for p in site.iterdir() if (p / "characters").is_dir()]
        pages[how] = (chronicle / "characters" / "101.html").read_text(encoding="utf-8")
    assert pages["game"] == pages["extract"]
    assert "was slain in battle by Fóunder" in pages["game"]


def test_prose_written_localized_survives_a_localized_build(tmp_path):
    # #54: prose written without the game's text had different facts from a
    # localized build, so every paragraph was stale and left out
    from ck3wiki.prose import main as prose_main

    saves = tmp_path / "saves"
    saves.mkdir()
    make_save(saves / "a.ck3", edits=EDITS)
    game = ["--game", str(game_dir(tmp_path))]
    common = ["--title", "k_testland", "--cache", str(tmp_path / "cache")]
    assert prose_main([str(saves), "--out", str(tmp_path / "prose"), *common, *game]) == 0
    site = tmp_path / "site"
    assert build_main([str(saves), "--out", str(site), "--prose", str(tmp_path / "prose"), *common, *game]) == 0
    (chronicle,) = [p for p in site.iterdir() if (p / "characters").is_dir()]
    page = (chronicle / "characters" / "200.html").read_text(encoding="utf-8")
    assert '<section class="prose">' in page and "Tést" in page

    # and a missing game folder is an argument error, not a traceback
    assert prose_main([str(saves), "--out", str(tmp_path / "p2"), *common, "--game", str(tmp_path / "nowhere")]) == 2



def test_a_cultures_heritage_is_the_games_name_for_it(tmp_path):
    # the save names heritage, language, ethos and martial custom by key; the
    # game keeps their names under `<key>_name`, beside `_desc`
    save = make_save(tmp_path / "a.ck3", edits=EDITS)
    localized = build_wiki(views(save), "k_testland", loc=Localization(dict(GAME)))
    plain = build_wiki(views(save), "k_testland")
    assert {c.heritage for c in localized.cultures.values()} == {"North Testic"}
    assert {c.heritage for c in plain.cultures.values()} == {"Test North"}  # the key, tidied, as before
    assert "heritage_test_north_name" in localized.loc.used  # so the extract keeps it


def test_the_games_text_is_only_used_for_its_own_version(tmp_path, capsys):
    # #58: a 1.4.4 save next to a 1.6.1.2 install is left as it was before #31
    saves = tmp_path / "saves"
    saves.mkdir()
    make_save(saves / "old.ck3", seed=9, version='"1.4.4"', edits=EDITS)
    make_save(saves / "new.ck3", seed=7, edits=EDITS)
    extract = tmp_path / "localization.json"
    common = ["--title", "k_testland", "--cache", str(tmp_path / "cache")]
    assert localize_main([str(saves), "--game", str(game_dir(tmp_path)), "--out", str(extract), *common]) == 0
    err = capsys.readouterr().err
    assert "skipped, the save was made on 1.4.4, the install is 1.6.1.2" in err
    assert list(Localization.extract_versions(extract)) == ["1.6.1.2"]

    for flag in (["--game", str(game_dir(tmp_path))], ["--localization", str(extract)]):
        site = tmp_path / ("site_" + flag[0].strip("-"))
        assert build_main([str(saves), "--out", str(site), *common, *flag]) == 0
        pages = {p.name: (p / "characters" / "200.html").read_text(encoding="utf-8")
                 for p in site.iterdir() if (p / "characters").is_dir()}
        assert "Tést" in pages["7-1-6-1-2"]  # its own version: localized
        assert "Tést" not in pages["9-1-4-4"] and "Test" in pages["9-1-4-4"]  # another: as before
        assert "not localized" in capsys.readouterr().err


def test_an_extract_keeps_each_versions_section(tmp_path):
    path = tmp_path / "localization.json"
    for version, name in (("1.6.1.2", "Tést"), ("1.4.4", "Testé")):
        loc = Localization({"Test": name}, version=version)
        loc.text("Test")
        loc.write_extract(path)
    assert sorted(Localization.extract_versions(path)) == ["1.4.4", "1.6.1.2"]
    assert Localization.from_extract(path, "1.4.4").text("Test") == "Testé"
    assert Localization.from_extract(path, "1.3.1") is None


def test_an_install_of_unknown_version_is_refused(tmp_path, capsys):
    from ck3parser.install import game_version, mismatch

    assert game_version(tmp_path / "nowhere" / "game") is None
    assert "unknown" in mismatch(None, "1.6.1.2") and "unknown" in mismatch("1.6.1.2", None)
    assert mismatch("1.6.1.2", "1.6.1.2") is None
    saves = tmp_path / "saves"
    saves.mkdir()
    make_save(saves / "a.ck3")
    game = game_dir(tmp_path)
    (tmp_path / "launcher" / "launcher-settings.json").unlink()
    assert localize_main([str(saves), "--game", str(game), "--out", str(tmp_path / "x.json"),
                          "--title", "k_testland", "--cache", str(tmp_path / "cache")]) == 2
    assert not (tmp_path / "x.json").exists()

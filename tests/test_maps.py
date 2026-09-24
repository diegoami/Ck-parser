import pytest

np = pytest.importorskip("numpy")
Image = pytest.importorskip("PIL.Image")

from ck3parser.portraits import realm_map_name  # noqa: E402
from ck3parser.titles import build_index  # noqa: E402
from ck3wiki.maps import PALETTE, GameMap, main, province_classes, render  # noqa: E402
from helpers import make_save  # noqa: E402

#: three baronies: b_one in c_test (held by a direct vassal of 200), b_two in
#: c_far (a vassal's vassal), b_three in d_empty -- a duchy, so no county and
#: no realm. Indices 5-7 follow c_far, the fixture's last title.
BARONIES = ((
    "\tde_jure_liege=1\n\tde_facto_liege=2\n}\n",
    "\tde_jure_liege=1\n\tde_facto_liege=2\n}\n"
    '5={\n\tkey="b_one"\n\tholder=201\n\tde_jure_liege=2\n\tde_facto_liege=2\n}\n'
    '6={\n\tkey="b_two"\n\tholder=202\n\tde_jure_liege=4\n\tde_facto_liege=4\n}\n'
    '7={\n\tkey="b_three"\n\tde_jure_liege=1\n}\n',
),)

#: province id -> its colour in provinces.png; 4 is sea, 5 belongs to no barony
COLOURS = {1: (10, 0, 0), 2: (20, 0, 0), 3: (30, 0, 0), 4: (40, 0, 0), 5: (50, 0, 0)}


def game_dir(tmp_path, version="1.6.1.2"):
    # the fixture's saves are 1.6.1.2; the install must say the same (#58)
    (tmp_path / "launcher").mkdir(exist_ok=True)
    (tmp_path / "launcher" / "launcher-settings.json").write_text(
        f'{{"rawVersion": "{version}", "version": "{version} (Test)"}}', encoding="utf-8-sig")
    root = tmp_path / "game"
    (root / "map_data").mkdir(parents=True)
    (root / "common" / "landed_titles").mkdir(parents=True)
    raster = np.array([[COLOURS[p] for p in (1, 2, 3, 4, 5)]] * 2, dtype=np.uint8)
    Image.fromarray(raster).save(root / "map_data" / "provinces.png")
    (root / "map_data" / "definition.csv").write_text(
        "0;0;0;0;x;x;\n" + "".join(f"{p};{r};{g};{b};P{p};x;\n" for p, (r, g, b) in COLOURS.items()),
        encoding="utf-8",
    )
    (root / "map_data" / "default.map").write_text("sea_zones = LIST { 4 }\n", encoding="utf-8")
    (root / "common" / "landed_titles" / "00_test.txt").write_text(
        "k_x = {\n\td_x = {\n\t\tc_x = {\n"
        "\t\t\tb_one = {\n\t\t\t\tprovince = 1\n\t\t\t}\n"
        "\t\t\tb_two = {\n\t\t\t\tprovince = 2\n\t\t\t\tcolor = { 1 2 3 }\n\t\t\t}\n"
        "\t\t\tb_three = { province = 3 }\n"
        "\t\t}\n\t}\n}\n",
        encoding="utf-8",
    )
    return root


def test_each_province_is_coloured_by_its_countys_rank(tmp_path):
    game = GameMap.load(game_dir(tmp_path))
    assert game.barony_province == {"b_one": 1, "b_two": 2, "b_three": 3} and game.water == {4}
    index = build_index(str(make_save(tmp_path / "a.ck3", edits=BARONIES)))
    classes, cover = province_classes(game, index, 200)
    # c_test is a direct vassal's, c_far a vassal's vassal's, d_empty no county
    assert classes == {1: 1, 2: 2, 3: "outside"}
    assert (cover.baronies, cover.placed, cover.unplaced) == (3, 3, [])

    pixels = np.asarray(render(game, classes, scale=1, crop=False))[0]
    assert [tuple(px) for px in pixels] == [
        PALETTE[1], PALETTE[2], PALETTE["outside"], PALETTE["sea"], PALETTE["waste"],
    ]


def test_a_province_is_found_past_nested_blocks_and_comments():
    # b_pockington and b_leeds open with cultural_names = { ... }, which a flat
    # pattern could not cross; a nested block's own `province` does not count
    from ck3wiki.maps import barony_provinces

    text = (
        "b_a = {\n\tcultural_names = {\n\t\tname_list_x = cn_a  # a comment { with a brace\n\t}\n"
        "\tprovince = 7\n}\n"
        "b_b = {\n\tholding = { province = 99 }\n\tprovince = 8\n}\n"
        "# b_c = { province = 9 }\n"
    )
    assert barony_provinces(text) == {"b_a": 7, "b_b": 8}


def test_a_barony_the_map_does_not_know_is_reported_not_guessed(tmp_path):
    root = game_dir(tmp_path)
    (root / "common" / "landed_titles" / "00_test.txt").write_text("b_one = { province = 1 }\n", encoding="utf-8")
    index = build_index(str(make_save(tmp_path / "a.ck3", edits=BARONIES)))
    classes, cover = province_classes(GameMap.load(root), index, 200)
    assert classes == {1: 1} and cover.unplaced == ["b_two", "b_three"]


def test_the_command_writes_the_map_the_page_links(tmp_path, capsys):
    saves = tmp_path / "saves"
    saves.mkdir()
    save = make_save(saves / "a.ck3", edits=BARONIES)
    out = tmp_path / "images"
    args = [str(saves), "--game", str(game_dir(tmp_path)), "--out", str(out), "--title", "k_testland",
            "--scale", "1"]
    assert main(args) == 0
    name = realm_map_name(save, "k_testland")
    assert (out / name).is_file()
    assert "3 of 3 baronies placed" in capsys.readouterr().err
    # a second run leaves it alone unless forced
    main(args)
    assert "already there" in capsys.readouterr().err


def test_the_realm_section_links_the_map_whether_or_not_it_is_there(tmp_path):
    from ck3wiki.model import build_wiki
    from ck3wiki.render import write_site
    from test_wiki import views

    save = make_save(tmp_path / "a.ck3", edits=BARONIES)
    wiki = build_wiki(views(save), "k_testland")
    name = realm_map_name(save, "k_testland")
    assert wiki.wanted_maps == [name]
    site = tmp_path / "site"
    write_site(wiki, site)
    page = (site / "titles" / "k_testland.html").read_text(encoding="utf-8")
    assert f'src="../portraits/{name}"' in page and "shot map awaited" in page

    # delivered, the next build copies it in and it is no longer awaited
    images = tmp_path / "images"
    images.mkdir()
    (images / name).write_bytes(b"png")
    write_site(wiki, site, images)
    assert (site / "portraits" / name).is_file()
    assert "shot map awaited" not in (site / "titles" / "k_testland.html").read_text(encoding="utf-8")


def test_no_game_files_is_a_clear_error(tmp_path, capsys):
    assert main([str(tmp_path), "--game", str(tmp_path / "nowhere"), "--out", str(tmp_path / "o")]) == 2
    assert "cannot find the game's map files" in capsys.readouterr().err


def test_a_save_from_another_game_version_gets_no_map(tmp_path, capsys):
    # #58: the map must come from the version that wrote the save; strict
    saves = tmp_path / "saves"
    saves.mkdir()
    save = make_save(saves / "a.ck3", version='"1.4.4"', edits=BARONIES)
    out = tmp_path / "images"
    args = [str(saves), "--game", str(game_dir(tmp_path)), "--out", str(out), "--title", "k_testland"]
    assert main(args) == 0
    assert not (out / realm_map_name(save, "k_testland")).exists()
    assert "skipped, the save was made on 1.4.4, the install is 1.6.1.2" in capsys.readouterr().err


def test_an_install_of_unknown_version_draws_nothing_and_fails(tmp_path, capsys):
    # #61: strict (#58), and a failure, not exit 0 with an empty folder
    saves = tmp_path / "saves"
    saves.mkdir()
    make_save(saves / "a.ck3", edits=BARONIES)
    game = game_dir(tmp_path)
    (tmp_path / "launcher" / "launcher-settings.json").unlink()
    out = tmp_path / "images"
    assert main([str(saves), "--game", str(game), "--out", str(out), "--title", "k_testland"]) == 2
    assert "no maps drawn" in capsys.readouterr().err and not out.exists()

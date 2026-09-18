import json
import re
from pathlib import Path

from ck3parser.pipeline import gather
from ck3parser.portraits import arms_name, portrait_name
from ck3wiki.build import discover, main, subject_of
from ck3wiki.manifest import chronicle_manifest
from ck3wiki.model import Tenure, Wiki, WikiCharacter, build_wiki, clean_name
from ck3wiki.render import (
    STYLE,
    e,
    harvested,
    render_index,
    render_landing,
    write_site,
)
from helpers import SUCCESSION_EDITS, make_save


def quiet():
    import os

    return open(os.devnull, "w")


def views(*saves, title="k_testland"):
    with quiet() as log:
        return [gather(str(s), title, log=log) for s in saves]


def two_snapshots(tmp_path):
    early = make_save(tmp_path / "a_1100.ck3", date="1100.6.1", seed=7, random_count=100)
    late = make_save(
        tmp_path / "b_1120.ck3", date="1120.1.1", seed=7, random_count=200, edits=SUCCESSION_EDITS
    )
    return early, late


# ---------------------------------------------------------------- names


def test_clean_name_drops_the_diacritic_marker_without_inventing_letters():
    assert clean_name("FranC_ois") == "Francois"  # François, diacritic dropped
    assert clean_name("O_zgul") == "Ozgul"
    assert clean_name("Is_mail") == "Ismail"
    assert clean_name("C_ilen") == "Cilen"  # leading letter keeps its case
    assert clean_name("SojA_") == "Soja"
    assert clean_name("Ludwig") == "Ludwig" and clean_name("") == ""


# ---------------------------------------------------------------- model


def test_wiki_merges_the_snapshots_of_a_run(tmp_path):
    early, late = two_snapshots(tmp_path)
    wiki = build_wiki(views(late, early), "k_testland")  # deliberately out of order
    assert wiki.snapshots == ["1100.6.1", "1120.1.1"]  # merged oldest first
    assert set(wiki.titles) == {"k_testland", "c_test", "x_mc_0"}
    kingdom = wiki.titles["k_testland"]
    assert [t.holder for t in kingdom.tenures] == [100, 101, 102, 200, 201]
    assert kingdom.holder == 201  # the later snapshot's holder wins


def test_a_tenure_seen_open_then_closed_ends_up_closed(tmp_path):
    early, late = two_snapshots(tmp_path)
    kingdom = build_wiki(views(early, late), "k_testland").titles["k_testland"]
    ruler_200 = next(t for t in kingdom.tenures if t.holder == 200)
    assert ruler_200.end == "1110.5.5" and not ruler_200.open
    assert next(t for t in kingdom.tenures if t.holder == 201).open


def test_vassals_are_recorded_per_snapshot(tmp_path):
    early, late = two_snapshots(tmp_path)
    kingdom = build_wiki(views(early, late), "k_testland").titles["k_testland"]
    assert sorted(kingdom.vassals) == ["1100.6.1", "1120.1.1"]
    assert kingdom.all_vassals == ["c_test", "x_mc_0"]


def test_characters_carry_death_and_the_saves_they_were_seen_in(tmp_path):
    early, late = two_snapshots(tmp_path)
    wiki = build_wiki(views(early, late), "k_testland")
    founder = wiki.characters[100]
    assert founder.death == "880.5.5" and founder.death_reason == "death_natural_causes"
    assert not founder.alive_at_last_sight and founder.lifespan == "830.1.1 – 880.5.5"
    assert wiki.characters[200].seen == ["1100.6.1", "1120.1.1"]
    assert wiki.characters[200].alive_at_last_sight


def test_held_by_lists_a_characters_reigns_in_order(tmp_path):
    early, _ = two_snapshots(tmp_path)
    wiki = build_wiki(views(early), "k_testland")
    assert [t.key for t, _ in wiki.held_by(201)] == ["c_test", "x_mc_0"]
    assert wiki.held_by(999999) == []


def test_named_falls_back_to_the_id():
    wiki = Wiki(run_id="r", title_key="k")
    assert wiki.named(7) == "Character 7"
    wiki.characters[7] = WikiCharacter(id=7, name="Ada")
    assert wiki.named(7) == "Ada"


# ---------------------------------------------------------------- render


def test_escaping_is_applied():
    assert e("<script>") == "&lt;script&gt;" and e(None) == ""


def test_index_lists_titles_and_characters(tmp_path):
    early, _ = two_snapshots(tmp_path)
    html = render_index(build_wiki(views(early), "k_testland"))
    assert "<!doctype html>" in html and "CK3 Chronicle" in html
    assert 'href="titles/k_testland.html"' in html
    assert 'href="characters/200.html"' in html


def test_write_site_produces_a_page_per_entity(tmp_path):
    early, late = two_snapshots(tmp_path)
    wiki = build_wiki(views(early, late), "k_testland")
    out = tmp_path / "site"
    pages = write_site(wiki, out)
    assert pages == 1 + len(wiki.titles) + len(wiki.characters) + len(wiki.houses)
    assert (out / "index.html").is_file() and (out / "style.css").read_text() == STYLE
    title_page = (out / "titles" / "k_testland.html").read_text()
    assert "Succession" in title_page and "../characters/200.html" in title_page
    assert "Kingdom of Testland" in title_page
    character_page = (out / "characters" / "100.html").read_text()
    assert "880.5.5" in character_page and "../titles/k_testland.html" in character_page


def test_a_portrait_is_linked_whether_or_not_it_has_been_harvested(tmp_path):
    early, _ = two_snapshots(tmp_path)
    wiki = build_wiki(views(early), "k_testland")
    wanted = wiki.characters[200].portraits[0].file
    assert wanted == portrait_name(str(early), 200)  # both projects derive this

    out = tmp_path / "site"
    write_site(wiki, out)  # nothing harvested yet
    page_html = (out / "characters" / "200.html").read_text()
    assert f'src="../portraits/{wanted}"' in page_html  # the link is there first
    assert "awaited" in page_html

    shots = tmp_path / "shots"
    shots.mkdir()
    (shots / wanted).write_bytes(b"\x89PNG")
    (shots / "another-run.png").write_bytes(b"\x89PNG")  # belongs to another chronicle
    assert harvested(shots) == {wanted, "another-run.png"} and harvested(None) == set()
    write_site(wiki, out, shots)
    page_html = (out / "characters" / "200.html").read_text()
    assert f'src="../portraits/{wanted}"' in page_html  # unchanged, as promised
    assert "awaited" not in page_html
    assert (out / "portraits" / wanted).is_file()
    # one directory can hold every run's images; a chronicle copies only its own
    assert not (out / "portraits" / "another-run.png").exists()


def test_a_character_gets_one_portrait_per_save_they_appear_in(tmp_path):
    early, late = two_snapshots(tmp_path)
    wiki = build_wiki(views(early, late), "k_testland")
    shots = wiki.characters[200].portraits
    assert [p.save_date for p in shots] == ["1100.6.1", "1120.1.1"]
    assert [p.save for p in shots] == ["a_1100.ck3", "b_1120.ck3"]
    assert len({p.file for p in shots}) == 2  # a different image per save
    out = tmp_path / "site"
    write_site(wiki, out)
    page_html = (out / "characters" / "200.html").read_text()
    assert "<h2>Portraits</h2>" in page_html
    for shot in shots:
        assert shot.file in page_html


def test_houses_are_read_from_the_save_and_get_a_page(tmp_path):
    early, _ = two_snapshots(tmp_path)
    wiki = build_wiki(views(early), "k_testland")
    house = wiki.houses[500]
    assert house.name == "of Test"  # the name key, with its prefix key
    assert house.dynasty is not None and house.dynasty.id == 50
    # eldest first, and 830.1.1 is before 1060.1.1: dates sort as dates
    assert [c.id for c in wiki.members_of(500)] == [100, 101, 102, 201, 200]
    out = tmp_path / "site"
    write_site(wiki, out)
    house_page = (out / "houses" / "500.html").read_text()
    assert "of Test" in house_page and "../characters/200.html" in house_page
    assert "1040.3.2" in house_page  # founded
    assert '<a href="../houses/500.html">' in (out / "characters" / "200.html").read_text()
    assert 'href="houses/500.html"' in (out / "index.html").read_text()


def test_a_houses_arms_are_wanted_too_and_scoped_to_the_save(tmp_path):
    early, _ = two_snapshots(tmp_path)
    wiki = build_wiki(views(early), "k_testland")
    arms = wiki.houses[500].arms
    assert arms is not None and arms.file == arms_name(str(early), 900)
    assert arms.coat_of_arms_id == 900 and arms.house == 500
    out = tmp_path / "site"
    write_site(wiki, out)
    assert f'src="../portraits/{arms.file}"' in (out / "houses" / "500.html").read_text()
    entry = next(
        p for p in chronicle_manifest(wiki, "s", have=set())["portraits"] if p["file"] == arms.file
    )
    assert entry["kind"] == "arms" and entry["page"] == "houses/500.html" and not entry["have"]


def test_the_manifest_lists_every_wanted_image_and_what_is_missing(tmp_path):
    early, late = two_snapshots(tmp_path)
    wiki = build_wiki(views(early, late), "k_testland")
    one = wiki.characters[200].portraits[0].file
    manifest = chronicle_manifest(wiki, "7-1-6-1-2", have={one})
    assert manifest["chronicle"] == "7-1-6-1-2" and manifest["images"] == "portraits"
    assert [s["file"] for s in manifest["saves"]] == ["a_1100.ck3", "b_1120.ck3"]
    entry = next(p for p in manifest["portraits"] if p["file"] == one)
    assert entry["kind"] == "portrait" and entry["character"] == 200 and entry["have"]
    assert entry["save"] == "a_1100.ck3" and entry["page"] == "characters/200.html"
    assert manifest["wanted"] == len(manifest["portraits"])
    assert manifest["missing"] == manifest["wanted"] - 1
    # names are never handed off; the companion drops them on principle
    assert "name" not in entry and "Test" not in json.dumps(manifest)


def test_the_build_writes_a_manifest_the_companion_can_scan(tmp_path):
    two_snapshots(tmp_path)
    out = tmp_path / "site"
    assert main([str(tmp_path), "--title", "k_testland", "--out", str(out)]) == 0
    root = json.loads((out / "portraits.json").read_text())
    assert root["chronicles"][0]["manifest"] == "7-1-6-1-2/portraits.json"
    assert root["missing"] == root["wanted"] > 0
    chronicle = json.loads((out / "7-1-6-1-2" / "portraits.json").read_text())
    assert chronicle["schema"] == root["schema"]
    assert all(not p["have"] for p in chronicle["portraits"])


# ---------------------------------------------------------------- the CLI


def test_cli_builds_one_chronicle_per_run(tmp_path, capsys):
    two_snapshots(tmp_path)
    out = tmp_path / "site"
    assert main([str(tmp_path), "--title", "k_testland", "--out", str(out)]) == 0
    assert "1 run(s) to build" in capsys.readouterr().err
    # the landing page sits above the chronicles, which are keyed by seed+version
    assert (out / "index.html").is_file()
    assert (out / "7-1-6-1-2" / "index.html").is_file()
    assert sorted(p.name for p in (out / "7-1-6-1-2" / "titles").iterdir()) == [
        "c_test.html", "k_testland.html", "x_mc_0.html"
    ]
    landing = (out / "index.html").read_text()
    assert 'href="7-1-6-1-2/index.html"' in landing and "576691683" not in landing


def test_two_runs_become_two_chronicles(tmp_path, capsys):
    make_save(tmp_path / "one.ck3", date="1100.6.1", seed=7, random_count=100)
    make_save(tmp_path / "two.ck3", date="1100.6.1", seed=8, random_count=100)
    out = tmp_path / "site"
    assert main([str(tmp_path), "--title", "k_testland", "--out", str(out)]) == 0
    assert "2 run(s) to build" in capsys.readouterr().err
    assert (out / "7-1-6-1-2" / "index.html").is_file()
    assert (out / "8-1-6-1-2" / "index.html").is_file()
    landing = (out / "index.html").read_text()
    assert landing.count('/index.html">') == 2


def test_the_same_seed_on_a_different_version_is_a_separate_chronicle(tmp_path):
    make_save(tmp_path / "one.ck3", date="1100.6.1", seed=7, random_count=100)
    make_save(tmp_path / "two.ck3", date="1100.6.1", seed=7, random_count=100, version='"1.7.0.0"')
    out = tmp_path / "site"
    assert main([str(tmp_path), "--title", "k_testland", "--out", str(out)]) == 0
    assert (out / "7-1-6-1-2" / "index.html").is_file()
    assert (out / "7-1-7-0-0" / "index.html").is_file()


def test_a_chronicle_links_back_to_the_landing_page(tmp_path):
    two_snapshots(tmp_path)
    out = tmp_path / "site"
    main([str(tmp_path), "--title", "k_testland", "--out", str(out)])
    assert 'href="../index.html">All chronicles' in (out / "7-1-6-1-2" / "index.html").read_text()
    assert 'href="../../index.html">All chronicles' in (
        out / "7-1-6-1-2" / "titles" / "k_testland.html"
    ).read_text()


def test_cli_rejects_an_unknown_title(tmp_path, capsys):
    two_snapshots(tmp_path)
    assert main([str(tmp_path), "--title", "k_nope", "--out", str(tmp_path / "s")]) == 2
    assert "no chronicles could be built" in capsys.readouterr().err


def test_discover_finds_runs_from_a_file_or_a_directory(tmp_path):
    early, _ = two_snapshots(tmp_path)
    assert [r.slug for r in discover(str(early))] == ["7-1-6-1-2"]
    assert [len(r.snapshots) for r in discover(str(tmp_path))] == [2]
    assert [r.slug for r in discover(str(tmp_path), run_id="7-1-6-1-2")] == ["7-1-6-1-2"]


def test_discover_complains_about_nothing_to_build(tmp_path):
    import pytest as _pytest

    with _pytest.raises(FileNotFoundError):
        discover(str(tmp_path))
    with _pytest.raises(FileNotFoundError):
        discover(str(tmp_path / "nope.ck3"))


def test_subject_defaults_to_the_played_characters_primary_title(tmp_path, capsys):
    early, _ = two_snapshots(tmp_path)
    run = discover(str(early))[0]
    with quiet() as log:
        # the fixture's played character holds k_testland
        assert subject_of(run, None, log) == "k_testland"
        assert subject_of(run, "c_test", log) == "c_test"


def test_landing_page_names_what_separates_the_runs():
    html = render_landing([
        {"slug": "7-1-6-1-2", "name": "Testland", "seed": 7, "version": "1.6.1.2",
         "snapshots": 2, "titles": 3, "characters": 5}
    ])
    assert "seed" in html.lower() and "version" in html.lower()
    assert 'href="7-1-6-1-2/index.html"' in html and "Testland" in html


def test_an_open_tenure_takes_the_latest_snapshots_end_date(tmp_path):
    # the current ruler's reign runs to whenever we last looked, not to the
    # first snapshot that saw it open
    early = make_save(tmp_path / "a_1100.ck3", date="1100.6.1", seed=7, random_count=100)
    later = make_save(tmp_path / "b_1120.ck3", date="1120.1.1", seed=7, random_count=200)
    kingdom = build_wiki(views(early, later), "k_testland").titles["k_testland"]
    current = next(t for t in kingdom.tenures if t.open)
    assert current.holder == 200 and current.end == "1120.1.1"
    # and the order the snapshots arrive in must not matter
    other = build_wiki(views(later, early), "k_testland").titles["k_testland"]
    assert next(t for t in other.tenures if t.open).end == "1120.1.1"


def test_the_infobox_is_a_grid_column_not_a_float(tmp_path):
    early, _ = two_snapshots(tmp_path)
    out = tmp_path / "site"
    write_site(build_wiki(views(early), "k_testland"), out)
    assert not re.search(r"float\s*:\s*(left|right)", STYLE)  # the declaration, not the prose
    page_html = (out / "titles" / "k_testland.html").read_text()
    assert '<div class="page">' in page_html and '<aside class="infobox card">' in page_html

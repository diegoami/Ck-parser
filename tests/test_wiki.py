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
from helpers import SUCCESSION_EDITS, VASSAL_MOVE_EDITS, make_save


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
    # the marker follows the letter it modifies, except on the first letter,
    # where it comes in front: `_Odgrim` is Ǫdgrim
    assert clean_name("_Odgrim") == "Odgrim"
    assert clean_name("BuR_islav") == "Burislav"


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


def test_index_lists_titles_characters_houses_and_what_is_missing(tmp_path):
    early, _ = two_snapshots(tmp_path)
    wiki = build_wiki(views(early), "k_testland")
    html = render_index(wiki)
    assert "<!doctype html>" in html and "CK3 Chronicle" in html
    assert 'href="titles/k_testland.html"' in html
    assert 'href="characters/200.html"' in html
    assert 'href="houses/500.html"' in html
    total = len(wiki.wanted_portraits) + len(wiki.wanted_arms)
    assert f"{total} images are linked" in html
    assert f"{total} are still to be harvested" in html
    # and one already in hand is one fewer to ask for
    one = wiki.characters[200].portraits[0].file
    assert f"{total - 1} are still to be harvested" in render_index(wiki, {one})


def test_write_site_produces_a_page_per_entity(tmp_path):
    early, late = two_snapshots(tmp_path)
    wiki = build_wiki(views(early, late), "k_testland")
    out = tmp_path / "site"
    pages = write_site(wiki, out)
    assert pages == 1 + len(wiki.titles) + len(wiki.characters) + len(wiki.houses) + len(
        wiki.cultures
    ) + len(wiki.faiths)
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


def test_the_dead_are_never_asked_for(tmp_path):
    # the companion harvests by switching to a character with `play <id>`, which
    # the game refuses for the dead, so a portrait of someone already buried is
    # work nobody can do. 1 277 of the Germania chronicle's 1 330 slots were
    # exactly that before this was enforced.
    early, _ = two_snapshots(tmp_path)
    wiki = build_wiki(views(early), "k_testland")
    founder = wiki.characters[100]
    assert founder.death == "880.5.5" and founder.portraits == []
    assert wiki.characters[200].portraits  # alive at 1100.6.1, so asked for

    out = tmp_path / "site"
    write_site(wiki, out)
    assert "<img" not in (out / "characters" / "100.html").read_text()
    assert not any(p["character"] == 100 for p in
                   chronicle_manifest(wiki, "s", have=set())["portraits"]
                   if p["kind"] == "portrait")


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
    # eldest first, and 830.1.1 is before 1060.1.1: dates sort as dates.
    # 205 is here because he is 200's brother, which is a page's worth on its own
    assert [c.id for c in wiki.members_of(500)] == [100, 101, 102, 201, 205, 200]
    out = tmp_path / "site"
    write_site(wiki, out)
    house_page = (out / "houses" / "500.html").read_text()
    assert "of Test" in house_page and "../characters/200.html" in house_page
    assert "1040.3.2" in house_page  # founded
    assert '<a href="../houses/500.html">' in (out / "characters" / "200.html").read_text()
    assert 'href="houses/500.html"' in (out / "index.html").read_text()


def test_a_houses_arms_are_named_after_the_recipe_that_draws_them(tmp_path):
    # the id indexes one save, so it cannot name a picture across runs; the
    # recipe can, and the same arms are then one file everywhere
    from ck3parser.arms import read_arms

    early, _ = two_snapshots(tmp_path)
    wiki = build_wiki(views(early), "k_testland")
    arms = wiki.houses[500].arms
    recipe = read_arms(str(early), {900})[900]
    assert arms is not None and arms.file == arms_name(recipe.digest)
    assert "900" not in arms.file  # the id is not in the name
    assert arms.coat_of_arms_id == 900 and arms.house == 500
    # and the recipe rides along, so a companion can draw it instead
    assert ["pattern", "pattern_solid.dds"] in arms.definition
    out = tmp_path / "site"
    write_site(wiki, out)
    assert f'src="../portraits/{arms.file}"' in (out / "houses" / "500.html").read_text()
    entry = next(
        p for p in chronicle_manifest(wiki, "s", have=set())["portraits"] if p["file"] == arms.file
    )
    # c_test bears the same arms, so the two collapse to one request that names
    # both bearers rather than two requests for the same picture
    assert entry["kind"] == "arms" and not entry["have"]
    assert set(entry["borne_by"]) == {"titles/c_test.html", "houses/500.html"}


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


# ---------------------------------------------------------------- vassalage


def test_a_vassal_that_moves_is_seen_by_the_snapshots_disagreeing(tmp_path):
    early = make_save(tmp_path / "a_1100.ck3", date="1100.6.1", seed=7, random_count=100)
    late = make_save(
        tmp_path / "b_1120.ck3", date="1120.1.1", seed=7, random_count=200, edits=VASSAL_MOVE_EDITS
    )
    wiki = build_wiki(views(early, late), "k_testland")
    moved = wiki.titles["x_mc_0"].vassalage(wiki.snapshots)
    assert [v.liege for v in moved] == ["k_testland", "c_test"]
    assert moved[1].began == "1100.6.1 – 1120.1.1"
    # and it is gone from the subject's vassals in the later snapshot
    kingdom = wiki.titles["k_testland"]
    assert "x_mc_0" in kingdom.vassals["1100.6.1"]
    assert "x_mc_0" not in kingdom.vassals["1120.1.1"]


def test_a_liege_outside_the_lineage_is_named_not_assumed(tmp_path):
    # the old code asserted every non-subject title's liege to be the subject,
    # because that is how it was selected; the save is asked instead
    early = make_save(tmp_path / "a_1100.ck3", date="1100.6.1", seed=7, random_count=100)
    late = make_save(
        tmp_path / "b_1120.ck3", date="1120.1.1", seed=7, random_count=200, edits=VASSAL_MOVE_EDITS
    )
    wiki = build_wiki(views(early, late), "k_testland")
    assert wiki.titles["x_mc_0"].liege == "c_test"  # its newest answer, not the subject
    assert wiki.titles["k_testland"].liege is None  # the subject answers to nobody


def test_the_subject_page_says_what_joined_and_left(tmp_path):
    early = make_save(tmp_path / "a_1100.ck3", date="1100.6.1", seed=7, random_count=100)
    late = make_save(
        tmp_path / "b_1120.ck3", date="1120.1.1", seed=7, random_count=200, edits=VASSAL_MOVE_EDITS
    )
    wiki = build_wiki(views(early, late), "k_testland")
    out = tmp_path / "site"
    write_site(wiki, out)
    kingdom_page = (out / "titles" / "k_testland.html").read_text()
    assert "<h2>Vassalage</h2>" in kingdom_page
    assert "1 left" in kingdom_page and "Between <strong>1100.6.1</strong>" in kingdom_page

    moved_page = (out / "titles" / "x_mc_0.html").read_text()
    assert "1100.6.1 – 1120.1.1" in moved_page
    assert '../titles/c_test.html' in moved_page


def test_vassalage_never_claims_a_date_the_save_does_not_give(tmp_path):
    # the whole point: a save says who holds a title and since when, but never
    # who its liege has been, so no exact date may appear for a change
    early = make_save(tmp_path / "a_1100.ck3", date="1100.6.1", seed=7, random_count=100)
    late = make_save(
        tmp_path / "b_1120.ck3", date="1120.1.1", seed=7, random_count=200, edits=VASSAL_MOVE_EDITS
    )
    wiki = build_wiki(views(early, late), "k_testland")
    for stretch in wiki.titles["x_mc_0"].vassalage(wiki.snapshots):
        for phrase in (stretch.began, stretch.ended):
            if phrase:
                # "by X" or a window "X – Y"; never a bare date claiming to be
                # the day it happened
                assert phrase.startswith("by ") or " – " in phrase, phrase


# ---------------------------------------------------------------- family


def test_family_reaches_the_character_pages(tmp_path):
    early, _ = two_snapshots(tmp_path)
    wiki = build_wiki(views(early), "k_testland")
    parent = wiki.characters[200]
    assert parent.children == [203, 204] and parent.spouses == [202]
    assert parent.has_family

    out = tmp_path / "site"
    write_site(wiki, out)
    page_html = (out / "characters" / "200.html").read_text()
    assert "<h2>Family</h2>" in page_html and "Children" in page_html
    assert "Spouse" in page_html


def test_the_direct_line_is_promoted_to_pages_of_its_own(tmp_path):
    # holding a title is what puts the others in; these are here by blood or
    # marriage. 202 is a spouse, 203 and 204 are children, and none of them
    # hold anything in this lineage.
    early, _ = two_snapshots(tmp_path)
    wiki = build_wiki(views(early), "k_testland")
    for cid in (202, 203, 204):
        assert cid in wiki.characters, cid
    assert wiki.characters[203].parents == [200, 202]
    assert wiki.characters[203].siblings == [204]

    out = tmp_path / "site"
    write_site(wiki, out)
    assert (out / "characters" / "202.html").is_file()
    assert '../characters/202.html' in (out / "characters" / "200.html").read_text()


def test_a_sibling_gets_a_page_and_no_siblings_takes_it_away(tmp_path):
    # a succession is usually a quarrel between siblings, so the brother who was
    # passed over is worth a page; --no-siblings goes back to the narrow line
    early, _ = two_snapshots(tmp_path)
    wiki = build_wiki(views(early), "k_testland")
    from ck3wiki.model import direct_line

    line = direct_line(wiki.characters[200])
    assert 205 in line  # the brother who was passed over
    assert 102 in line and 202 in line  # and the father and the spouse, as before
    assert 205 not in direct_line(wiki.characters[200], with_siblings=False)


def test_no_siblings_leaves_them_named_but_page_less(tmp_path):
    early, _ = two_snapshots(tmp_path)
    narrow = build_wiki(views(early), "k_testland", with_siblings=False)
    wide = build_wiki(views(early), "k_testland")
    # 205 is 200's brother and holds nothing, so nothing but the sibling rule
    # reaches him: only the wide build gives him a page
    assert 205 in wide.characters
    assert 205 not in narrow.characters and 205 in narrow.relatives
    # either way he is named on the page he appears on
    assert 205 in narrow.characters[200].siblings


def test_a_promoted_characters_house_is_resolved_too(tmp_path):
    # houses used to be read before the promotion, so everyone it brought in
    # showed a bare house id tagged "not in this wiki"
    early, _ = two_snapshots(tmp_path)
    wiki = build_wiki(views(early), "k_testland")
    for record in wiki.characters.values():
        if record.house is not None:
            assert record.house in wiki.houses, record.id


def test_kin_can_be_left_out_and_are_then_only_named(tmp_path):
    early, _ = two_snapshots(tmp_path)
    wiki = build_wiki(views(early), "k_testland", with_kin=False)
    assert 202 not in wiki.characters  # holds no title in this lineage
    assert wiki.relatives[202].name == "Spouse" and wiki.relatives[202].birth == "1062.2.2"
    assert wiki.named(202) == "Spouse"


def test_family_can_be_skipped_because_it_costs_a_full_pass(tmp_path):
    early, _ = two_snapshots(tmp_path)
    wiki = build_wiki(views(early), "k_testland", with_family=False)
    assert not wiki.characters[200].has_family and wiki.relatives == {}


def test_a_marriage_that_ended_is_listed_once_as_former(tmp_path):
    # the older save has them under `spouse`, the newer under `former_spouses`;
    # unioning both would name the person twice on the page
    from ck3wiki.model import WikiCharacter, _merge_family
    from ck3parser.family import Family

    record = WikiCharacter(id=1, spouses=[9])
    _merge_family(record, Family(id=1, former_spouses=[9]))
    assert record.spouses == [] and record.former_spouses == [9]


def test_family_unions_across_snapshots(tmp_path):
    # a later save knows of more children, never fewer, and an older one is the
    # only source for anyone the newest has pruned
    early, late = two_snapshots(tmp_path)
    wiki = build_wiki(views(early, late), "k_testland")
    assert wiki.characters[200].children == [203, 204]


# ---------------------------------------------------------------- releases


def test_a_release_tags_a_save_but_never_decides_its_run(tmp_path):
    # a release is the batch a save was published in. One run already spans
    # three of them, so grouping still comes from the fingerprint alone.
    from ck3wiki.manifest import with_releases

    saves = [{"file": "a_1100.ck3", "date": "1100.6.1"}, {"file": "b_1120.ck3", "date": "1120.1.1"}]
    tagged = with_releases(saves, {"a_1100.ck3": "0.0.2", "b_1120.ck3": "0.0.3"})
    assert [s["release"] for s in tagged] == ["0.0.2", "0.0.3"]
    # a save the index does not mention gets an empty tag, not a guess
    assert with_releases(saves, {"a_1100.ck3": "0.0.2"})[1]["release"] == ""
    # and with no index at all the key is absent rather than empty
    assert "release" not in with_releases(saves, None)[0]


def test_two_releases_still_build_one_chronicle(tmp_path):
    # the two snapshots share a run key, so they are one chronicle however many
    # releases they arrived in
    early, late = two_snapshots(tmp_path)
    (tmp_path / "releases.json").write_text(
        json.dumps({"a_1100.ck3": "0.0.2", "b_1120.ck3": "0.0.3"}), encoding="utf-8"
    )
    out = tmp_path / "site"
    assert main([str(tmp_path), "--title", "k_testland", "--out", str(out)]) == 0
    root = json.loads((out / "portraits.json").read_text())
    assert len(root["chronicles"]) == 1
    assert root["chronicles"][0]["releases"] == ["0.0.2", "0.0.3"]
    chronicle = json.loads((out / "7-1-6-1-2" / "portraits.json").read_text())
    assert [s["release"] for s in chronicle["saves"]] == ["0.0.2", "0.0.3"]


def test_a_directory_with_no_release_index_says_nothing_about_releases(tmp_path):
    from ck3wiki.build import read_releases

    two_snapshots(tmp_path)
    assert read_releases(str(tmp_path)) == {}
    out = tmp_path / "site"
    main([str(tmp_path), "--title", "k_testland", "--out", str(out)])
    chronicle = json.loads((out / "7-1-6-1-2" / "portraits.json").read_text())
    assert all("release" not in s for s in chronicle["saves"])


def test_a_title_bears_arms_of_its_own(tmp_path):
    # all 12 915 titles of the 1364 save carry a coat_of_arms_id, and the title
    # parser used to drop it
    from ck3parser.arms import read_arms

    early, _ = two_snapshots(tmp_path)
    wiki = build_wiki(views(early), "k_testland")
    arms = wiki.titles["k_testland"].arms
    recipe = read_arms(str(early), {902})[902]
    assert arms is not None and arms.file == arms_name(recipe.digest)
    assert arms.title == "k_testland" and arms.house == 0
    assert arms.page == "titles/k_testland.html"
    assert ["pattern", "pattern_checkers_01.dds"] in arms.definition

    out = tmp_path / "site"
    write_site(wiki, out)
    assert f'src="../portraits/{arms.file}"' in (out / "titles" / "k_testland.html").read_text()


def test_a_title_and_a_house_drawn_alike_share_one_file(tmp_path):
    # c_test and house 500 both use recipe 900, so they are one image: the name
    # comes from the recipe, never from who bears it
    early, _ = two_snapshots(tmp_path)
    wiki = build_wiki(views(early), "k_testland")
    county = wiki.titles["c_test"].arms
    house = wiki.houses[500].arms
    assert county is not None and house is not None
    assert county.file == house.file
    assert county.title == "c_test" and house.house == 500

    wanted = [a.file for a in wiki.wanted_arms]
    entries = [p for p in chronicle_manifest(wiki, "s", have=set())["portraits"]
               if p["kind"] == "arms"]
    assert wanted.count(county.file) == 2  # two bearers
    assert [e["file"] for e in entries].count(county.file) == 1  # one request


def test_title_arms_are_a_different_picture_from_the_houses(tmp_path):
    early, _ = two_snapshots(tmp_path)
    wiki = build_wiki(views(early), "k_testland")
    assert wiki.titles["k_testland"].arms.file != wiki.houses[500].arms.file


# ------------------------------------------------------- cultures and faiths


def test_a_character_page_says_the_culture_and_faith(tmp_path):
    early, late = two_snapshots(tmp_path)
    wiki = build_wiki(views(early, late), "k_testland")
    out = tmp_path / "site"
    write_site(wiki, out)
    page = (out / "characters" / "200.html").read_text()
    assert "<th>Culture</th>" in page and "<th>Faith</th>" in page
    assert "../cultures/1.html" in page and "../faiths/1.html" in page
    assert "Testish-Farrish" in page and "Testarianism" in page


def test_a_faith_founded_in_the_run_says_so_on_its_page(tmp_path):
    early, late = two_snapshots(tmp_path)
    wiki = build_wiki(views(early, late), "k_testland")
    out = tmp_path / "site"
    write_site(wiki, out)
    page = (out / "faiths" / "1.html").read_text()
    assert "founded during the run" in page
    # 102 holds a title, so he has a page of his own to link
    assert "../characters/102.html" in page
    # and the faith it was reformed out of is named, since both share a template
    assert "test_pagan" in page


def test_a_templated_culture_says_its_name_is_a_key(tmp_path):
    early, late = two_snapshots(tmp_path)
    wiki = build_wiki(views(early, late), "k_testland")
    out = tmp_path / "site"
    write_site(wiki, out)
    keyed = (out / "cultures" / "0.html").read_text()
    assert "localization key" in keyed and "Testish" in keyed
    # and it does not claim that a template says when the culture began
    assert "can still have emerged during this run" in keyed
    made = (out / "cultures" / "1.html").read_text()
    assert "no template for this culture" in made
    # a created culture shows where it came from, and the parent is a link
    assert "../cultures/0.html" in made


def test_the_newest_save_decides_a_characters_culture_and_faith(tmp_path):
    # a character can convert or assimilate, so this follows the same rule as
    # the house: the newest save's answer wins
    early = make_save(tmp_path / "a_1100.ck3", date="1100.6.1", seed=7, random_count=100)
    late = make_save(
        tmp_path / "b_1120.ck3", date="1120.1.1", seed=7, random_count=200,
        edits=[("\t\tculture=1\n\t\tfaith=1\n", "\t\tculture=0\n\t\tfaith=0\n")],
    )
    wiki = build_wiki(views(early, late), "k_testland")
    assert wiki.characters[200].culture == 0 and wiki.characters[200].faith == 0


def test_the_index_lists_cultures_and_faiths(tmp_path):
    early, late = two_snapshots(tmp_path)
    wiki = build_wiki(views(early, late), "k_testland")
    page = render_index(wiki)
    assert "<h2>Cultures</h2>" in page and "<h2>Faiths</h2>" in page
    # a culture with the 1.1.1 sentinel says so in words, not as a date
    assert "from the start" in page and "1.1.1" not in page


def test_every_manifest_says_where_the_naming_rule_is_written(tmp_path):
    # a consumer with the queue but not the rule can still deliver the wrong
    # file name, and the rule is the one thing both sides must agree on without
    # talking to each other
    from ck3wiki.manifest import DOCS, chronicle_manifest

    early, late = two_snapshots(tmp_path)
    wiki = build_wiki(views(early, late), "k_testland")
    manifest = chronicle_manifest(wiki, "slug", set())
    assert manifest["docs"] == DOCS and "names" in manifest["docs"]

    out = tmp_path / "site"
    assert main([str(tmp_path), "--out", str(out), "--title", "k_testland"]) == 0
    root = json.loads((out / "portraits.json").read_text())
    assert root["docs"]["names"].endswith("COMPANION_PROPOSAL.md#the-rule")


#: Gives 205, 200's brother, two children: 206 holds the fixture's unheld duchy,
#: which is outside the lineage, and 207 holds nothing. Both are in the second
#: ring -- the direct line of someone who only has a page by blood.
NEPHEW_EDITS = (
    ('key="d_empty"\n\tname="Empty Duchy"', 'key="d_empty"\n\tholder=206\n\tname="Empty Duchy"'),
    (
        "faith=0\n\t\tdynasty_house=500\n\t\tfamily_data={\n\t\t}",
        "faith=0\n\t\tdynasty_house=500\n\t\tfamily_data={\n\t\t\tchild={ 206 207 }\n\t\t}",
    ),
    (
        "\n}\ndead_unprunable={",
        '\n\t206={\n\t\tfirst_name="Nephew"\n\t\tbirth=1080.1.1\n\t}'
        '\n\t207={\n\t\tfirst_name="Niece"\n\t\tbirth=1082.1.1\n\t\tfemale=yes\n\t}'
        "\n}\ndead_unprunable={",
    ),
)


def test_the_second_ring_gets_pages_only_where_it_holds_a_title(tmp_path):
    # a ruler's nephew who holds a duchy elsewhere is worth a page; one who holds
    # nothing is one of ~13 000 dead ends and stays a name (docs/PLAN.md §10)
    save = make_save(tmp_path / "a.ck3", edits=NEPHEW_EDITS)
    wiki = build_wiki(views(save), "k_testland")
    assert 206 in wiki.characters
    assert 207 not in wiki.characters and wiki.named(207) == "Niece"
    assert wiki.characters[206].parents == [205]
    assert wiki.characters[206].portraits  # alive, so harvestable like anyone else

    narrow = build_wiki(views(save), "k_testland", with_titled_kin=False)
    assert 206 not in narrow.characters and 206 in narrow.relatives


def test_the_second_ring_is_reached_only_through_somebody_with_a_page(tmp_path):
    # without sibling pages the brother has none, so his titled son is two steps
    # from anyone paged and the ring does not reach him
    save = make_save(tmp_path / "a.ck3", edits=NEPHEW_EDITS)
    wiki = build_wiki(views(save), "k_testland", with_siblings=False)
    assert 205 not in wiki.characters and 206 not in wiki.characters


def test_a_page_says_what_its_character_held_outside_the_chronicle(tmp_path):
    save = make_save(tmp_path / "a.ck3", edits=NEPHEW_EDITS)
    wiki = build_wiki(views(save), "k_testland")
    # the spouse holds c_far, which answers to c_test and so is not a title of
    # this lineage; the ruler's own kingdom is, and is not repeated
    assert [h.key for h in wiki.held_elsewhere(202)] == ["c_far"]
    assert wiki.held_elsewhere(200) == []

    out = tmp_path / "site"
    write_site(wiki, out)
    nephew = (out / "characters" / "206.html").read_text()
    assert "<h2>Titles held elsewhere</h2>" in nephew and "Empty Duchy" in nephew
    assert "Titles held elsewhere" not in (out / "characters" / "200.html").read_text()

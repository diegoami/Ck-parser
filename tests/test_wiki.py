import json
import re
from pathlib import Path

from ck3parser.pipeline import gather
from ck3parser.portraits import arms_name, portrait_name
from ck3wiki.build import discover, main, subject_of
from ck3wiki.manifest import chronicle_manifest
from ck3wiki.model import Tenure, Wiki, WikiCharacter, _runs_of, build_wiki, clean_name
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


# ---------------------------------------------------------------- vassalage


def test_stretches_collapse_and_carry_their_bounds():
    snaps = ["1100.6.1", "1110.1.1", "1120.1.1"]
    # same liege throughout: one stretch, open, and no lower bound to give
    one = _runs_of({d: "k_testland" for d in snaps}, snaps)
    assert len(one) == 1 and one[0].open
    assert one[0].began == "by 1100.6.1" and one[0].ended == ""

    # a change between the last two: the date is unknown, the bounds are not
    two = _runs_of({"1100.6.1": "k_testland", "1110.1.1": "k_testland", "1120.1.1": "c_test"}, snaps)
    assert [v.liege for v in two] == ["k_testland", "c_test"]
    assert two[0].ended == "1110.1.1 – 1120.1.1" and not two[0].open
    assert two[1].began == "1110.1.1 – 1120.1.1" and two[1].open


def test_independence_is_a_liege_of_none_and_absence_is_not():
    snaps = ["1100.6.1", "1110.1.1", "1120.1.1"]
    free = _runs_of({d: None for d in snaps}, snaps)
    assert len(free) == 1 and free[0].liege is None

    # absent from the middle save: we did not see it under anyone, so the
    # stretch breaks rather than bridging a gap we cannot see across
    gap = _runs_of({"1100.6.1": "k_testland", "1120.1.1": "k_testland"}, snaps)
    assert [v.liege for v in gap] == ["k_testland", "k_testland"]
    assert gap[0].ended == "1100.6.1 – 1110.1.1"
    assert gap[1].began == "1110.1.1 – 1120.1.1"


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
    child = wiki.characters[203] if 203 in wiki.characters else None
    parent = wiki.characters[200]
    assert parent.children == [203, 204] and parent.spouses == [202]
    assert parent.has_family

    out = tmp_path / "site"
    write_site(wiki, out)
    page_html = (out / "characters" / "200.html").read_text()
    assert "<h2>Family</h2>" in page_html and "Children" in page_html
    # 202, 203 and 204 hold none of the lineage's titles, so they have no page;
    # they are still named rather than shown as bare ids
    assert "Spouse" in page_html and 'characters/202.html' not in page_html
    assert child is None


def test_a_relative_without_a_page_is_named_not_numbered(tmp_path):
    early, _ = two_snapshots(tmp_path)
    wiki = build_wiki(views(early), "k_testland")
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

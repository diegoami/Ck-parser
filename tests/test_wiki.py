import re
from pathlib import Path

from ck3parser.pipeline import gather
from ck3wiki.build import main
from ck3wiki.model import Tenure, Wiki, WikiCharacter, build_wiki, clean_name
from ck3wiki.render import STYLE, e, find_portraits, render_index, write_site
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
    assert pages == 1 + len(wiki.titles) + len(wiki.characters)
    assert (out / "index.html").is_file() and (out / "style.css").read_text() == STYLE
    title_page = (out / "titles" / "k_testland.html").read_text()
    assert "Succession" in title_page and "../characters/200.html" in title_page
    assert "Kingdom of Testland" in title_page
    character_page = (out / "characters" / "100.html").read_text()
    assert "880.5.5" in character_page and "../titles/k_testland.html" in character_page


def test_portraits_are_linked_only_when_present(tmp_path):
    early, _ = two_snapshots(tmp_path)
    wiki = build_wiki(views(early), "k_testland")
    shots = tmp_path / "shots"
    shots.mkdir()
    (shots / "200_1100_6_1.png").write_bytes(b"\x89PNG")
    assert find_portraits(shots, [200, 201]) == {200: "200_1100_6_1.png"}
    assert find_portraits(None, [200]) == {}
    out = tmp_path / "site"
    write_site(wiki, out, shots)
    assert "../portraits/200_1100_6_1.png" in (out / "characters" / "200.html").read_text()
    assert "<img" not in (out / "characters" / "201.html").read_text()
    assert (out / "portraits" / "200_1100_6_1.png").is_file()


# ---------------------------------------------------------------- the CLI


def test_cli_builds_a_site_from_a_run(tmp_path, capsys):
    two_snapshots(tmp_path)
    out = tmp_path / "site"
    assert main([str(tmp_path), "--title", "k_testland", "--out", str(out)]) == 0
    assert "wrote" in capsys.readouterr().err
    assert (out / "index.html").is_file()
    assert sorted(p.name for p in (out / "titles").iterdir()) == [
        "c_test.html", "k_testland.html", "x_mc_0.html"
    ]


def test_cli_rejects_an_unknown_title(tmp_path, capsys):
    two_snapshots(tmp_path)
    assert main([str(tmp_path), "--title", "k_nope", "--out", str(tmp_path / "s")]) == 2
    assert "not found in any" in capsys.readouterr().err


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

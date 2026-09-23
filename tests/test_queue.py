import json

from ck3wiki.build import main as build_main
from ck3wiki.queue import harvester_name, load_entries
from ck3wiki.queue import main as queue_main
from helpers import make_save
from test_wiki import NEPHEW_EDITS


def built(tmp_path):
    """One chronicle from a save whose second ring holds a title (206)."""
    saves = tmp_path / "saves"
    saves.mkdir()
    make_save(saves / "a.ck3", edits=NEPHEW_EDITS)
    site = tmp_path / "site"
    assert build_main([str(saves), "--title", "k_testland", "--out", str(site),
                       "--cache", str(tmp_path / "cache")]) == 0
    return site


def test_every_portrait_says_why_its_character_is_in_the_queue(tmp_path):
    site = built(tmp_path)
    root = json.loads((site / "portraits.json").read_text(encoding="utf-8"))
    assert root["schema"] == "ck3-images/3"
    by_id = {e["character"]: e for e in load_entries(site / "portraits.json")}
    # 200 holds the kingdom, 202 is his wife, 206 his titled nephew
    assert by_id[200]["role"] == "ever-holder"
    assert by_id[202]["role"] == "kin" and by_id[202]["sex"] == "female"
    assert by_id[206]["role"] == "titled-kin" and by_id[206]["birth"] == "1080.1.1"


def test_ids_writes_one_file_per_save_rulers_first(tmp_path):
    site = built(tmp_path)
    out = tmp_path / "ids"
    assert queue_main(["ids", str(site / "portraits.json"), "--out", str(out)]) == 0
    (only,) = out.glob("*.ids")
    ids = only.read_text(encoding="utf-8").split()
    roles = {e["character"]: e["role"] for e in load_entries(site / "portraits.json")}
    order = [roles[int(i)] for i in ids]
    assert order == sorted(order, key=["ever-holder", "kin", "titled-kin"].index)
    assert ids[0] == "200" and "206" in ids

    narrow = tmp_path / "narrow"
    queue_main(["ids", str(site / "portraits.json"), "--out", str(narrow), "--role", "ever-holder"])
    assert {roles[int(i)] for i in next(narrow.glob("*.ids")).read_text(encoding="utf-8").split()} == {"ever-holder"}


def test_collect_gives_a_capture_the_name_the_page_links(tmp_path):
    # the harvester writes <id>_<save date>.png; the wiki links another name,
    # so without this a harvest lands where no page looks
    site = built(tmp_path)
    entries = load_entries(site / "portraits.json")
    ruler = next(e for e in entries if e["character"] == 200)
    harvested = tmp_path / "harvested"
    harvested.mkdir()
    (harvested / harvester_name(200, ruler["save_date"])).write_bytes(b"png")
    images = tmp_path / "images"

    assert queue_main(["collect", str(site / "portraits.json"),
                       "--from", str(harvested), "--to", str(images)]) == 0
    assert (images / ruler["file"]).read_bytes() == b"png"
    assert (harvested / harvester_name(200, ruler["save_date"])).exists()  # copied, not moved
    # delivered, the build now shows it: nothing else needs to change
    site2 = tmp_path / "site2"
    build_main([str(tmp_path / "saves"), "--title", "k_testland", "--out", str(site2),
                "--cache", str(tmp_path / "cache"), "--portraits", str(images)])
    again = {e["file"]: e["have"] for e in load_entries(site2 / "portraits.json")}
    assert again[ruler["file"]] is True


def test_collect_never_overwrites(tmp_path, capsys):
    site = built(tmp_path)
    ruler = next(e for e in load_entries(site / "portraits.json") if e["character"] == 200)
    harvested, images = tmp_path / "harvested", tmp_path / "images"
    harvested.mkdir()
    images.mkdir()
    (harvested / harvester_name(200, ruler["save_date"])).write_bytes(b"new")
    (images / ruler["file"]).write_bytes(b"old")
    queue_main(["collect", str(site / "portraits.json"), "--from", str(harvested), "--to", str(images)])
    assert (images / ruler["file"]).read_bytes() == b"old"
    assert "1 already there" in capsys.readouterr().err

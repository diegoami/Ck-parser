"""The character digest: same answers as the save, read in seconds not minutes."""

import gzip
import json

from ck3parser.characters import find_characters, living_characters
from ck3parser.digest import (
    SCHEMA,
    cache_key,
    digest_for,
    digest_path,
    read_digest,
    write_digest,
)
from ck3parser.family import read_index
from ck3parser.fingerprint import fingerprint
from helpers import make_save


def digested(tmp_path, name="a.ck3"):
    save = make_save(tmp_path / name)
    fp = fingerprint(save, with_sha256=False)
    return save, fp, digest_for(save, fp, tmp_path / "cache")


def test_a_digest_answers_exactly_what_the_save_does(tmp_path):
    save, _, digest = digested(tmp_path)
    wanted = {100, 102, 200, 203, 205, 300, 999999}

    from_save = find_characters(save, wanted)
    from_digest = digest.find(wanted)
    assert set(from_save) == set(from_digest)
    for cid in from_save:
        a, b = from_save[cid], from_digest[cid]
        for key in ("first_name", "birth", "dynasty_house", "culture", "faith"):
            assert str(a.get(key) or "") == str(b.get(key) or ""), (cid, key)
        assert (a.get("dead_data") is None) == (b.get("dead_data") is None), cid


def test_the_inversion_from_a_digest_matches_the_one_from_the_save(tmp_path):
    save, _, digest = digested(tmp_path)
    wanted = {200, 203}
    direct = read_index(save, wanted)
    cached = digest.family_index(wanted)
    assert direct.brood == cached.brood
    assert direct.parents == cached.parents
    # and the records asked for by name, which is where spouses live
    assert {c: f.spouses for c, f in direct.own.items()} == {c: f.spouses for c, f in cached.own.items()}
    # the save states parentage downward only, so this is the whole point
    assert cached.family_of(200).parents == [102, 103]
    assert cached.family_of(200).siblings == [205]


def test_only_the_living_without_a_death_block_count_as_living(tmp_path):
    save, _, digest = digested(tmp_path)
    wanted = {100, 200, 201, 300}
    # both conditions, because someone who died on the save's own date still
    # sits in `living` carrying the block
    assert set(digest.living(wanted)) == set(living_characters(save, wanted))
    assert 100 not in digest.living(wanted)  # dead_unprunable
    assert 200 in digest.living(wanted)


def test_a_digest_is_reused_and_a_changed_save_is_not(tmp_path):
    save, fp, _ = digested(tmp_path)
    path = digest_path(tmp_path / "cache", fp, save)
    assert path.is_file()
    # a second call reads it rather than writing it again
    before = path.stat().st_mtime_ns
    digest_for(save, fp, tmp_path / "cache")
    assert path.stat().st_mtime_ns == before

    # a different save of the same run gets its own digest
    other = make_save(tmp_path / "b.ck3", date="1120.1.1", seed=7, random_count=200)
    other_fp = fingerprint(other, with_sha256=False)
    assert cache_key(other_fp, other) != cache_key(fp, save)


def test_a_stale_or_damaged_digest_is_ignored_rather_than_trusted(tmp_path):
    save, fp, _ = digested(tmp_path)
    path = digest_path(tmp_path / "cache", fp, save)

    # written by an older version of the row shape
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({"schema": "ck3-characters/0", "key": cache_key(fp, save)}) + "\n")
    assert read_digest(path, fp, save) is None

    # truncated mid-write, or not gzip at all
    path.write_bytes(b"not a gzip file")
    assert read_digest(path, fp, save) is None
    # a cache that cannot be read costs a slow build, never a failed one
    assert digest_for(save, fp, tmp_path / "cache") is not None


def test_no_cache_directory_means_no_digest(tmp_path):
    save = make_save(tmp_path / "a.ck3")
    fp = fingerprint(save, with_sha256=False)
    assert digest_for(save, fp, None) is None


def test_the_header_carries_the_schema_so_it_can_be_thrown_away(tmp_path):
    save = make_save(tmp_path / "a.ck3")
    fp = fingerprint(save, with_sha256=False)
    path = tmp_path / "d.jsonl.gz"
    written = write_digest(save, fp, path)
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        header = json.loads(fh.readline())
        rows = [json.loads(line) for line in fh]
    assert header["schema"] == SCHEMA and len(rows) == written
    # nothing is left behind from the temporary write
    assert not path.with_suffix(".part").exists()


def test_a_cached_build_renders_exactly_what_an_uncached_one_does(tmp_path):
    """The only thing a cache may change is how long it took."""
    from ck3wiki.build import run_build

    early = make_save(tmp_path / "a_1100.ck3", date="1100.6.1", seed=7, random_count=100)
    late = make_save(tmp_path / "b_1120.ck3", date="1120.1.1", seed=7, random_count=200)
    saves = tmp_path / "saves"
    saves.mkdir()
    for path in (early, late):
        (saves / path.name).write_bytes(path.read_bytes())

    with open(tmp_path / "log", "w") as log:
        assert run_build(str(saves), str(tmp_path / "cold"), title="k_testland",
                         cache=None, log=log) == 0
        assert run_build(str(saves), str(tmp_path / "warm"), title="k_testland",
                         cache=str(tmp_path / "cache"), log=log) == 0
        # and again, now that every save is already digested
        assert run_build(str(saves), str(tmp_path / "warmer"), title="k_testland",
                         cache=str(tmp_path / "cache"), log=log) == 0

    def pages(root):
        return {
            p.relative_to(root).as_posix(): p.read_text()
            for p in sorted(root.rglob("*")) if p.is_file()
        }

    assert pages(tmp_path / "cold") == pages(tmp_path / "warm")
    assert pages(tmp_path / "warm") == pages(tmp_path / "warmer")
    assert (tmp_path / "log").read_text().count("cached:") == 2  # the third build's reads


def test_the_first_section_wins_the_way_a_save_search_does(tmp_path):
    # find_characters searches living, then dead_unprunable, then dead_prunable
    # and keeps the first hit; a dict built the other way round would silently
    # prefer the last
    save, fp, _ = digested(tmp_path)
    path = digest_path(tmp_path / "cache", fp, save)
    with gzip.open(path, "at", encoding="utf-8") as fh:
        fh.write(json.dumps({"i": 200, "g": 2, "n": "Impostor", "d": "999.1.1"}) + "\n")
    digest = read_digest(path, fp, save)
    assert str(digest.find({200})[200].get("first_name")) == "Test"
    assert 200 in digest.living({200})

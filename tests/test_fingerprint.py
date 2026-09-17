from ck3parser.fingerprint import fingerprint
from helpers import make_save


def test_fingerprint_fields(tmp_path):
    p = make_save(tmp_path / "a.ck3", date="1100.6.1", seed=7, random_count=99)
    fp = fingerprint(p)
    assert fp.random_seed == 7 and fp.random_count == 99 and fp.bookmark_date == "867.1.1"
    assert fp.date == "1100.6.1" and fp.meta_real_date == "126.3.6" and fp.first_start is False
    assert fp.played_character == 200 and fp.player_name == "King Test of Testland"
    assert fp.ironman is False and fp.version == "1.6.1.2"
    assert len(fp.sha256) == 64 and fp.size == p.stat().st_size
    assert fp.run_key == (7, "867.1.1", fp.rules_hash, fp.dlcs_hash)


def test_hashes_are_stable_and_order_independent(tmp_path):
    a = fingerprint(make_save(tmp_path / "a.ck3"), with_sha256=False)
    b = fingerprint(make_save(tmp_path / "b.ck3", date="1101.1.1"), with_sha256=False)
    assert a.dlcs_hash == b.dlcs_hash and a.rules_hash == b.rules_hash and a.sha256 is None

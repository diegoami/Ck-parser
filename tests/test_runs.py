import json

from ck3parser.runs import format_runs, is_prefix, main, read_legacy, scan, verify_runs, write_manifest
from helpers import make_save


def _dir(tmp_path):
    # run 1: three snapshots, one taken before a succession (legacy shorter by one)
    make_save(tmp_path / "r1_1050.ck3", date="1050.1.1", real_date="126.2.21", seed=1, random_count=100, legacy_trim=1)
    make_save(tmp_path / "r1_1100.ck3", date="1100.6.1", real_date="126.2.26", seed=1, random_count=200)
    make_save(tmp_path / "r1_1120.ck3", date="1120.1.1", real_date="126.3.6", seed=1, random_count=300)
    # run 2: same bookmark, different seed
    make_save(tmp_path / "r2_1100.ck3", date="1100.6.1", real_date="126.3.1", seed=2, random_count=150)
    return tmp_path


def test_scan_groups_and_orders(tmp_path):
    runs = scan(_dir(tmp_path))
    assert [(r.random_seed, [s.fp.date for s in r.snapshots]) for r in runs] == [
        (1, ["1050.1.1", "1100.6.1", "1120.1.1"]),
        (2, ["1100.6.1"]),
    ]
    assert all(not r.warnings for r in runs)


def test_tier1_splits_on_backwards_counter(tmp_path):
    make_save(tmp_path / "a.ck3", date="1050.1.1", seed=1, random_count=500)
    make_save(tmp_path / "b.ck3", date="1100.1.1", seed=1, random_count=100)  # later date, fewer RNG draws
    runs = scan(tmp_path)
    assert len(runs) == 2 and "random_count decreases" in runs[0].warnings[0]


def test_tier1_flags_a_duplicate(tmp_path):
    make_save(tmp_path / "a.ck3", date="1050.1.1", seed=1, random_count=500)
    make_save(tmp_path / "b.ck3", date="1050.1.1", seed=1, random_count=500)
    runs = scan(tmp_path)
    assert len(runs) == 1 and len(runs[0].snapshots) == 2
    assert any("duplicates" in w for w in runs[0].warnings)


def test_a_different_game_version_is_a_different_run(tmp_path):
    # `version` is the version the run was STARTED on, so it cannot drift
    # mid-run: two saves that disagree about it are two playthroughs
    make_save(tmp_path / "a.ck3", date="1050.1.1", seed=1, random_count=500)
    make_save(tmp_path / "b.ck3", date="1060.1.1", seed=1, random_count=600, version='"1.7.0.0"')
    runs = scan(tmp_path)
    assert len(runs) == 2
    assert {r.version for r in runs} == {"1.6.1.2", "1.7.0.0"}
    assert {r.slug for r in runs} == {"1-1-6-1-2", "1-1-7-0-0"}
    assert all(not r.warnings for r in runs)


def test_read_legacy_and_prefix(tmp_path):
    _dir(tmp_path)
    name, short = read_legacy(tmp_path / "r1_1050.ck3")
    _, full = read_legacy(tmp_path / "r1_1100.ck3")
    assert name == "tester" and len(short) == 3 and len(full) == 4
    assert is_prefix(short, full) and not is_prefix(full, short)


def test_verify_passes_clean_chain_and_splits_divergent(tmp_path):
    runs = verify_runs(scan(_dir(tmp_path)))
    assert [len(r.snapshots) for r in runs] == [3, 1] and all(not r.warnings for r in runs)
    # a save with the same seed but a different player account is not the same chain
    make_save(tmp_path / "r1_1130.ck3", date="1130.1.1", real_date="126.3.7", seed=1, random_count=400, player_account="someone_else")
    runs = verify_runs(scan(tmp_path))
    assert [len(r.snapshots) for r in runs] == [3, 1, 1]
    assert "player account differs" in runs[0].warnings[0]


def test_manifest_roundtrip_and_cli(tmp_path, capsys):
    d = _dir(tmp_path)
    manifest = tmp_path / "runs.json"
    rc = main(["verify", str(d), "--json", str(manifest)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "run 1-1.6.1.2-867.1.1" in out and "legacy=3" in out
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert [len(r["snapshots"]) for r in data["runs"]] == [3, 1]
    assert data["runs"][0]["player_account"] == "tester"
    # second scan reuses the manifest (sha256 preserved without rehashing)
    runs = scan(d, with_sha256=False, manifest=manifest)
    assert all(s.fp.sha256 for r in runs for s in r.snapshots)
    write_manifest(runs, manifest)
    assert format_runs(runs).count("run ") == 2


# ---------------------------------------------------------------- #30: a DLC toggled mid-run

FEWER_DLCS = (('dlcs={ "The Northern Lords" "Royal Court" }', 'dlcs={ "The Northern Lords" }'),)


def test_a_dlc_toggled_mid_run_is_still_one_playthrough(tmp_path):
    # the legacy chain continues across the change: same player, same game
    make_save(tmp_path / "a.ck3", date="1050.1.1", seed=1, random_count=100, legacy_trim=1)
    make_save(tmp_path / "b.ck3", date="1100.6.1", seed=1, random_count=200, edits=FEWER_DLCS)
    make_save(tmp_path / "c.ck3", date="1120.1.1", seed=1, random_count=300)  # and back on
    (run,) = scan(tmp_path)
    assert [s.label for s in run.snapshots] == ["a.ck3", "b.ck3", "c.ck3"]
    assert run.warnings == [] and len(run.notes) == 2
    assert "DLC set changed between 1050.1.1 (a.ck3) and 1100.6.1 (b.ck3)" in run.notes[0]
    # named, as before, after its first save
    assert run.run_id == scan(tmp_path)[0].snapshots[0].fp.run_id
    # a note is not a failure: verify keeps it, and still passes
    (verified,) = verify_runs([run])
    assert verified.notes == run.notes and verified.warnings == []
    assert main(["verify", str(tmp_path)]) == 0


def test_a_dlc_change_without_a_continuing_chain_splits(tmp_path):
    # the later save's legacy is shorter: not this game continued, so two runs
    make_save(tmp_path / "a.ck3", date="1050.1.1", seed=1, random_count=100)
    make_save(tmp_path / "b.ck3", date="1100.6.1", seed=1, random_count=200, edits=FEWER_DLCS, legacy_trim=1)
    first, second = scan(tmp_path)
    assert [s.label for s in first.snapshots] == ["a.ck3"] and [s.label for s in second.snapshots] == ["b.ck3"]
    assert "legacy is not a prefix; split" in first.warnings[0]
    assert first.run_id != second.run_id


def test_an_unchanged_dlc_set_never_reads_the_legacy_chain(tmp_path, monkeypatch):
    # tier 2 streams most of a gamestate; a build must not pay for it for nothing
    import ck3parser.runs as runs

    def boom(path):
        raise AssertionError(f"read_legacy({path}) with no DLC change")

    monkeypatch.setattr(runs, "read_legacy", boom)
    make_save(tmp_path / "a.ck3", date="1050.1.1", seed=1, random_count=100)
    make_save(tmp_path / "b.ck3", date="1100.6.1", seed=1, random_count=200)
    (run,) = scan(tmp_path)
    assert len(run.snapshots) == 2 and run.notes == []


def test_runs_that_would_share_a_name_are_told_apart(tmp_path):
    # #52: off and back on, with the chain broken both times, gave the first and
    # last runs one id; and any two runs of one seed and version shared a slug,
    # the chronicle's directory, so one overwrote the other
    make_save(tmp_path / "a.ck3", date="1000.1.1", seed=1, random_count=100, player_account="tester")
    make_save(tmp_path / "b.ck3", date="1100.1.1", seed=1, random_count=200, edits=FEWER_DLCS, player_account="bob")
    make_save(tmp_path / "c.ck3", date="1200.1.1", seed=1, random_count=300, player_account="tester")
    runs = scan(tmp_path)
    assert [[s.label for s in r.snapshots] for r in runs] == [["a.ck3"], ["b.ck3"], ["c.ck3"]]
    assert len({r.run_id for r in runs}) == 3 and len({r.slug for r in runs}) == 3
    # the first keeps its name; only the repeats are suffixed
    assert runs[0].run_id == runs[0].snapshots[0].fp.run_id and runs[0].slug == runs[0].snapshots[0].fp.run_slug
    assert runs[1].slug == f"{runs[0].slug}-2" and runs[2].run_id == f"{runs[0].run_id}-2"

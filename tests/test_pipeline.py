from ck3parser.pipeline import collect_characters, main
from ck3parser.titles import build_index
from helpers import make_save


def test_traced_dry_run_loads_title_with_vassals(tmp_path, capsys):
    p = make_save(tmp_path / "a.ck3")
    assert main([str(p), "--title", "k_testland", "--dry-run"]) == 0
    out, err = capsys.readouterr()
    assert "with 2 immediate vassal(s)" in err
    assert "5 referenced, 5 found, 5 kept, 0 missing" in err
    # four tenures of the kingdom plus one each for the two vassals
    assert out.count("HELD_BY") == 6
    # both vassals get a de facto edge; c_test is also de jure under the kingdom,
    # which is the same liege, so no separate de jure edge is written for it
    assert out.count("VASSAL_OF") == 2


def test_no_vassals_flag_narrows_to_one_title(tmp_path, capsys):
    p = make_save(tmp_path / "a.ck3")
    assert main([str(p), "--title", "k_testland", "--dry-run", "--no-vassals"]) == 0
    out, err = capsys.readouterr()
    assert "with 0 immediate vassal(s)" in err
    assert out.count("HELD_BY") == 4 and "VASSAL_OF" not in out


def test_de_jure_edge_written_when_it_differs(tmp_path, capsys):
    p = make_save(tmp_path / "a.ck3")
    assert main([str(p), "--title", "c_test", "--dry-run"]) == 0
    out, _ = capsys.readouterr()
    # c_far is de facto under c_test but de jure under d_empty
    assert out.count("VASSAL_OF") == 2
    assert "'liege': 'd_empty'" in out and "'kind': 'de_jure'" in out


def test_missing_title_exits_two(tmp_path, capsys):
    p = make_save(tmp_path / "a.ck3")
    assert main([str(p), "--title", "k_missing", "--dry-run"]) == 2
    _, err = capsys.readouterr()
    assert "not found in any of the 1 save(s)" in err


def test_collect_characters_reaches_every_section(tmp_path):
    p = make_save(tmp_path / "a.ck3")
    found = collect_characters(p, {200, 100, 300, 999999})
    assert set(found) == {200, 100, 300}  # living, dead_unprunable, dead_prunable
    assert str(found[300]["first_name"]) == "Prunable"


def test_pipeline_titles_match_the_index(tmp_path):
    index = build_index(make_save(tmp_path / "a.ck3"))
    assert [v.key for v in index.immediate_vassals("k_testland")] == ["x_mc_0", "c_test"]


# ---------------------------------------------------------------- whole runs

HISTORY_END = "1090.2.1=200 }"
SUCCESSION = "1090.2.1=200 1110.5.5=201 }"
FOUNDER_DEATH = 'dead_data={\n\t\t\tdate=880.5.5'


def _two_snapshots(tmp_path, **later):
    """One run, saved in 1100 and again in 1120 after a succession."""
    make_save(tmp_path / "a_1100.ck3", date="1100.6.1", real_date="126.2.21", seed=7, random_count=100)
    make_save(
        tmp_path / "b_1120.ck3",
        date="1120.1.1",
        real_date="126.2.26",
        seed=7,
        random_count=200,
        edits=later.pop("edits", ((HISTORY_END, SUCCESSION),)),
        **later,
    )
    return tmp_path


def test_directory_loads_every_snapshot_oldest_first(tmp_path, capsys):
    assert main([str(_two_snapshots(tmp_path)), "--title", "k_testland", "--dry-run"]) == 0
    out, err = capsys.readouterr()
    assert "run 7-867.1.1" in err and "2 snapshot(s), oldest first" in err
    assert err.index("a_1100.ck3") < err.index("b_1120.ck3")
    assert out.count("MERGE (s:Snapshot") == 2
    # the tenure open in 1100 is closed by the 1120 snapshot, on one relationship
    held = [line for line in out.splitlines() if "'holder': 200" in line and "'from': '1090.2.1'" in line]
    assert [("'to': '1100.6.1'" in held[0]), ("'to': '1110.5.5'" in held[1])] == [True, True]
    assert "'open': True" in held[0] and "'open': False" in held[1]


def test_later_snapshot_adds_the_new_ruler(tmp_path, capsys):
    main([str(_two_snapshots(tmp_path)), "--title", "k_testland", "--dry-run"])
    out, _ = capsys.readouterr()
    assert "'holder': 201, 'from': '1110.5.5'" in out.replace("**", "")


def test_changed_history_is_reported_but_still_loads(tmp_path, capsys):
    tmp_path = _two_snapshots(tmp_path, edits=((HISTORY_END, SUCCESSION), ("880.5.5=101", "880.5.5=999")))
    assert main([str(tmp_path), "--title", "k_testland", "--dry-run"]) == 1
    out, err = capsys.readouterr()
    assert "disagreement: k_testland: history at 880.5.5" in err
    assert "1 disagreement(s) between snapshots" in err
    assert out.count("MERGE (s:Snapshot") == 2  # the load still happened


def test_changed_death_date_is_reported(tmp_path, capsys):
    tmp_path = _two_snapshots(
        tmp_path, edits=((HISTORY_END, SUCCESSION), (FOUNDER_DEATH, 'dead_data={\n\t\t\tdate=881.1.1'))
    )
    assert main([str(tmp_path), "--title", "k_testland", "--dry-run"]) == 1
    _, err = capsys.readouterr()
    assert "character 100 died 880.5.5 but the later snapshot says 881.1.1" in err


def test_no_check_flag_silences_the_comparison(tmp_path, capsys):
    tmp_path = _two_snapshots(tmp_path, edits=((HISTORY_END, SUCCESSION), ("880.5.5=101", "880.5.5=999")))
    assert main([str(tmp_path), "--title", "k_testland", "--dry-run", "--no-check"]) == 0
    _, err = capsys.readouterr()
    assert "disagreement" not in err


def test_ambiguous_directory_asks_for_a_run(tmp_path, capsys):
    make_save(tmp_path / "one.ck3", date="1100.6.1", seed=1, random_count=100)
    make_save(tmp_path / "two.ck3", date="1100.6.1", seed=2, random_count=100)
    assert main([str(tmp_path), "--title", "k_testland", "--dry-run"]) == 2
    _, err = capsys.readouterr()
    assert "holds 2 runs; pick one with --run" in err
    assert main([str(tmp_path), "--title", "k_testland", "--dry-run", "--run", "2-867.1.1"]) == 2
    _, err = capsys.readouterr()  # run ids carry the rules and dlc hashes, so that id is incomplete
    assert "2-867.1.1" in err


def test_named_run_loads_only_that_run(tmp_path, capsys):
    from ck3parser.runs import scan

    make_save(tmp_path / "one.ck3", date="1100.6.1", seed=1, random_count=100)
    make_save(tmp_path / "two.ck3", date="1100.6.1", seed=2, random_count=100)
    wanted = next(r for r in scan(tmp_path, with_sha256=False) if r.random_seed == 2)
    assert main([str(tmp_path), "--title", "k_testland", "--dry-run", "--run", wanted.run_id]) == 0
    out, _ = capsys.readouterr()
    assert out.count("MERGE (s:Snapshot") == 1


def test_empty_directory_is_an_argument_error(tmp_path, capsys):
    assert main([str(tmp_path), "--title", "k_testland", "--dry-run"]) == 2
    _, err = capsys.readouterr()
    assert "no .ck3 saves under" in err


def test_a_title_absent_from_one_snapshot_is_skipped_not_fatal(tmp_path, capsys):
    # dynamic titles vanish when destroyed; the snapshots that have it still load
    tmp_path = _two_snapshots(tmp_path, edits=((HISTORY_END, SUCCESSION), ('key="c_test"', 'key="c_gone"')))
    assert main([str(tmp_path), "--title", "c_test", "--dry-run"]) == 0
    out, err = capsys.readouterr()
    assert "'c_test' is not in b_1120.ck3, skipped" in err
    assert out.count("MERGE (s:Snapshot") == 1

from ck3parser.pipeline import collect_characters, main
from ck3parser.titles import build_index
from helpers import make_save


def test_traced_dry_run_loads_title_with_vassals(tmp_path, capsys):
    p = make_save(tmp_path / "a.ck3")
    assert main([str(p), "--title", "k_testland", "--dry-run"]) == 0
    out, err = capsys.readouterr()
    assert "with 2 immediate vassal(s)" in err
    assert "characters found 5, kept 5, missing 0" in err
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


def test_missing_title_exits_two(tmp_path):
    p = make_save(tmp_path / "a.ck3")
    assert main([str(p), "--title", "k_missing", "--dry-run"]) == 2


def test_collect_characters_reaches_every_section(tmp_path):
    p = make_save(tmp_path / "a.ck3")
    found = collect_characters(p, {200, 100, 300, 999999})
    assert set(found) == {200, 100, 300}  # living, dead_unprunable, dead_prunable
    assert str(found[300]["first_name"]) == "Prunable"


def test_pipeline_titles_match_the_index(tmp_path):
    index = build_index(make_save(tmp_path / "a.ck3"))
    assert [v.key for v in index.immediate_vassals("k_testland")] == ["x_mc_0", "c_test"]

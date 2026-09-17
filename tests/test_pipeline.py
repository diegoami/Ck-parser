from ck3parser.pipeline import main
from helpers import make_save


def test_traced_dry_run(tmp_path, capsys):
    p = make_save(tmp_path / "a.ck3")
    assert main([str(p), "--title", "k_testland", "--dry-run"]) == 0
    captured = capsys.readouterr()
    assert "kept after filter 4" in captured.err
    assert captured.out.count("HELD_BY") == 4
    assert main([str(p), "--title", "k_missing", "--dry-run"]) == 2

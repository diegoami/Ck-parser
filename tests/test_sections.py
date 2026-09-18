from ck3parser.sections import (
    ParseReport,
    format_index,
    iter_sections,
    section_index,
    summarize,
    verify_parse,
)
from helpers import fixture_text, make_save


def test_iter_sections_finds_top_level_keys_only():
    names = [s.name for s in iter_sections(fixture_text().splitlines(True))]
    # numbered title entries also sit at column 0 but start with a digit
    assert names == [
        "meta_data", "ironman_manager", "date", "bookmark_date", "first_start", "speed",
        "random_seed", "random_count", "variables", "provinces", "landed_titles", "dynasties",
        "coat_of_arms", "culture_manager", "religion", "deleted_characters", "living",
        "dead_unprunable", "characters",
        "played_character",
        "currently_played_characters",
    ]


def test_sections_know_whether_they_are_blocks():
    by_name = {s.name: s for s in iter_sections(fixture_text().splitlines(True))}
    assert by_name["living"].block and not by_name["date"].block
    assert by_name["date"].lines == 1


def test_sections_span_to_the_next_top_level_key(tmp_path):
    sections = section_index(make_save(tmp_path / "a.ck3"))
    by_name = {s.name: s for s in sections}
    living, dead = by_name["living"], by_name["dead_unprunable"]
    assert living.end_line == dead.start_line - 1
    assert living.lines > 20  # four characters' worth
    assert sections[0].start_line == 1


def test_summarize_collapses_repeats():
    text = "a={\n}\nb=1\na={\n\n}\n"
    rows = summarize(iter_sections(text.splitlines(True)))
    assert [(r.name, r.occurrences, r.lines) for r in rows] == [("a", 2, 5), ("b", 1, 1)]
    assert rows[0].first_line == 1


def test_verify_parse_balances_on_a_real_container(tmp_path):
    report = verify_parse(make_save(tmp_path / "a.ck3"))
    assert report.ok and report.balanced and report.final_depth == 0
    assert report.tokens > 100 and report.max_depth >= 3


def test_parse_report_reads_clearly():
    assert ParseReport(tokens=10, max_depth=3, final_depth=0, reached_end=True).ok
    bad = ParseReport(tokens=10, max_depth=3, final_depth=2, reached_end=True)
    assert not bad.ok and "unbalanced" in str(bad)


def test_format_index_is_tabular():
    rows = summarize(iter_sections("a={\n}\nb=1\n".splitlines(True)))
    text = format_index(rows, total_lines=3)
    assert "section" in text and "b (scalar)" in text and "%" in text

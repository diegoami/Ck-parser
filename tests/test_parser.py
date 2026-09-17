from ck3parser.parser import Block, PushbackLines, Quoted, date_key, iter_children, iter_top_level, parse_text, read_top_level
from helpers import fixture_text


def test_scalars_and_types():
    b = parse_text('a=1\nb=-2.5\nc="quoted str"\nd=bare\ne=yes\nf=no\ng=867.1.1\n')
    assert b["a"] == 1 and b["b"] == -2.5
    assert b["c"] == "quoted str" and isinstance(b["c"], Quoted)
    assert b["d"] == "bare" and not isinstance(b["d"], Quoted)
    assert b["e"] is True and b["f"] is False
    assert b["g"] == "867.1.1"


def test_bare_list_and_anonymous_blocks():
    b = parse_text("skill={ 5 7 4 }\nlegacy={ {\n\tcharacter=1\n\tdate=867.1.1\n}\n {\n\tcharacter=2\n} }\nempty={\n}\n")
    assert b["skill"] == [5, 7, 4]
    assert [e["character"] for e in b["legacy"]] == [1, 2]
    assert b["empty"] == Block() and isinstance(b["empty"], Block)


def test_repeated_keys_kept():
    b = parse_text('perk="a"\nperk="b"\n')
    assert b.getall("perk") == ["a", "b"]
    assert b.as_dict() == {"perk": "b"}


def test_history_mixed_forms_and_column_zero_entries():
    top = parse_text(fixture_text())
    titles = top["landed_titles"]["landed_titles"]
    assert titles.keys() == ["0", "1", "2"]
    hist = titles["0"]["history"]
    assert hist.keys() == ["867.1.1", "880.5.5", "900.1.1", "950.3.3", "1090.2.1"]
    assert hist["900.1.1"]["type"] == "destroyed"
    assert hist["1090.2.1"] == 200


def test_iter_top_level_with_only_skips_others():
    pairs = dict(iter_top_level(fixture_text().splitlines(True), only={"random_seed", "date", "currently_played_characters"}))
    assert pairs == {"random_seed": 424242, "date": "1100.6.1", "currently_played_characters": [200]}


def test_iter_children_streams_nested_section():
    lines = PushbackLines(fixture_text().splitlines(True))
    keys = [t["key"] for _, t in iter_children(lines, ("landed_titles", "landed_titles"))]
    assert keys == ["k_testland", "d_empty", "c_test"]


def test_iter_children_living_and_dead_prunable():
    ids = [int(k) for k, _ in iter_children(fixture_text().splitlines(True), ("living",))]
    assert ids == [200, 201, 202, 203]
    ids = [int(k) for k, _ in iter_children(fixture_text().splitlines(True), ("characters", "dead_prunable"))]
    assert ids == [300]


def test_read_top_level_seeks_deep_section():
    pc = read_top_level(fixture_text().splitlines(True), "played_character")
    assert pc["name"] == "tester"
    assert [(e["character"], e["date"]) for e in pc["legacy"]] == [(100, "867.1.1"), (101, "880.5.5"), (102, "950.3.3"), (200, "1090.2.1")]
    assert read_top_level(fixture_text().splitlines(True), "does_not_exist") is None


def test_date_key():
    assert date_key("867.1.1") < date_key("1066.9.15") < date_key("1066.10.1")

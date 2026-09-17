from ck3parser.filter import collect_referenced_ids, filter_characters, title_holder_ids
from ck3parser.parser import iter_children, parse_text
from helpers import fixture_text


def test_title_holder_ids_include_history_and_skip_typed_entries():
    top = parse_text(fixture_text())
    title = top["landed_titles"]["landed_titles"]["0"]
    assert title_holder_ids(title) == {100, 101, 102, 200}


def test_filler_pool_dropped_but_family_kept():
    top = parse_text(fixture_text())
    titles = [t for _, t in top["landed_titles"]["landed_titles"]]
    referenced = collect_referenced_ids(titles)
    chars = []
    for section in (("living",), ("dead_unprunable",)):
        chars += [(int(k), v) for k, v in iter_children(fixture_text().splitlines(True), section)]
    kept = [cid for cid, _ in filter_characters(chars, referenced)]
    assert 9001 not in kept and 9002 not in kept
    assert {100, 101, 102, 200, 201} <= set(kept)
    # spouse/child of a kept character are pulled in through family_data
    assert 202 in referenced and 203 in referenced

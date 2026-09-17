from ck3parser.consistency import MAX_REPORTED, check_deaths, check_snapshots, check_title_history, death_dates
from ck3parser.parser import parse_text
from ck3parser.titles import TitleIndex, TitleRecord


def index(*records: TitleRecord) -> TitleIndex:
    built = TitleIndex()
    for record in records:
        built.add(record)
    return built


def title(key: str, history, idx: int = 1) -> TitleRecord:
    return TitleRecord(idx=idx, key=key, history=list(history))


def chars(**by_id):
    """``chars(_1="880.5.5", _2=None)`` -> character blocks, None meaning alive."""
    out = {}
    for name, death in by_id.items():
        cid = int(name.lstrip("_"))
        body = f'dead_data={{ date={death} reason="x" }}' if death else "alive_data={ gold=1 }"
        out[cid] = parse_text(f"c={{ first_name=\"n\" {body} }}")["c"]
    return out


# ---------------------------------------------------------------- history


def test_history_prefix_holds_when_the_run_simply_continued():
    earlier = index(title("k_a", [("900.1.1", 1, None)]))
    later = index(title("k_a", [("900.1.1", 1, None), ("950.1.1", 2, "granted")]))
    assert check_title_history(earlier, "1000.1.1", later) == []


def test_history_entry_that_changed_is_reported():
    earlier = index(title("k_a", [("900.1.1", 1, None), ("950.1.1", 2, None)]))
    later = index(title("k_a", [("900.1.1", 1, None), ("950.1.1", 99, None)]))
    assert check_title_history(earlier, "1000.1.1", later) == [
        "k_a: history at 950.1.1 was (2, None) and is now (99, None)"
    ]


def test_history_entry_that_vanished_is_reported():
    earlier = index(title("k_a", [("900.1.1", 1, None), ("950.1.1", 2, None)]))
    later = index(title("k_a", [("900.1.1", 1, None)]))
    warnings = check_title_history(earlier, "1000.1.1", later)
    assert warnings == ["k_a: history entry ('950.1.1', 2, None) at 950.1.1 is missing from the later snapshot"]


def test_only_history_up_to_the_earlier_date_is_compared():
    earlier = index(title("k_a", [("900.1.1", 1, None), ("990.1.1", 7, None)]))
    later = index(title("k_a", [("900.1.1", 1, None), ("950.1.1", 2, None)]))
    assert check_title_history(earlier, "950.1.1", later) == []  # the 990 entry is past the cutoff


def test_a_title_missing_from_the_later_snapshot_is_not_a_disagreement():
    # destroyed dynamic titles disappear; that is why old snapshots are loaded
    earlier = index(title("x_x_1", [("900.1.1", 1, None)]), title("k_a", []))
    assert check_title_history(earlier, "1000.1.1", index(title("k_a", []))) == []


def test_keys_narrow_the_comparison():
    earlier = index(title("k_a", [("900.1.1", 1, None)]), title("k_b", [("900.1.1", 3, None)], idx=2))
    later = index(title("k_a", [("900.1.1", 9, None)]), title("k_b", [("900.1.1", 8, None)], idx=2))
    assert len(check_title_history(earlier, "1000.1.1", later)) == 2
    assert len(check_title_history(earlier, "1000.1.1", later, keys=["k_a"])) == 1


def test_many_disagreements_are_truncated():
    n = MAX_REPORTED + 5
    earlier = index(*(title(f"k_{i}", [("900.1.1", 1, None)], idx=i) for i in range(n)))
    later = index(*(title(f"k_{i}", [("900.1.1", 2, None)], idx=i) for i in range(n)))
    warnings = check_title_history(earlier, "1000.1.1", later)
    assert len(warnings) == MAX_REPORTED + 1
    assert warnings[-1] == "... and 5 more title history disagreement(s)"


# ---------------------------------------------------------------- deaths


def test_death_dates_reads_only_the_dead():
    assert death_dates(chars(_1="880.5.5", _2=None)) == {1: "880.5.5"}


def test_matching_death_dates_agree():
    assert check_deaths(chars(_1="880.5.5"), chars(_1="880.5.5", _2="900.1.1")) == []


def test_changed_death_date_is_reported():
    assert check_deaths(chars(_1="880.5.5"), chars(_1="881.1.1")) == [
        "character 1 died 880.5.5 but the later snapshot says 881.1.1"
    ]


def test_resurrection_is_reported():
    assert check_deaths(chars(_1="880.5.5"), chars(_1=None)) == [
        "character 1 died 880.5.5 but is alive in the later snapshot"
    ]


def test_pruned_character_is_not_a_disagreement():
    assert check_deaths(chars(_1="880.5.5"), chars(_2="900.1.1")) == []


def test_check_snapshots_runs_both_checks():
    earlier = index(title("k_a", [("900.1.1", 1, None)]))
    later = index(title("k_a", [("900.1.1", 2, None)]))
    warnings = check_snapshots(earlier, "1000.1.1", chars(_1="880.5.5"), later, chars(_1="881.1.1"))
    assert len(warnings) == 2 and "k_a" in warnings[0] and "character 1" in warnings[1]

"""The collapse of per-snapshot observations into stretches with bounds."""

from ck3parser.vassalage import stretches


def test_stretches_collapse_and_carry_their_bounds():
    snaps = ["1100.6.1", "1110.1.1", "1120.1.1"]
    # same liege throughout: one stretch, open, and no lower bound to give
    one = stretches({d: "k_testland" for d in snaps}, snaps)
    assert len(one) == 1 and one[0].open
    assert one[0].began == "by 1100.6.1" and one[0].ended == ""

    # a change between the last two: the date is unknown, the bounds are not
    two = stretches({"1100.6.1": "k_testland", "1110.1.1": "k_testland", "1120.1.1": "c_test"}, snaps)
    assert [v.liege for v in two] == ["k_testland", "c_test"]
    assert two[0].ended == "1110.1.1 – 1120.1.1" and not two[0].open
    assert two[1].began == "1110.1.1 – 1120.1.1" and two[1].open


def test_independence_is_a_liege_of_none_and_absence_is_not():
    snaps = ["1100.6.1", "1110.1.1", "1120.1.1"]
    free = stretches({d: None for d in snaps}, snaps)
    assert len(free) == 1 and free[0].liege is None

    # absent from the middle save: we did not see it under anyone, so the
    # stretch breaks rather than bridging a gap we cannot see across
    gap = stretches({"1100.6.1": "k_testland", "1120.1.1": "k_testland"}, snaps)
    assert [v.liege for v in gap] == ["k_testland", "k_testland"]
    assert gap[0].ended == "1100.6.1 – 1110.1.1"
    assert gap[1].began == "1110.1.1 – 1120.1.1"

from frailty_toolkit.validation.public_checks import coverage_check, concordance, redesign_overlap


def test_every_category_covered_in_every_state():
    cov = coverage_check()
    assert cov["passes"].all(), cov[~cov["passes"]]
    assert (cov["n_dx_codes"] + cov["n_sufficient_codes"] > 0).all()


def test_concordance_runs_and_overlaps():
    c = concordance()
    assert (c["n_both"] > 0).all()


def test_redesign_overlap():
    o = redesign_overlap()
    assert "ALL (union)" in set(o["category"])

import math

import numpy as np
import pandas as pd
import pytest

from frailty_toolkit import evaluate, load_state_config
from frailty_toolkit.synthetic import make_population
from frailty_toolkit.validation import convergent_validity, diagnostic_metrics, validate, wilson_ci
from frailty_toolkit.validation.metrics import poisson_rate_ci


def test_wilson_matches_known_value():
    # 8/10: Wilson 95% CI (0.490, 0.943) - Newcombe (1998) Table I, method 3
    p, lo, hi = wilson_ci(8, 10)
    assert p == 0.8 and lo == pytest.approx(0.4902, abs=1e-3) and hi == pytest.approx(0.9433, abs=1e-3)
    assert all(math.isnan(x) for x in wilson_ci(0, 0))


def test_diagnostic_metrics_denominators():
    m = diagnostic_metrics(np.array([1, 1, 0, 0, 1], bool), np.array([1, 0, 1, 0, 1], bool))
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (2, 1, 1, 1)
    assert m["sensitivity_num"] == 2 and m["sensitivity_den"] == 3


def test_poisson_ci_brackets_rate():
    r, lo, hi = poisson_rate_ci(10, 5)
    assert lo < r < hi and r == 2


@pytest.fixture(scope="module")
def pop():
    med, el, ref = make_population(n=6000, seed=11, detection_by_race={"White": 0.9, "Black": 0.5, "Hispanic": 0.7,
                                                                      "AIAN": 0.5, "Asian": 0.8})
    res = evaluate(med, load_state_config("template"), "2027-01-01", eligibility=el)
    return res, ref


def test_harness_outputs(pop):
    res, ref = pop
    out = validate(res.persons, ref, n_boot=300)
    ov = out["overall"].set_index("operating_point")
    assert 0 < ov.at["likely", "sensitivity"] < 1
    assert ov.at["likely", "sensitivity_lo"] <= ov.at["likely", "sensitivity"] <= ov.at["likely", "sensitivity_hi"]
    gaps = out["race_sensitivity_gaps"]
    black = gaps[(gaps.operating_point == "likely") & (gaps.race_ethnicity == "Black")].iloc[0]
    # simulated detection 0.90 (White) vs 0.50 (Black): gap should be positive with CI excluding 0
    assert black["gap_vs_reference_pp"] > 0 and black["gap_lo_pp"] > 0
    assert set(out["per_category"]["category"]) >= {"serious_or_complex_medical", "disabling_mental_disorder"}


def test_convergent_validity(pop):
    res, ref = pop
    cv = convergent_validity(res.persons, ref[["person_id", "acute_care_events", "member_months", "total_paid"]],
                             n_boot=300)
    rr = cv[cv["flag"] == "ratio_flagged_vs_not"].iloc[0]
    assert rr["acute_care_rate_ratio"] > 1 and rr["acute_care_rr_lo"] > 1
    assert rr["pmpm_difference"] > 0


def test_reference_people_without_claims_count_as_not_flagged(pop):
    res, ref = pop
    extra = pd.DataFrame({"person_id": ["SYN-NOCLAIMS"], "reference_frail": [1], "race_ethnicity": ["White"]})
    out = validate(res.persons, pd.concat([ref, extra]), n_boot=50)
    assert out["overall"].iloc[0]["n"] == len(ref) + 1


def test_thin_record_share_reported_by_race_and_rurality(pop):
    res, ref = pop
    out = validate(res.persons, ref, n_boot=50)
    tg = out["tier_by_group"]
    thin = tg[(tg.tier == "thin_record_outreach") & (tg.subset == "reference_positive")]
    assert set(thin["dimension"]) == {"race_ethnicity", "rurality"}
    # lower simulated detection for Black than White enrollees -> larger thin-record share
    pct = thin[thin.dimension == "race_ethnicity"].set_index("group")["pct_of_group"]
    assert pct["Black"] > pct["White"]
    ov = out["overall"].set_index("operating_point")
    assert ov.at["any_outreach", "sensitivity"] >= ov.at["likely_or_possible", "sensitivity"]
    assert "by_rurality" in out

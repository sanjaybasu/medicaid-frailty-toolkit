"""Regression test for 0.2.1: Tuva's core medical_claim has no diagnosis_code_* columns
(diagnoses live in the core condition table, undotted, ranked). Screening such a table
used to run silently on non-diagnosis markers only."""
import warnings

import pandas as pd
import pytest

from frailty_toolkit import TIER_LIKELY, TIER_POSSIBLE, evaluate, load_state_config
from frailty_toolkit.tuva import attach_conditions

AS_OF = "2027-01-01"
TUVA_CORE_MEDICAL = ["medical_claim_id", "claim_id", "claim_line_number", "encounter_id", "encounter_type",
                     "claim_type", "person_id", "member_id", "payer", "plan", "claim_start_date", "claim_end_date",
                     "place_of_service_code", "bill_type_code", "revenue_center_code", "hcpcs_code", "paid_amount",
                     "data_source"]


def _to_tuva_core(med: pd.DataFrame):
    """Split a wide synthetic claims table into Tuva-core medical_claim + condition."""
    dx = [c for c in med.columns if c.startswith("diagnosis_code_")]
    cond = med.melt(id_vars=["person_id", "claim_id", "claim_start_date"], value_vars=dx,
                    var_name="pos", value_name="normalized_code").dropna(subset=["normalized_code"])
    cond["condition_rank"] = cond["pos"].str.replace("diagnosis_code_", "").astype(int)
    cond["normalized_code_type"] = "icd-10-cm"
    cond["recorded_date"] = cond["claim_start_date"]
    cond = cond.drop(columns=["pos", "claim_start_date"])
    core = med.drop(columns=dx).copy()
    for c in TUVA_CORE_MEDICAL:
        if c not in core.columns:
            core[c] = None
    return core[TUVA_CORE_MEDICAL], cond


def test_core_medical_claim_without_diagnoses_is_rejected(scenarios):
    med, ph, el, exp = scenarios
    core, _ = _to_tuva_core(med)
    with pytest.raises(ValueError, match="attach_conditions"):
        evaluate(core, load_state_config("template"), AS_OF, pharmacy_claims=ph, eligibility=el)


def test_attach_conditions_reproduces_wide_results(scenarios):
    med, ph, el, exp = scenarios
    core, cond = _to_tuva_core(med)
    wide = evaluate(med, load_state_config("template"), AS_OF, pharmacy_claims=ph, eligibility=el).persons
    fixed = evaluate(attach_conditions(core, cond), load_state_config("template"), AS_OF,
                     pharmacy_claims=ph, eligibility=el).persons
    a = wide.set_index("person_id")["tier"]
    b = fixed.set_index("person_id")["tier"]
    assert a.equals(b.loc[a.index])
    m = fixed.merge(exp, on="person_id")
    assert (m["tier"] == m["expected_tier"]).all()


def test_state_dx_only_config_differs_from_template_on_tuva_core(scenarios):
    """The OH example (diagnosis alone suffices) must flag more people than the template."""
    med, ph, el, _ = scenarios
    core, cond = _to_tuva_core(med)
    fixed = attach_conditions(core, cond)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        oh = evaluate(fixed, load_state_config("oh"), AS_OF, pharmacy_claims=ph, eligibility=el).persons
    tm = evaluate(fixed, load_state_config("template"), AS_OF, pharmacy_claims=ph, eligibility=el).persons
    assert (oh["tier"] == TIER_LIKELY).sum() > (tm["tier"] == TIER_LIKELY).sum()


def test_attach_conditions_formats():
    core = pd.DataFrame([{"person_id": "SYN-T", "claim_id": "7", "claim_start_date": "2026-11-01",
                          "place_of_service_code": "11"},
                         {"person_id": "SYN-T", "claim_id": "8", "claim_start_date": "2026-12-01",
                          "place_of_service_code": "11"}])
    cond = pd.DataFrame([
        {"claim_id": 7, "condition_rank": 2, "normalized_code": "f1120 ", "normalized_code_type": "ICD-10-CM"},
        {"claim_id": 7, "condition_rank": 1, "normalized_code": "I10", "normalized_code_type": "icd-10-cm"},
        {"claim_id": 8, "condition_rank": 1, "normalized_code": "F11.20", "normalized_code_type": "icd-10-cm"},
        {"claim_id": None, "condition_rank": 1, "normalized_code": "F2090", "normalized_code_type": None}])
    out = attach_conditions(core, cond)
    assert out.set_index("claim_id").at["7", "diagnosis_code_1"] == "I10"
    assert out.set_index("claim_id").at["7", "diagnosis_code_2"] == "F1120"
    assert out.set_index("claim_id").at["8", "diagnosis_code_1"] == "F1120"
    assert evaluate(out, load_state_config("template"), AS_OF).persons["tier"].iloc[0] == TIER_POSSIBLE

import warnings

import pandas as pd
import pytest

from frailty_toolkit import TIER_LIKELY, TIER_NONE, TIER_POSSIBLE, TIER_THIN, evaluate, load_state_config
from frailty_toolkit.states import validate_config

from .conftest import AS_OF


def _run(scen, cfg):
    med, ph, el, exp = scen
    r = evaluate(med, cfg, AS_OF, pharmacy_claims=ph, eligibility=el)
    return r, r.persons.merge(exp, on="person_id")


def test_every_scenario_gets_expected_tier(scenarios, template_cfg):
    r, m = _run(scenarios, template_cfg)
    bad = m[m["tier"] != m["expected_tier"]]
    assert bad.empty, bad[["scenario", "expected_tier", "tier", "categories_partial"]]


def test_expected_category_is_the_one_met(scenarios, template_cfg):
    _, m = _run(scenarios, template_cfg)
    for _, row in m[m["expected_tier"] == TIER_LIKELY].iterrows():
        assert row["expected_category"] in row["categories_met"].split(";"), row["scenario"]


def test_flag_equals_likely(scenarios, template_cfg):
    r, _ = _run(scenarios, template_cfg)
    assert (r.persons["flag"] == (r.persons["tier"] == TIER_LIKELY)).all()


def test_evidence_is_auditable(scenarios, template_cfg):
    r, m = _run(scenarios, template_cfg)
    ev = r.evidence
    for pid in m.loc[m["tier"] == TIER_LIKELY, "person_id"]:
        e = ev[ev["person_id"] == pid]
        assert len(e) > 0
        assert e["claim_id"].notna().all() and e["service_date"].notna().all()
        assert e["code"].notna().all() and e["source_id"].notna().all()
    # every evidence date is inside the window
    assert (pd.to_datetime(ev["service_date"]) > r.window_start - pd.Timedelta(days=1)).all()
    assert (pd.to_datetime(ev["service_date"]) <= r.as_of).all()


def test_not_identified_note_says_not_a_determination(scenarios, template_cfg):
    r, _ = _run(scenarios, template_cfg)
    notes = r.persons.loc[r.persons["tier"] == TIER_NONE, "note"]
    assert notes.str.contains("not a determination").all()


def test_paid_only_config_drops_denied_claims(scenarios, quiet):
    raw = load_state_config("template").raw.copy()
    raw["include_claim_statuses"] = ["paid"]
    cfg = validate_config(raw)
    _, m = _run(scenarios, cfg)
    assert m.set_index("scenario").at["esrd_denied_claims", "tier"] == TIER_THIN  # its only claim was denied


def test_shorter_lookback_excludes_older_claims(scenarios, quiet):
    raw = load_state_config("template").raw.copy()
    raw["lookback_months"] = 1
    _, m = _run(scenarios, validate_config(raw))
    t = m.set_index("scenario")["tier"]
    assert t["cp_wheelchair"] == TIER_THIN            # claims 100-200 days back: nothing in window
    assert t["hospice_only"] == TIER_LIKELY           # claim 10 days back


def test_redesign_domain_routes_to_attestation_only(scenarios, quiet):
    raw = load_state_config("template").raw.copy()
    raw["optional_domains"] = {"redesign_expanded_icd10_families": {"enabled": True},
                               "redesign_social_determinants": {"enabled": True}}
    _, m = _run(scenarios, validate_config(raw))
    t = m.set_index("scenario")
    assert t.at["hypertension_only", "tier"] == TIER_POSSIBLE
    assert t.at["homelessness_code_only", "tier"] == TIER_POSSIBLE
    assert "redesign_social_determinants" in t.at["homelessness_code_only", "optional_domains_hit"]


def test_ohio_diagnosis_only_rule(scenarios, quiet):
    oh = load_state_config("oh")
    _, m = _run(scenarios, oh)
    t = m.set_index("scenario")["tier"]
    assert t["depression_single_outpatient"] == TIER_LIKELY   # 1 claim, dx-only
    assert t["schizophrenia_outside_window"] == TIER_THIN     # no claims inside the window


def test_diagnosis_position_limit(quiet):
    med = pd.DataFrame([{"person_id": "SYN-X", "claim_id": "c1", "claim_start_date": "2026-12-01",
                         "diagnosis_code_1": "I10", "diagnosis_code_2": "M545", "diagnosis_code_3": "F209",
                         "place_of_service_code": "11"}])
    oh = load_state_config("oh")
    assert evaluate(med, oh, AS_OF).persons["tier"].iloc[0] == TIER_THIN   # one service date, dx excluded
    assert evaluate(med, load_state_config("template"), AS_OF).persons["tier"].iloc[0] == TIER_POSSIBLE


def test_tobacco_excluded_from_sud(scenarios, template_cfg):
    _, m = _run(scenarios, template_cfg)
    assert m.set_index("scenario").at["tobacco_only", "tier"] == TIER_NONE


def test_related_provisions_reported(scenarios, quiet):
    wa = load_state_config("wa")
    r, m = _run(scenarios, wa)
    t = m.set_index("scenario")
    assert pd.notna(t.at["oud_with_moud", "related_sud_treatment_program_last_date"])
    assert t.at["schizophrenia_inpatient_psych", "hardship_inpatient_months"] != ""


def test_wa_z_code_is_adl_evidence(quiet):
    med = pd.DataFrame([
        {"person_id": "SYN-Z", "claim_id": "c1", "claim_start_date": "2026-11-01", "diagnosis_code_1": "G809",
         "diagnosis_code_2": "Z741"},
        {"person_id": "SYN-Z", "claim_id": "c2", "claim_start_date": "2026-12-01", "diagnosis_code_1": "G809"}])
    assert evaluate(med, load_state_config("wa"), AS_OF).persons["tier"].iloc[0] == TIER_LIKELY


def test_eligibility_marker(quiet):
    raw = load_state_config("template").raw.copy()
    raw["eligibility_markers"] = [{"category": "blind_or_disabled", "column": "aid_category", "values": ["D1"],
                                   "label": "synthetic disability aid category", "citation": "test fixture"}]
    cfg = validate_config(raw)
    med = pd.DataFrame([{"person_id": "SYN-E", "claim_id": "c1", "claim_start_date": "2026-12-01",
                         "diagnosis_code_1": None}])
    el = pd.DataFrame([{"person_id": "SYN-E", "enrollment_start_date": "2026-01-01", "enrollment_end_date": None,
                        "aid_category": "D1"}])
    r = evaluate(med, cfg, AS_OF, eligibility=el)
    assert r.persons["tier"].iloc[0] == TIER_LIKELY
    assert (r.evidence["role"] == "eligibility").any()


def test_missing_required_column_raises(template_cfg):
    with pytest.raises(ValueError, match="missing required columns"):
        evaluate(pd.DataFrame({"person_id": ["a"]}), template_cfg, AS_OF)


def test_tuva_aliases_and_dotted_codes(template_cfg):
    med = pd.DataFrame([{"member_id": "SYN-A", "claim_id": "c1", "claim_start_date": "2026-12-01",
                         "diagnosis_code_1": "n18.6", "place_of_service": "65"}])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        r = evaluate(med, template_cfg, AS_OF)
    assert r.persons["tier"].iloc[0] == TIER_LIKELY


def test_oud_diagnosis_without_treatment_is_attestation_tier(template_cfg):
    med = pd.DataFrame([
        {"person_id": "SYN-O", "claim_id": "c1", "claim_start_date": "2026-10-01", "diagnosis_code_1": "F1120",
         "place_of_service_code": "11"},
        {"person_id": "SYN-O", "claim_id": "c2", "claim_start_date": "2026-11-01", "diagnosis_code_1": "F1120",
         "place_of_service_code": "11"}])
    assert evaluate(med, template_cfg, AS_OF).persons["tier"].iloc[0] == TIER_POSSIBLE


def test_thin_record_tier(scenarios, quiet):
    """Channel B of Basu & Berkowitz 2026: absence of claims evidence is not evidence of absence."""
    r, m = _run(scenarios, load_state_config("template"))
    t = m.set_index("scenario")
    assert t.at["no_claims_enrolled", "tier"] == TIER_THIN
    assert t.at["no_claims_enrolled", "n_service_dates_in_window"] == 0
    assert "never use this tier to deny" in t.at["no_claims_enrolled", "note"]
    assert not r.persons.loc[r.persons["tier"] == TIER_THIN, "flag"].any()
    assert t.at["hypertension_only", "tier"] == TIER_NONE          # 3 service dates, no qualifying evidence


def test_thin_record_threshold_is_configurable(scenarios, quiet):
    raw = load_state_config("template").raw.copy()
    raw["thin_record_max_service_dates"] = 0
    _, m = _run(scenarios, validate_config(raw))
    assert TIER_THIN not in set(m["tier"])
    raw["thin_record_max_service_dates"] = 5
    _, m = _run(scenarios, validate_config(raw))
    assert m.set_index("scenario").at["hypertension_only", "tier"] == TIER_THIN
    raw["thin_record_max_service_dates"] = -1
    with pytest.raises(Exception, match="thin_record"):
        validate_config(raw)


def test_thin_record_does_not_override_evidence(scenarios, template_cfg):
    _, m = _run(scenarios, template_cfg)
    t = m.set_index("scenario")
    assert t.at["hospice_only", "tier"] == TIER_LIKELY                         # one date, sufficient marker
    assert t.at["depression_single_outpatient", "tier"] == TIER_POSSIBLE       # one date, partial evidence


def test_tier_by_group_reports_race_and_rurality(quiet):
    from frailty_toolkit.synthetic import make_population
    med, el, ref = make_population(n=800, seed=5)
    r = evaluate(med, load_state_config("template"), AS_OF, eligibility=el)
    g = r.tier_by_group()
    assert set(g["dimension"]) == {"race_ethnicity", "rurality"}
    assert TIER_THIN in set(g["tier"])
    tot = g[(g.dimension == "rurality")].groupby("group")["pct_of_group"].sum()
    assert ((tot - 100).abs() < 0.5).all()

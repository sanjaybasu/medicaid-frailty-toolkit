"""Synthetic claims for tests and demonstrations. Contains no real member data.

Person identifiers are of the form SYN-0001. All codes come from the toolkit's own code
lists, so a synthetic claim can only use a code the toolkit already sources.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DX_COLS = [f"diagnosis_code_{i}" for i in range(1, 26)]

# Scenario: person label -> (list of claim dicts, expected tier under the template config)
# Each claim dict: days_before (as_of - service date), dx (list), hcpcs, pos, tob, rev, status
SCENARIOS: dict[str, dict] = {
    "esrd_dialysis": {"expect": "likely", "category": "serious_or_complex_medical", "claims": [
        {"d": 20, "dx": ["N186"], "hcpcs": "90999", "rev": "0821", "tob": "0721", "type": "institutional"},
        {"d": 50, "dx": ["N186"], "hcpcs": "90999", "rev": "0821", "tob": "0721", "type": "institutional"}]},
    "hospice_only": {"expect": "likely", "category": "serious_or_complex_medical", "claims": [
        {"d": 10, "dx": [], "hcpcs": "Q5001", "pos": "12"}]},
    "schizophrenia_inpatient_psych": {"expect": "likely", "category": "disabling_mental_disorder", "claims": [
        {"d": 90, "dx": ["F209"], "pos": "51"}, {"d": 60, "dx": ["F209"], "pos": "11"}]},
    "depression_single_outpatient": {"expect": "possible_needs_attestation", "category": "disabling_mental_disorder",
                                     "claims": [{"d": 30, "dx": ["F331"], "pos": "11"}]},
    "depression_two_dates_no_util": {"expect": "possible_needs_attestation", "category": "disabling_mental_disorder",
                                     "claims": [{"d": 30, "dx": ["F331"], "pos": "11"},
                                                {"d": 120, "dx": ["F331"], "pos": "11"}]},
    "oud_with_moud": {"expect": "likely", "category": "substance_use_disorder", "claims": [
        {"d": 40, "dx": ["F1120"], "pos": "11", "hcpcs": "J0572"}, {"d": 70, "dx": ["F1120"], "pos": "11"}]},
    "cp_wheelchair": {"expect": "likely", "category": "physical_idd_disability_adl", "claims": [
        {"d": 100, "dx": ["G809"], "pos": "11"}, {"d": 200, "dx": ["G809"], "pos": "12", "hcpcs": "K0001"}]},
    "personal_care_only": {"expect": "possible_needs_attestation", "category": "physical_idd_disability_adl",
                           "claims": [{"d": 15, "dx": [], "hcpcs": "T1019", "pos": "12"},
                                      {"d": 45, "dx": [], "hcpcs": "T1019", "pos": "12"}]},
    "hypertension_only": {"expect": "not_identified", "category": None, "claims": [
        {"d": 30, "dx": ["I10"], "pos": "11"}, {"d": 90, "dx": ["I10"], "pos": "11"},
        {"d": 150, "dx": ["I10"], "pos": "11"}]},
    "schizophrenia_outside_window": {"expect": "thin_record_outreach", "category": None, "claims": [
        {"d": 400, "dx": ["F209"], "pos": "51"}, {"d": 430, "dx": ["F209"], "pos": "11"}]},
    "legal_blindness": {"expect": "likely", "category": "blind_or_disabled", "claims": [
        {"d": 25, "dx": ["H548"], "pos": "11"}, {"d": 85, "dx": ["H548"], "pos": "11"}]},
    "copd_single_inpatient": {"expect": "likely", "category": "serious_or_complex_medical", "claims": [
        {"d": 33, "dx": ["J441"], "tob": "0111", "type": "institutional", "rev": "0120"}]},
    "esrd_denied_claims": {"expect": "likely", "category": "serious_or_complex_medical", "claims": [
        {"d": 20, "dx": ["N186"], "hcpcs": "90999", "rev": "0821", "tob": "0721", "status": "denied",
         "type": "institutional"}]},
    "tobacco_only": {"expect": "not_identified", "category": None, "claims": [
        {"d": 30, "dx": ["F17210"], "pos": "11"}, {"d": 60, "dx": ["F17210"], "pos": "11"}]},
    "homelessness_code_only": {"expect": "not_identified", "category": None, "claims": [
        {"d": 30, "dx": ["Z5900"], "pos": "11"}, {"d": 60, "dx": ["Z5900"], "pos": "11"}]},
    "hiv_without_severity": {"expect": "possible_needs_attestation", "category": "serious_or_complex_medical",
                             "claims": [{"d": 30, "dx": ["B20"], "pos": "11"}, {"d": 120, "dx": ["B20"], "pos": "11"}]},
    "breast_cancer_chemo": {"expect": "likely", "category": "serious_or_complex_medical", "claims": [
        {"d": 30, "dx": ["C50911"], "pos": "22", "hcpcs": "J9171"}, {"d": 51, "dx": ["C50911"], "pos": "22"}]},
    "intellectual_disability_habilitation": {"expect": "likely", "category": "physical_idd_disability_adl", "claims": [
        {"d": 30, "dx": ["F71"], "pos": "11"}, {"d": 60, "dx": ["F71"], "pos": "99", "hcpcs": "T2021"}]},
}
# Persons with pharmacy-only or eligibility-only records
PHARMACY_ONLY = {"buprenorphine_pharmacy_only": {"expect": "possible_needs_attestation", "days_before": 20}}
ELIGIBILITY_ONLY = {"no_claims_enrolled": {"expect": "thin_record_outreach"}}


def person_ids(labels) -> dict:
    return {lab: f"SYN-{i:04d}" for i, lab in enumerate(labels, start=1)}


def make_scenarios(as_of="2027-01-01"):
    """Return (medical_claim, pharmacy_claim, eligibility, expected) DataFrames."""
    from .definitions import load_codes

    as_of = pd.Timestamp(as_of)
    labels = list(SCENARIOS) + list(PHARMACY_ONLY) + list(ELIGIBILITY_ONLY)
    ids = person_ids(labels)
    rows = []
    for lab, sc in SCENARIOS.items():
        for j, c in enumerate(sc["claims"]):
            r = {"person_id": ids[lab], "claim_id": f"{ids[lab]}-C{j + 1}", "claim_line_number": 1,
                 "claim_start_date": (as_of - pd.Timedelta(days=c["d"])).date(),
                 "claim_type": c.get("type", "professional"), "hcpcs_code": c.get("hcpcs"),
                 "place_of_service_code": c.get("pos"), "bill_type_code": c.get("tob"),
                 "revenue_center_code": c.get("rev"), "claim_status": c.get("status", "paid")}
            for k, col in enumerate(DX_COLS):
                r[col] = c["dx"][k] if k < len(c["dx"]) else None
            rows.append(r)
    medical = pd.DataFrame(rows)
    ndc = load_codes()
    bup = ndc[ndc["component_id"].str.endswith("__ndc_buprenorphine")]["code"].iloc[0]
    pharmacy = pd.DataFrame([{"person_id": ids[lab], "claim_id": f"{ids[lab]}-RX1", "claim_line_number": 1,
                              "dispensing_date": (as_of - pd.Timedelta(days=v["days_before"])).date(),
                              "ndc_code": bup, "claim_status": "paid"} for lab, v in PHARMACY_ONLY.items()])
    elig = pd.DataFrame([{"person_id": ids[lab], "enrollment_start_date": (as_of - pd.DateOffset(months=24)).date(),
                          "enrollment_end_date": None} for lab in labels])
    exp = pd.DataFrame([{"person_id": ids[lab], "scenario": lab,
                         "expected_tier": {**SCENARIOS, **PHARMACY_ONLY, **ELIGIBILITY_ONLY}[lab]["expect"],
                         "expected_category": SCENARIOS.get(lab, {}).get("category")} for lab in labels])
    return medical, pharmacy, elig, exp


def make_population(n=4000, seed=7, as_of="2027-01-01", detection_by_race=None, rural_penalty=0.1):
    """Synthetic population with a known reference label and race- and rurality-differential
    claims visibility, for exercising the validation harness. Numbers are arbitrary."""
    rng = np.random.default_rng(seed)
    as_of = pd.Timestamp(as_of)
    races = np.array(["White", "Black", "Hispanic", "AIAN", "Asian"])
    race = rng.choice(races, size=n, p=[0.45, 0.25, 0.2, 0.05, 0.05])
    rural = np.where(rng.random(n) < 0.2, "nonmetro", "metro")
    detection_by_race = detection_by_race or {"White": 0.8, "Black": 0.65, "Hispanic": 0.7, "AIAN": 0.55, "Asian": 0.75}
    frail = rng.random(n) < 0.25
    pids = [f"SYN-P{i:05d}" for i in range(n)]
    templates = [SCENARIOS[k] for k in ("esrd_dialysis", "schizophrenia_inpatient_psych", "oud_with_moud",
                                         "cp_wheelchair", "breast_cancer_chemo", "legal_blindness")]
    noise = SCENARIOS["hypertension_only"]
    rows = []
    for i, pid in enumerate(pids):
        chosen = []
        p_detect = detection_by_race[race[i]] - (rural_penalty if rural[i] == "nonmetro" else 0.0)
        if frail[i] and rng.random() < p_detect:
            chosen.append(templates[rng.integers(len(templates))])
        if not frail[i] and rng.random() < 0.04:  # false-positive-like utilisation
            chosen.append(templates[rng.integers(len(templates))])
        if rng.random() < 0.5:
            chosen.append(noise)
        for t_i, t in enumerate(chosen):
            for j, c in enumerate(t["claims"]):
                r = {"person_id": pid, "claim_id": f"{pid}-{t_i}-{j}", "claim_line_number": 1,
                     "claim_start_date": (as_of - pd.Timedelta(days=c["d"])).date(),
                     "claim_type": c.get("type", "professional"), "hcpcs_code": c.get("hcpcs"),
                     "place_of_service_code": c.get("pos"), "bill_type_code": c.get("tob"),
                     "revenue_center_code": c.get("rev"), "claim_status": "paid"}
                for k, col in enumerate(DX_COLS):
                    r[col] = c["dx"][k] if k < len(c["dx"]) else None
                rows.append(r)
    medical = pd.DataFrame(rows)
    ref = pd.DataFrame({"person_id": pids, "reference_frail": frail.astype(int), "race_ethnicity": race,
                        "rurality": rural, "state": "TEMPLATE"})
    # outcomes for convergent validity: frail people have more acute care and cost
    mm = rng.integers(6, 13, size=n)
    lam = np.where(frail, 1.2, 0.3) * mm / 12
    ref["acute_care_events"] = rng.poisson(lam)
    ref["member_months"] = mm
    ref["total_paid"] = np.round(rng.gamma(2.0, np.where(frail, 900, 250)) * mm, 2)
    elig = pd.DataFrame({"person_id": pids, "enrollment_start_date": (as_of - pd.DateOffset(months=24)).date(),
                         "enrollment_end_date": None, "race_ethnicity": race, "rurality": rural})
    return medical, elig, ref

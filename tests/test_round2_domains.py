"""SAMHSA and DSM-5-TR mental disorder lists, antipsychotic NDCs, the pregnancy/postpartum
exclusion, CPT descriptor hygiene, national-scope configs."""
import re
import subprocess
import warnings
from pathlib import Path

import pandas as pd
import pytest

from frailty_toolkit import TIER_LIKELY, TIER_POSSIBLE, evaluate, load_state_config
from frailty_toolkit.definitions import component_codes, load_codes, load_sources
from frailty_toolkit.states import ConfigError, available_examples, validate_config

AS_OF = "2027-01-01"
ROOT = Path(__file__).resolve().parents[1]


def _raw():
    return load_state_config("template").raw.copy()


def test_mental_disorder_category_uses_samhsa_and_dsm5tr():
    c = load_state_config("template").categories["disabling_mental_disorder"]
    for ref in ("samhsa_mhcld_schizophrenia_psychotic", "samhsa_mhcld_trauma_stressor", "dsm5tr_trauma_stressor",
                "dsm5tr_adjustment_disorders"):
        assert ref in c.dx_components
    assert "rxnav_antipsychotic_ndc" in c.impairment_components
    assert c.require_impairment_evidence
    assert not c.sufficient_components            # no diagnosis qualifies on its own
    assert len(component_codes("samhsa_mhcld_schizophrenia_psychotic")) >= 20


def test_samhsa_only_code_is_attributed_to_samhsa():
    ccw = set(component_codes("ccw_schizophrenia_and_other_psychotic_disorders")["code"])
    sam = component_codes("samhsa_mhcld_schizophrenia_psychotic")
    only = sorted(set(sam["code"]) - ccw)
    assert only, "expected at least one SAMHSA-only psychotic-disorder code"
    code = only[0]
    med = pd.DataFrame([
        {"person_id": "SYN-S", "claim_id": "c1", "claim_start_date": "2026-11-01", "diagnosis_code_1": code,
         "place_of_service_code": "51"},
        {"person_id": "SYN-S", "claim_id": "c2", "claim_start_date": "2026-12-01", "diagnosis_code_1": code,
         "place_of_service_code": "11"}])
    r = evaluate(med, load_state_config("template"), AS_OF)
    assert r.persons["tier"].iloc[0] == TIER_LIKELY
    ev = r.evidence[r.evidence["role"] == "dx"]
    assert set(ev["source_id"]) == {"samhsa_mhcld_2023"}


def test_trauma_codes_valid_in_fy2027_and_complete():
    t = pd.concat([component_codes("dsm5tr_trauma_stressor"), component_codes("dsm5tr_adjustment_disorders")])
    assert (t["source_id"] == "cms_icd10cm_fy2027").all()      # present in the FY2027 order file
    prefixes = ("F430", "F431", "F432", "F438", "F439", "F941", "F942")
    assert all(c.startswith(prefixes) for c in t["code"])
    for p in prefixes:
        assert any(c.startswith(p) for c in t["code"]), p
    assert {"F4310", "F4311", "F4312", "F4381", "F4389"} <= set(t["code"])


def test_ptsd_with_antipsychotic_dispensing_is_likely():
    ndc = component_codes("rxnav_antipsychotic_ndc")["code"].iloc[0]
    med = pd.DataFrame([{"person_id": "SYN-P", "claim_id": f"c{i}", "claim_start_date": d, "diagnosis_code_1": "F4312",
                         "place_of_service_code": "11"} for i, d in enumerate(["2026-10-01", "2026-11-01"])])
    ph = pd.DataFrame([{"person_id": "SYN-P", "claim_id": "rx1", "dispensing_date": "2026-11-15", "ndc_code": ndc}])
    assert evaluate(med, load_state_config("template"), AS_OF, pharmacy_claims=ph).persons["tier"].iloc[0] == TIER_LIKELY
    assert evaluate(med, load_state_config("template"), AS_OF).persons["tier"].iloc[0] == TIER_POSSIBLE


def test_antipsychotic_ndcs_exclude_lithium_and_antiemetics():
    d = pd.concat([component_codes("rxnav_antipsychotic_ndc"), component_codes("fda_ndc_antipsychotic_epc")])
    assert len(d) > 1000 and d["code"].str.fullmatch(r"\d{11}").all()
    low = d["description"].str.lower()
    for bad in ("lithium", "prochlorperazine", "droperidol"):
        assert not low.str.contains(bad).any(), bad


def test_pregnancy_is_separate_from_frailty():
    med = pd.DataFrame([
        {"person_id": "SYN-Q", "claim_id": "c1", "claim_start_date": "2026-08-01", "diagnosis_code_1": "Z3401"},
        {"person_id": "SYN-Q", "claim_id": "c2", "claim_start_date": "2026-09-01", "diagnosis_code_1": "O99280"},
        {"person_id": "SYN-Q", "claim_id": "c3", "claim_start_date": "2026-10-01", "hcpcs_code": "59400"}])
    r = evaluate(med, load_state_config("template"), AS_OF)
    p = r.persons.iloc[0]
    assert p["exemptions_claims"] == "pregnancy_postpartum"
    assert not p["flag"] and p["categories_met"] == ""
    assert pd.Timestamp(p["pregnancy_last_service_date"]) == pd.Timestamp("2026-10-01")
    assert "pregnancy" not in " ".join(load_state_config("template").categories)
    raw = _raw()
    raw["categories"]["pregnancy_postpartum"] = {"enabled": True}
    with pytest.raises(ConfigError):
        validate_config(raw)


def test_postpartum_window_is_configurable():
    med = pd.DataFrame([{"person_id": "SYN-R", "claim_id": "c1", "claim_start_date": "2026-03-01",
                         "diagnosis_code_1": "Z390"}])
    raw = _raw()
    raw["specified_exemptions"] = {"pregnancy_postpartum": {"postpartum_months": 6}}
    assert evaluate(med, validate_config(raw), AS_OF).persons["exemptions_claims"].iloc[0] == ""
    raw["specified_exemptions"] = {"pregnancy_postpartum": {"postpartum_months": 12}}
    assert evaluate(med, validate_config(raw), AS_OF).persons["exemptions_claims"].iloc[0] == "pregnancy_postpartum"
    raw["specified_exemptions"] = {"pregnancy_postpartum": {"postpartum_months": 40}}
    with pytest.raises(ConfigError):
        validate_config(raw)


def test_eligibility_only_exemption_markers():
    raw = _raw()
    raw["exemption_markers"] = [{"exemption": "former_foster_youth", "column": "aid_group", "values": ["FFY"],
                                 "citation": "synthetic fixture"}]
    med = pd.DataFrame([{"person_id": "SYN-F", "claim_id": "c1", "claim_start_date": "2026-12-01"}])
    el = pd.DataFrame([{"person_id": "SYN-F", "enrollment_start_date": "2026-01-01", "enrollment_end_date": None,
                        "aid_group": "FFY"}])
    p = evaluate(med, validate_config(raw), AS_OF, eligibility=el).persons.iloc[0]
    assert p["exemptions_eligibility"] == "former_foster_youth" and p["exemptions_claims"] == ""
    raw["exemption_markers"] = [{"exemption": "homeless", "column": "x", "values": ["1"], "citation": "x"}]
    with pytest.raises(ConfigError):
        validate_config(raw)


def test_cpt_codes_carry_no_ama_descriptors():
    cpt = load_codes().query("code_system == 'CPT'")
    assert cpt["code"].str.fullmatch(r"\d{5}").all()
    desc = cpt["description"].fillna("")
    assert (desc.eq("") | desc.str.contains("CPT code", regex=False)).all(), desc.unique()[:5]
    # phrases that appear in AMA CPT descriptors of codes the toolkit lists; none may appear in the repo
    phrases = ["Office or other outpatient visit for the evaluation and management",
               "Hemodialysis procedure with single evaluation", "Routine obstetric care including antepartum care",
               "Vaginal delivery only", "Cesarean delivery only", "Dialysis procedure other than hemodialysis"]
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split() or \
        [str(p.relative_to(ROOT)) for p in ROOT.rglob("*.*") if ".git" not in p.parts]
    for f in files:
        p = ROOT / f
        if p.suffix in {".svg"} or not p.exists() or p.name == Path(__file__).name:
            continue
        text = p.read_text(errors="ignore")
        for ph in phrases:
            assert ph.lower() not in text.lower(), (f, ph)


def test_new_sources_registered_with_hash_and_license():
    src = load_sources()
    for sid in ("samhsa_mhcld_2023", "nlm_rxnav_n05a", "fda_ndc_directory", "ama_cpt2027_maternity",
                "ne_dhhs_mf_index", "dsm5tr_2022", "friedman_2011_dsm5_trauma"):
        assert sid in src and src[sid].get("license")
        if src[sid].get("file"):
            assert re.fullmatch(r"[0-9a-f]{64}", src[sid]["sha256"])
    assert src["friedman_2011_dsm5_trauma"]["url"] == "https://doi.org/10.1002/da.20845"


def test_federal_default_is_primary_and_examples_load():
    assert set(available_examples()) >= {"wa", "va", "oh", "il", "ne"}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for e in available_examples():
            assert "example" in load_state_config(e).rule_version
            assert load_state_config(f"examples/{e}").state == load_state_config(e).state
    assert load_state_config("federal").state == "TEMPLATE"


def test_nebraska_example_uses_state_index():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ne = load_state_config("ne")
    code = component_codes("ne_dhhs_mf_dx_other")["code"].iloc[0]
    med = pd.DataFrame([{"person_id": "SYN-N", "claim_id": "c1", "claim_start_date": "2026-12-01",
                         "diagnosis_code_1": code, "place_of_service_code": "11"}])
    assert evaluate(med, ne, AS_OF).persons["tier"].iloc[0] == TIER_LIKELY

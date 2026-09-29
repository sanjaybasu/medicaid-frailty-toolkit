"""Validation checks that need only public data.

(a) coverage   every federal category, in every bundled state config, has diagnosis codes
               and impairment or sufficient markers.
(b) provenance every code in every component is found in the source file it cites
               (requires the downloaded source cache), and concordance between the toolkit's
               category lists and the Elixhauser/CCW groupings they overlap with.
(c) redesign   how the Basu & Berkowitz 2026 redesign families relate to the federal lists.

Usage:
    python -m frailty_toolkit.validation.public_checks --out DIR [--cache-dir CACHE]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import zipfile
from pathlib import Path

import pandas as pd

from ..definitions import (FEDERAL_CATEGORY_ORDER, component_codes, load_category_definitions,
                           load_codes, load_components, load_sources)
from ..states import available_states, load_state_config


# ---------------------------------------------------------------------------
# (a) coverage
# ---------------------------------------------------------------------------
def _n_codes(refs, exclude_prefixes=()) -> int:
    """Number of distinct (code_system, code) pairs across the referenced components."""
    if not refs:
        return 0
    c = pd.concat([component_codes(r)[["code_system", "code"]] for r in refs]).drop_duplicates()
    if exclude_prefixes:
        c = c[~((c["code_system"] == "ICD10CM") & c["code"].str.startswith(tuple(exclude_prefixes)))]
    return int(c.shape[0])


def coverage_check() -> pd.DataFrame:
    rows = []
    for st in available_states():
        cfg = load_state_config(st)
        for cat in FEDERAL_CATEGORY_ORDER:
            s = cfg.categories[cat]
            n_dx, n_imp = _n_codes(s.dx_components, s.exclude_dx_prefixes), _n_codes(s.impairment_components)
            n_suf, n_pos = _n_codes(s.sufficient_components), _n_codes(s.possible_components)
            ok = s.enabled and (n_dx + n_suf) > 0 and (n_imp + n_suf > 0 or not s.require_impairment_evidence
                                                        or bool(s.strong_dx_prefixes))
            rows.append({"state_config": st, "rule_version": cfg.rule_version, "category": cat, "cfr": s.cfr,
                         "enabled": s.enabled, "n_dx_components": len(s.dx_components), "n_dx_codes": n_dx,
                         "n_impairment_components": len(s.impairment_components), "n_impairment_codes": n_imp,
                         "n_sufficient_components": len(s.sufficient_components), "n_sufficient_codes": n_suf,
                         "n_possible_codes": n_pos, "passes": ok})
    return pd.DataFrame(rows)


def category_source_table() -> pd.DataFrame:
    """Category -> component -> source, for documentation."""
    defs = load_category_definitions()
    comps = load_components().set_index("component_id")
    src = load_sources()
    rows = []
    for cat in FEDERAL_CATEGORY_ORDER:
        d = defs["federal_categories"][cat]
        for role in ("dx_components", "impairment_components", "sufficient_components", "possible_components",
                     "optional_dx_components"):
            for ref in d.get(role, []):
                cid = ref.split(":")[0]
                c = comps.loc[cid]
                sids = sorted({s for s in re.split(r"[,; ]+", str(c["source_id"])) if s in src})
                rows.append({"category": cat, "cfr": d["cfr"], "role": role.replace("_components", ""),
                             "component": ref, "label": c["label"], "code_system": c["code_system"],
                             "n_codes": len(component_codes(ref)),
                             "sources": "; ".join(sids) or str(c["source_id"]),
                             "source_versions": "; ".join(f"{src[s]['version']}" for s in sids)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# (b) provenance and concordance
# ---------------------------------------------------------------------------
def _dotted(code: str) -> str:
    return code if len(code) <= 3 else f"{code[:3]}.{code[3:]}"


def provenance_check(cache_dir: Path) -> pd.DataFrame:
    """Re-open each source file and confirm every code attributed to it is present."""
    codes = load_codes()
    src = load_sources()
    rows = []
    cache_dir = Path(cache_dir)

    # Elixhauser: code must be flagged 1 under the named comorbidity column
    m = pd.read_excel(cache_dir / src["hcup_cmr_v2026_1"]["file"], sheet_name="DX_to_Comorb_Mapping",
                      header=1, dtype=str)
    m = m.rename(columns={m.columns[0]: "code"}).set_index("code")
    ex = codes[codes["source_id"] == "hcup_cmr_v2026_1"]
    for cid, g in ex.groupby("component_id"):
        col = cid.replace("elix_", "").upper()
        ok = g["code"].map(lambda c: c in m.index and str(m.at[c, col]) == "1")
        rows.append({"component_id": cid, "source_id": "hcup_cmr_v2026_1", "n": len(g), "n_found": int(ok.sum())})

    # CCW PDFs: the dotted code string must appear in the PDF text; NDCs as 11 digits
    for sid in ("ccw_otcc_2026_08", "ccw_chronic30_2026_08"):
        txt = subprocess.run(["pdftotext", "-layout", str(cache_dir / src[sid]["file"]), "-"],
                             capture_output=True, text=True, check=True).stdout
        tokens = set(re.findall(r"[A-Z0-9][A-Z0-9.]{2,10}", txt))
        g0 = codes[codes["source_id"] == sid]
        for cid, g in g0.groupby("component_id"):
            ok = g.apply(lambda r: (_dotted(r["code"]) if r["code_system"] == "ICD10CM" else r["code"]) in tokens,
                         axis=1)
            rows.append({"component_id": cid, "source_id": sid, "n": len(g), "n_found": int(ok.sum())})

    # ICD-10-CM order files
    icd = set()
    for fy in (2024, 2025, 2026, 2027):
        z = zipfile.ZipFile(cache_dir / src[f"cms_icd10cm_fy{fy}"]["file"])
        name = [n for n in z.namelist() if re.search(rf"icd10cm_order_{fy}\.txt$", n)][0]
        icd |= {ln[6:13].strip() for ln in z.read(name).decode("latin-1").splitlines() if len(ln) > 14}
    g0 = codes[codes["source_id"].str.startswith("cms_icd10cm")]
    for cid, g in g0.groupby("component_id"):
        rows.append({"component_id": cid, "source_id": "cms_icd10cm_fy2024..2027", "n": len(g),
                     "n_found": int(g["code"].isin(icd).sum())})
    # all ICD-10-CM codes in any component must be valid in at least one of FY2024-FY2027
    allicd = codes[codes["code_system"] == "ICD10CM"]
    rows.append({"component_id": "ALL_ICD10CM_CODES", "source_id": "cms_icd10cm_fy2024..2027",
                 "n": allicd["code"].nunique(), "n_found": int(allicd["code"].drop_duplicates().isin(icd).sum())})

    # HCPCS file
    z = zipfile.ZipFile(cache_dir / src["cms_hcpcs_2026_oct"]["file"])
    name = [n for n in z.namelist() if re.search(r"ANWEB_\d+\.xlsx$", n)][0]
    with z.open(name) as f:
        hc = set(pd.read_excel(f, dtype=str)["HCPC"])
    g0 = codes[codes["code_system"] == "HCPCS"]
    for cid, g in g0.groupby("component_id"):
        rows.append({"component_id": cid, "source_id": "cms_hcpcs_2026_oct (membership)", "n": len(g),
                     "n_found": int(g["code"].isin(hc).sum())})

    # POS page
    t = (cache_dir / src["cms_pos"]["file"]).read_text(errors="replace")
    pos = set(re.findall(r">\s*(\d{2})\s*<", t))
    g0 = codes[codes["code_system"] == "POS"]
    for cid, g in g0.groupby("component_id"):
        rows.append({"component_id": cid, "source_id": "cms_pos", "n": len(g), "n_found": int(g["code"].isin(pos).sum())})

    # Individually cited codes: the literal code (or 'NNNx' prefix form) appears in the cited document
    txts = {}
    for sid in ("cms_mcpm_ch8", "cms_mcpm_ch10", "cms_mcpm_ch11"):
        txts[sid] = subprocess.run(["pdftotext", "-layout", str(cache_dir / src[sid]["file"]), "-"],
                                   capture_output=True, text=True, check=True).stdout
    txts["resdac_fac_type"] = (cache_dir / src["resdac_fac_type"]["file"]).read_text(errors="replace")
    txts["resdac_srvc_cls"] = (cache_dir / src["resdac_srvc_cls"]["file"]).read_text(errors="replace")
    g0 = codes[codes["source_id"].isin(txts)]
    for cid, g in g0.groupby("component_id"):
        def found(r):
            t = txts[r["source_id"]]
            c = r["code"]
            if r["code_system"] == "TOB_PREFIX":
                return (f"0{c}x" in t or f"0{c}X" in t) if r["source_id"].startswith("cms_mcpm") else True
            if r["code_system"] == "REV_PREFIX" and len(c) == 3:
                return f"{c}x" in t or f"{c}X" in t
            return c in t
        ok = g.apply(found, axis=1)
        rows.append({"component_id": cid, "source_id": ",".join(sorted(set(g["source_id"]))), "n": len(g),
                     "n_found": int(ok.sum())})
    out = pd.DataFrame(rows)
    out["all_found"] = out["n"] == out["n_found"]
    return out


CONCORDANCE_PAIRS = [
    ("substance_use_disorder (default dx)", "category:substance_use_disorder",
     ["elix_alcohol", "elix_drug_abuse"]),
    ("disabling_mental_disorder (default dx)", "category:disabling_mental_disorder",
     ["elix_psychoses", "elix_depress"]),
    ("CCW leukemias and lymphomas", ["ccw_leukemias_and_lymphomas"], ["elix_cancer_leuk", "elix_cancer_lymph"]),
    ("CCW30 heart failure and non-ischemic heart disease", ["ccw30_heart_failure_and_non_ischemic_heart_disease"],
     ["elix_hf"]),
    ("CCW30 COPD", ["ccw30_chronic_obstructive_pulmonary_disease"], ["elix_lung_chronic"]),
    ("IFC-named Parkinson's disease (G20)", ["ifc_parkinson"], ["ccw30_parkinson_s_disease_and_secondary_parkinsonism"]),
    ("IFC-named HIV disease (B20) + Elixhauser AIDS", ["ifc_hiv_disease", "elix_aids"],
     ["ccw_human_immunodeficiency_virus_and_or_acquired_immunodeficienc"]),
    ("CCW mobility impairments + spinal cord injury + CP", ["ccw_mobility_impairments", "ccw_spinal_cord_injury",
                                                            "ccw_cerebral_palsy"], ["elix_paralysis"]),
    ("IFC-named ESRD/dialysis", ["ifc_esrd_dialysis"], ["elix_renlfl_sev"]),
    ("Elixhauser dementia (cognitive impairment)", ["elix_dementia"],
     ["ccw30_alzheimer_s_disease", "ccw30_non_alzheimer_s_dementia"]),
]


def _codes_for(spec) -> set:
    if isinstance(spec, str) and spec.startswith("category:"):
        cat = spec.split(":", 1)[1]
        d = load_category_definitions()["federal_categories"][cat]
        s = set()
        for r in d["dx_components"]:
            s |= set(component_codes(r).query("code_system == 'ICD10CM'")["code"])
        for p in d.get("exclude_dx_prefixes", []):
            s = {c for c in s if not c.startswith(p)}
        return s
    s = set()
    for r in spec:
        s |= set(component_codes(r).query("code_system == 'ICD10CM'")["code"])
    return s


def concordance() -> pd.DataFrame:
    desc = load_codes().drop_duplicates("code").set_index("code")["description"]
    rows = []
    for label, a, b in CONCORDANCE_PAIRS:
        A, B = _codes_for(a), _codes_for(b)
        inter = A & B
        rows.append({"comparison": label, "toolkit_list": a if isinstance(a, str) else "+".join(a),
                     "reference_grouping": "+".join(b), "n_toolkit": len(A), "n_reference": len(B),
                     "n_both": len(inter), "jaccard": round(len(inter) / max(len(A | B), 1), 3),
                     "pct_toolkit_in_reference": round(100 * len(inter) / max(len(A), 1), 1),
                     "pct_reference_in_toolkit": round(100 * len(inter) / max(len(B), 1), 1),
                     "examples_toolkit_only": "; ".join(f"{c} {desc.get(c, '')[:40]}" for c in sorted(A - B)[:5]),
                     "examples_reference_only": "; ".join(f"{c} {desc.get(c, '')[:40]}" for c in sorted(B - A)[:5])})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# (c) redesign mapping
# ---------------------------------------------------------------------------
REDESIGN_MAPPING = [
    ("Expanded ICD-10 recognition (13 CA+NY families)",
     "optional_domains.redesign_expanded_icd10_families (attestation tier only)",
     "The IFC requires a state list consistent with the five categories and says hypertension, diabetes, "
     "obesity, asthma are not typically qualifying (91 FR 33376); whole-chapter families are outreach aids."),
    ("Z59/Z60 social-determinant codes", "optional_domains.redesign_social_determinants (attestation tier only)",
     "The IFC states homelessness alone is not a medical condition (91 FR 33373)."),
    ("ADL threshold of 1 (federal floor)", "physical_idd_disability_adl: any one ADL marker satisfies impairment",
     "Statute: 'significantly impairs ... 1 or more activities of daily living'."),
    ("HIE integration", "engine accepts encounter records from any source in medical_claim (data_source column kept)",
     "42 CFR 435.557(f)(1) names encounter data as reliable information."),
    ("Full ex parte determination", "engine runs on administrative data with no enrollee action",
     "42 CFR 435.557(f)(1) requires an attempt to verify from reliable information first."),
    ("Short claims lag", "evaluation date and window are explicit; pended and denied claims included",
     "42 CFR 435.557(f)(1) includes pended and denied claims, which shortens effective lag."),
    ("No physician certification", "no certification input exists in the engine",
     "IFC allows provider documentation from many practitioner types (91 FR 33406)."),
]


def redesign_overlap() -> pd.DataFrame:
    defs = load_category_definitions()
    fam = {}
    for r in defs["optional_domains"]["redesign_expanded_icd10_families"]["dx_components"] + \
            defs["optional_domains"]["redesign_social_determinants"]["dx_components"]:
        fam[r] = set(component_codes(r)["code"])
    union = set().union(*fam.values())
    rows = []
    for cat in FEDERAL_CATEGORY_ORDER:
        s = _codes_for(f"category:{cat}")
        inside = s & union
        rows.append({"category": cat, "n_federal_default_dx_codes": len(s), "n_inside_redesign_families": len(inside),
                     "pct_inside": round(100 * len(inside) / max(len(s), 1), 1),
                     "chapters_outside": ", ".join(sorted({c[0] for c in s - union}))})
    allfed = set().union(*[_codes_for(f"category:{c}") for c in FEDERAL_CATEGORY_ORDER])
    rows.append({"category": "ALL (union)", "n_federal_default_dx_codes": len(allfed),
                 "n_inside_redesign_families": len(allfed & union),
                 "pct_inside": round(100 * len(allfed & union) / len(allfed), 1),
                 "chapters_outside": ", ".join(sorted({c[0] for c in allfed - union}))})
    rows.append({"category": "redesign families (union)", "n_federal_default_dx_codes": len(union),
                 "n_inside_redesign_families": len(union & allfed),
                 "pct_inside": round(100 * len(union & allfed) / len(union), 1),
                 "chapters_outside": "share of redesign-family codes that are in any federal default list"})
    return pd.DataFrame(rows)


def run_all(out: Path, cache_dir: Path | None = None) -> dict:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    res = {}
    cov = coverage_check()
    cov.to_csv(out / "a_coverage_by_state_category.csv", index=False)
    res["coverage_all_pass"] = bool(cov["passes"].all())
    category_source_table().to_csv(out / "category_to_source_table.csv", index=False)
    con = concordance()
    con.to_csv(out / "b_concordance_with_elixhauser_ccw.csv", index=False)
    if cache_dir is not None:
        prov = provenance_check(cache_dir)
        prov.to_csv(out / "b_provenance_every_code_in_source.csv", index=False)
        res["provenance_all_found"] = bool(prov["all_found"].all())
        res["provenance_n_codes_checked"] = int(prov.loc[prov["component_id"] != "ALL_ICD10CM_CODES", "n"].sum())
    ov = redesign_overlap()
    ov.to_csv(out / "c_redesign_family_overlap.csv", index=False)
    pd.DataFrame(REDESIGN_MAPPING, columns=["paper_redesign_modification", "toolkit_feature", "regulatory_note"]) \
        .to_csv(out / "c_redesign_mapping.csv", index=False)
    (out / "summary.json").write_text(json.dumps(res, indent=2))
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--cache-dir", type=Path, default=None)
    a = ap.parse_args(argv)
    print(json.dumps(run_all(a.out, a.cache_dir), indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Convert the medically frail workbook that Washington HCA published (prepared by
Ne'eman, McIntyre, Smithers, Sommers; Harvard T.H. Chan School of Public Health and
Brigham and Women's Hospital) into an `external_code_lists` CSV, at run time.

The workbook is NOT bundled with this toolkit. Its cover page states: "These materials are
free to use with attribution to the research team for any state agency. However,
for-profit entities must contact Harvard University's Office of Technology Development at
otd@harvard.edu for a license for permission to use." The terms grant use to state
agencies and require a license for for-profit entities; they do not grant a right to
redistribute. The workbook also reproduces AMA CPT descriptors. Run this only if your
organization is covered by those terms; the output keeps code numbers and categories and
drops every description.

    python scripts/import_hca_workbook.py --workbook medically-frail-code-list.xlsx \\
        --out /secure/path/hca_workbook_codes.csv --accept-terms

Then, in a state config (see states/examples/wa.yaml):
    external_code_lists: [{path: /secure/path/hca_workbook_codes.csv, citation: "..."}]
    min_impairment_dates: 2   # workbook method: 2+ qualifying outpatient services ...
    # ... or any inpatient stay with a qualifying diagnosis
    categories: {<each category>: {inpatient_with_dx_counts_as_impairment: true}}
"""
import argparse
import sys

import pandas as pd

CATEGORY = {"blind or disabled": "blind_or_disabled", "sud": "substance_use_disorder",
            "dmd": "disabling_mental_disorder", "pd-id-dd": "physical_idd_disability_adl",
            "scmc": "serious_or_complex_medical"}
ALL = list(CATEGORY.values())


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--workbook", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--accept-terms", action="store_true",
                    help="confirm your organization may use the workbook under its stated terms")
    a = ap.parse_args(argv)
    if not a.accept_terms:
        sys.exit(__doc__)
    dx = pd.read_excel(a.workbook, sheet_name="Medical Frailty ICD-10 codes", dtype=str)
    dx.columns = [c.strip() for c in dx.columns]
    rows = []
    for _, r in dx.iterrows():
        cat = CATEGORY.get(str(r.get("Statutory Category", "")).strip().lower())
        code = str(r.get("Diagnosis Code", "")).strip().replace(".", "").upper()
        if not cat or not code:
            continue
        kind = str(r.get("Type of Code", "")).upper()
        if "NDC" in kind or "HCPCS" in kind:
            system = "NDC" if code.isdigit() and len(code) == 11 else "HCPCS"
            rows.append((code, system, cat, "impairment"))
        else:
            rows.append((code, "ICD10CM", cat, "dx"))
    ut = pd.read_excel(a.workbook, sheet_name="Utilization Codes CPT_HCPCS", dtype=str)
    for code in ut.iloc[:, 0].dropna().str.strip().str.upper():
        system = "CPT" if code[:1].isdigit() else "HCPCS"
        rows.extend((code, system, cat, "impairment") for cat in ALL)
    out = pd.DataFrame(rows, columns=["code", "code_system", "category", "role"]).drop_duplicates()
    out.to_csv(a.out, index=False)
    print(f"wrote {len(out)} rows (no descriptions) to {a.out}")


if __name__ == "__main__":
    main()

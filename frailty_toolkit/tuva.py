"""Adapters for the Tuva Project core data model.

Tuva's core `medical_claim` table does not carry diagnosis_code_1..25; diagnoses live in
the core `condition` table (one row per claim diagnosis, with `claim_id`,
`condition_rank`, and `normalized_code`, stored without dots). `attach_conditions`
pivots those rows back onto the claims in the wide layout the engine reads.
"""
from __future__ import annotations

import pandas as pd

N_DX = 25


def _norm_id(s: pd.Series) -> pd.Series:
    return s.map(lambda v: str(int(v)) if isinstance(v, float) and v.is_integer() else str(v))


def attach_conditions(medical_claim: pd.DataFrame, condition: pd.DataFrame,
                      code_types=("icd-10-cm",), code_col: str = "normalized_code") -> pd.DataFrame:
    """Return medical_claim with diagnosis_code_1..25 filled from the Tuva condition table.

    Rows are matched on claim_id and ordered by condition_rank (then code). Condition rows
    without a claim_id, or with a code type outside `code_types`, are ignored. Existing
    diagnosis_code_* columns on medical_claim are replaced."""
    need = {"claim_id", code_col}
    if not need <= set(condition.columns):
        raise ValueError(f"condition table needs columns {sorted(need)}")
    c = condition[condition["claim_id"].notna() & condition[code_col].notna()].copy()
    if code_types and "normalized_code_type" in c.columns:
        c = c[c["normalized_code_type"].astype(str).str.lower().isin([t.lower() for t in code_types])]
    c["claim_id"] = _norm_id(c["claim_id"])
    c["_code"] = c[code_col].astype(str).str.upper().str.replace(r"[^0-9A-Z]", "", regex=True)
    rank = c["condition_rank"] if "condition_rank" in c.columns else pd.Series(0, index=c.index)
    c = c.assign(_rank=pd.to_numeric(rank, errors="coerce").fillna(999)).sort_values(["claim_id", "_rank", "_code"])
    c = c.drop_duplicates(["claim_id", "_code"])
    c["_pos"] = c.groupby("claim_id").cumcount() + 1
    c = c[c["_pos"] <= N_DX]
    wide = c.pivot(index="claim_id", columns="_pos", values="_code")
    wide.columns = [f"diagnosis_code_{i}" for i in wide.columns]
    for i in range(1, N_DX + 1):
        if f"diagnosis_code_{i}" not in wide.columns:
            wide[f"diagnosis_code_{i}"] = pd.NA
    wide = wide[[f"diagnosis_code_{i}" for i in range(1, N_DX + 1)]].reset_index()
    mc = medical_claim.drop(columns=[x for x in medical_claim.columns if x.startswith("diagnosis_code_")])
    mc = mc.assign(claim_id=_norm_id(mc["claim_id"]))
    return mc.merge(wide, on="claim_id", how="left")

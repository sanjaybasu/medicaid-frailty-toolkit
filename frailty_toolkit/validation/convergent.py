"""Convergent validity: do flagged people have more later acute care and higher cost?

Outcome columns (per person, measured in a follow-up window AFTER the flag window):
    acute_care_events   count of emergency department visits plus inpatient admissions
    member_months       months enrolled in the follow-up window (exposure)
    total_paid          total paid amount in the follow-up window (optional)

Rates are per member-year (events / (member_months / 12)); cost is PMPM
(total_paid / member_months). Group rates use exact Poisson CIs; rate ratios and PMPM
differences use a person-level percentile bootstrap. These are descriptive associations,
not causal effects.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .metrics import bootstrap_ci, poisson_rate_ci


def convergent_validity(persons: pd.DataFrame, outcomes: pd.DataFrame, group_col: str = "flag",
                        n_boot: int = 2000, seed: int = 20260929) -> pd.DataFrame:
    need = {"person_id", "acute_care_events", "member_months"}
    if not need <= set(outcomes.columns):
        raise ValueError(f"outcomes need columns {sorted(need)}")
    o = outcomes.copy()
    o["person_id"] = o["person_id"].astype("string")
    p = persons[["person_id", group_col]].copy()
    p["person_id"] = p["person_id"].astype("string")
    df = o.merge(p, on="person_id", how="left")
    df[group_col] = df[group_col].fillna(False if group_col == "flag" else "not_identified")
    df = df[df["member_months"] > 0].reset_index(drop=True)
    has_cost = "total_paid" in df.columns
    rows = []
    for g, sub in df.groupby(group_col):
        ev, mm = float(sub["acute_care_events"].sum()), float(sub["member_months"].sum())
        r, lo, hi = poisson_rate_ci(ev, mm / 12)
        row = {group_col: g, "n_people": len(sub), "member_months": mm, "acute_care_events": ev,
               "acute_care_per_member_year": r, "acute_care_lo": lo, "acute_care_hi": hi}
        if has_cost:
            pmpm = sub["total_paid"].sum() / mm
            idx_all = np.arange(len(sub))
            vals, mms = sub["total_paid"].values, sub["member_months"].values
            plo, phi, _ = bootstrap_ci(lambda idx: vals[idx].sum() / mms[idx].sum(), len(idx_all),
                                       n_boot=n_boot, seed=seed)
            row.update({"pmpm": pmpm, "pmpm_lo": plo, "pmpm_hi": phi})
        rows.append(row)
    out = pd.DataFrame(rows)
    if group_col == "flag" and set(df["flag"]) == {True, False}:
        f = df["flag"].values.astype(bool)
        ev, mm = df["acute_care_events"].values.astype(float), df["member_months"].values.astype(float)

        def rr(idx):
            a, b = idx[f[idx]], idx[~f[idx]]
            if len(a) == 0 or len(b) == 0 or ev[b].sum() == 0:
                return np.nan
            return (ev[a].sum() / mm[a].sum()) / (ev[b].sum() / mm[b].sum())
        lo, hi, _ = bootstrap_ci(rr, len(df), n_boot=n_boot, seed=seed, strata=f)
        extra = {group_col: "ratio_flagged_vs_not", "acute_care_rate_ratio": rr(np.arange(len(df))),
                 "acute_care_rr_lo": lo, "acute_care_rr_hi": hi}
        if has_cost:
            tp = df["total_paid"].values.astype(float)

            def dpmpm(idx):
                a, b = idx[f[idx]], idx[~f[idx]]
                if len(a) == 0 or len(b) == 0:
                    return np.nan
                return tp[a].sum() / mm[a].sum() - tp[b].sum() / mm[b].sum()
            dlo, dhi, _ = bootstrap_ci(dpmpm, len(df), n_boot=n_boot, seed=seed, strata=f)
            extra.update({"pmpm_difference": dpmpm(np.arange(len(df))), "pmpm_diff_lo": dlo, "pmpm_diff_hi": dhi})
        out = pd.concat([out, pd.DataFrame([extra])], ignore_index=True)
    return out

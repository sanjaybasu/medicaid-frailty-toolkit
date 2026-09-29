"""Validation of engine output against a reference-label file.

Reference file columns
    person_id (required), reference_frail (required; 1/0 or true/false),
    race_ethnicity (optional), state (optional),
    reference_<category> (optional per-category reference labels).

Three operating points are reported: 'likely' (flag == True), 'likely_or_possible'
(any claims evidence; the set a caseworker would review), and 'any_outreach' (also
including the thin_record_outreach tier).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..definitions import FEDERAL_CATEGORY_ORDER
from ..engine import TIER_LIKELY, TIER_POSSIBLE, TIER_THIN
from .metrics import bootstrap_ci, diagnostic_metrics

OPERATING_POINTS = {
    "likely": (TIER_LIKELY,),
    "likely_or_possible": (TIER_LIKELY, TIER_POSSIBLE),
    # every route to exclusion or outreach, including the thin-record tier
    "any_outreach": (TIER_LIKELY, TIER_POSSIBLE, TIER_THIN),
}
EQUITY_DIMENSIONS = ("race_ethnicity", "rurality")


def _truthy(s: pd.Series) -> pd.Series:
    if s.dtype == bool:
        return s
    return s.astype(str).str.strip().str.lower().isin(["1", "true", "t", "yes", "y"])


def join_reference(persons: pd.DataFrame, reference: pd.DataFrame, missing_tier: str = TIER_THIN) -> pd.DataFrame:
    """Left-join engine output onto the reference file. People in the reference whom the
    engine never saw (no claims and no eligibility rows) are kept, are not flagged, and are
    assigned `missing_tier` (default thin_record_outreach, since they have no claims)."""
    ref = reference.copy()
    ref["person_id"] = ref["person_id"].astype("string")
    if "reference_frail" not in ref.columns:
        raise ValueError("reference file needs a reference_frail column")
    ref["reference_frail"] = _truthy(ref["reference_frail"])
    keep = ["person_id", "tier", "flag", "categories_met", "categories_partial", "n_service_dates_in_window"] + \
        [c for c in persons.columns if c.startswith("cat_")]
    p = persons[[c for c in keep if c in persons.columns]].copy()
    p["person_id"] = p["person_id"].astype("string")
    df = ref.merge(p, on="person_id", how="left", suffixes=("", "_engine"))
    df["tier"] = df["tier"].fillna(missing_tier)
    df["flag"] = df["flag"].astype("boolean").fillna(False).astype(bool)
    for c in [c for c in df.columns if c.startswith("cat_")]:
        df[c] = df[c].fillna("none")
    return df


def overall_metrics(df: pd.DataFrame, by: str | None = None) -> pd.DataFrame:
    rows = []
    if by is not None:
        df = df.assign(**{by: df[by].astype("object").where(df[by].notna(), "missing")})
    groups = [("all", df)] if by is None else list(df.groupby(by))
    for g, sub in groups:
        for op, tiers in OPERATING_POINTS.items():
            m = diagnostic_metrics(sub["tier"].isin(tiers).values, sub["reference_frail"].values)
            rows.append({"group": g, "operating_point": op, **m})
    return pd.DataFrame(rows)


def race_sensitivity_gaps(df: pd.DataFrame, race_col: str = "race_ethnicity", reference_group: str = "White",
                          n_boot: int = 2000, seed: int = 20260929, min_positives: int = 10) -> pd.DataFrame:
    """Sensitivity by race/ethnicity and the gap (reference group minus group) with
    percentile bootstrap CIs, resampling reference-positive people within race strata."""
    if race_col not in df.columns:
        return pd.DataFrame()
    pos = df[df["reference_frail"]].reset_index(drop=True)
    race = pos[race_col].astype("object").where(pos[race_col].notna(), "missing").astype(str).values
    rows = []
    for op, tiers in OPERATING_POINTS.items():
        hit = pos["tier"].isin(tiers).values.astype(float)
        if reference_group not in set(race):
            continue
        ref_mask = race == reference_group
        for g in sorted(set(race)):
            gm = race == g
            n_g = int(gm.sum())
            sens = hit[gm].mean() if n_g else np.nan
            row = {"operating_point": op, "race_ethnicity": g, "n_reference_positive": n_g,
                   "n_flagged": int(hit[gm].sum()), "sensitivity": sens}
            if g != reference_group and n_g >= min_positives and ref_mask.sum() >= min_positives:
                def stat(idx, gm=gm):
                    r = ref_mask[idx]
                    q = gm[idx]
                    if r.sum() == 0 or q.sum() == 0:
                        return np.nan
                    return hit[idx][r].mean() - hit[idx][q].mean()
                lo, hi, _ = bootstrap_ci(stat, len(pos), n_boot=n_boot, seed=seed, strata=race)
                row.update({"gap_vs_reference_pp": 100 * (hit[ref_mask].mean() - sens),
                            "gap_lo_pp": 100 * lo, "gap_hi_pp": 100 * hi, "reference_group": reference_group})
            elif g != reference_group:
                row.update({"gap_vs_reference_pp": np.nan, "note": f"fewer than {min_positives} reference positives"})
            rows.append(row)
    return pd.DataFrame(rows)


def per_category_table(df: pd.DataFrame) -> pd.DataFrame:
    """For each federal category: confusion of 'category met' against reference_frail, and
    against reference_<category> when the reference file supplies it."""
    rows = []
    for cat in FEDERAL_CATEGORY_ORDER:
        col = f"cat_{cat}"
        if col not in df.columns:
            continue
        pred = df[col].eq("met").values
        m = diagnostic_metrics(pred, df["reference_frail"].values)
        rows.append({"category": cat, "reference": "reference_frail", **m,
                     "n_met": int(pred.sum()), "n_partial": int(df[col].eq("partial").sum())})
        rc = f"reference_{cat}"
        if rc in df.columns:
            m2 = diagnostic_metrics(pred, _truthy(df[rc]).values)
            rows.append({"category": cat, "reference": rc, **m2, "n_met": int(pred.sum()),
                         "n_partial": int(df[col].eq("partial").sum())})
    return pd.DataFrame(rows)


def validate(persons: pd.DataFrame, reference: pd.DataFrame, reference_group: str = "White",
             n_boot: int = 2000, seed: int = 20260929) -> dict[str, pd.DataFrame]:
    df = join_reference(persons, reference)
    out = {"overall": overall_metrics(df), "per_category": per_category_table(df)}
    if "state" in df.columns:
        out["by_state"] = overall_metrics(df, by="state")
    if "race_ethnicity" in df.columns:
        out["by_race"] = overall_metrics(df, by="race_ethnicity")
        out["race_sensitivity_gaps"] = race_sensitivity_gaps(df, reference_group=reference_group,
                                                             n_boot=n_boot, seed=seed)
    out["tier_by_reference"] = pd.crosstab(df["tier"], df["reference_frail"]).reset_index()
    tg = tier_distribution(df)
    if len(tg):
        out["tier_by_group"] = tg
    for dim in EQUITY_DIMENSIONS:
        if dim in df.columns and dim != "race_ethnicity":
            out[f"by_{dim}"] = overall_metrics(df, by=dim)
    return out


def tier_distribution(df: pd.DataFrame) -> pd.DataFrame:
    """Tier sizes by race/ethnicity and rurality (when present), overall and among
    reference-positive people. The thin_record_outreach share among reference-positive
    people is the claims-visibility gap the paper's Channel B describes."""
    rows = []
    for dim in EQUITY_DIMENSIONS:
        if dim not in df.columns:
            continue
        g = df[dim].astype("object").where(df[dim].notna(), "missing")
        for subset, mask in (("all", pd.Series(True, index=df.index)), ("reference_positive", df["reference_frail"])):
            tab = pd.crosstab(g[mask], df.loc[mask, "tier"])
            for grp, r in tab.iterrows():
                n = int(r.sum())
                for tier, k in r.items():
                    rows.append({"dimension": dim, "subset": subset, "group": grp, "tier": tier, "n": int(k),
                                 "n_group": n, "pct_of_group": 100 * k / n if n else float("nan")})
    return pd.DataFrame(rows)


def write_report(results: dict[str, pd.DataFrame], outdir) -> list:
    from pathlib import Path
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    paths = []
    for k, v in results.items():
        p = outdir / f"{k}.csv"
        v.to_csv(p, index=False)
        paths.append(p)
    return paths

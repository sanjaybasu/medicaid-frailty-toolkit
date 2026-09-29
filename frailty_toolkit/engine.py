"""Claims-based screening engine for the medically frail exclusion.

Input tables follow the Tuva Project data model (https://thetuvaproject.com):

medical_claim (required)
    person_id, claim_id, claim_start_date, claim_type, hcpcs_code, place_of_service_code
    (alias: place_of_service), diagnosis_code_1 .. diagnosis_code_25.
    Optional: claim_line_number, bill_type_code, revenue_center_code, claim_status
    (paid / pended / denied), data_source.
pharmacy_claim (optional)
    person_id, claim_id, dispensing_date (alias: claim_start_date), ndc_code.
eligibility (optional)
    person_id, enrollment_start_date, enrollment_end_date, plus any columns referenced by
    the state config's eligibility_markers.

Output (FrailtyResult)
    persons   one row per person: tier, flag, categories met/partial, related provisions.
    evidence  one row per matched code on a claim: category, role, component, code,
              description, claim_id, claim line, date, so a caseworker can audit each flag.

Tiers
    likely                       at least one federal category met
    possible_needs_attestation   some evidence, no category met; request attestation or
                                 provider documentation
    thin_record_outreach         no qualifying evidence AND fewer than
                                 `thin_record_max_service_dates` distinct service dates in the
                                 window (or no claims at all). Absence of evidence is not evidence of
                                 absence; route to proactive attestation outreach, never to
                                 non-exemption.
    not_identified               no qualifying evidence in the window. This is NOT a finding
                                 that the person is not medically frail: the absence of claims
                                 "may not be used to determine ineligibility for the exclusion"
                                 (CMS-2454-IFC, 91 FR 33406).

The output is a screening aid for exemption review. It is never a final eligibility
determination; the state agency makes that determination.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .definitions import component_codes, load_codes, split_component_ref
from .states import StateConfig

TIER_LIKELY = "likely"
TIER_POSSIBLE = "possible_needs_attestation"
TIER_THIN = "thin_record_outreach"
TIER_NONE = "not_identified"
N_DX = 25

NOT_IDENTIFIED_NOTE = ("No qualifying claims evidence in the look-back window. This is not a determination "
                       "that the person is not medically frail (CMS-2454-IFC, 91 FR 33406); the person may "
                       "request consideration with documentation (42 CFR 435.554(c)(5)(ii)(C)).")
SCREENING_NOTE = "Screening aid for exemption review; not an eligibility determination."
THIN_NOTE = ("Few or no claims in the look-back window. Absence of claims evidence is not evidence of absence: "
             "real conditions are under-documented in claims, more so for some groups (Basu & Berkowitz 2026). "
             "Route to proactive attestation outreach; never use this tier to deny the exclusion.")
EQUITY_COLUMN_CANDIDATES = {
    "race_ethnicity": ["race_ethnicity", "race", "ethnicity"],
    "rurality": ["rurality", "rural_urban", "metro_status", "ruca", "rural"],
}

ALIASES = {"place_of_service": "place_of_service_code", "dispensing_date": "claim_start_date",
           "member_id": "person_id"}


@dataclass
class FrailtyResult:
    persons: pd.DataFrame
    evidence: pd.DataFrame
    config: StateConfig
    as_of: pd.Timestamp
    window_start: pd.Timestamp

    def summary(self) -> pd.DataFrame:
        s = self.persons["tier"].value_counts().rename_axis("tier").reset_index(name="n")
        s["pct"] = (100 * s["n"] / max(len(self.persons), 1)).round(1)
        return s

    def tier_by_group(self) -> pd.DataFrame:
        """Tier sizes (n and % of the group) by race/ethnicity and by rurality, for whichever
        of those columns the eligibility input carried. Empty if neither is present."""
        rows = []
        for col in EQUITY_COLUMN_CANDIDATES:
            if col not in self.persons.columns:
                continue
            g = self.persons[col].astype("object").where(self.persons[col].notna(), "missing")
            tab = pd.crosstab(g, self.persons["tier"])
            for grp, r in tab.iterrows():
                n = int(r.sum())
                for tier, k in r.items():
                    rows.append({"dimension": col, "group": grp, "tier": tier, "n": int(k), "n_group": n,
                                 "pct_of_group": round(100 * k / n, 1) if n else float("nan")})
        return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _norm_icd(s: pd.Series) -> pd.Series:
    return s.astype("string").str.upper().str.replace(r"[^0-9A-Z]", "", regex=True)


def _norm_hcpcs(s: pd.Series) -> pd.Series:
    return s.astype("string").str.upper().str.strip().str[:5]


def _norm_pos(s: pd.Series) -> pd.Series:
    x = s.astype("string").str.replace(r"\D", "", regex=True)
    return x.where(x.str.len() > 0).str.zfill(2)


def _norm_tob_prefix(s: pd.Series) -> pd.Series:
    x = s.astype("string").str.replace(r"\D", "", regex=True)
    x = x.where(~((x.str.len() == 4) & x.str.startswith("0")), x.str[1:])
    return x.str[:2]


def _norm_rev(s: pd.Series) -> pd.Series:
    x = s.astype("string").str.replace(r"\D", "", regex=True)
    return x.where(x.str.len() > 0).str.zfill(4)


def _norm_ndc(s: pd.Series) -> pd.Series:
    return s.astype("string").str.replace(r"\D", "", regex=True)


def _prepare(df: pd.DataFrame, name: str, required: list[str]) -> pd.DataFrame:
    df = df.rename(columns={k: v for k, v in ALIASES.items() if k in df.columns and v not in df.columns})
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"{name} is missing required columns {missing}")
    df = df.copy()
    df["person_id"] = df["person_id"].astype("string")
    df["claim_start_date"] = pd.to_datetime(df["claim_start_date"], errors="coerce")
    if "claim_id" not in df.columns:
        warnings.warn(f"{name} has no claim_id; using row numbers, which weakens the audit trail", stacklevel=3)
        df["claim_id"] = [f"{name}_row{i}" for i in range(len(df))]
    df["claim_id"] = df["claim_id"].astype("string")
    if "claim_line_number" not in df.columns:
        df["claim_line_number"] = pd.NA
    return df


def _window(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    return df[(df["claim_start_date"] >= start) & (df["claim_start_date"] <= end)]


def _status_filter(df: pd.DataFrame, statuses: list[str]) -> pd.DataFrame:
    if "claim_status" not in df.columns:
        return df
    st = df["claim_status"].astype("string").str.lower().str.strip()
    known = st.isin(["paid", "pended", "denied"])
    if (~known & st.notna()).any():
        warnings.warn("claim_status values other than paid/pended/denied are kept", stacklevel=3)
    return df[st.isin(statuses) | ~known | st.isna()]


# ---------------------------------------------------------------------------
# lookup construction
# ---------------------------------------------------------------------------
def build_lookup(config: StateConfig) -> pd.DataFrame:
    """(code_system, code) -> (group, role, component_id) for every code this config uses.

    group is a federal category name, 'optional:<domain>', 'related:<provision>', or
    'inpatient_definition'."""
    parts = []

    def add(ref: str, group: str, role: str):
        c = component_codes(ref)[["code_system", "code", "description"]].copy()
        cid, prefix = split_component_ref(ref)
        c["component_id"] = cid if prefix is None else f"{cid}:{prefix}"
        c["group"], c["role"] = group, role
        parts.append(c)

    for name in config.enabled_categories:
        spec = config.categories[name]
        for role, refs in (("dx", spec.dx_components), ("impairment", spec.impairment_components),
                           ("sufficient", spec.sufficient_components), ("possible", spec.possible_components)):
            for r in refs:
                add(r, name, role)
        for e in spec.extra_codes:
            code = str(e["code"]).upper().replace(".", "")
            parts.append(pd.DataFrame([{
                "code_system": e["code_system"], "code": code, "description": e.get("label", ""),
                "component_id": "state_extra_code", "group": name, "role": e["role"]}]))
    for x in config.external_code_lists:
        parts.append(load_external_code_list(x, config))
    for k, d in config.optional_domains.items():
        if d["enabled"]:
            for r in d["dx_components"]:
                add(r, f"optional:{k}", "dx")
    for k, d in config.related_provisions.items():
        if d["enabled"]:
            for r in d["components"]:
                add(r, f"related:{k}", "marker")
    for r in config.inpatient_definition["pos_components"] + config.inpatient_definition["tob_components"]:
        add(r, "inpatient_definition", "marker")
    lk = pd.concat(parts, ignore_index=True).drop_duplicates(["code_system", "code", "group", "role", "component_id"])

    # category-specific exclusions and remission handling
    for name in config.enabled_categories:
        spec = config.categories[name]
        m = (lk["group"] == name) & (lk["role"] == "dx") & (lk["code_system"] == "ICD10CM")
        for p in spec.exclude_dx_prefixes:
            lk = lk[~(m & lk["code"].str.startswith(p))]
            m = (lk["group"] == name) & (lk["role"] == "dx") & (lk["code_system"] == "ICD10CM")
        if spec.remission_codes == "possible_only":
            rem = m & lk["description"].str.contains("in remission", case=False, na=False)
            lk.loc[rem, "role"] = "possible"
        if spec.strong_dx_prefixes:
            strong = m & lk["code"].str.startswith(tuple(spec.strong_dx_prefixes))
            extra = lk[strong].copy()
            extra["role"] = "strong_dx"
            lk = pd.concat([lk, extra], ignore_index=True)
    return lk.reset_index(drop=True)


def load_external_code_list(spec: dict, config: StateConfig) -> pd.DataFrame:
    """Load a state-supplied code list at run time (never bundled in the package).

    CSV columns: code, code_system (ICD10CM|HCPCS|CPT|NDC|POS|TOB_PREFIX|REV_PREFIX),
    category (a federal category name), role (dx|impairment|sufficient|possible),
    optional description. The config entry must carry the list's citation."""
    from pathlib import Path

    p = Path(spec["path"]).expanduser()
    df = pd.read_csv(p, dtype=str, keep_default_na=False)
    need = {"code", "code_system", "category", "role"}
    if not need <= set(df.columns):
        raise ValueError(f"external code list {p} needs columns {sorted(need)}")
    bad = set(df["category"]) - set(config.categories)
    if bad:
        raise ValueError(f"external code list {p}: unknown categories {sorted(bad)}")
    df = df[df["category"].isin(config.enabled_categories)]
    out = pd.DataFrame({
        "code_system": df["code_system"].str.upper(),
        "code": df["code"].str.upper().str.replace(".", "", regex=False).str.strip(),
        "description": df.get("description", pd.Series("", index=df.index)),
        "component_id": f"external:{p.name}", "group": df["category"], "role": df["role"]})
    return out


# ---------------------------------------------------------------------------
# event extraction
# ---------------------------------------------------------------------------
def _medical_events(mc: pd.DataFrame, lookup: pd.DataFrame) -> pd.DataFrame:
    base = ["person_id", "claim_id", "claim_line_number", "claim_start_date"]
    ev = []
    dx_codes = set(lookup.loc[lookup["code_system"] == "ICD10CM", "code"])
    for i in range(1, N_DX + 1):
        col = f"diagnosis_code_{i}"
        if col not in mc.columns:
            continue
        codes = _norm_icd(mc[col])
        keep = codes.isin(dx_codes)
        if keep.any():
            e = mc.loc[keep, base].copy()
            e["code"], e["code_system"], e["field"] = codes[keep].values, "ICD10CM", col
            e["dx_position"] = i
            ev.append(e)
    if "hcpcs_code" in mc.columns:
        codes = _norm_hcpcs(mc["hcpcs_code"])
        for system in ("HCPCS", "CPT"):
            keep = codes.isin(set(lookup.loc[lookup["code_system"] == system, "code"]))
            if keep.any():
                e = mc.loc[keep, base].copy()
                e["code"], e["code_system"], e["field"] = codes[keep].values, system, "hcpcs_code"
                ev.append(e)
    if "place_of_service_code" in mc.columns:
        codes = _norm_pos(mc["place_of_service_code"])
        keep = codes.isin(set(lookup.loc[lookup["code_system"] == "POS", "code"]))
        if keep.any():
            e = mc.loc[keep, base].copy()
            e["code"], e["code_system"], e["field"] = codes[keep].values, "POS", "place_of_service_code"
            ev.append(e)
    if "bill_type_code" in mc.columns:
        codes = _norm_tob_prefix(mc["bill_type_code"])
        keep = codes.isin(set(lookup.loc[lookup["code_system"] == "TOB_PREFIX", "code"]))
        if keep.any():
            e = mc.loc[keep, base].copy()
            e["code"], e["code_system"], e["field"] = codes[keep].values, "TOB_PREFIX", "bill_type_code"
            ev.append(e)
    if "revenue_center_code" in mc.columns:
        rev = _norm_rev(mc["revenue_center_code"])
        prefixes = set(lookup.loc[lookup["code_system"] == "REV_PREFIX", "code"])
        for n in (3, 4):
            codes = rev.str[:n]
            keep = codes.isin(prefixes)
            if keep.any():
                e = mc.loc[keep, base].copy()
                e["code"], e["code_system"], e["field"] = codes[keep].values, "REV_PREFIX", "revenue_center_code"
                ev.append(e)
    if not ev:
        return pd.DataFrame(columns=base + ["code", "code_system", "field", "source"])
    out = pd.concat(ev, ignore_index=True)
    out["source"] = "medical_claim"
    return out


def _pharmacy_events(pc: pd.DataFrame | None, lookup: pd.DataFrame) -> pd.DataFrame:
    base = ["person_id", "claim_id", "claim_line_number", "claim_start_date"]
    if pc is None or len(pc) == 0 or "ndc_code" not in pc.columns:
        return pd.DataFrame(columns=base + ["code", "code_system", "field", "source"])
    codes = _norm_ndc(pc["ndc_code"])
    keep = codes.isin(set(lookup.loc[lookup["code_system"] == "NDC", "code"]))
    e = pc.loc[keep, base].copy()
    e["code"], e["code_system"], e["field"], e["source"] = codes[keep].values, "NDC", "ndc_code", "pharmacy_claim"
    return e


def _inpatient_claims(events: pd.DataFrame, lookup: pd.DataFrame) -> set:
    ip = lookup[lookup["group"] == "inpatient_definition"][["code_system", "code"]].drop_duplicates()
    m = events.merge(ip, on=["code_system", "code"])
    return set(m["claim_id"])


# ---------------------------------------------------------------------------
# main entry point
# ---------------------------------------------------------------------------
def evaluate(medical_claims: pd.DataFrame, config: StateConfig, as_of,
             pharmacy_claims: pd.DataFrame | None = None,
             eligibility: pd.DataFrame | None = None) -> FrailtyResult:
    """Screen every person in the inputs as of `as_of` (the evaluation date)."""
    as_of = pd.Timestamp(as_of).normalize()
    start = as_of - pd.DateOffset(months=config.lookback_months) + pd.Timedelta(days=1)

    mc_all = _prepare(medical_claims, "medical_claim", ["person_id", "claim_start_date"])
    mc = _status_filter(_window(mc_all, start, as_of), config.include_claim_statuses)
    pc = None
    if pharmacy_claims is not None:
        pc_all = _prepare(pharmacy_claims, "pharmacy_claim", ["person_id", "claim_start_date"])
        pc = _status_filter(_window(pc_all, start, as_of), config.include_claim_statuses)

    lookup = build_lookup(config)
    parts = [x for x in (_medical_events(mc, lookup), _pharmacy_events(pc, lookup)) if len(x)]
    events = pd.concat(parts, ignore_index=True) if parts else _medical_events(mc.iloc[:0], lookup)
    if "dx_position" not in events.columns:
        events["dx_position"] = pd.NA
    ip_claims = _inpatient_claims(events, lookup)
    events["inpatient_claim"] = events["claim_id"].isin(ip_claims)
    hits = events.merge(lookup[lookup["group"] != "inpatient_definition"], on=["code_system", "code"])
    hits = hits.rename(columns={"claim_start_date": "service_date"})

    # universe of persons
    ids = [mc_all["person_id"]]
    if pharmacy_claims is not None:
        ids.append(pc_all["person_id"])
    if eligibility is not None:
        ids.append(eligibility["person_id"].astype("string"))
    persons = pd.DataFrame({"person_id": pd.concat(ids).dropna().drop_duplicates().sort_values().values})

    n_claims = mc.groupby("person_id")["claim_id"].nunique()
    persons["n_medical_claims_in_window"] = persons["person_id"].map(n_claims).fillna(0).astype(int)
    dates = [mc[["person_id", "claim_start_date"]]]
    if pc is not None:
        dates.append(pc[["person_id", "claim_start_date"]])
    n_dates = pd.concat(dates).dropna().drop_duplicates().groupby("person_id").size()
    persons["n_service_dates_in_window"] = persons["person_id"].map(n_dates).fillna(0).astype(int)

    status = {}
    reasons = {}
    for name in config.enabled_categories:
        st, rs = _evaluate_category(hits, config.categories[name])
        status[name], reasons[name] = st, rs

    # eligibility markers
    elig_evidence = []
    if eligibility is not None and config.eligibility_markers:
        el = eligibility.copy()
        el["person_id"] = el["person_id"].astype("string")
        s = pd.to_datetime(el.get("enrollment_start_date"), errors="coerce")
        e = pd.to_datetime(el.get("enrollment_end_date"), errors="coerce").fillna(pd.Timestamp.max)
        el = el[(s <= as_of) & (e >= start)]
        for m in config.eligibility_markers:
            if m["column"] not in el.columns:
                warnings.warn(f"eligibility marker column {m['column']} not in eligibility table", stacklevel=2)
                continue
            vals = {str(v) for v in m["values"]}
            got = el[el[m["column"]].astype("string").isin(vals)]
            for pid, v in zip(got["person_id"], got[m["column"]]):
                cat = m["category"]
                status.setdefault(cat, {})[pid] = "met"
                reasons.setdefault(cat, {})[pid] = f"eligibility marker {m['column']}={v}"
                elig_evidence.append({"person_id": pid, "group": cat, "role": "eligibility",
                                      "component_id": "eligibility_marker", "code_system": "ELIGIBILITY",
                                      "code": f"{m['column']}={v}", "description": m.get("label", ""),
                                      "source": "eligibility", "citation": m["citation"]})

    met_cols, partial_cols = [], []
    for name in config.enabled_categories:
        st = persons["person_id"].map(status.get(name, {})).fillna("none")
        persons[f"cat_{name}"] = st
        persons[f"why_{name}"] = persons["person_id"].map(reasons.get(name, {})).fillna("")
        met_cols.append(st.eq("met").rename(name))
        partial_cols.append(st.eq("partial").rename(name))
    met = pd.concat(met_cols, axis=1) if met_cols else pd.DataFrame(index=persons.index)
    partial = pd.concat(partial_cols, axis=1) if partial_cols else pd.DataFrame(index=persons.index)

    # optional domains (outreach aid; attestation tier unless counts_toward_flag)
    opt_names = {pid: [] for pid in persons["person_id"]}
    opt_flag_ids: set = set()
    for k, d in config.optional_domains.items():
        if not d["enabled"]:
            continue
        h = hits[hits["group"] == f"optional:{k}"]
        for pid in set(h["person_id"]):
            opt_names[pid].append(k)
        if d["counts_toward_flag"] and len(h):
            g = h.groupby("person_id").agg(n=("service_date", "nunique"), ip=("inpatient_claim", "any"))
            opt_flag_ids |= set(g.index[(g["n"] >= config.min_distinct_dates)
                                        | (config.single_inpatient_sufficient & g["ip"])])
    persons["optional_domains_hit"] = persons["person_id"].map(lambda p: ";".join(opt_names.get(p, [])))
    opt_hit = persons["optional_domains_hit"].ne("")
    opt_flag = persons["person_id"].isin(opt_flag_ids)

    any_met = met.any(axis=1) | opt_flag
    any_partial = partial.any(axis=1) | opt_hit
    thin = persons["n_service_dates_in_window"] < config.thin_record_max_service_dates
    persons["tier"] = np.where(any_met, TIER_LIKELY, np.where(any_partial, TIER_POSSIBLE,
                                                              np.where(thin, TIER_THIN, TIER_NONE)))
    persons["flag"] = persons["tier"].eq(TIER_LIKELY)
    persons["categories_met"] = met.apply(lambda r: ";".join(c for c, v in r.items() if v), axis=1) if len(met.columns) else ""
    persons["categories_partial"] = partial.apply(lambda r: ";".join(c for c, v in r.items() if v), axis=1) if len(partial.columns) else ""

    # related provisions
    for k, d in config.related_provisions.items():
        if not d["enabled"]:
            continue
        h = hits[hits["group"] == f"related:{k}"]
        if k == "short_term_hardship_inpatient":
            months = h.assign(m=h["service_date"].dt.strftime("%Y-%m")).groupby("person_id")["m"].apply(
                lambda s: ";".join(sorted(set(s))))
            months = months.to_dict()
            persons["hardship_inpatient_months"] = [months.get(p, "") for p in persons["person_id"]]
        else:
            last = h.groupby("person_id")["service_date"].max().to_dict()
            persons[f"related_{k}_last_date"] = pd.to_datetime(
                pd.Series([last.get(p) for p in persons["person_id"]], index=persons.index, dtype="object"))

    if eligibility is not None:
        persons["enrolled_months_in_window"] = persons["person_id"].map(
            _enrolled_months(eligibility, start, as_of)).fillna(0).astype(int)

    persons["note"] = np.select([persons["tier"].eq(TIER_NONE), persons["tier"].eq(TIER_THIN)],
                                [NOT_IDENTIFIED_NOTE, THIN_NOTE], SCREENING_NOTE)
    if eligibility is not None:
        el_last = eligibility.copy()
        el_last["person_id"] = el_last["person_id"].astype("string")
        if "enrollment_start_date" in el_last.columns:
            el_last = el_last.sort_values("enrollment_start_date")
        el_last = el_last.groupby("person_id").tail(1).set_index("person_id")
        for out_col, cands in EQUITY_COLUMN_CANDIDATES.items():
            src_col = next((c for c in cands if c in el_last.columns), None)
            if src_col and out_col not in persons.columns:
                persons[out_col] = persons["person_id"].map(el_last[src_col])
    persons.insert(1, "state", config.state)
    persons.insert(2, "rule_version", config.rule_version)
    persons.insert(3, "as_of", as_of.date().isoformat())
    persons.insert(4, "window_start", start.date().isoformat())

    evidence = _evidence_table(hits, elig_evidence, config)
    return FrailtyResult(persons=persons, evidence=evidence, config=config, as_of=as_of, window_start=start)


def _evaluate_category(hits: pd.DataFrame, spec) -> tuple[dict, dict]:
    h = hits[hits["group"] == spec.name]
    if spec.diagnosis_positions < N_DX and "dx_position" in h.columns:
        is_dx = h["code_system"].eq("ICD10CM")
        h = h[~is_dx | (h["dx_position"].fillna(99) <= spec.diagnosis_positions)]
    if h.empty:
        return {}, {}
    status: dict = {}
    why: dict = {}

    def summarize(sub: pd.DataFrame):
        if sub.empty:
            return pd.DataFrame(columns=["n_dates", "ip"])
        return sub.groupby("person_id").agg(n_dates=("service_date", "nunique"), ip=("inpatient_claim", "any"))

    dx = summarize(h[h["role"] == "dx"])
    strong = summarize(h[h["role"] == "strong_dx"])
    rule = lambda g: (g["n_dates"] >= spec.min_distinct_dates) | (spec.single_inpatient_sufficient & g["ip"])  # noqa: E731
    dx_met = set(dx.index[rule(dx)]) if len(dx) else set()
    strong_met = set(strong.index[rule(strong)]) if len(strong) else set()
    dx_ip = set(dx.index[dx["ip"]]) if len(dx) else set()

    imp_h = h[h["role"] == "impairment"]
    imp = imp_h.groupby("person_id")["component_id"].apply(lambda s: ",".join(sorted(set(s))))
    suf = h[h["role"] == "sufficient"].groupby("person_id")["component_id"].apply(lambda s: ",".join(sorted(set(s))))
    pos = h[h["role"] == "possible"].groupby("person_id")["component_id"].apply(lambda s: ",".join(sorted(set(s))))

    for pid in set(h["person_id"]):
        n = int(dx.at[pid, "n_dates"]) if pid in dx.index else 0
        has_imp = pid in imp.index or (spec.inpatient_with_dx_counts_as_impairment and pid in dx_ip)
        if pid in suf.index:
            status[pid], why[pid] = "met", f"sufficient marker: {suf[pid]}"
        elif pid in dx_met and (not spec.require_impairment_evidence or has_imp or pid in strong_met):
            parts = [f"diagnosis on {n} date(s)" + (" incl. inpatient" if pid in dx_ip else "")]
            if pid in strong_met:
                parts.append("diagnosis code itself indicates impairment")
            if pid in imp.index:
                parts.append(f"impairment/utilization: {imp[pid]}")
            elif spec.inpatient_with_dx_counts_as_impairment and pid in dx_ip:
                parts.append("inpatient stay with qualifying diagnosis")
            status[pid], why[pid] = "met", "; ".join(parts)
        else:
            parts = []
            if n:
                parts.append(f"diagnosis on {n} date(s)" + ("" if pid in dx_met else " (below count rule)"))
                if pid in dx_met:
                    parts.append("no impairment or utilization marker")
            if pid in imp.index and (n or spec.marker_alone_is_partial):
                parts.append(f"marker without qualifying diagnosis: {imp[pid]}" if not n else
                             f"marker: {imp[pid]}")
            if pid in pos.index:
                parts.append(f"weaker marker: {pos[pid]}")
            if parts:
                status[pid], why[pid] = "partial", "; ".join(parts)
    return status, why


def _enrolled_months(elig: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    el = elig.copy()
    el["person_id"] = el["person_id"].astype("string")
    s = pd.to_datetime(el["enrollment_start_date"], errors="coerce").clip(lower=start)
    e = pd.to_datetime(el["enrollment_end_date"], errors="coerce").fillna(end).clip(upper=end)
    el = el.assign(s=s, e=e)[s <= e]
    months = el.apply(lambda r: set(pd.period_range(r["s"], r["e"], freq="M")), axis=1)
    return months.groupby(el["person_id"]).apply(lambda x: len(set().union(*x)))


def _evidence_table(hits: pd.DataFrame, elig_rows: list, config: StateConfig) -> pd.DataFrame:
    cols = ["person_id", "group", "role", "component_id", "code_system", "code", "description",
            "claim_id", "claim_line_number", "service_date", "inpatient_claim", "source", "field", "source_id"]
    if hits.empty and not elig_rows:
        return pd.DataFrame(columns=cols)
    ev = hits.copy()
    codes = load_codes()
    src = codes.set_index(["component_id", "code_system", "code"])["source_id"]
    src = src[~src.index.duplicated()]
    base = ev["component_id"].astype(str).str.split(":").str[0]
    ev["source_id"] = [src.get((c, a, b), "state_config") for c, a, b in zip(base, ev["code_system"], ev["code"])]
    if elig_rows:
        ev = pd.concat([ev, pd.DataFrame(elig_rows)], ignore_index=True)
    ev = ev.reindex(columns=cols + (["citation"] if elig_rows else []))
    return ev.sort_values(["person_id", "group", "service_date"], na_position="last").reset_index(drop=True)


def iter_states(medical_claims, configs, as_of, **kw):
    """Run several state configs over the same input; yields (state, FrailtyResult)."""
    for cfg in configs:
        yield cfg.state, evaluate(medical_claims, cfg, as_of, **kw)


__all__ = ["FrailtyResult", "TIER_LIKELY", "TIER_POSSIBLE", "TIER_THIN", "TIER_NONE", "build_lookup", "evaluate",
           "iter_states", "NOT_IDENTIFIED_NOTE"]


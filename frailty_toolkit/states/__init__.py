"""Per-state configuration: loading, merging with federal defaults, and validation."""
from __future__ import annotations

import copy
import re
import warnings
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from ..definitions import (
    FEDERAL_CATEGORY_ORDER,
    load_category_definitions,
    load_components,
    split_component_ref,
)

MAX_LOOKBACK_MONTHS = 12  # 91 FR 33405: "States may not consider information older than 12 months"
CLAIM_STATUSES = {"paid", "pended", "denied"}
COMPONENT_LIST_KEYS = ("dx_components", "impairment_components", "sufficient_components", "possible_components")
TOP_LEVEL_KEYS = {
    "rule_version", "state", "state_name", "program", "policy_status", "requirement_start",
    "sources", "notes", "lookback_months", "min_distinct_dates", "single_inpatient_sufficient",
    "include_claim_statuses", "categories", "optional_domains", "related_provisions",
    "eligibility_markers", "extends", "diagnosis_positions", "external_code_lists",
    "thin_record_max_service_dates", "specified_exemptions", "exemption_markers", "min_impairment_dates",
}
CATEGORY_KEYS = {
    "enabled", "require_impairment_evidence", "min_distinct_dates", "single_inpatient_sufficient",
    "remission_codes", "inpatient_with_dx_counts_as_impairment", "extra_codes", "notes",
    "use_optional_dx_components", "diagnosis_positions", "min_impairment_dates", "replace_dx_components",
} | {f"{op}_{k}" for op in ("add", "remove") for k in COMPONENT_LIST_KEYS}


class ConfigError(ValueError):
    """Raised when a state configuration is invalid."""


@dataclass
class CategorySpec:
    name: str
    label: str
    cfr: str
    enabled: bool
    require_impairment_evidence: bool
    min_distinct_dates: int
    single_inpatient_sufficient: bool
    dx_components: list[str]
    exclude_dx_prefixes: list[str]
    strong_dx_prefixes: list[str]
    impairment_components: list[str]
    sufficient_components: list[str]
    possible_components: list[str]
    inpatient_with_dx_counts_as_impairment: bool
    remission_codes: str = "count"
    marker_alone_is_partial: bool = True
    diagnosis_positions: int = 25
    min_impairment_dates: int = 1
    extra_codes: list[dict] = field(default_factory=list)


@dataclass
class StateConfig:
    rule_version: str
    state: str
    state_name: str
    lookback_months: int
    min_distinct_dates: int
    single_inpatient_sufficient: bool
    include_claim_statuses: list[str]
    categories: dict[str, CategorySpec]
    optional_domains: dict[str, dict]
    related_provisions: dict[str, dict]
    eligibility_markers: list[dict]
    inpatient_definition: dict
    raw: dict
    diagnosis_positions: int = 25
    external_code_lists: list[dict] = field(default_factory=list)
    thin_record_max_service_dates: int = 2
    specified_exemptions: dict = field(default_factory=dict)
    exemption_markers: list[dict] = field(default_factory=list)

    @property
    def enabled_categories(self) -> list[str]:
        return [c for c in FEDERAL_CATEGORY_ORDER if self.categories[c].enabled]


def _known_components() -> set[str]:
    return set(load_components()["component_id"])


def _check_components(refs: list[str], where: str, known: set[str]) -> None:
    for r in refs:
        cid, _ = split_component_ref(r)
        if cid not in known:
            raise ConfigError(f"{where}: unknown component '{cid}' (see codelists/components.csv)")


def available_states() -> list[str]:
    """'template' (the federal default, the primary product) plus the worked state examples."""
    return ["template"] + available_examples()


def available_examples() -> list[str]:
    d = resources.files(__name__).joinpath("examples")
    return sorted(p.name[:-5] for p in d.iterdir() if p.name.endswith(".yaml"))


def _read_yaml(path_or_name: str | Path) -> dict:
    p = Path(path_or_name)
    if p.suffix in (".yaml", ".yml") and p.exists():
        return yaml.safe_load(p.read_text()) or {}
    name = str(path_or_name).lower().removeprefix("examples/")
    if name in ("federal", "federal_default"):
        name = "template"
    base = resources.files(__name__)
    for res in (base.joinpath(f"{name}.yaml"), base.joinpath("examples", f"{name}.yaml")):
        if res.is_file():
            return yaml.safe_load(res.read_text()) or {}
    raise ConfigError(f"no state config '{path_or_name}'; available: {available_states()}")


def load_state_config(path_or_name: str | Path) -> StateConfig:
    """Load a state config by bundled name ('wa', 'template') or YAML path, merge with the
    federal category definitions, and validate."""
    raw = _read_yaml(path_or_name)
    if "extends" in raw:
        base = _read_yaml(raw["extends"])
        merged = copy.deepcopy(base)
        for k, v in raw.items():
            if k in ("categories", "optional_domains", "related_provisions") and isinstance(v, dict):
                merged.setdefault(k, {})
                for kk, vv in v.items():
                    merged[k].setdefault(kk, {}).update(vv or {})
            else:
                merged[k] = v
        raw = merged
    return validate_config(raw)


def validate_config(raw: dict[str, Any]) -> StateConfig:
    unknown = set(raw) - TOP_LEVEL_KEYS
    if unknown:
        raise ConfigError(f"unknown top-level keys: {sorted(unknown)}")
    rv = raw.get("rule_version")
    if not isinstance(rv, str) or not rv.strip():
        raise ConfigError("rule_version is required (string). Bump it whenever lists or logic change; "
                          "the medically frail definition is under litigation.")
    state = raw.get("state")
    if not isinstance(state, str) or not re.fullmatch(r"[A-Z]{2}|TEMPLATE", state):
        raise ConfigError("state must be a two-letter uppercase code")
    lb = raw.get("lookback_months", 12)
    if not isinstance(lb, int) or lb < 1:
        raise ConfigError("lookback_months must be a positive integer")
    if lb > MAX_LOOKBACK_MONTHS:
        raise ConfigError(f"lookback_months={lb} exceeds 12; CMS-2454-IFC (91 FR 33405) states that "
                          "States may not consider information older than 12 months")
    mdd = raw.get("min_distinct_dates", 2)
    if not isinstance(mdd, int) or mdd < 1:
        raise ConfigError("min_distinct_dates must be an integer >= 1")
    sis = raw.get("single_inpatient_sufficient", True)
    if not isinstance(sis, bool):
        raise ConfigError("single_inpatient_sufficient must be true/false")
    dpos = raw.get("diagnosis_positions", 25)
    if not isinstance(dpos, int) or not 1 <= dpos <= 25:
        raise ConfigError("diagnosis_positions must be an integer 1-25")
    statuses = raw.get("include_claim_statuses", ["paid", "pended", "denied"])
    if not set(statuses) <= CLAIM_STATUSES or not statuses:
        raise ConfigError(f"include_claim_statuses must be a non-empty subset of {sorted(CLAIM_STATUSES)}")
    if set(statuses) != CLAIM_STATUSES:
        warnings.warn("42 CFR 435.557(f)(1) directs states to use paid, pended, and denied adjudicated "
                      f"claims; this config uses only {statuses}", stacklevel=2)

    defs = load_category_definitions()
    known = _known_components()
    cats_raw = raw.get("categories", {}) or {}
    bad = set(cats_raw) - set(FEDERAL_CATEGORY_ORDER)
    if bad:
        raise ConfigError(f"unknown categories {sorted(bad)}; the IFC does not allow states to add "
                          "categories (91 FR 33373). Use optional_domains for outreach-only domains.")
    cats: dict[str, CategorySpec] = {}
    for name in FEDERAL_CATEGORY_ORDER:
        d = defs["federal_categories"][name]
        c = cats_raw.get(name, {}) or {}
        extra = set(c) - CATEGORY_KEYS
        if extra:
            raise ConfigError(f"categories.{name}: unknown keys {sorted(extra)}")
        lists = {k: list(d.get(k, [])) for k in COMPONENT_LIST_KEYS}
        if c.get("replace_dx_components") is not None:
            lists["dx_components"] = list(c["replace_dx_components"])
        if c.get("use_optional_dx_components"):
            lists["dx_components"] += list(d.get("optional_dx_components", []))
        for k in COMPONENT_LIST_KEYS:
            for r in c.get(f"remove_{k}", []) or []:
                if r not in lists[k]:
                    raise ConfigError(f"categories.{name}.remove_{k}: '{r}' is not in the default list")
                lists[k].remove(r)
            lists[k] += [r for r in (c.get(f"add_{k}", []) or []) if r not in lists[k]]
            _check_components(lists[k], f"categories.{name}.{k}", known)
        for e in c.get("extra_codes", []) or []:
            if not {"code", "code_system", "role", "citation"} <= set(e):
                raise ConfigError(f"categories.{name}.extra_codes entries need code, code_system, role, "
                                  "and citation (every added code must cite a primary document)")
            if e["role"] not in ("dx", "impairment", "sufficient", "possible"):
                raise ConfigError(f"categories.{name}.extra_codes: bad role {e['role']}")
        rem = c.get("remission_codes", "count")
        if rem not in ("count", "possible_only"):
            raise ConfigError("remission_codes must be 'count' or 'possible_only'")
        spec = CategorySpec(
            name=name, label=d["label"], cfr=d["cfr"],
            enabled=bool(c.get("enabled", True)),
            require_impairment_evidence=bool(c.get("require_impairment_evidence", True)),
            min_distinct_dates=int(c.get("min_distinct_dates", mdd)),
            single_inpatient_sufficient=bool(c.get("single_inpatient_sufficient", sis)),
            dx_components=lists["dx_components"],
            exclude_dx_prefixes=[p.replace(".", "").upper() for p in d.get("exclude_dx_prefixes", [])],
            strong_dx_prefixes=[p.replace(".", "").upper() for p in d.get("strong_dx_prefixes", [])],
            impairment_components=lists["impairment_components"],
            sufficient_components=lists["sufficient_components"],
            possible_components=lists["possible_components"],
            inpatient_with_dx_counts_as_impairment=bool(c.get(
                "inpatient_with_dx_counts_as_impairment", d.get("inpatient_with_dx_counts_as_impairment", True))),
            remission_codes=rem,
            marker_alone_is_partial=bool(d.get("marker_alone_is_partial", True)),
            diagnosis_positions=int(c.get("diagnosis_positions", dpos)),
            min_impairment_dates=int(c.get("min_impairment_dates", raw.get("min_impairment_dates", 1))),
            extra_codes=list(c.get("extra_codes", []) or []),
        )
        if spec.enabled and not spec.require_impairment_evidence:
            warnings.warn(f"categories.{name}: require_impairment_evidence=false flags on diagnosis alone; "
                          "the IFC preamble (91 FR 33373) reads the statute as requiring that the condition "
                          "significantly impair the ability to comply", stacklevel=2)
        if spec.enabled and not spec.dx_components and not spec.sufficient_components:
            raise ConfigError(f"categories.{name} is enabled but has no diagnosis or sufficient markers")
        cats[name] = spec

    opt_raw = raw.get("optional_domains", {}) or {}
    opt = {}
    for k, d in defs["optional_domains"].items():
        o = opt_raw.get(k, {}) or {}
        enabled = bool(o.get("enabled", False))
        counts = bool(o.get("counts_toward_flag", False))
        if counts:
            warnings.warn(f"optional_domains.{k}.counts_toward_flag=true makes a non-federal domain produce "
                          "a 'likely' flag; CMS-2454-IFC does not permit added categories (91 FR 33373)",
                          stacklevel=2)
        _check_components(d["dx_components"], f"optional_domains.{k}", known)
        opt[k] = {"enabled": enabled, "counts_toward_flag": counts, **d}
    bad = set(opt_raw) - set(opt)
    if bad:
        raise ConfigError(f"unknown optional_domains {sorted(bad)}")

    rel_raw = raw.get("related_provisions", {}) or {}
    rel = {}
    for k, d in defs["related_provisions"].items():
        r = rel_raw.get(k, {}) or {}
        default_on = k == "sud_treatment_program"
        rel[k] = {"enabled": bool(r.get("enabled", default_on)), **d}
        _check_components(d["components"], f"related_provisions.{k}", known)

    em = raw.get("eligibility_markers", []) or []
    for m in em:
        if not {"category", "column", "values", "citation"} <= set(m):
            raise ConfigError("eligibility_markers entries need category, column, values, citation")
        if m["category"] not in FEDERAL_CATEGORY_ORDER:
            raise ConfigError(f"eligibility_markers: unknown category {m['category']}")

    thin = raw.get("thin_record_max_service_dates", 2)
    if not isinstance(thin, int) or thin < 0:
        raise ConfigError("thin_record_max_service_dates must be an integer >= 0 (0 disables the tier)")
    se_raw = raw.get("specified_exemptions", {}) or {}
    se_defs = defs.get("specified_exemptions", {})
    bad = set(se_raw) - set(se_defs)
    if bad:
        raise ConfigError(f"unknown specified_exemptions {sorted(bad)}")
    se = {}
    for k, d in se_defs.items():
        o = se_raw.get(k, {}) or {}
        pm = o.get("postpartum_months", 12)
        if k == "pregnancy_postpartum" and (not isinstance(pm, int) or not 1 <= pm <= 24):
            raise ConfigError("specified_exemptions.pregnancy_postpartum.postpartum_months must be 1-24")
        se[k] = {**d, "enabled": bool(o.get("enabled", True)), "postpartum_months": pm}
        for r in d.get("components", []):
            _check_components([r], f"specified_exemptions.{k}", known)
    xm = raw.get("exemption_markers", []) or []
    for m in xm:
        if not {"exemption", "column", "values", "citation"} <= set(m):
            raise ConfigError("exemption_markers entries need exemption, column, values, citation")
        if m["exemption"] not in se_defs:
            raise ConfigError(f"exemption_markers: unknown exemption {m['exemption']}")
    ext = raw.get("external_code_lists", []) or []
    for x in ext:
        if not {"path", "citation"} <= set(x):
            raise ConfigError("external_code_lists entries need path and citation")

    return StateConfig(
        diagnosis_positions=dpos, external_code_lists=list(ext), thin_record_max_service_dates=thin,
        specified_exemptions=se, exemption_markers=list(xm),
        rule_version=rv.strip(), state=state, state_name=raw.get("state_name", state),
        lookback_months=lb, min_distinct_dates=mdd, single_inpatient_sufficient=sis,
        include_claim_statuses=list(statuses), categories=cats, optional_domains=opt,
        related_provisions=rel, eligibility_markers=em,
        inpatient_definition=defs["inpatient_definition"], raw=raw,
    )


__all__ = ["CategorySpec", "ConfigError", "StateConfig", "available_examples", "available_states", "load_state_config",
           "validate_config", "MAX_LOOKBACK_MONTHS"]

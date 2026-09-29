"""Command-line interface.

    frailty-toolkit list-states
    frailty-toolkit check-config wa            # or a path to a YAML file
    frailty-toolkit screen --state wa --medical medical_claim.csv [--pharmacy pharmacy_claim.csv]
                           [--eligibility eligibility.csv] --as-of 2027-01-01 --out results/
    frailty-toolkit validate --persons results/persons.csv --reference reference.csv --out results/validation
    frailty-toolkit demo --out /tmp/frailty_demo   # synthetic data only
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from . import __version__
from .engine import evaluate
from .states import available_states, load_state_config


def _read(p):
    p = Path(p)
    return pd.read_parquet(p) if p.suffix == ".parquet" else pd.read_csv(p, dtype=str)


def cmd_screen(a):
    cfg = load_state_config(a.state)
    res = evaluate(_read(a.medical), cfg, a.as_of,
                   pharmacy_claims=_read(a.pharmacy) if a.pharmacy else None,
                   eligibility=_read(a.eligibility) if a.eligibility else None)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    res.persons.to_csv(out / "persons.csv", index=False)
    res.evidence.to_csv(out / "evidence.csv", index=False)
    res.summary().to_csv(out / "tier_summary.csv", index=False)
    (out / "run_metadata.json").write_text(json.dumps(res.metadata(), indent=2))
    print(res.summary().to_string(index=False))


def cmd_validate(a):
    from .validation import validate, write_report
    persons = pd.read_csv(a.persons, dtype={"person_id": str})
    persons["flag"] = persons["flag"].astype(str).str.lower().eq("true")
    res = validate(persons, pd.read_csv(a.reference, dtype={"person_id": str}), reference_group=a.reference_group)
    for p in write_report(res, a.out):
        print(p)


def cmd_check(a):
    cfg = load_state_config(a.config)
    print(json.dumps({"state": cfg.state, "rule_version": cfg.rule_version,
                      "lookback_months": cfg.lookback_months, "enabled_categories": cfg.enabled_categories},
                     indent=2))


def cmd_demo(a):
    from .synthetic import make_scenarios
    med, ph, el, exp = make_scenarios(a.as_of)
    res = evaluate(med, load_state_config(a.state), a.as_of, pharmacy_claims=ph, eligibility=el)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    res.persons.merge(exp, on="person_id").to_csv(out / "persons.csv", index=False)
    res.evidence.to_csv(out / "evidence.csv", index=False)
    (out / "run_metadata.json").write_text(json.dumps(res.metadata(), indent=2))
    print(res.persons.merge(exp, on="person_id")[["scenario", "tier", "categories_met"]].to_string(index=False))


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="frailty-toolkit", description=f"frailty_toolkit {__version__}",
        epilog="Screening aid, not a determination. Provided as is, without warranty; see the Disclaimer "
               "in README.md and NOTICE.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list-states").set_defaults(fn=lambda a: print("\n".join(available_states())))
    c = sub.add_parser("check-config")
    c.add_argument("config")
    c.set_defaults(fn=cmd_check)
    s = sub.add_parser("screen")
    s.add_argument("--state", required=True)
    s.add_argument("--medical", required=True)
    s.add_argument("--pharmacy")
    s.add_argument("--eligibility")
    s.add_argument("--as-of", required=True)
    s.add_argument("--out", required=True)
    s.set_defaults(fn=cmd_screen)
    v = sub.add_parser("validate")
    v.add_argument("--persons", required=True)
    v.add_argument("--reference", required=True)
    v.add_argument("--reference-group", default="White")
    v.add_argument("--out", required=True)
    v.set_defaults(fn=cmd_validate)
    d = sub.add_parser("demo")
    d.add_argument("--state", default="template")
    d.add_argument("--as-of", default="2027-01-01")
    d.add_argument("--out", required=True)
    d.set_defaults(fn=cmd_demo)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()

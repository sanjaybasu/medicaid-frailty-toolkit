# Changelog

All notable changes to this project are recorded here. Versions follow semantic versioning.
Each state configuration also carries its own `rule_version`, which changes whenever that
state's lists or logic change.

## [0.1.0] - 2026-09-29

### Added
- `frailty_toolkit.definitions`: the five federal medically frail categories of
  42 CFR 435.554(c)(5)(i)(A)-(E) (CMS-2454-IFC, 91 FR 33348, June 3, 2026), mapped to
  186 code-list components (29,830 code rows) built from AHRQ HCUP Elixhauser Refined
  v2026.1, CMS CCW condition algorithms (revised 08/2026), CMS ICD-10-CM FY2024-FY2027,
  the CMS HCPCS October 2026 file, the CMS Place of Service code set, and individually
  cited CMS manual codes. The Basu & Berkowitz 2026 redesign families are optional domains.
- `frailty_toolkit.states`: validated YAML configs for WA, VA, OH, IL and a federal-floor
  template, each with `rule_version` and cited sources.
- `frailty_toolkit.engine`: Tuva-compatible screening with four tiers (likely,
  possible_needs_attestation, thin_record_outreach, not_identified), a per-code evidence
  table, tier sizes by race/ethnicity and rurality, and reporting of the SUD
  treatment-program exclusion and the inpatient short-term hardship exception.
- `thin_record_outreach` tier (`thin_record_max_service_dates`, default 2): people with no
  qualifying evidence and few or no claims, routed to attestation outreach, never to
  non-exemption (the claims-visibility channel of Basu & Berkowitz 2026).
- `frailty_toolkit.validation`: reference-label harness (sensitivity, specificity, PPV,
  NPV with Wilson CIs at three operating points; race-stratified sensitivity gaps with
  bootstrap CIs; rurality strata; thin-record share by group; per-category tables), convergent validity (acute care per member-year and PMPM), and public-data
  checks (coverage, provenance of every code, concordance with Elixhauser and CCW).
- `scripts/build_codelists.py` to rebuild every list from the official files.
- Synthetic-data tests and GitHub Actions CI.

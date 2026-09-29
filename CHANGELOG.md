# Changelog

All notable changes to this project are recorded here. Versions follow semantic versioning.
Each state configuration also carries its own `rule_version`, which changes whenever that
state's lists or logic change.

## [0.2.0] - 2026-09-29

### Added
- Disabling mental disorder (category C): SAMHSA MH-CLD 2023 Table C-2 ICD crosswalk
  (schizophrenia and other psychotic, bipolar, depressive, panic, trauma- and
  stressor-related groups), alongside the CCW lists, with the contributing source recorded
  per code. Trauma- and stressor-related disorders mapped to the DSM-5-TR chapter
  (F43.0, F43.1x, F43.2x, F43.8x, F43.9, F94.1, F94.2; all valid in ICD-10-CM FY2027),
  adjustment disorders in a separate component. Diagnoses still require an impairment or
  service marker.
- Antipsychotic dispensing marker for category C: 7,208 NDCs from NLM RxNav (ATC N05A,
  excluding lithium, prochlorperazine, droperidol, acepromazine) plus 41 FDA NDC Directory
  "Antipsychotic [EPC]" packages not yet in RxNorm; query and date recorded for rebuild.
- Pregnancy and postpartum exclusion (SSA 1902(xx)(9)(A)(ii)(IX); 42 CFR 435.554(c)(10))
  as a separate exemption outside the frailty categories: ICD-10-CM O00-O9A, Z33.1, Z34,
  Z36, Z3A, Z39, and maternity CPT code numbers from the AMA CPT 2027 guidelines (no
  descriptors); configurable postpartum period (default 12 months).
- `specified_exemptions` and `exemption_markers`: every statutory specified exclusion and
  the 435.553 mandatory exceptions, split into claims-supported and eligibility-only, with
  citations; output columns `exemptions_claims` and `exemptions_eligibility`.
- Nebraska worked example built from the published NE DHHS conditions index.
- `scripts/import_hca_workbook.py` to convert the HCA-published workbook at run time;
  `min_impairment_dates` and `replace_dx_components` config keys.
- Disclaimer (README and NOTICE), CLI epilog, and a screening-aid note in every output
  file and `run_metadata.json`.

### Changed
- The federal default (`template`) is the primary product; state configs moved to
  `states/examples/` as worked examples (still loadable by name). README section "Using
  this in any state".
- License notes and SHA-256 for every source; docs/sources.md quotes the terms of the
  NCQA NDC lists and the HCA-published workbook, neither of which is bundled.

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

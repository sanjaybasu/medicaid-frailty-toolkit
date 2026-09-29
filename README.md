<p align="left"><img src="docs/assets/waymark-logo.svg" alt="Waymark" width="220"></p>

A Waymark work product

# Medicaid Frailty Toolkit

`frailty_toolkit` is a source-available Python package that screens Medicaid claims for adults who may qualify for the medically frail exclusion from the community engagement ("work") requirement. The requirement was added to the Social Security Act at section 1902(xx) by Public Law 119-21, section 71119, and states must implement it by January 1, 2027. CMS implemented it in the interim final rule CMS-2454-IFC (91 FR 33348, June 3, 2026; Federal Register document 2026-11094), which defines "medically frail" at 42 CFR 435.554(c)(5).

The toolkit reads claims in the [Tuva Project](https://thetuvaproject.com) data model, applies a per-state YAML configuration, and returns, for each person, a screening tier, the categories met, and an evidence table listing every code, claim, and date behind the result so that a caseworker can audit it. A validation harness reports accuracy against reference labels, race-stratified sensitivity gaps, and convergent validity against later acute care and cost.

The toolkit extends Basu S, Berkowitz SA. Redesigning Medicaid frailty algorithms: improved identification of medically frail adults under community engagement. *Health Affairs Scholar*. 2026;4(6):qxag108. doi:[10.1093/haschl/qxag108](https://doi.org/10.1093/haschl/qxag108) ([article](https://academic.oup.com/healthaffairsscholar/article/4/6/qxag108/8672780)). That paper used a microsimulation on public survey data; this package works on claims.

## What it is and what it is not

The toolkit is a screening aid for exemption review. It is never a final eligibility determination, and it must not be used as one. The state Medicaid agency determines eligibility.

A result of `not_identified` or `thin_record_outreach` means only that the look-back window contains no qualifying claims evidence. It is not a finding that the person is not medically frail. The IFC preamble states that "the absence of adjudicated claims or encounter data altogether ... may not be used to determine ineligibility for the exclusion" (91 FR 33406), and a person whose condition is not on a state's list may request consideration (42 CFR 435.554(c)(5)(ii)(C)).

The toolkit cannot establish disability as defined in section 1614 of the Social Security Act, which is a Social Security determination; states should supply eligibility-file markers for that. Claims measure functional impairment only indirectly, through services such as personal care, durable medical equipment, and inpatient care. The package has been tested on synthetic data only; its accuracy on real Medicaid populations has not yet been measured.

## Legal basis and litigation

The five federal categories, and only these five, are implemented as categories. The IFC does not permit states to add categories (91 FR 33373).

| Category (config key) | Statute | Regulation |
|---|---|---|
| Blind or disabled (`blind_or_disabled`) | SSA 1902(xx)(9)(A)(ii)(V)(aa) | 42 CFR 435.554(c)(5)(i)(A) |
| Substance use disorder, excluding stable recovery of 5 or more years (`substance_use_disorder`) | (bb) | (c)(5)(i)(B) |
| Disabling mental disorder (`disabling_mental_disorder`) | (cc) | (c)(5)(i)(C) |
| Physical, intellectual, or developmental disability that significantly impairs one or more ADLs (`physical_idd_disability_adl`) | (dd) | (c)(5)(i)(D) |
| Serious or complex medical condition (`serious_or_complex_medical`) | (ee) | (c)(5)(i)(E) |

Each category also requires that the condition "significantly impairs the individual's ability to comply with the community engagement requirement" (42 CFR 435.554(c)(5)(i)). Verification must first use "claim(s) relevant to the individual that have been adjudicated in the preceding 12 months, including those that have been paid, pended or denied, and encounter data" (42 CFR 435.557(f)(1)), and "States may not consider information older than 12 months" (91 FR 33405). The configuration loader rejects look-back windows longer than 12 months and warns when a config drops pended or denied claims.

The medically frail provisions are contested. In *Commonwealth of Massachusetts v. Oz* (D. Mass. No. 1:26-cv-12962-RGS), filed June 29, 2026 (23 states and the District of Columbia are plaintiffs, according to the Georgetown litigation tracker), the court denied a preliminary injunction on July 29, 2026 and set expedited merits briefing. A summary-judgment hearing has been reported for October 20, 2026; that date comes from secondary trackers and should be confirmed on the docket. Washington, Virginia, and Illinois are plaintiffs; Ohio is not. Because the rule could change, every state config carries a required `rule_version` string that records which rule text and which state guidance it implements, and every output row repeats it.

## Screening logic

For each enabled category the engine looks for three kinds of evidence inside the look-back window.

1. A qualifying diagnosis, counted when it appears on claims with at least `min_distinct_dates` distinct service dates (default 2) or on one inpatient claim when `single_inpatient_sufficient` is true (default). This is the CCW convention of "at least 1 inpatient claim OR 2 other non-drug claims".
2. An impairment or utilization marker for that category, such as personal care services, a wheelchair or patient lift, an inpatient psychiatric stay, medication for opioid use disorder, home oxygen, or an inpatient stay with the qualifying diagnosis.
3. A sufficient marker that meets the category on its own. By default these are hospice and maintenance dialysis for the serious or complex category.

A category is `met` when a sufficient marker is present, or when a qualifying diagnosis is present together with an impairment marker (the IFC reads the statute as requiring functional impairment; a state may set `require_impairment_evidence: false`, and the loader warns). A category is `partial` when some evidence is present but the rule is not satisfied.

| Tier | Rule | Intended action |
|---|---|---|
| `likely` | at least one category met | exclude, subject to the state's verification process |
| `possible_needs_attestation` | some evidence, no category met | ask for attestation or provider documentation |
| `thin_record_outreach` | no qualifying evidence, and fewer than `thin_record_max_service_dates` distinct service dates in the window (default 2), or no claims at all | proactive attestation outreach; never grounds for denying the exclusion |
| `not_identified` | no qualifying evidence despite a claims history | no conclusion; the person may still qualify and may request consideration |

The engine also reports two provisions that are not medical frailty but are identifiable from the same claims: participation in an SUD treatment program (42 CFR 435.554(c)(8)), reported as the most recent service date, and the optional inpatient short-term hardship exception (42 CFR 435.555(d)(1)), reported as calendar months.

## Install and quick start

```bash
pip install -e .            # Python 3.10+
pytest -q                   # synthetic-data tests
frailty-toolkit demo --out /tmp/frailty_demo
```

```python
import pandas as pd
from frailty_toolkit import evaluate, load_state_config

cfg = load_state_config("wa")                 # or a path to your own YAML
res = evaluate(medical_claim, cfg, as_of="2027-01-01",
               pharmacy_claims=pharmacy_claim, eligibility=eligibility)
res.persons      # one row per person: tier, flag, categories_met, why_<category>, ...
res.evidence     # one row per matched code: claim_id, service_date, code, component, source_id
```

```bash
frailty-toolkit screen --state wa --medical medical_claim.csv --pharmacy pharmacy_claim.csv \
    --eligibility eligibility.csv --as-of 2027-01-01 --out results/
frailty-toolkit validate --persons results/persons.csv --reference reference.csv --out results/validation
```

### Input columns

| Table | Required | Optional |
|---|---|---|
| `medical_claim` | `person_id`, `claim_start_date`; codes in `diagnosis_code_1` to `diagnosis_code_25`, `hcpcs_code`, `place_of_service_code` (alias `place_of_service`) | `claim_id` (strongly recommended), `claim_line_number`, `claim_type`, `bill_type_code`, `revenue_center_code`, `claim_status` (paid, pended, denied), `data_source` |
| `pharmacy_claim` | `person_id`, `dispensing_date` (or `claim_start_date`), `ndc_code` (11 digits) | `claim_id`, `claim_status` |
| `eligibility` | `person_id`, `enrollment_start_date`, `enrollment_end_date` | any column named in `eligibility_markers` |

Diagnosis codes may be written with or without the dot. Encounter records from a health information exchange or another source can be appended to `medical_claim`.

## Code lists and sources

The bundled lists contain 29,830 code rows in 186 components. Every code comes from a downloaded official file or is individually cited to a CMS document, and every source is recorded with its URL, version, access date, and file hash in `frailty_toolkit/definitions/codelists/sources.json`. The full category-to-component-to-source table is in [docs/sources.md](docs/sources.md).

| Source | Version | Used for |
|---|---|---|
| AHRQ HCUP Elixhauser Comorbidity Software Refined for ICD-10-CM | v2026.1 | cancer, metastatic disease, AIDS, dementia, paralysis, severe liver and pulmonary circulation disease |
| CMS Chronic Conditions Data Warehouse, Other Chronic or Potentially Disabling Conditions algorithms | revised 08/2026 | SUD, OUD and MOUD (HCPCS and NDC), psychotic, bipolar, depressive, and panic disorders, blindness, intellectual disability, cerebral palsy, spinal cord injury, mobility impairments, MS, muscular dystrophy, TBI, sickle cell disease, chronic hepatitis |
| CMS CCW 30 Chronic Conditions algorithms | revised 08/2026 | COPD, heart failure |
| CMS ICD-10-CM order files | FY2024 to FY2027 | code validation; IFC-named conditions (for example ALS, Huntington's disease, sarcoidosis, hemophilia, ESRD); functional-status Z codes |
| CMS HCPCS Level II file | October 2026 | personal care, home health, DME, hospice, dialysis, SUD and intensive mental health services, long-acting injectable antipsychotics |
| CMS Place of Service code set; CMS Claims Processing Manual chapters 8, 10, 11; ResDAC type-of-bill tables | as accessed 2026-09-29 | inpatient, psychiatric, nursing facility, hospice, ESRD settings; dialysis CPT codes; type-of-bill and revenue-code prefixes |

No NCQA value sets are used. SAMHSA and ISMICC define serious mental illness by functional impairment and publish no code list, so the mental disorder category uses CCW algorithms for the conditions the IFC names (91 FR 33375). The Harvard T.H. Chan School of Public Health workbook that Washington adopted is not bundled because its terms require a license for for-profit use; a state agency can load it at run time with `external_code_lists`. To rebuild every list from the official files:

```bash
pip install -e ".[build]"                       # adds openpyxl; also needs poppler's pdftotext
python scripts/build_codelists.py --cache-dir /path/to/cache --download
python scripts/render_sources_md.py
python -m frailty_toolkit.validation.public_checks --out /path/to/results --cache-dir /path/to/cache
```

## State configurations

| Config | Program | Status as of 2026-09-29 |
|---|---|---|
| `template` | federal floor | defaults in `definitions/categories.yaml` |
| `wa` | Apple Health for Adults | federal floor plus the ten Z codes named in the HCA memo of 2026-08-21; inpatient hardship reported. HCA adopted the Harvard list and method (diagnosis, then severity from inpatient care, high-intensity office visits, or procedures), which is not bundled. |
| `va` | Medicaid Expansion | federal floor; DMAS had not published a claims method or list; inpatient hardship on request |
| `oh` | Group VIII | reproduces ODM's published parameters: one claim suffices, primary or secondary diagnosis only, diagnosis alone suffices, no hardship exception. ODM's 1,935-code list had not been posted, so the federal lists stand in. ODM's stated 5-year SUD look-back is not represented because the IFC caps the window at 12 months. |
| `il` | ACA Adults | federal floor; HFS states a diagnosis alone will often not suffice; hardship on request |

Each config lists its primary sources. These are the toolkit's reading of public state documents, not statements by the states.

## Adapting to a state

1. Copy `frailty_toolkit/states/template.yaml`, or write a short file with `extends: template` and only the keys that differ.
2. Set `rule_version`, `state`, `program`, `requirement_start`, `policy_status`, and `sources`.
3. Set `lookback_months` (1 to 12), `min_distinct_dates`, `single_inpatient_sufficient`, `diagnosis_positions`, and `include_claim_statuses`.
4. For each category, add or remove components with `add_dx_components`, `remove_impairment_components`, and similar keys; component ids are listed in `definitions/codelists/components.csv`. Add individual codes with `extra_codes`, each of which must carry a `citation`.
5. Load a state's own list at run time with `external_code_lists` (a CSV with `code`, `code_system`, `category`, `role`). Such files stay outside the package.
6. Map disability-based eligibility categories with `eligibility_markers`, citing the state document that defines each value.
7. Run `frailty-toolkit check-config path/to/state.yaml`, then validate against a reference sample before use.

The loader rejects unknown keys, unknown components, look-back windows over 12 months, added categories, and codes without citations.

## Validation harness

`frailty_toolkit.validation.validate(persons, reference)` takes a reference file with `person_id`, `reference_frail`, and optionally `race_ethnicity`, `state`, and `reference_<category>` columns. It reports sensitivity, specificity, PPV, and NPV with Wilson 95% CIs and their numerators and denominators at two operating points (`likely`, and `likely` or `possible_needs_attestation`); sensitivity by race and ethnicity with the gap from a reference group and a percentile bootstrap 95% CI; and a per-category confusion table. People in the reference file with no claims count as not flagged.

`convergent_validity(persons, outcomes)` compares flagged and unflagged people on acute care, defined as emergency department visits plus inpatient admissions, per member-year (exact Poisson CIs), and on cost per member per month (bootstrap CIs), with a rate ratio and a PMPM difference. Outcomes should come from a follow-up window after the flag window. These comparisons describe associations; they do not estimate causal effects, and they are subject to regression to the mean, enrollment truncation, and a 60- to 90-day claims lag.

### Public-data checks (run 2026-09-29)

Every federal category, in all five bundled configs, has diagnosis codes and impairment or sufficient markers. A provenance check re-opened each source file and found all 29,830 code rows in the file each cites (188 component-by-source checks); all 20,402 distinct ICD-10-CM codes are valid in at least one of FY2024 to FY2027. Concordance with overlapping Elixhauser and CCW groupings, and the overlap between the federal lists and the paper's redesign families, are written to CSV by `public_checks`.

## Lessons from Basu & Berkowitz 2026 built into this toolkit

The paper's redesigned algorithm made four changes to state frailty algorithms, and its microsimulation separated under-identification into three channels: algorithm design, claims visibility, and documentation burden. The toolkit carries each change into claims-based screening where the interim final rule permits it, and it constrains the change where the rule does not.

The first change was expanded diagnostic recognition, which widened the recognized ICD-10 families to the union of the California and New York lists (13 families, including Z59 housing and economic circumstances and Z60 social environment). The toolkit keeps these families as two optional domains, `redesign_expanded_icd10_families` and `redesign_social_determinants`, and turns them off by default. When a state turns them on, hits route to the attestation tier as an outreach aid and do not by themselves produce a `likely` flag. We relied on three passages of the IFC preamble for that default. On added categories, CMS wrote: "Further, unlike medical frailty implemented in ABPs, we are not providing States with the option to add additional categories of people to the definition of medical frailty for community engagement purposes" (91 FR 33373). On social circumstances, CMS wrote that "we do not believe it would be reasonable for States to consider an individual who is homeless as medically frail solely on the basis that the individual is homeless, as that circumstance is not a medical condition" (91 FR 33373). On common conditions, CMS wrote: "Examples of conditions that we would not typically expect to significantly impair an individual's ability to meet the community engagement requirement include asthma, hypertension, anemia, generalized pain, pre-diabetes, Type I or II diabetes, obesity, psoriasis, headaches, and Attention-Deficit/Hyperactivity Disorder" (91 FR 33376). The first passage clearly bars new categories, so the configuration loader rejects any category name other than the five federal ones. The passages do not clearly bar a state from placing particular codes on its list under an existing category, because the regulation leaves list content to the state, subject to being "auditable, justifiable, and consistent with the definitions" (42 CFR 435.554(c)(5)(ii)(A)). Counting the optional domains toward the flag is therefore a documented state choice, `counts_toward_flag: true`, which the loader accepts with a warning rather than an error. The public-data check quantifies the difference between the two approaches: the 13 families contain 17,198 ICD-10-CM codes, of which 2,085 (12.1%) appear in any federal-default list, and they contain 2,085 of the 3,049 federal-default diagnosis codes (68.4%). The families contain no blindness codes (chapter H) and omit chromosomal anomalies, spinal cord and brain injury sequelae, HIV disease, sickle cell disease, and hemophilia, all of which the IFC names.

The second change set the ADL threshold at 1, the federal floor. The statute requires a disability "that significantly impairs their ability to perform 1 or more activities of daily living", so any one ADL marker (personal or attendant care, a home health aide, a wheelchair, a patient lift, a hospital bed, a commode, an ADL-dependence Z code, or an ICF/IID or nursing facility stay) satisfies the impairment requirement for category (D). The IFC counts ADLs but not IADLs (91 FR 33375), so homemaker, chore, companion, meal, and emergency-response services yield only the attestation tier.

The third change integrated data sources through health information exchange, full ex parte determination, and a short claims lag. The engine runs entirely on administrative data with no enrollee action, accepts encounter records from any source (a `data_source` column is kept), includes pended and denied claims as 42 CFR 435.557(f)(1) directs, and makes the evaluation date and window explicit so that a state can see how much run-out its claims have. The look-back window cannot exceed 12 months, because the IFC preamble states that "States may not consider information older than 12 months" (91 FR 33405).

The fourth change removed physician certification. The engine has no certification input, and the evidence table is designed to be read by a caseworker. The IFC allows provider documentation from a range of practitioners when claims do not suffice (91 FR 33406).

The claims-visibility channel carries the paper's main equity lesson. Conditions that are real can be under-documented in claims, and the paper's simulation parameterized that under-documentation as larger for American Indian and Alaska Native, Black, and rural enrollees, with Z codes recorded less often for people who use less care. In claims, the absence of evidence is not evidence of absence, and the IFC says as much: "the absence of adjudicated claims or encounter data altogether ... may not be used to determine ineligibility for the exclusion" (91 FR 33406). The toolkit therefore places people with no qualifying evidence and fewer than `thin_record_max_service_dates` distinct service dates in the window (default 2, state-configurable, 0 to disable), including people with no claims at all, in a separate `thin_record_outreach` tier. That tier routes to proactive attestation outreach and never to non-exemption. `FrailtyResult.tier_by_group()` reports the size of every tier by race and ethnicity and by rurality whenever the eligibility input carries those columns.

The validation harness applies the paper's equity evaluation to claims. It reports sensitivity by race and ethnicity with the gap from a reference group and a bootstrap 95% CI, sensitivity by rurality when a `rurality` column is supplied, a third operating point (`any_outreach`) that counts the thin-record tier as reached, and the share of reference-positive people who land in the thin-record tier in each group. That last share is the claims-visibility gap measured directly.

## License

Source-available under the [PolyForm Noncommercial License 1.0.0](LICENSE); it is not open-source software. Government institutions, public health organizations, and public research organizations may use it under that license. Commercial use, including use by managed care organizations or by commercial contractors working for a state, requires a separate license from Waymark, Inc. (sanjay.basu@waymarkcare.com). See [NOTICE](NOTICE) for trademark terms and third-party code-set terms.

Copyright (c) 2026 Waymark, Inc.

## Citation

Please cite the paper above and this software; see [CITATION.cff](CITATION.cff).

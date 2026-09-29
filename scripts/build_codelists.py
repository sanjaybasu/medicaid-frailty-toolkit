#!/usr/bin/env python3
"""Rebuild the toolkit's code lists from official public source files.

Every code written by this script comes from one of the downloaded source files
listed in SOURCES below, or from the individually cited entries in
``frailty_toolkit/definitions/specs/cited_codes.yaml``. Nothing is typed in by hand
except (a) code *ranges or prefixes* used to select codes from an official file
and (b) the cited entries, each of which carries its primary-document citation.

Usage:
    python scripts/build_codelists.py --cache-dir /path/to/cache [--download]

Outputs (committed to the repository; they contain no member data):
    frailty_toolkit/definitions/codelists/codes.csv        one row per (component, code)
    frailty_toolkit/definitions/codelists/components.csv   one row per component
    frailty_toolkit/definitions/codelists/sources.json     source registry with sha256
    frailty_toolkit/definitions/codelists/build_report.json tokens rejected, counts

Requires ``pdftotext`` (poppler) for the CCW PDF algorithms.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html as htmllib
import json
import re
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd
import yaml

REPO = Path(__file__).resolve().parents[1]
DEF_DIR = REPO / "frailty_toolkit" / "definitions"
OUT_DIR = DEF_DIR / "codelists"
SPEC_DIR = DEF_DIR / "specs"

UA = {"User-Agent": "Mozilla/5.0 (medicaid-frailty-toolkit build script)"}

# ---------------------------------------------------------------------------
# Source registry. access_date is filled with the date the file was fetched.
# ---------------------------------------------------------------------------
SOURCES = {
    "hcup_cmr_v2026_1": {
        "title": "Elixhauser Comorbidity Software Refined for ICD-10-CM, v2026.1 (reference file)",
        "publisher": "Agency for Healthcare Research and Quality, Healthcare Cost and Utilization Project",
        "url": "https://hcup-us.ahrq.gov/toolssoftware/comorbidityicd10/CMR-Reference-File-v2026-1.xlsx",
        "landing_page": "https://hcup-us.ahrq.gov/toolssoftware/comorbidityicd10/comorbidity_icd10.jsp",
        "version": "v2026.1",
        "file": "CMR-Reference-File-v2026-1.xlsx",
    },
    "ccw_otcc_2026_08": {
        "title": "CCW Other Chronic Health, Mental Health, and Potentially Disabling Chronic Conditions Algorithms (MBSF_OTCC)",
        "publisher": "Centers for Medicare & Medicaid Services, Chronic Conditions Data Warehouse",
        "url": "https://www2.ccwdata.org/documents/10280/19139421/other-condition-algorithms.pdf",
        "landing_page": "https://www2.ccwdata.org/web/guest/condition-categories-other",
        "version": "Revised 08/2026",
        "file": "other-condition-algorithms.pdf",
    },
    "ccw_chronic30_2026_08": {
        "title": "30 CCW Chronic Conditions Algorithms (MBSF_CHRONIC)",
        "publisher": "Centers for Medicare & Medicaid Services, Chronic Conditions Data Warehouse",
        "url": "https://www2.ccwdata.org/documents/10280/19139421/chr-chronic-condition-algorithms.pdf",
        "landing_page": "https://www2.ccwdata.org/web/guest/condition-categories-chronic",
        "version": "Revised 08/2026",
        "file": "chr-chronic-condition-algorithms.pdf",
    },
    "cms_icd10cm_fy2027": {
        "title": "ICD-10-CM FY2027 code descriptions in tabular order (order file)",
        "publisher": "Centers for Medicare & Medicaid Services / NCHS",
        "url": "https://www.cms.gov/files/zip/2027-code-descriptions-tabular-order.zip",
        "landing_page": "https://www.cms.gov/medicare/coding-billing/icd-10-codes",
        "version": "FY2027 (effective 2026-10-01)",
        "file": "2027-code-descriptions-tabular-order.zip",
    },
    "cms_icd10cm_fy2026": {
        "title": "ICD-10-CM FY2026 code descriptions in tabular order (order file)",
        "publisher": "Centers for Medicare & Medicaid Services / NCHS",
        "url": "https://www.cms.gov/files/zip/2026-code-descriptions-tabular-order.zip",
        "landing_page": "https://www.cms.gov/medicare/coding-billing/icd-10-codes",
        "version": "FY2026 (effective 2025-10-01)",
        "file": "2026-code-descriptions-tabular-order.zip",
    },
    "cms_icd10cm_fy2025": {
        "title": "ICD-10-CM FY2025 code descriptions in tabular order (order file)",
        "publisher": "Centers for Medicare & Medicaid Services / NCHS",
        "url": "https://www.cms.gov/files/zip/2025-code-descriptions-tabular-order.zip",
        "landing_page": "https://www.cms.gov/medicare/coding-billing/icd-10-codes",
        "version": "FY2025 (effective 2024-10-01)",
        "file": "2025-code-descriptions-tabular-order.zip",
    },
    "cms_icd10cm_fy2024": {
        "title": "ICD-10-CM FY2024 code descriptions in tabular order (order file, updated 02/01/2024)",
        "publisher": "Centers for Medicare & Medicaid Services / NCHS",
        "url": "https://www.cms.gov/files/zip/2024-code-descriptions-tabular-order-updated-02/01/2024.zip",
        "landing_page": "https://www.cms.gov/medicare/coding-billing/icd-10-codes",
        "version": "FY2024 (effective 2023-10-01)",
        "file": "2024-code-descriptions-tabular-order.zip",
    },
    "cms_hcpcs_2026_oct": {
        "title": "HCPCS Level II alpha-numeric file, October 2026 quarterly update",
        "publisher": "Centers for Medicare & Medicaid Services",
        "url": "https://www.cms.gov/files/zip/october-2026-alpha-numeric-hcpcs-file.zip",
        "landing_page": "https://www.cms.gov/medicare/coding-billing/healthcare-common-procedure-system/quarterly-update",
        "version": "2026 October (HCPC2026_OCT_ANWEB_09232026)",
        "file": "october-2026-alpha-numeric-hcpcs-file.zip",
    },
    "cms_pos": {
        "title": "Place of Service Code Set",
        "publisher": "Centers for Medicare & Medicaid Services",
        "url": "https://www.cms.gov/medicare/coding-billing/place-of-service-codes/code-sets",
        "landing_page": "https://www.cms.gov/medicare/coding-billing/place-of-service-codes/code-sets",
        "version": "web page as accessed",
        "file": "pos.html",
    },
    "resdac_fac_type": {
        "title": "ResDAC: Claim Facility Type Code (FFS) and Claim Service Classification Type Code (FFS) tables (type-of-bill digits)",
        "publisher": "Research Data Assistance Center (CMS contractor)",
        "url": "https://resdac.org/cms-data/variables/claim-facility-type-code-ffs",
        "landing_page": "https://resdac.org/cms-data/variables/claim-service-classification-type-code-ffs",
        "version": "web page as accessed",
        "file": "resdac_fac.html",
    },
    "resdac_srvc_cls": {
        "title": "ResDAC: Claim Service Classification Type Code Table",
        "publisher": "Research Data Assistance Center (CMS contractor)",
        "url": "https://resdac.org/sites/default/files/Claim%20Service%20Classification%20Type%20Code%20Table.txt",
        "landing_page": "https://resdac.org/cms-data/variables/claim-service-classification-type-code-ffs",
        "version": "file as accessed",
        "file": "resdac_cls_table.txt",
    },
    "cms_mcpm_ch8": {
        "title": "Medicare Claims Processing Manual, Chapter 8 - Outpatient ESRD Hospital, Independent Facility, and Physician/Supplier Claims",
        "publisher": "Centers for Medicare & Medicaid Services",
        "url": "https://www.cms.gov/Regulations-and-Guidance/Guidance/Manuals/Downloads/clm104c08.pdf",
        "landing_page": "https://www.cms.gov/medicare/regulations-guidance/manuals/internet-only-manuals-ioms",
        "version": "PDF as accessed",
        "file": "clm104c08.pdf",
    },
    "cms_mcpm_ch10": {
        "title": "Medicare Claims Processing Manual, Chapter 10 - Home Health Agency Billing",
        "publisher": "Centers for Medicare & Medicaid Services",
        "url": "https://www.cms.gov/Regulations-and-Guidance/Guidance/Manuals/Downloads/clm104c10.pdf",
        "landing_page": "https://www.cms.gov/medicare/regulations-guidance/manuals/internet-only-manuals-ioms",
        "version": "PDF as accessed",
        "file": "clm104c10.pdf",
    },
    "cms_mcpm_ch11": {
        "title": "Medicare Claims Processing Manual, Chapter 11 - Processing Hospice Claims",
        "publisher": "Centers for Medicare & Medicaid Services",
        "url": "https://www.cms.gov/Regulations-and-Guidance/Guidance/Manuals/Downloads/clm104c11.pdf",
        "landing_page": "https://www.cms.gov/medicare/regulations-guidance/manuals/internet-only-manuals-ioms",
        "version": "PDF as accessed",
        "file": "clm104c11.pdf",
    },
    "cms_2454_ifc": {
        "title": "Medicaid Program; Community Engagement Requirement for Certain Individuals (CMS-2454-IFC), 91 FR 33348, June 3, 2026, FR Doc. 2026-11094",
        "publisher": "Centers for Medicare & Medicaid Services (Federal Register via GovInfo)",
        "url": "https://www.govinfo.gov/content/pkg/FR-2026-06-03/html/2026-11094.htm",
        "landing_page": "https://www.federalregister.gov/documents/2026/06/03/2026-11094/medicaid-program-community-engagement-requirement-for-certain-individuals",
        "version": "Interim final rule, effective 2026-07-31",
        "file": "fr_gi.html",
    },
    "obbba_sec71119": {
        "title": "Public Law 119-21 (H.R. 1), Sec. 71119, enrolled text reproduced by CHCS",
        "publisher": "Center for Health Care Strategies (reproduction of enrolled bill text, H.R. 1 pp. 235-242)",
        "url": "https://www.chcs.org/media/OBBBA-Work-Requirements_Sec.-71119.pdf",
        "landing_page": "https://www.congress.gov/bill/119th-congress/house-bill/1/text",
        "version": "Enrolled bill text",
        "file": "chcs_sec71119.pdf",
    },
    "basu_berkowitz_2026": {
        "title": "Basu S, Berkowitz SA. Redesigning Medicaid frailty algorithms: improved identification of medically frail adults under community engagement. Health Aff Sch. 2026;4(6):qxag108 (redesign families = union of CA and NY recognized_conditions in sanjaybasu/medicaid-frailty-bias frailty_definitions/state_definitions.py)",
        "publisher": "Health Affairs Scholar (Oxford University Press)",
        "url": "https://doi.org/10.1093/haschl/qxag108",
        "landing_page": "https://academic.oup.com/healthaffairsscholar/article/4/6/qxag108/8672780",
        "version": "vol 4 issue 6, published 2026-05-08",
        "file": None,
    },
}

ICD_RE = re.compile(r"^([A-Z][0-9][0-9A-Z])(?:\.([0-9A-Z]{1,4}))?$")
HCPCS_RE = re.compile(r"^[A-V][0-9]{4}$")
NDC11_RE = re.compile(r"^[0-9]{11}$")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(cache: Path) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    for sid, s in SOURCES.items():
        if not s.get("file"):
            continue
        dest = cache / s["file"]
        if dest.exists():
            continue
        print(f"downloading {sid} -> {dest}")
        req = urllib.request.Request(s["url"], headers=UA)
        with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
            f.write(r.read())


# ---------------------------------------------------------------------------
# Official code sets
# ---------------------------------------------------------------------------
def load_icd10cm(cache: Path) -> pd.DataFrame:
    """Union of FY2024-FY2027 order files (headers and billable codes). FY2024 and FY2025
    are included so that retrospective validation on 2024-2025 claims sees the codes that
    were valid on the date of service."""
    frames = []
    for fy in (2024, 2025, 2026, 2027):
        sid = f"cms_icd10cm_fy{fy}"
        z = zipfile.ZipFile(cache / SOURCES[sid]["file"])
        name = [n for n in z.namelist() if re.search(rf"icd10cm_order_{fy}\.txt$", n)][0]
        rows = []
        for line in z.read(name).decode("latin-1").splitlines():
            if len(line) < 16:
                continue
            code = line[6:13].strip()
            billable = line[14:15] == "1"
            desc = line[77:].strip() or line[16:76].strip()
            rows.append((code, billable, desc, fy))
        frames.append(pd.DataFrame(rows, columns=["code", "billable", "description", "fy"]))
    df = pd.concat(frames)
    # keep the most recent description; record fiscal years present
    fys = df.groupby("code")["fy"].apply(lambda s: ",".join(str(x) for x in sorted(set(s))))
    df = df.sort_values("fy").groupby("code").tail(1).set_index("code")
    df["fiscal_years"] = fys
    df["source_id"] = "cms_icd10cm_fy" + df["fy"].astype(str)
    return df


def load_hcpcs(cache: Path) -> pd.DataFrame:
    z = zipfile.ZipFile(cache / SOURCES["cms_hcpcs_2026_oct"]["file"])
    name = [n for n in z.namelist() if re.search(r"ANWEB_\d+\.xlsx$", n)][0]
    with z.open(name) as f:
        df = pd.read_excel(f, dtype=str)
    df = df[df["RECID"] == "3"][["HCPC", "LONG DESCRIPTION", "TERM DT"]]
    df.columns = ["code", "description", "term_date"]
    return df.drop_duplicates("code").set_index("code")


def norm_icd(tok: str) -> str:
    return tok.replace(".", "").upper()


# ---------------------------------------------------------------------------
# Elixhauser Refined (HCUP CMR)
# ---------------------------------------------------------------------------
def build_elixhauser(cache: Path, icd: pd.DataFrame, rows: list, comps: list, report: dict) -> None:
    path = cache / SOURCES["hcup_cmr_v2026_1"]["file"]
    meas = pd.read_excel(path, sheet_name="Comorbidity_Measures", header=1)
    meas.columns = ["abbr", "description", "poa"]
    meas = meas[meas["abbr"].astype(str).str.startswith("CMR_")]
    labels = {a.replace("CMR_", ""): d.strip() for a, d in zip(meas["abbr"], meas["description"])}
    m = pd.read_excel(path, sheet_name="DX_to_Comorb_Mapping", header=1, dtype=str)
    m = m.rename(columns={m.columns[0]: "code", m.columns[1]: "description"})
    for abbr, label in labels.items():
        if abbr not in m.columns:
            report.setdefault("elixhauser_missing_columns", []).append(abbr)
            continue
        codes = m.loc[(m[abbr] == "1") & m["code"].astype(str).str.fullmatch(r"[A-Z][0-9A-Z]{2,6}"),
                      ["code", "description"]]
        cid = f"elix_{abbr.lower()}"
        for c, d in codes.itertuples(index=False):
            rows.append((cid, "ICD10CM", c, d, "hcup_cmr_v2026_1"))
        comps.append((cid, f"Elixhauser Refined: {label}", "ICD10CM", "hcup_cmr_v2026_1",
                      f"CMR_{abbr}", "all ICD-10-CM codes flagged 1 in DX_to_Comorb_Mapping", len(codes)))
    valid = m["code"].astype(str).str.fullmatch(r"[A-Z][0-9A-Z]{2,6}")
    report["elixhauser_codes_not_in_fy2024_27"] = sorted(set(m.loc[valid, "code"]) - set(icd.index))


# ---------------------------------------------------------------------------
# CCW PDFs
# ---------------------------------------------------------------------------
def _pdf_words(pdf: Path):
    html = subprocess.run(["pdftotext", "-bbox-layout", str(pdf), "-"], capture_output=True,
                          text=True, check=True).stdout
    pages = html.split("<page ")[1:]
    out = []
    for pi, p in enumerate(pages):
        words = [(float(a), float(b), htmllib.unescape(t), pi) for a, b, _c, _d, t in re.findall(
            r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>', p)]
        out.append(words)
    return out


def parse_ccw(pdf: Path, code_col_min_x: float):
    """Return list of dicts: name, period, text tokens (in reading order) of the ICD-10 column,
    and the 'number/type of claims to qualify' text."""
    pages = _pdf_words(pdf)
    rows, cur = [], None
    for words in pages:
        ref = [w for w in words if w[2] == "Reference"]
        nt = [w for w in words if w[2].startswith("Number/Type")]
        if not ref or not nt:
            continue
        xref, yhdr = ref[0][0], ref[0][1]
        xq = nt[0][0]
        hdr_words = [w for w in words if w[1] < yhdr + 40 and (w[2].startswith("Qualify") or w[2] in ("Period", "years)"))]
        ytop = max(w[1] for w in hdr_words) + 6 if hdr_words else yhdr + 25
        foot = [w[1] for w in words if w[2] == "Chronic" and w[1] > 480]
        ybot = min(foot) if foot else 1e9
        body = [w for w in words if ytop < w[1] < ybot - 2]
        starts = sorted({round(w[1], 1) for w in body
                         if xref - 12 < w[0] < xref + 12 and re.fullmatch(r"\d+", w[2])})
        first = starts[0] if starts else 1e9
        if cur is not None:
            cur["code_words"] += [w for w in body if w[1] < first - 3 and code_col_min_x <= w[0] < xq - 2]
            cur["q_words"] += [w for w in body if w[1] < first - 3 and w[0] >= xq - 2]
        bounds = starts + [1e9]
        for i, s in enumerate(starts):
            e = bounds[i + 1]
            rw = [w for w in body if s - 3 <= w[1] < e - 3]
            name = " ".join(w[2] for w in sorted([w for w in rw if w[0] < xref - 12],
                                                 key=lambda w: (round(w[1]), w[0])))
            cur = {"name": name, "period": " ".join(w[2] for w in rw if xref - 12 < w[0] < xref + 45),
                   "code_words": [w for w in rw if code_col_min_x <= w[0] < xq - 2],
                   "q_words": [w for w in rw if w[0] >= xq - 2]}
            rows.append(cur)
    for r in rows:
        r["tokens"] = [w[2] for w in sorted(r["code_words"], key=lambda w: (w[3], round(w[1]), w[0]))]
        r["qualify"] = " ".join(w[2] for w in sorted(r["q_words"], key=lambda w: (w[3], round(w[1]), w[0])))
        r["name"] = re.sub(r"\s+\d$", "", re.sub(r"\s+", " ", r["name"]).strip())
    return rows


def slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")
    return s[:60]


def build_ccw(cache, sid, code_col_min_x, prefix, icd, hcpcs, rows, comps, report):
    parsed = parse_ccw(cache / SOURCES[sid]["file"], code_col_min_x)
    rep = report.setdefault(sid, {})
    for r in parsed:
        if not r["name"] or len(r["name"]) > 120:
            continue
        cid = f"{prefix}_{slug(r['name'])}"
        if cid.endswith("_including"):
            cid = cid[: -len("_including")]
        n = {"ICD10CM": 0, "HCPCS": 0, "NDC": 0}
        rejected = []
        ndc_group = None
        for raw in r["tokens"]:
            tok = raw.strip(",;:()")
            low = raw.lower()
            if "buprenorphine" in low:
                ndc_group = "buprenorphine"
            elif "naltrexone" in low:
                ndc_group = "naltrexone"
            elif "methadone" in low:
                ndc_group = "methadone"
            if not tok:
                continue
            if ICD_RE.match(tok) and "." in tok or re.fullmatch(r"[A-Z][0-9]{2}", tok):
                c = norm_icd(tok)
                if c in icd.index:
                    rows.append((cid, "ICD10CM", c, icd.at[c, "description"], sid))
                    n["ICD10CM"] += 1
                else:
                    rejected.append(tok)
            elif HCPCS_RE.match(tok):
                if tok in hcpcs.index:
                    rows.append((cid, "HCPCS", tok, hcpcs.at[tok, "description"], sid))
                    n["HCPCS"] += 1
                else:
                    rejected.append(tok)
            elif NDC11_RE.match(tok):
                rows.append((cid + (f"__ndc_{ndc_group}" if ndc_group else "__ndc"), "NDC", tok,
                             f"NDC listed by CCW under {ndc_group or 'unlabelled'}", sid))
                n["NDC"] += 1
            elif re.match(r"^[A-Z][0-9][0-9A-Z]\.?[0-9A-Z]*$", tok):
                rejected.append(tok)
        total = sum(n.values())
        comps.append((cid, f"CCW: {r['name']}", "mixed" if sum(v > 0 for v in n.values()) > 1 else
                      next((k for k, v in n.items() if v), "none"), sid, r["name"],
                      f"codes parsed from ICD-10 column; qualify rule: {r['qualify'][:160]}", total))
        rep[cid] = {"name": r["name"], "period": r["period"], "qualify": r["qualify"], "counts": n,
                    "rejected_tokens_not_in_official_code_sets": sorted(set(rejected))}
        # NDC sub-components
        for grp in ("buprenorphine", "naltrexone", "methadone", None):
            sub = cid + (f"__ndc_{grp}" if grp else "__ndc")
            k = sum(1 for x in rows if x[0] == sub)
            if k:
                comps.append((sub, f"CCW: {r['name']} - NDCs ({grp or 'unlabelled'})", "NDC", sid, r["name"],
                              "11-digit NDCs parsed from the algorithm", k))


# ---------------------------------------------------------------------------
# Selections from official files by prefix / range (specs/selections.yaml)
# ---------------------------------------------------------------------------
def expand_range(spec: str, universe: list[str]) -> list[str]:
    spec = spec.strip()
    if "-" in spec:
        a, b = [x.strip() for x in spec.split("-")]
        return [c for c in universe if a <= c[: len(a)] and c[: len(b)] <= b]
    return [c for c in universe if c.startswith(spec)]


def build_selections(icd, hcpcs, pos, rows, comps, report):
    spec = yaml.safe_load(open(SPEC_DIR / "selections.yaml"))
    icd_universe = sorted(icd.index)
    hc_universe = sorted(hcpcs.index)
    rep = report.setdefault("selections", {})
    for cid, s in spec["components"].items():
        system = s["code_system"]
        codes: list[str] = []
        if system == "ICD10CM":
            for p in s["include"]:
                codes += expand_range(p.replace(".", ""), icd_universe)
            for p in s.get("exclude", []):
                ex = set(expand_range(p.replace(".", ""), icd_universe))
                codes = [c for c in codes if c not in ex]
            codes = sorted(set(codes))
            desc = lambda c: icd.at[c, "description"]  # noqa: E731
            src = None  # per code: latest FY order file containing the code
        elif system == "HCPCS":
            for p in s["include"]:
                codes += expand_range(p, hc_universe)
            for p in s.get("exclude", []):
                ex = set(expand_range(p, hc_universe))
                codes = [c for c in codes if c not in ex]
            kw = s.get("require_description_regex")
            if kw:
                codes = [c for c in codes if re.search(kw, str(hcpcs.at[c, "description"]), re.I)]
            codes = sorted(set(codes))
            desc = lambda c: hcpcs.at[c, "description"]  # noqa: E731
            src = "cms_hcpcs_2026_oct"
        elif system == "POS":
            codes = [str(c).zfill(2) for c in s["include"]]
            missing = [c for c in codes if c not in pos]
            if missing:
                raise SystemExit(f"{cid}: POS codes not in CMS POS code set: {missing}")
            desc = lambda c: pos[c]  # noqa: E731
            src = "cms_pos"
        else:
            raise SystemExit(f"unknown code_system {system}")
        if not codes:
            raise SystemExit(f"selection {cid} resolved to zero codes")
        for c in codes:
            rows.append((cid, system, c, desc(c), src or icd.at[c, "source_id"]))
        src_label = src or "cms_icd10cm_fy2024..fy2027"
        if cid.startswith("redesign_"):
            src_label += "; selection from basu_berkowitz_2026"
        comps.append((cid, s["label"], system, src_label, "; ".join(map(str, s["include"])),
                      s.get("rationale", ""), len(codes)))
        rep[cid] = {"n": len(codes), "include": s["include"], "exclude": s.get("exclude", [])}


def build_cited(rows, comps, report):
    """Codes that are individually cited to a primary document (CPT, type-of-bill and
    revenue-code prefixes). Each entry must carry a citation with URL and locator."""
    spec = yaml.safe_load(open(SPEC_DIR / "cited_codes.yaml"))
    for cid, s in spec["components"].items():
        for e in s["codes"]:
            if not e.get("citation") or not e.get("source"):
                raise SystemExit(f"{cid}:{e['code']} lacks a citation")
            if e["source"] not in SOURCES:
                raise SystemExit(f"{cid}: unknown source {e['source']}")
            rows.append((cid, s["code_system"], str(e["code"]), e.get("label", ""), e["source"]))
        comps.append((cid, s["label"], s["code_system"], ",".join(sorted({e['source'] for e in s['codes']})),
                      "individually cited", s.get("rationale", ""), len(s["codes"])))


def load_pos(cache: Path) -> dict:
    t = open(cache / SOURCES["cms_pos"]["file"], encoding="utf-8", errors="replace").read()
    t = re.sub(r"<script.*?</script>", "", t, flags=re.S)
    out = {}
    for r in re.findall(r"<tr[^>]*>(.*?)</tr>", t, flags=re.S):
        cells = [re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", c))).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, flags=re.S)]
        if cells and re.fullmatch(r"\d{2}", cells[0]):
            out[cells[0]] = cells[1]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir", required=True, type=Path)
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--access-date", default=None,
                    help="date the source files were fetched (YYYY-MM-DD); default = file mtime")
    a = ap.parse_args(argv)
    cache = a.cache_dir
    if a.download:
        download(cache)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    icd = load_icd10cm(cache)
    hcpcs = load_hcpcs(cache)
    pos = load_pos(cache)
    rows: list = []
    comps: list = []
    report: dict = {"generated": dt.date.today().isoformat()}

    build_elixhauser(cache, icd, rows, comps, report)
    build_ccw(cache, "ccw_otcc_2026_08", 345.0, "ccw", icd, hcpcs, rows, comps, report)
    build_ccw(cache, "ccw_chronic30_2026_08", 185.0, "ccw30", icd, hcpcs, rows, comps, report)
    build_selections(icd, hcpcs, pos, rows, comps, report)
    build_cited(rows, comps, report)

    codes = pd.DataFrame(rows, columns=["component_id", "code_system", "code", "description", "source_id"])
    codes = codes.drop_duplicates(["component_id", "code_system", "code"]).sort_values(
        ["component_id", "code_system", "code"])
    comp = pd.DataFrame(comps, columns=["component_id", "label", "code_system", "source_id",
                                        "source_element", "derivation", "n_codes"])
    comp = comp.drop_duplicates("component_id")
    comp["n_codes"] = comp["component_id"].map(codes.groupby("component_id").size()).fillna(0).astype(int)
    codes.to_csv(OUT_DIR / "codes.csv", index=False)
    comp.to_csv(OUT_DIR / "components.csv", index=False)

    reg = {}
    for sid, s in SOURCES.items():
        entry = dict(s)
        f = cache / s["file"] if s.get("file") else None
        if f is not None and f.exists():
            entry["sha256"] = sha256(f)
            entry["access_date"] = a.access_date or dt.date.fromtimestamp(f.stat().st_mtime).isoformat()
        else:
            entry["access_date"] = a.access_date
        reg[sid] = entry
    json.dump(reg, open(OUT_DIR / "sources.json", "w"), indent=2)
    json.dump(report, open(OUT_DIR / "build_report.json", "w"), indent=2, default=str)
    print(f"wrote {len(codes)} code rows across {len(comp)} components")


if __name__ == "__main__":
    sys.exit(main())

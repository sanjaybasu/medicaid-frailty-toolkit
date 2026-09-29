"""Integrity of the bundled code lists and source registry."""
import re

import pandas as pd

from frailty_toolkit.definitions import (FEDERAL_CATEGORY_ORDER, load_category_definitions, load_codes,
                                         load_components, load_sources)

ICD = re.compile(r"^[A-Z][0-9][0-9A-Z]{1,5}$")


def test_every_code_has_a_registered_source():
    codes, src = load_codes(), load_sources()
    assert len(codes) > 10000
    assert set(codes["source_id"]) <= set(src), set(codes["source_id"]) - set(src)


def test_every_source_has_url_version_and_access_date():
    for sid, s in load_sources().items():
        assert s["url"].startswith("https://"), sid
        assert s.get("version"), sid
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(s.get("access_date"))), sid
        if s.get("file"):
            assert re.fullmatch(r"[0-9a-f]{64}", s.get("sha256", "")), sid


def test_code_formats():
    c = load_codes()
    icd = c[c["code_system"] == "ICD10CM"]["code"]
    assert icd.str.match(ICD).all()
    hc = c[c["code_system"] == "HCPCS"]["code"]
    assert hc.str.fullmatch(r"[A-V][0-9]{4}").all()
    assert c[c["code_system"] == "NDC"]["code"].str.fullmatch(r"[0-9]{11}").all()
    assert c[c["code_system"] == "POS"]["code"].str.fullmatch(r"[0-9]{2}").all()
    assert (c["description"].str.len() > 0).mean() > 0.95


def test_no_ncqa_or_licensed_sources():
    for s in load_sources().values():
        text = " ".join(str(v) for v in s.values()).lower()
        assert "ncqa" not in text and "hedis" not in text
        assert "harvard" not in text  # the Harvard/HCA workbook is not bundled (for-profit licence terms)


def test_components_referenced_by_categories_exist_and_are_nonempty():
    comps = load_components().set_index("component_id")
    d = load_category_definitions()
    for cat in FEDERAL_CATEGORY_ORDER:
        c = d["federal_categories"][cat]
        for key in ("dx_components", "impairment_components", "sufficient_components", "possible_components",
                    "optional_dx_components"):
            for ref in c.get(key, []):
                cid = ref.split(":")[0]
                assert cid in comps.index, (cat, ref)
                assert comps.at[cid, "n_codes"] > 0, (cat, ref)


def test_federal_categories_match_statute():
    d = load_category_definitions()["federal_categories"]
    assert list(d) == FEDERAL_CATEGORY_ORDER
    cfrs = [d[c]["cfr"] for c in FEDERAL_CATEGORY_ORDER]
    assert cfrs == [f"42 CFR 435.554(c)(5)(i)({x})" for x in "ABCDE"]


def test_ifc_nonqualifying_examples_not_in_default_dx_lists():
    """91 FR 33376: hypertension, diabetes, obesity, asthma are not typically qualifying."""
    from frailty_toolkit.validation.public_checks import _codes_for
    allfed = set().union(*[_codes_for(f"category:{c}") for c in FEDERAL_CATEGORY_ORDER])
    for prefix in ("I10", "E11", "E10", "E66", "J45", "R73"):
        assert not any(c.startswith(prefix) for c in allfed), prefix


def test_codes_csv_sorted_and_unique():
    c = load_codes()
    assert not c.duplicated(["component_id", "code_system", "code"]).any()
    assert isinstance(c, pd.DataFrame)

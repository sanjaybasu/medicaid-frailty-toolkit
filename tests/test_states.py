import warnings

import pytest
import yaml

from frailty_toolkit.states import ConfigError, available_states, load_state_config, validate_config


def _base():
    return yaml.safe_load(open(__import__("frailty_toolkit.states", fromlist=["x"]).__path__[0] + "/template.yaml"))


def test_bundled_states_load():
    assert {"wa", "va", "oh", "il", "template"} <= set(available_states())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for s in available_states():
            cfg = load_state_config(s)
            assert cfg.rule_version
            assert cfg.lookback_months <= 12
            assert len(cfg.enabled_categories) == 5


def test_rule_version_required():
    raw = _base()
    raw.pop("rule_version")
    with pytest.raises(ConfigError, match="rule_version"):
        validate_config(raw)


def test_lookback_over_12_rejected():
    raw = _base()
    raw["lookback_months"] = 60
    with pytest.raises(ConfigError, match="12"):
        validate_config(raw)


def test_unknown_category_rejected():
    raw = _base()
    raw["categories"]["homelessness"] = {"enabled": True}
    with pytest.raises(ConfigError, match="does not allow states to add"):
        validate_config(raw)


def test_unknown_component_rejected():
    raw = _base()
    raw["categories"]["serious_or_complex_medical"]["add_dx_components"] = ["made_up_component"]
    with pytest.raises(ConfigError, match="unknown component"):
        validate_config(raw)


def test_extra_codes_need_citation():
    raw = _base()
    raw["categories"]["serious_or_complex_medical"]["extra_codes"] = [{"code": "Z515", "code_system": "ICD10CM",
                                                                        "role": "dx"}]
    with pytest.raises(ConfigError, match="citation"):
        validate_config(raw)


def test_paid_only_warns():
    raw = _base()
    raw["include_claim_statuses"] = ["paid"]
    with pytest.warns(UserWarning, match="pended"):
        validate_config(raw)


def test_optional_domain_counting_warns():
    raw = _base()
    raw["optional_domains"]["redesign_social_determinants"] = {"enabled": True, "counts_toward_flag": True}
    with pytest.warns(UserWarning, match="91 FR 33373"):
        validate_config(raw)


def test_ohio_mirrors_odm_parameters():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        oh = load_state_config("oh")
    assert oh.min_distinct_dates == 1 and oh.diagnosis_positions == 2
    assert not oh.related_provisions["short_term_hardship_inpatient"]["enabled"]
    assert not any(c.require_impairment_evidence for c in oh.categories.values())


def test_wa_extra_z_codes_present():
    wa = load_state_config("wa")
    codes = {e["code"] for c in wa.categories.values() for e in c.extra_codes}
    assert {"Z74.1", "Z51.5", "Z73.6"} <= codes

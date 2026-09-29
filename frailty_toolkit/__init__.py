"""frailty_toolkit: claims-based screening for the Medicaid medically frail exclusion
(SSA 1902(xx)(9)(A)(ii)(V); 42 CFR 435.554(c)(5)).

A screening aid for exemption review. It never makes an eligibility determination.
"""
from .engine import TIER_LIKELY, TIER_NONE, TIER_POSSIBLE, TIER_THIN, FrailtyResult, evaluate
from .states import ConfigError, available_states, load_state_config

__version__ = "0.2.0"

__all__ = ["ConfigError", "FrailtyResult", "TIER_LIKELY", "TIER_NONE", "TIER_POSSIBLE", "TIER_THIN", "__version__",
           "available_states", "evaluate", "load_state_config"]

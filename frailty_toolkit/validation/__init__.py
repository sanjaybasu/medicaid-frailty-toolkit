"""Validation harness: reference-label accuracy, equity gaps, convergent validity, public checks."""
from .convergent import convergent_validity
from .harness import join_reference, per_category_table, race_sensitivity_gaps, validate, write_report
from .metrics import bootstrap_ci, diagnostic_metrics, poisson_rate_ci, wilson_ci

__all__ = ["bootstrap_ci", "convergent_validity", "diagnostic_metrics", "join_reference", "per_category_table",
           "poisson_rate_ci", "race_sensitivity_gaps", "validate", "wilson_ci", "write_report"]

"""Small, dependency-light statistics used by the validation harness."""
from __future__ import annotations

import math

import numpy as np
from scipy import stats


def wilson_ci(k: int, n: int, alpha: float = 0.05) -> tuple[float, float, float]:
    """Proportion k/n with the Wilson score interval. Returns (p, lo, hi); NaNs when n == 0."""
    if n == 0:
        return (math.nan, math.nan, math.nan)
    z = stats.norm.ppf(1 - alpha / 2)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (p, max(0.0, centre - half), min(1.0, centre + half))


def confusion(pred: np.ndarray, truth: np.ndarray) -> dict:
    pred = np.asarray(pred, dtype=bool)
    truth = np.asarray(truth, dtype=bool)
    tp = int((pred & truth).sum())
    fp = int((pred & ~truth).sum())
    fn = int((~pred & truth).sum())
    tn = int((~pred & ~truth).sum())
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "n": tp + fp + fn + tn}


def diagnostic_metrics(pred, truth, alpha: float = 0.05) -> dict:
    """Sensitivity, specificity, PPV, NPV with Wilson CIs; each carries its numerator and denominator."""
    c = confusion(pred, truth)
    out = dict(c)
    for name, k, n in (("sensitivity", c["tp"], c["tp"] + c["fn"]),
                       ("specificity", c["tn"], c["tn"] + c["fp"]),
                       ("ppv", c["tp"], c["tp"] + c["fp"]),
                       ("npv", c["tn"], c["tn"] + c["fn"])):
        p, lo, hi = wilson_ci(k, n, alpha)
        out[name] = p
        out[f"{name}_lo"] = lo
        out[f"{name}_hi"] = hi
        out[f"{name}_num"] = k
        out[f"{name}_den"] = n
    return out


def bootstrap_ci(stat_fn, n: int, n_boot: int = 2000, seed: int = 20260929, alpha: float = 0.05,
                 strata: np.ndarray | None = None) -> tuple[float, float, np.ndarray]:
    """Percentile bootstrap over row indices 0..n-1. stat_fn(idx) -> float.
    If strata is given, resample within each stratum (keeps group sizes fixed)."""
    rng = np.random.default_rng(seed)
    draws = np.empty(n_boot)
    if strata is None:
        for b in range(n_boot):
            draws[b] = stat_fn(rng.integers(0, n, size=n))
    else:
        groups = [np.flatnonzero(strata == s) for s in np.unique(strata)]
        for b in range(n_boot):
            idx = np.concatenate([g[rng.integers(0, len(g), size=len(g))] for g in groups if len(g)])
            draws[b] = stat_fn(idx)
    draws = draws[~np.isnan(draws)]
    if len(draws) == 0:
        return (math.nan, math.nan, draws)
    return (float(np.quantile(draws, alpha / 2)), float(np.quantile(draws, 1 - alpha / 2)), draws)


def poisson_rate_ci(events: float, exposure: float, alpha: float = 0.05) -> tuple[float, float, float]:
    """Exact (Garwood) CI for a Poisson rate events/exposure."""
    if exposure <= 0:
        return (math.nan, math.nan, math.nan)
    lo = stats.chi2.ppf(alpha / 2, 2 * events) / 2 if events > 0 else 0.0
    hi = stats.chi2.ppf(1 - alpha / 2, 2 * (events + 1)) / 2
    return (events / exposure, lo / exposure, hi / exposure)

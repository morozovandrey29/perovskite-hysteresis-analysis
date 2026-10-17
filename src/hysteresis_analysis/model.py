"""Phenomenological multi-relaxation model and nonlinear fitting routines."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.interpolate import PchipInterpolator
from scipy.optimize import least_squares

from .io import FrequencyDataset

@dataclass
class FitResult:
    device: str
    k: int
    f0_hz: np.ndarray
    tau_s: np.ndarray
    amplitude: np.ndarray
    baseline: float
    x_fit: np.ndarray
    y_fit: np.ndarray
    components_fit: list[np.ndarray]
    y_meas_fitgrid: np.ndarray
    y_smooth_x: np.ndarray
    y_smooth: np.ndarray
    weights: np.ndarray
    weighted_rmse: float
    r2: float
    rss: float
    aic: float
    aicc: float
    n_used: int
    n_params: int
    beta: float


# Physics-inspired relaxation model and fitting
# ---------------------------------------------------------------------------


def debye_component(f: np.ndarray, amplitude: float, f0: float, beta: float = 1.0) -> np.ndarray:
    """Debye/Cole-Cole-like symmetric loss peak. beta=1 is exact Debye.

    beta < 1 broadens the peak symmetrically in log-frequency; beta is a
    fixed phenomenological shape parameter, not an independently fitted ion parameter.
    """
    x = np.asarray(f, dtype=float) / float(f0)
    b = max(float(beta), 1e-3)
    xb = np.power(x, b)
    return amplitude * (2.0 * xb / (1.0 + xb * xb))


def model_from_params(theta: np.ndarray, f: np.ndarray, k: int, beta: float = 1.0,
                       fit_baseline: bool = False) -> np.ndarray:
    """Evaluate the relaxation model.

    By default H0 is fixed to zero, so every relaxation contribution vanishes
    for f -> 0. H0 can be optionally fitted for datasets where a non-zero
    asymptotic measurement floor is intentionally modeled.
    """
    offset = 1 if fit_baseline else 0
    h0 = math.exp(theta[0]) if fit_baseline else 0.0
    y = np.full_like(f, h0, dtype=float)
    for i in range(k):
        a = math.exp(theta[offset + 2 * i])
        f0 = math.exp(theta[offset + 1 + 2 * i])
        y += debye_component(f, a, f0, beta)
    return y


def frequency_weights(f: np.ndarray, mode: str, cutoff_hz: float, power: float) -> np.ndarray:
    f = np.asarray(f, dtype=float)
    cutoff = max(float(cutoff_hz), 1e-12)
    if mode == "all":
        return np.ones_like(f)
    if mode == "exclude":
        return (f <= cutoff).astype(float)
    return 1.0 / (1.0 + (f / cutoff) ** max(power, 0.1))


def _fit_once(f, y, k, w, seed_f0, beta, fit_baseline):
    base0 = max(1e-6, float(np.percentile(y, 10)) * 0.8)
    amp0 = max(1e-5, float(max(y) - (base0 if fit_baseline else 0.0)) / max(k, 1))
    p0 = []
    if fit_baseline:
        p0.append(math.log(base0))
    for f0 in seed_f0:
        p0.extend([math.log(amp0), math.log(max(f0, 1e-9))])

    ymax = max(float(np.max(y)), 1e-6)
    fmin = max(float(np.min(f)) / 100.0, 1e-8)
    fmax = max(float(np.max(f)) * 100.0, fmin * 10)

    lower = []
    upper = []
    if fit_baseline:
        lower.append(math.log(1e-12))
        upper.append(math.log(max(ymax * 3.0, 1e-6)))
    for _ in range(k):
        lower.extend([math.log(1e-12), math.log(fmin)])
        upper.extend([math.log(max(ymax * 5.0, 1e-6)), math.log(fmax)])

    sqrtw = np.sqrt(np.maximum(w, 0.0))

    def residual(theta):
        return (model_from_params(theta, f, k, beta, fit_baseline) - y) * sqrtw

    res = least_squares(
        residual,
        x0=np.asarray(p0, dtype=float),
        bounds=(np.asarray(lower), np.asarray(upper)),
        max_nfev=50000,
        xtol=1e-12,
        ftol=1e-12,
        gtol=1e-12,
    )
    rss = float(np.sum(residual(res.x) ** 2))
    return res, rss


def fit_relaxation(
    ds: FrequencyDataset,
    k: int,
    weight_mode: str,
    cutoff_hz: float,
    power: float,
    beta: float = 1.0,
    fit_baseline: bool = False,
) -> FitResult:
    f = ds.frequency_hz
    y = ds.hyst_area
    w_all = frequency_weights(f, weight_mode, cutoff_hz, power)
    mask = w_all > 0
    ff, yy, ww = f[mask], y[mask], w_all[mask]

    n = len(ff)
    p = (1 if fit_baseline else 0) + 2 * k
    if n <= p:
        raise ValueError(
            f"Not enough points to fit {k} component(s): {n} data points are available for {p} parameters. "
            "Expand the frequency range or reduce the number of components."
        )

    log_min, log_max = math.log(ff.min()), math.log(ff.max())
    starts = []
    base_grid = np.linspace(log_min, log_max, k + 2)[1:-1]
    shifts = (-0.45, -0.2, 0.0, 0.2, 0.45)
    for shift in shifts:
        arr = np.clip(base_grid + shift, log_min, log_max)
        starts.append(np.exp(arr))
    top = ff[np.argsort(yy)[::-1][: min(len(ff), 4)]]
    if k == 1:
        for t in top:
            starts.append(np.array([t], dtype=float))
    elif k > 1:
        for t in top:
            spread = np.linspace(-0.5, 0.5, k)
            starts.append(np.exp(np.log(max(t, 1e-9)) + spread))

    best = None
    for seed in starts:
        try:
            res, rss = _fit_once(ff, yy, k, ww, seed, beta, fit_baseline)
        except Exception:
            continue
        if best is None or rss < best[0]:
            best = (rss, res)
    if best is None:
        raise RuntimeError("The optimizer could not find a stable fit.")

    rss, res = best
    theta = res.x
    offset = 1 if fit_baseline else 0
    baseline = math.exp(theta[0]) if fit_baseline else 0.0
    amps = []
    f0s = []
    for i in range(k):
        amps.append(math.exp(theta[offset + 2 * i]))
        f0s.append(math.exp(theta[offset + 1 + 2 * i]))

    order = np.argsort(f0s)
    amps = np.asarray(amps)[order]
    f0s = np.asarray(f0s)[order]
    taus = 1.0 / (2.0 * np.pi * f0s)

    f_dense = np.logspace(np.log10(f.min()) - 1.0, np.log10(f.max()) + 1.0, 900)
    components_dense = [debye_component(f_dense, a, f0, beta) for a, f0 in zip(amps, f0s)]
    y_dense = np.full_like(f_dense, baseline)
    for comp in components_dense:
        y_dense += comp

    # Interpolate the measured curve in log10(f), because the experimental
    # frequency axis spans several decades and is displayed logarithmically.
    try:
        smooth = PchipInterpolator(np.log10(f), y)
        x_s = np.logspace(np.log10(f.min()), np.log10(f.max()), 500)
        y_s = smooth(np.log10(x_s))
    except Exception:
        x_s, y_s = np.asarray(f, dtype=float), np.asarray(y, dtype=float)

    y_pred_meas = model_from_params(theta, ff, k, beta, fit_baseline)
    ybar = float(np.average(yy, weights=ww))
    ss_tot = float(np.sum(ww * (yy - ybar) ** 2))
    r2 = 1.0 - rss / ss_tot if ss_tot > 0 else float("nan")
    rmse = math.sqrt(rss / max(np.sum(ww), 1e-30))

    aic = n * math.log(max(rss / n, 1e-30)) + 2 * p
    if n - p - 1 > 0:
        aicc = aic + 2 * p * (p + 1) / (n - p - 1)
    else:
        aicc = float("inf")

    return FitResult(
        device=ds.device,
        k=k,
        f0_hz=f0s,
        tau_s=taus,
        amplitude=amps,
        baseline=baseline,
        x_fit=f_dense,
        y_fit=y_dense,
        components_fit=components_dense,
        y_meas_fitgrid=y_pred_meas,
        y_smooth_x=x_s,
        y_smooth=y_s,
        weights=w_all,
        weighted_rmse=rmse,
        r2=r2,
        rss=rss,
        aic=aic,
        aicc=aicc,
        n_used=n,
        n_params=p,
        beta=beta,
    )

def auto_fit(ds: FrequencyDataset, max_k: int, weight_mode: str, cutoff_hz: float, power: float, beta: float = 1.0, fit_baseline: bool = False) -> FitResult:
    candidates = []
    for k in range(1, max_k + 1):
        try:
            result = fit_relaxation(ds, k, weight_mode, cutoff_hz, power, beta, fit_baseline)
            if np.isfinite(result.aicc):
                candidates.append(result)
        except Exception:
            continue
    if not candidates:
        raise ValueError("No stable candidate model could be fitted.")
    return min(candidates, key=lambda r: r.aicc)



"""Derived analytics for the workbench UI.

Everything here reads artifacts a run has *already written*; nothing recomputes
the pipeline. The single exception is the per-stock view, which applies the
same 3-line rolling-volatility definition used by ``risk.analytics`` to the
already-aligned return panel -- flagged where it happens.

The watchword of this module is provenance: a number is only ever returned
together with the run it came from, and the ``evidence`` function encodes the
guardrails that say when a number must *not* be trusted.
"""

from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from risk.analytics import risk_decomposition  # noqa: E402
from risk.exposures import latest_cross_section, load_exposures  # noqa: E402

from workbench import runstore  # noqa: E402

TRADING_DAYS = 252
SAMPLE_WARMUP_DAYS = 252  # momentum lookback (L=252, S=21) -- the binding constraint


# --------------------------------------------------------------------------- #
# artifact access
# --------------------------------------------------------------------------- #

@lru_cache(maxsize=64)
def _manifest_cached(run_id: str, _stamp: float) -> dict:
    return runstore.get_run(run_id)["manifest"] or {}


def manifest(run_id: str) -> dict:
    """The run's manifest, cache-busted by the manifest file's mtime."""
    directory = runstore.run_dir(run_id)
    path = directory / runstore.MANIFEST_FILE
    stamp = path.stat().st_mtime if path.exists() else 0.0
    return _manifest_cached(run_id, stamp)


@lru_cache(maxsize=32)
def _frame(run_id: str, name: str, _stamp: float) -> pd.DataFrame:
    return pd.read_parquet(runstore.run_dir(run_id) / name)


def artifact_frame(run_id: str, name: str) -> pd.DataFrame:
    path = runstore.run_dir(run_id) / name
    if not path.exists():
        raise FileNotFoundError(name)
    return _frame(run_id, name, path.stat().st_mtime)


@lru_cache(maxsize=32)
def _selfcheck(run_id: str, _stamp: float) -> pd.DataFrame:
    path = runstore.run_dir(run_id) / "selfcheck_report.csv"
    frame = pd.read_csv(path, parse_dates=["Date"]).set_index("Date")
    return frame.sort_index()


def selfcheck_report(run_id: str) -> pd.DataFrame:
    path = runstore.run_dir(run_id) / "selfcheck_report.csv"
    if not path.exists():
        raise FileNotFoundError("selfcheck_report.csv")
    return _selfcheck(run_id, path.stat().st_mtime)


@lru_cache(maxsize=16)
def _exposures(path: str, _stamp: float) -> pd.DataFrame:
    return load_exposures(Path(path))


def _exposures_path(run_id: str) -> Path:
    inputs = (manifest(run_id).get("inputs") or {}).get("exposures") or {}
    candidate = inputs.get("path")
    if candidate and Path(candidate).is_file():
        return Path(candidate)
    return PROJECT_ROOT / "Data" / "Processed" / "exposures.parquet"


def run_exposures(run_id: str) -> pd.DataFrame:
    path = _exposures_path(run_id)
    return _exposures(str(path), path.stat().st_mtime)


# --------------------------------------------------------------------------- #
# calibration
# --------------------------------------------------------------------------- #

def calibration(run_id: str) -> dict:
    """Everything the Calibration tab needs, straight from selfcheck_report.csv."""
    report = selfcheck_report(run_id)
    rel = report["rel_error_mean"].dropna()
    if rel.empty:
        raise ValueError("self-check report has no usable rows")

    rolling = rel.rolling(20, min_periods=5).median()
    quarterly = [
        {
            "period": str(period),
            "days": int(group.size),
            "median": float(group.median()),
            "mean": float(group.mean()),
        }
        for period, group in rel.groupby(rel.index.to_period("Q"))
    ]
    counts, edges = np.histogram(rel.to_numpy(dtype=float), bins=24)

    return {
        "run_id": run_id,
        "summary": {
            "effective_dates": int(rel.size),
            "first_date": rel.index.min().strftime("%Y-%m-%d"),
            "last_date": rel.index.max().strftime("%Y-%m-%d"),
            "median": float(rel.median()),
            "mean": float(rel.mean()),
            "p25": float(rel.quantile(0.25)),
            "p75": float(rel.quantile(0.75)),
            "worst": float(rel.max()),
            "best": float(rel.min()),
        },
        "series": {
            "dates": [d.strftime("%Y-%m-%d") for d in rel.index],
            "rel_error": [float(v) for v in rel],
            "rolling_median": [
                None if np.isnan(v) else float(v) for v in rolling
            ],
            "model_vol": [float(v) for v in report["model_vol_mean"].reindex(rel.index)],
            "realized_vol": [
                float(v) for v in report["realized_vol_mean"].reindex(rel.index)
            ],
        },
        "quarterly": quarterly,
        "histogram": {
            "edges": [float(e) for e in edges],
            "counts": [int(c) for c in counts],
        },
    }


# --------------------------------------------------------------------------- #
# risk view
# --------------------------------------------------------------------------- #

def _project_box_simplex(v: np.ndarray, cap: float) -> np.ndarray:
    """Project onto {w : 0 <= w <= cap, sum(w) = 1} by bisecting the shift."""
    lo, hi = float(v.min() - cap), float(v.max())
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if np.clip(v - mid, 0.0, cap).sum() > 1.0:
            lo = mid
        else:
            hi = mid
    return np.clip(v - (lo + hi) / 2.0, 0.0, cap)


def _min_variance(sigma: np.ndarray, cap: float = 0.30, iters: int = 2000) -> np.ndarray:
    """Long-only minimum-variance weights with a per-name cap.

    Accelerated projected gradient (FISTA) instead of a generic SLSQP: on these
    Sigma matrices SLSQP spends ~17 s finite-stepping an ill-conditioned
    463-dimension problem, while FISTA reaches a *slightly better* objective in
    ~0.2 s. Step size is 1/L with L = lambda_max(Sigma).
    """
    n = sigma.shape[0]
    lipschitz = float(np.linalg.eigvalsh(sigma).max())
    step = 1.0 / lipschitz if lipschitz > 0 else 1.0
    weights = np.full(n, 1.0 / n)
    y = weights.copy()
    momentum = 1.0
    for _ in range(iters):
        candidate = _project_box_simplex(y - step * (sigma @ y), cap)
        t_next = (1.0 + np.sqrt(1.0 + 4.0 * momentum * momentum)) / 2.0
        y = candidate + ((momentum - 1.0) / t_next) * (candidate - weights)
        if np.max(np.abs(candidate - weights)) < 1e-13:
            weights = candidate
            break
        weights, momentum = candidate, t_next
    return weights


def _all_weights(sigma: np.ndarray) -> dict[str, tuple[np.ndarray, str]]:
    """Every supported weighting scheme for one Sigma, computed once."""
    n = sigma.shape[0]
    vol = np.sqrt(np.diag(sigma))
    inverse = 1.0 / np.clip(vol, 1e-12, None)
    return {
        "equal": (np.full(n, 1.0 / n), "等权 1/N"),
        "inverse_vol": (inverse / inverse.sum(), "逆波动率加权"),
        "min_variance": (_min_variance(sigma), "最小方差（long-only, 单票 ≤30%）"),
    }


def risk_view(run_id: str, scheme: str = "equal") -> dict:
    """Cached entry point, keyed by run, scheme and the Sigma artifact's mtime."""
    sigma_path = runstore.run_dir(run_id) / "asset_covariance_latest.parquet"
    if not sigma_path.exists():
        raise FileNotFoundError("asset_covariance_latest.parquet")
    return _risk_view_cached(run_id, scheme, sigma_path.stat().st_mtime)


@lru_cache(maxsize=24)
def _risk_view_cached(run_id: str, scheme: str, _stamp: float) -> dict:
    return _risk_view(run_id, scheme)


def _risk_view(run_id: str, scheme: str) -> dict:
    """Portfolio-level risk picture for one weight scheme.

    Sigma is taken verbatim from the run's artifacts; X, F and D come from the
    exact inputs recorded in the manifest, so the view cannot drift from the
    run it claims to describe.
    """
    sigma_frame = artifact_frame(run_id, "asset_covariance_latest.parquet")
    factor_cov = artifact_frame(run_id, "factor_cov.parquet")
    specific_var = artifact_frame(run_id, "specific_variance.parquet")

    sigma = sigma_frame.to_numpy(dtype=float)
    weight_map = _all_weights(sigma)
    if scheme not in weight_map:
        raise ValueError(f"unknown scheme: {scheme!r}")
    weights_array, scheme_label = weight_map[scheme]

    as_of = selfcheck_report(run_id).index.max()
    exposures = run_exposures(run_id)
    cross_section = latest_cross_section(exposures, as_of)
    tickers = list(sigma_frame.index)
    x_t = cross_section.reindex(tickers).dropna(how="any")

    weights = pd.Series(weights_array, index=tickers).reindex(x_t.index)
    weights = weights / weights.sum()

    factor_cov_aligned = factor_cov.reindex(index=x_t.columns, columns=x_t.columns)
    d_aligned = specific_var.reindex(index=x_t.index, columns=x_t.index).fillna(0.0)

    decomposition = risk_decomposition(
        weights, x_t, factor_cov_aligned, d_aligned
    )

    # Barra factor attribution: b = X'w, variance contribution of factor k is
    # b_k * (F b)_k, and the contributions sum to the factor variance.
    b = x_t.to_numpy(dtype=float).T @ weights.to_numpy(dtype=float)
    f_matrix = factor_cov_aligned.to_numpy(dtype=float)
    contributions = b * (f_matrix @ b)
    factor_rows = sorted(
        (
            {
                "factor": name,
                "exposure": float(b[i]),
                "variance_contribution": float(contributions[i]),
                "vol_contribution": float(
                    np.sqrt(max(contributions[i], 0.0) * TRADING_DAYS)
                ),
            }
            for i, name in enumerate(x_t.columns)
        ),
        key=lambda row: abs(row["variance_contribution"]),
        reverse=True,
    )

    model_vol = np.sqrt(np.diag(sigma_frame.to_numpy(dtype=float)) * TRADING_DAYS)
    top = (
        pd.Series(weights_array, index=tickers)
        .sort_values(ascending=False)
        .head(10)
        .round(4)
    )

    eigenvalues = np.linalg.eigvalsh((sigma + sigma.T) / 2.0)
    conditioning = {
        "lambda_max": float(eigenvalues.max()),
        "lambda_min": float(eigenvalues.min()),
        "condition_number": float(
            eigenvalues.max() / max(eigenvalues.min(), np.finfo(float).tiny)
        ),
    }

    return {
        "run_id": run_id,
        "scheme": scheme,
        "scheme_label": scheme_label,
        "as_of": as_of.strftime("%Y-%m-%d"),
        "universe": int(len(x_t)),
        "conditioning": conditioning,
        "portfolio": {
            "vol_annualized": float(decomposition["portfolio_vol_annualized"]),
            "factor_pct": float(decomposition["factor_pct"]),
            "specific_pct": float(decomposition["specific_pct"]),
            "factor_variance": float(decomposition["factor_variance"]),
            "specific_variance": float(decomposition["specific_variance"]),
            "effective_n": float(1.0 / np.sum(weights_array**2)),
            "max_weight": float(weights_array.max()),
            "top_holdings": [
                {"ticker": str(t), "weight": float(w)} for t, w in top.items()
            ],
        },
        "factors": factor_rows,
        "model_vol_distribution": {
            "edges": [float(e) for e in np.histogram(model_vol, bins=24)[1]],
            "counts": [int(c) for c in np.histogram(model_vol, bins=24)[0]],
            "median": float(np.median(model_vol)),
        },
        "schemes": _scheme_table(sigma, weight_map),
    }


def _scheme_table(sigma: np.ndarray, weight_map: dict) -> list[dict]:
    rows = []
    for scheme, (weights, label) in weight_map.items():
        variance = float(weights @ sigma @ weights)
        rows.append(
            {
                "scheme": scheme,
                "label": label,
                "vol_annualized": float(np.sqrt(variance * TRADING_DAYS)),
                "effective_n": float(1.0 / np.sum(weights**2)),
                "max_weight": float(weights.max()),
            }
        )
    return rows


# --------------------------------------------------------------------------- #
# evidence guardrails
# --------------------------------------------------------------------------- #

def evidence(run_id: str) -> list[dict]:
    """The badges that decide whether a screen full of numbers means anything.

    These are *computed* checks, not decoration: each one corresponds to a way
    this model has been observed to mislead.
    """
    run_manifest = manifest(run_id)
    shapes = run_manifest.get("shapes", {})
    badges: list[dict] = []

    dates = (run_manifest.get("selfcheck") or {}).get("effective_dates")
    first = (run_manifest.get("selfcheck") or {}).get("first_date")
    last = (run_manifest.get("selfcheck") or {}).get("last_date")
    if dates is not None:
        badges.append(
            {
                "level": "warn" if dates < TRADING_DAYS else "ok",
                "title": f"{dates} 个可用检验日",
                "detail": (
                    f"{first} → {last}。可用截面 ≈ 原始交易日 − {SAMPLE_WARMUP_DAYS}"
                    f"（momentum L=252 的预热）；样本偏短时误差中位数本身就不稳定。"
                ),
            }
        )

    try:
        columns = list(run_exposures(run_id).columns)
    except FileNotFoundError:
        columns = []
    if "market" not in columns:
        badges.append(
            {
                "level": "danger",
                "title": "缺常数市场因子",
                "detail": (
                    "X 只有风格因子列，r = Xf + ε 没有市场项，市场共同波动被计入残差 ε，"
                    "组合风险会被系统性低估（等权组合年化波动甚至低于 5%）。"
                    "该 run 的组合波动不可用作风险估计。"
                ),
            }
        )
    else:
        badges.append(
            {
                "level": "ok",
                "title": "含常数市场因子",
                "detail": "X 中包含 market 列（全 1），市场共同波动由因子项承载。",
            }
        )

    badges.append(
        {
            "level": "danger",
            "title": "样本内检查",
            "detail": (
                "F 与 D 用全样本估计一次，再回溯套用到每个历史日期，因此该 self-check "
                "是样本内诊断，不是样本外验证；真实预测误差应更差。"
            ),
        }
    )

    checks = run_manifest.get("checks", {})
    if checks:
        healthy = all(
            [
                checks.get("F_positive_definite"),
                checks.get("D_all_positive"),
                checks.get("Sigma_positive_definite"),
            ]
        )
        badges.append(
            {
                "level": "ok" if healthy else "danger",
                "title": "矩阵正定性" + ("通过" if healthy else "**未通过**"),
                "detail": (
                    f"F min eig {checks.get('F_min_eigenvalue'):.3g} · "
                    f"Σ min eig {checks.get('Sigma_min_eigenvalue'):.3g} · "
                    f"D min var {checks.get('D_min_specific_variance'):.3g}"
                ),
            }
        )

    exposures_input = (run_manifest.get("inputs") or {}).get("exposures") or {}
    if exposures_input.get("exists"):
        badges.append(
            {
                "level": "info",
                "title": "输入可追溯",
                "detail": (
                    f"X: {Path(exposures_input['path']).name} "
                    f"{exposures_input.get('size_bytes', 0):,} bytes @ "
                    f"{exposures_input.get('modified_utc', '?')} · "
                    f"X shape {shapes.get('X')}"
                ),
            }
        )
    return badges


# --------------------------------------------------------------------------- #
# comparison
# --------------------------------------------------------------------------- #

def compare(left: str, right: str) -> dict:
    """Diff two runs: parameters, inputs, shapes, checks and calibration."""
    left_manifest, right_manifest = manifest(left), manifest(right)
    if not left_manifest or not right_manifest:
        raise ValueError("both runs need a manifest")

    def _diff(section: str) -> list[dict]:
        a = left_manifest.get(section) or {}
        b = right_manifest.get(section) or {}
        rows = []
        for key in sorted(set(a) | set(b)):
            va, vb = a.get(key), b.get(key)
            if isinstance(va, float) and isinstance(vb, float) and va != vb:
                same = abs(va - vb) < 1e-12
            else:
                same = va == vb
            rows.append({"field": key, "left": va, "right": vb, "changed": not same})
        return rows

    left_report = selfcheck_report(left)["rel_error_mean"].dropna()
    right_report = selfcheck_report(right)["rel_error_mean"].dropna()
    common = left_report.index.intersection(right_report.index)
    overlapping = None
    if len(common) > 5:
        overlapping = {
            "dates": [d.strftime("%Y-%m-%d") for d in common],
            "left": [float(v) for v in left_report.loc[common]],
            "right": [float(v) for v in right_report.loc[common]],
            "left_median_on_common": float(left_report.loc[common].median()),
            "right_median_on_common": float(right_report.loc[common].median()),
        }

    def _inputs(run_manifest: dict) -> dict:
        """Normalise the manifest's inputs section: values may be dicts or plain strings."""
        out = {}
        for name, value in (run_manifest.get("inputs") or {}).items():
            if isinstance(value, dict):
                out[name] = {
                    "path": value.get("path"),
                    "size_bytes": value.get("size_bytes"),
                    "modified_utc": value.get("modified_utc"),
                }
            else:
                out[name] = {"path": str(value), "size_bytes": None, "modified_utc": None}
        return out

    return {
        "left": {"run_id": left, "summary": runstore.get_run(left)["summary"]},
        "right": {"run_id": right, "summary": runstore.get_run(right)["summary"]},
        "parameters": _diff("parameters"),
        "shapes": _diff("shapes"),
        "checks": _diff("checks"),
        "selfcheck": _diff("selfcheck"),
        "inputs": {"left": _inputs(left_manifest), "right": _inputs(right_manifest)},
        "overlap": overlapping,
    }

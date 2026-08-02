"""Risk analytics: portfolio exposure, variance decomposition, self-check.

Pure-function helpers consumed by Kani's reporting and validated by
``tests/test_risk.py``. All functions operate on a single cross-section
(``X_t``, ``F``, ``D``) or on aligned daily series, with no hidden state.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def portfolio_exposure(
    weights: pd.Series, exposures_t: pd.DataFrame
) -> pd.Series:
    """Portfolio factor exposure = X_t' w (K-vector)."""
    w = weights.reindex(exposures_t.index).to_numpy(dtype=float)
    X = exposures_t.to_numpy(dtype=float)
    return pd.Series(X.T @ w, index=exposures_t.columns, name="portfolio_exposure")


def risk_decomposition(
    weights: pd.Series,
    exposures_t: pd.DataFrame,
    factor_cov: pd.DataFrame,
    specific_var: pd.DataFrame,
) -> dict:
    """Decompose portfolio variance into factor and specific components.

    Returns
    -------
    dict with keys: total_variance, factor_variance, specific_variance,
    factor_pct, specific_pct, portfolio_vol_annualized.
    """
    w = weights.reindex(exposures_t.index).to_numpy(dtype=float)
    X = exposures_t.to_numpy(dtype=float)
    F = factor_cov.to_numpy(dtype=float)
    D = specific_var.to_numpy(dtype=float)

    systematic = X @ F @ X.T
    total = float(w @ systematic @ w + w @ D @ w)
    factor_var = float(w @ systematic @ w)
    specific_var_val = float(w @ D @ w)

    return {
        "total_variance": total,
        "factor_variance": factor_var,
        "specific_variance": specific_var_val,
        "factor_pct": (factor_var / total) if total else float("nan"),
        "specific_pct": (specific_var_val / total) if total else float("nan"),
        "portfolio_vol_annualized": np.sqrt(total * TRADING_DAYS),
    }


def _rolling_realized_vol(
    returns: pd.DataFrame, window: int
) -> pd.DataFrame:
    """Rolling annualized realized volatility per ticker."""
    r = returns["r"] if "r" in returns.columns else returns.iloc[:, 0]
    realized = r.groupby(level="Ticker", sort=False).transform(
        lambda s: s.rolling(window, min_periods=max(window // 2, 2)).std()
        * np.sqrt(TRADING_DAYS)
    )
    return realized.rename("realized_vol")


def volatility_selfcheck(
    exposures: pd.DataFrame,
    factor_cov: pd.DataFrame,
    specific_var: pd.DataFrame,
    returns: pd.DataFrame,
    *,
    window: int = 60,
    min_history: int = 120,
    progress_every: int | None = 100,
) -> pd.DataFrame:
    """Compare model-implied volatility to realized volatility.

    For each trading day t (after ``min_history`` days), build Sigma_t from the
    cross-section X_t and compute each stock's annualized model volatility,
    then compare with the rolling realized volatility over ``window`` days.

    Returns a per-date report with columns:
        model_vol_mean, realized_vol_mean, abs_error_mean, rel_error_mean
    """
    dates = exposures.index.get_level_values("Date").unique()
    if len(dates) < min_history:
        raise ValueError("not enough history for self-check")

    realized_vol = _rolling_realized_vol(returns, window)

    rows = []
    start = min_history
    for i, d in enumerate(dates[start:], start=start):
        x_t = exposures.xs(d, level="Date")
        # align D to this cross-section
        d_t = specific_var.reindex(index=x_t.index, columns=x_t.index)
        if d_t.isna().any().any():
            d_t = d_t.fillna(0.0)
        sigma = x_t.to_numpy(dtype=float) @ factor_cov.to_numpy(dtype=float) @ x_t.to_numpy(dtype=float).T
        sigma = sigma + d_t.to_numpy(dtype=float)
        model_vol = pd.Series(
            np.sqrt(np.diag(sigma) * TRADING_DAYS), index=x_t.index
        )

        rv = realized_vol.xs(d, level="Date")
        common = model_vol.index.intersection(rv.index)
        if len(common) < 10:
            continue
        mv = model_vol.loc[common]
        rv = rv.loc[common]
        abs_err = (mv - rv).abs().mean()
        rel_err = ((mv - rv).abs() / rv.replace(0, np.nan)).mean()
        rows.append(
            {
                "Date": d,
                "model_vol_mean": mv.mean(),
                "realized_vol_mean": rv.mean(),
                "abs_error_mean": abs_err,
                "rel_error_mean": rel_err,
            }
        )
        if progress_every and (i - start + 1) % progress_every == 0:
            print(
                f"[selfcheck] {i + 1}/{len(dates)} dates", flush=True
            )

    return pd.DataFrame(rows).set_index("Date")

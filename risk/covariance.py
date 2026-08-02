"""Barra structured risk model: factor and specific covariance estimation.

Implements the corrected methodology from COLLABORATION_PLAN §2.3:

    r = X f + eps

where ``r`` is the N x 1 vector of daily stock returns, ``X`` is the N x K
matrix of (orthogonalized) factor exposures, ``f`` is the K x 1 vector of
factor returns and ``eps`` is the N x 1 vector of idiosyncratic returns. The
asset covariance is then

    Sigma = X F X' + D

with ``F`` the K x K factor covariance (Ledoit-Wolf shrinkage on the factor
return series) and ``D`` the N x N diagonal specific-risk covariance. The
specific covariance is diagonal only -- estimating a full N x N residual
covariance is impossible when T < N and would contradict the Barra paradigm.

We do NOT shrink the exposure matrix X directly; only the estimated factor
return series f is shrunk.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

TRADING_DAYS = 252


def estimate_factor_returns(
    exposures: pd.DataFrame,
    returns: pd.DataFrame,
    *,
    use_market_cap_weights: bool = False,
    progress_every: int | None = 100,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Cross-sectional OLS ``r_t = X_t f_t + eps_t`` for every trading day.

    Parameters
    ----------
    exposures : [Date, Ticker] matrix, K factor columns. Should already be
        cleaned so that each (date, ticker) pair used has no NaN.
    returns   : [Date, Ticker] matrix with a single column ``r``.
    use_market_cap_weights : if True, run weighted-LS using a ``market_cap``
        column carried on ``exposures`` (optional; ignored if absent).

    Returns
    -------
    factor_returns : K x T DataFrame (factor names x dates).
    idio_returns   : N x T DataFrame (tickers x dates) of residuals eps.
    """
    if "r" not in returns.columns:
        # allow either a single-column frame or a frame named differently
        if returns.shape[1] == 1:
            returns = returns.rename(columns={returns.columns[0]: "r"})
        else:
            raise ValueError("returns must have exactly one column ('r').")

    dates = exposures.index.get_level_values("Date").unique()
    factor_names = list(exposures.columns)
    tickers = exposures.index.get_level_values("Ticker").unique()

    f_matrix = np.full((len(factor_names), len(dates)), np.nan)
    eps_matrix = np.full((len(tickers), len(dates)), np.nan)

    has_weights = use_market_cap_weights and "market_cap" in exposures.columns

    for j, d in enumerate(dates):
        x_day = exposures.xs(d, level="Date")
        r_day = returns.xs(d, level="Date")["r"]
        # align on the intersection of tickers present in both
        common = x_day.index.intersection(r_day.index)
        if len(common) < len(factor_names) + 1:
            continue
        X = x_day.loc[common].to_numpy(dtype=float)
        y = r_day.loc[common].to_numpy(dtype=float)
        w = None
        if has_weights:
            w = x_day.loc[common, "market_cap"].to_numpy(dtype=float)
            w = np.sqrt(np.clip(w, 0, None))

        if w is None:
            beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        else:
            W = np.diag(w)
            Xw = W @ X
            yw = W @ y
            beta, *_ = np.linalg.lstsq(Xw, yw, rcond=None)

        f_matrix[:, j] = beta
        row_idx = tickers.get_indexer(common)
        eps_matrix[row_idx, j] = y - X @ beta

        if progress_every and (j + 1) % progress_every == 0:
            print(f"[cov] factor returns {j + 1}/{len(dates)}", flush=True)

    factor_returns = pd.DataFrame(
        f_matrix, index=factor_names, columns=pd.DatetimeIndex(dates)
    )
    idio_returns = pd.DataFrame(
        eps_matrix, index=tickers, columns=pd.DatetimeIndex(dates)
    )
    return factor_returns, idio_returns


def estimate_factor_covariance(
    factor_returns: pd.DataFrame,
    *,
    shrinkage: str = "ledoit-wolf",
) -> pd.DataFrame:
    """Estimate the K x K factor covariance ``F`` from factor returns.

    Parameters
    ----------
    factor_returns : K x T DataFrame (factor names x dates).
    shrinkage : ``"ledoit-wolf"`` (default) or ``"sample"``.
    """
    f = factor_returns.T.to_numpy(dtype=float)  # T x K
    if shrinkage == "ledoit-wolf":
        lw = LedoitWolf().fit(f)
        cov = lw.covariance_
    elif shrinkage == "sample":
        cov = np.cov(f, rowvar=False, ddof=1)
    else:
        raise ValueError(f"unknown shrinkage method: {shrinkage!r}")
    return pd.DataFrame(
        cov,
        index=factor_returns.index,
        columns=factor_returns.index,
    )


def estimate_specific_variance(
    idio_returns: pd.DataFrame,
    *,
    shrinkage: str = "none",
) -> pd.DataFrame:
    """Estimate the diagonal specific-risk covariance ``D`` (N x N).

    Only the diagonal is estimated -- a full N x N residual covariance is not
    identified when T < N. Each stock's specific variance is its residual
    variance across time. Optional ``shrinkage="diagonal"`` pulls each stock's
    variance toward the cross-sectional average for stability.

    Returns an N x N diagonal DataFrame.
    """
    var = idio_returns.var(axis=1, ddof=1)  # N
    var = var.fillna(var.mean())
    if shrinkage == "diagonal":
        target = var.mean()
        var = 0.8 * var + 0.2 * target
    elif shrinkage not in ("none", None):
        raise ValueError(f"unknown shrinkage method: {shrinkage!r}")
    d = pd.DataFrame(
        np.diag(var.to_numpy(dtype=float)),
        index=idio_returns.index,
        columns=idio_returns.index,
    )
    return d


def asset_covariance(
    exposures_t: pd.DataFrame,
    factor_cov: pd.DataFrame,
    specific_var: pd.DataFrame,
) -> pd.DataFrame:
    """Synthesize the N x N asset covariance ``Sigma = X F X' + D``.

    Parameters
    ----------
    exposures_t  : N x K factor exposures for a single cross-section.
    factor_cov   : K x K factor covariance ``F``.
    specific_var : N x N diagonal specific-risk covariance ``D``.
    """
    X = exposures_t.to_numpy(dtype=float)
    F = factor_cov.to_numpy(dtype=float)
    D = specific_var.to_numpy(dtype=float)
    systematic = X @ F @ X.T
    sigma = systematic + D
    tickers = list(exposures_t.index)
    return pd.DataFrame(sigma, index=tickers, columns=tickers)


def asset_volatility(
    exposures_t: pd.DataFrame,
    factor_cov: pd.DataFrame,
    specific_var: pd.DataFrame,
) -> pd.Series:
    """Annualized asset volatility from Sigma = X F X' + D."""
    sigma = asset_covariance(exposures_t, factor_cov, specific_var)
    vol = np.sqrt(np.diag(sigma.to_numpy(dtype=float)) * TRADING_DAYS)
    return pd.Series(vol, index=sigma.index, name="vol_annualized")

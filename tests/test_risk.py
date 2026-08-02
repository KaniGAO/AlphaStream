"""Unit tests for Kani's risk module (Barra structured risk model).

Coverage:
* data-bridge panel construction
* exposure / return loading and alignment
* factor-return regression, factor covariance, specific variance, asset Sigma
* portfolio exposure, variance decomposition, volatility self-check

Synthetic fixtures keep the covariance/analytics tests fast and isolated;
integration asserts use the generated ``exposures.parquet`` for light shape
checks only.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from risk.covariance import (  # noqa: E402
    asset_covariance,
    estimate_factor_covariance,
    estimate_factor_returns,
    estimate_specific_variance,
)
from risk.exposures import (  # noqa: E402
    aligned_panel,
    load_exposures,
    load_returns,
)
from risk.analytics import (  # noqa: E402
    portfolio_exposure,
    risk_decomposition,
    volatility_selfcheck,
)

EXPOSURES_PATH = PROJECT_ROOT / "Data" / "Processed" / "exposures.parquet"
CONTRACT_COLS = [
    "px_last", "market_cap", "pb", "earn_yld", "beta", "volume",
    "growth_sales", "growth_eps", "leverage",
    "gics_sector", "gics_industry_group", "gics_sub_industry",
]


# --------------------------------------------------------------------------- #
# data bridge
# --------------------------------------------------------------------------- #
def test_build_panel_shape_and_columns():
    from Data.build_panel import build_panel

    panel = build_panel()
    assert list(panel.columns) == CONTRACT_COLS
    assert list(panel.index.names) == ["Date", "Ticker"]
    assert not panel.index.has_duplicates
    assert panel.shape[1] == len(CONTRACT_COLS)
    assert panel.index.get_level_values("Ticker").nunique() > 100


def test_build_panel_no_future_leak():
    from Data.build_panel import build_panel

    panel = build_panel()
    dates = panel.index.get_level_values("Date")
    assert dates.is_monotonic_increasing


# --------------------------------------------------------------------------- #
# exposures / returns
# --------------------------------------------------------------------------- #
def test_load_exposures_and_returns_align():
    if not EXPOSURES_PATH.exists():
        pytest.skip("run Data/generate_exposures.py first")
    X = load_exposures()
    assert list(X.index.names) == ["Date", "Ticker"]
    assert X.shape[1] == 10
    r = load_returns(X)
    assert r.index.equals(X.index)


def test_aligned_panel_same_index():
    if not EXPOSURES_PATH.exists():
        pytest.skip("run Data/generate_exposures.py first")
    X = load_exposures()
    r = load_returns(X)
    xc, rc = aligned_panel(X, r)
    assert xc.index.equals(rc.index)
    assert xc.notna().all().all()
    assert rc["r"].notna().all()


# --------------------------------------------------------------------------- #
# covariance (synthetic fixtures)
# --------------------------------------------------------------------------- #
@pytest.fixture
def synthetic():
    rng = np.random.default_rng(0)
    K, N, T = 3, 20, 50
    tickers = [f"T{i}" for i in range(N)]
    dates = pd.date_range("2024-01-01", periods=T, freq="B")
    idx = pd.MultiIndex.from_product([dates, tickers], names=["Date", "Ticker"])
    X = pd.DataFrame(
        rng.standard_normal((N * T, K)), index=idx,
        columns=["f0", "f1", "f2"],
    )
    f_true = rng.standard_normal((K, T))
    eps = rng.standard_normal((N * T,)) * 0.5
    r_long = (X.to_numpy() * f_true[:, :1].T.ravel()).sum(axis=1) + eps
    r = pd.DataFrame(r_long, index=idx, columns=["r"])
    return X, r


def test_estimate_factor_returns_shape(synthetic):
    X, r = synthetic
    f, eps = estimate_factor_returns(X, r)
    assert f.shape[0] == 3
    assert eps.shape[0] == X.index.get_level_values("Ticker").nunique()


def test_factor_covariance_symmetric_pd(synthetic):
    X, r = synthetic
    f, _ = estimate_factor_returns(X, r)
    F = estimate_factor_covariance(f)
    assert F.shape == (3, 3)
    assert np.allclose(F.to_numpy(float), F.to_numpy(float).T)
    assert np.linalg.eigvalsh(F.to_numpy(float)).min() >= -1e-10


def test_specific_variance_diagonal(synthetic):
    X, r = synthetic
    _, eps = estimate_factor_returns(X, r)
    D = estimate_specific_variance(eps)
    off_diag = D.to_numpy(float) - np.diag(np.diag(D.to_numpy(float)))
    assert np.allclose(off_diag, 0.0)
    assert (np.diag(D.to_numpy(float)) >= 0).all()


def test_asset_covariance_formula(synthetic):
    X, r = synthetic
    f, eps = estimate_factor_returns(X, r)
    F = estimate_factor_covariance(f)
    D = estimate_specific_variance(eps)
    d0 = X.index.get_level_values("Date").unique()[0]
    xt = X.xs(d0, level="Date")
    dt = D.reindex(index=xt.index, columns=xt.index)
    S = asset_covariance(xt, F, dt)
    Xm, Fm, Dm = xt.to_numpy(float), F.to_numpy(float), dt.to_numpy(float)
    expected = Xm @ Fm @ Xm.T + Dm
    assert np.allclose(S.to_numpy(float), expected)
    assert np.linalg.eigvalsh(S.to_numpy(float)).min() > 0


# --------------------------------------------------------------------------- #
# analytics (synthetic fixtures)
# --------------------------------------------------------------------------- #
def test_portfolio_exposure_shape(synthetic):
    X, _ = synthetic
    d0 = X.index.get_level_values("Date").unique()[0]
    xt = X.xs(d0, level="Date")
    w = pd.Series(1.0 / len(xt), index=xt.index)
    pe = portfolio_exposure(w, xt)
    assert pe.shape == (3,)
    assert list(pe.index) == list(xt.columns)


def test_risk_decomposition_additive(synthetic):
    X, r = synthetic
    f, eps = estimate_factor_returns(X, r)
    F = estimate_factor_covariance(f)
    D = estimate_specific_variance(eps)
    d0 = X.index.get_level_values("Date").unique()[0]
    xt = X.xs(d0, level="Date")
    dt = D.reindex(index=xt.index, columns=xt.index)
    w = pd.Series(1.0 / len(xt), index=xt.index)
    dec = risk_decomposition(w, xt, F, dt)
    assert abs(
        (dec["factor_variance"] + dec["specific_variance"])
        - dec["total_variance"]
    ) < 1e-9
    assert abs(dec["factor_pct"] + dec["specific_pct"] - 1.0) < 1e-9


def test_volatility_selfcheck_returns_report(synthetic):
    X, r = synthetic
    f, eps = estimate_factor_returns(X, r)
    F = estimate_factor_covariance(f)
    D = estimate_specific_variance(eps)
    report = volatility_selfcheck(X, F, D, r, window=10, min_history=20)
    assert isinstance(report, pd.DataFrame)
    assert "rel_error_mean" in report.columns
    assert (report["rel_error_mean"] >= 0).all()

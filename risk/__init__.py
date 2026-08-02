"""Kani's risk-model module (Barra structured risk model).

Public entry points
-------------------
- ``risk.exposures`` : load factor exposures X and point-in-time returns r
- ``risk.covariance`` : estimate factor covariance F, specific variance D,
  and the asset covariance Sigma = X F X' + D
- ``risk.analytics``  : portfolio exposure, risk decomposition, self-check

The module consumes Zeon's ``Data/Processed/exposures.parquet`` as the single
hand-off artifact and never reaches back into ``factors/`` internals.
"""

from risk.analytics import (
    portfolio_exposure,
    risk_decomposition,
    volatility_selfcheck,
)
from risk.covariance import (
    asset_covariance,
    estimate_factor_covariance,
    estimate_factor_returns,
    estimate_specific_variance,
)
from risk.exposures import load_exposures, load_returns

__all__ = [
    "load_exposures",
    "load_returns",
    "estimate_factor_returns",
    "estimate_factor_covariance",
    "estimate_specific_variance",
    "asset_covariance",
    "portfolio_exposure",
    "risk_decomposition",
    "volatility_selfcheck",
]

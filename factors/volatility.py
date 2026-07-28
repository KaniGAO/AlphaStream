"""Raw historical Volatility Factor implementation."""

from __future__ import annotations

import numpy as np
import pandas as pd

from factors.base import Factor


class VolatilityFactor(Factor):
    """Annualized volatility of trailing daily price returns.

    Raw definition
    --------------
    For stock i on date t, calculate simple daily returns from valid positive
    prices and then:

    ``volatility(t, i) = std(return[t-59:t, i], ddof=0) * sqrt(252)``

    The default 60-return window requires 61 valid consecutive prices.

    Point-in-time rule
    ------------------
    Returns and rolling standard deviations are calculated independently
    within each Ticker. Only prices dated on or before t are used.

    Missing and invalid values
    --------------------------
    Missing, zero, or negative prices are invalid. No fill or backfill is
    performed. A window without all required returns remains NaN.
    """

    name = "volatility"
    required_columns = ("px_last",)

    lookback_days = 60
    annualization_days = 252

    def _compute(self, panel: pd.DataFrame) -> pd.Series:
        """Calculate trailing annualized volatility for every ticker."""
        if (
            not isinstance(self.lookback_days, int)
            or isinstance(self.lookback_days, bool)
            or self.lookback_days < 2
        ):
            raise ValueError("lookback_days must be an integer >= 2.")
        if (
            not isinstance(self.annualization_days, int)
            or isinstance(self.annualization_days, bool)
            or self.annualization_days < 1
        ):
            raise ValueError("annualization_days must be an integer >= 1.")

        original_index = panel.index
        prices = (
            panel["px_last"]
            .copy()
            .sort_index(level=["Date", "Ticker"])
            .where(lambda values: values > 0)
        )
        grouped_prices = prices.groupby(level="Ticker", sort=False)
        previous_prices = grouped_prices.shift(1)
        daily_returns = prices.div(previous_prices).sub(1)
        volatility = daily_returns.groupby(
            level="Ticker",
            sort=False,
        ).transform(
            lambda values: values.rolling(
                window=self.lookback_days,
                min_periods=self.lookback_days,
            ).std(ddof=0)
        )
        volatility = volatility.mul(np.sqrt(self.annualization_days))
        volatility.name = self.name
        return volatility.reindex(original_index)

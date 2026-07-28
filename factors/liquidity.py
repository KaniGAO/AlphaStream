"""Raw trading-volume Liquidity Factor implementation."""

from __future__ import annotations

import numpy as np
import pandas as pd

from factors.base import Factor


class LiquidityFactor(Factor):
    """Liquidity measured by trailing average daily trading volume.

    Raw definition
    --------------
    For stock i on date t:

    ``liquidity(t, i) = log(mean(volume[t-59:t, i]))``

    Larger values represent more actively traded, more liquid securities.
    The logarithm reduces the strong right skew in raw trading volume.

    Point-in-time rule
    ------------------
    The rolling mean is calculated independently within each Ticker and uses
    only volume observations dated on or before t.

    Missing and invalid values
    --------------------------
    Missing, zero, or negative volume is invalid. No fill or backfill is
    performed. A window without all 60 valid observations remains NaN.
    """

    name = "liquidity"
    required_columns = ("volume",)

    lookback_days = 60

    def _compute(self, panel: pd.DataFrame) -> pd.Series:
        """Calculate log trailing average volume for every ticker."""
        if (
            not isinstance(self.lookback_days, int)
            or isinstance(self.lookback_days, bool)
            or self.lookback_days < 1
        ):
            raise ValueError("lookback_days must be an integer >= 1.")

        original_index = panel.index
        volume = (
            panel["volume"]
            .copy()
            .sort_index(level=["Date", "Ticker"])
            .where(lambda values: values > 0)
        )
        average_volume = volume.groupby(
            level="Ticker",
            sort=False,
        ).transform(
            lambda values: values.rolling(
                window=self.lookback_days,
                min_periods=self.lookback_days,
            ).mean()
        )
        liquidity = np.log(average_volume)
        liquidity.name = self.name
        return liquidity.reindex(original_index)

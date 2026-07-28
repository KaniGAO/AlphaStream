"""Raw 12-1 Momentum Factor implementation."""

from __future__ import annotations

import pandas as pd

from factors.base import Factor


class MomentumFactor(Factor):
    """Price momentum measured over the prior 12 months, excluding one month.

    Raw definition
    --------------
    With daily trading observations, let ``L=252`` trading days (about twelve
    months) and ``S=21`` trading days (about one month).  For stock i on date
    t, define:

    ``momentum(t, i) = PX_LAST(t-S, i) / PX_LAST(t-L, i) - 1``

    This is the conventional *12-1 momentum*: it measures the return from
    approximately twelve months ago up to approximately one month ago.  The
    most recent month is deliberately excluded because short-horizon returns
    can exhibit reversal rather than momentum.

    Point-in-time rule
    ------------------
    Both prices used in the formula must have Date <= t.  Calculate shifts
    separately within each Ticker's time series; never use prices from another
    Ticker and never use a negative shift (which would read future rows).

    Missing and invalid values
    --------------------------
    A stock without enough earlier observations has NaN momentum.  Prices that
    are missing, zero, or negative cannot form a valid price ratio and should
    lead to NaN.  Do not fill or backfill prices in this factor.
    """

    name = "momentum"
    required_columns = ("px_last",)

    lookback_days = 252
    skip_days = 21

    def _compute(self, panel: pd.DataFrame) -> pd.Series:
        """Calculate raw 12-1 momentum without cross-stock contamination.
        """
        if not (self.lookback_days > self.skip_days >= 0):
            raise ValueError(
                f"Invalid configuration: lookback_days ({self.lookback_days}) "
                f"must be strictly greater than skip_days ({self.skip_days}) >= 0."
            )

        original_index = panel.index
        prices = (
            panel["px_last"]
            .copy()
            .sort_index(level=["Date", "Ticker"])
        )
        prices = prices.where(prices > 0)
        grouped = prices.groupby(level="Ticker", sort=False)
        recent = grouped.shift(self.skip_days)
        old = grouped.shift(self.lookback_days)
        momentum = recent.div(old).sub(1)
        momentum.name = self.name
        return momentum.reindex(original_index)

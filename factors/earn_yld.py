"""Raw Earnings-Yield Factor implementation."""

from __future__ import annotations

import pandas as pd

from factors.base import Factor


class EarningsYieldFactor(Factor):
    """Value exposure based on Bloomberg's earnings-yield descriptor.

    Raw definition
    --------------
    ``earn_yld(t, i) = earn_yld(t, i)``

    A higher earnings yield means more earnings per unit of market price, so it
    represents a higher value exposure.  Negative earnings yield is valid: it
    represents a loss-making company and must not be converted to NaN.

    Point-in-time rule
    ------------------
    ``earn_yld`` is descriptor data already backward-asof aligned by the
    loader.  At Date=t this factor uses only a descriptor effective at or
    before t.
    """

    name = "earn_yld"
    required_columns = ("earn_yld",)

    def _compute(self, panel: pd.DataFrame) -> pd.Series:
        raw_earn_yld = panel["earn_yld"].copy()
        raw_earn_yld.name = self.name
        return raw_earn_yld

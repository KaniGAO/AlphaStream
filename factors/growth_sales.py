"""Raw Sales-Growth Factor implementation."""

from __future__ import annotations

import pandas as pd

from factors.base import Factor


class SalesGrowthFactor(Factor):
    """Growth exposure based on Bloomberg's sales-growth descriptor.

    Raw definition
    --------------
    ``growth_sales(t, i) = growth_sales(t, i)``

    Higher sales growth represents a higher growth exposure.  Negative growth
    is valid information about shrinking sales, so it must be retained.

    Point-in-time rule
    ------------------
    ``growth_sales`` is quarterly descriptor data already backward-asof
    aligned per Ticker by the loader.  At Date=t it reflects only information
    whose effective date is at or before t.
    """

    name = "growth_sales"
    required_columns = ("growth_sales",)

    def _compute(self, panel: pd.DataFrame) -> pd.Series:
        raw_growth_sales = panel["growth_sales"].copy()
        raw_growth_sales.name = self.name
        return raw_growth_sales

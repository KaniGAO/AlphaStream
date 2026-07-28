"""Raw EPS-Growth Factor implementation."""

from __future__ import annotations

import pandas as pd

from factors.base import Factor


class EPSGrowthFactor(Factor):
    """Growth exposure based on Bloomberg's EPS-growth descriptor.

    Raw definition
    --------------
    ``growth_eps(t, i) = growth_eps(t, i)``

    Higher EPS growth represents a higher growth exposure.  Negative growth
    is valid information and must remain in the raw exposure; daily
    winsorization handles cross-sectional extremes downstream.

    Point-in-time rule
    ------------------
    ``growth_eps`` is quarterly descriptor data already backward-asof aligned
    per Ticker by the loader.  At Date=t it reflects only information whose
    effective date is at or before t.
    """

    name = "growth_eps"
    required_columns = ("growth_eps",)

    def _compute(self, panel: pd.DataFrame) -> pd.Series:
        raw_growth_eps = panel["growth_eps"].copy()
        raw_growth_eps.name = self.name
        return raw_growth_eps

"""Raw Beta Factor implementation."""

from __future__ import annotations

import pandas as pd

from factors.base import Factor


class BetaFactor(Factor):
    """Market-sensitivity exposure from Bloomberg's adjusted beta descriptor.

    Raw definition
    --------------
    ``beta(t, i) = beta(t, i)``

    Higher beta means stronger sensitivity to market movements.  Negative beta
    is an economically meaningful value and must be preserved; only missing
    descriptor values remain NaN.

    Point-in-time rule
    ------------------
    ``beta`` is descriptor data already backward-asof aligned by the loader.
    At Date=t this factor uses only a descriptor effective at or before t.
    """

    name = "beta"
    required_columns = ("beta",)

    def _compute(self, panel: pd.DataFrame) -> pd.Series:
        raw_beta = panel["beta"].copy()
        raw_beta.name = self.name
        return raw_beta

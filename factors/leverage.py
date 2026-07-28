"""Raw Leverage Factor implementation."""

from __future__ import annotations

import pandas as pd

from factors.base import Factor


class LeverageFactor(Factor):
    """Leverage exposure based on Bloomberg's debt-to-common-equity ratio.

    Raw definition
    --------------
    ``leverage(t, i) = leverage(t, i)``

    Higher debt relative to common equity represents higher leverage exposure.
    The first version deliberately preserves Bloomberg's raw numeric values;
    daily winsorization handles extreme observations.  Do not assume a
    negative value is invalid without first reviewing its data meaning.

    Point-in-time rule
    ------------------
    ``leverage`` is quarterly descriptor data already backward-asof aligned
    per Ticker by the loader.  At Date=t it reflects only information whose
    effective date is at or before t.
    """

    name = "leverage"
    required_columns = ("leverage",)

    def _compute(self, panel: pd.DataFrame) -> pd.Series:
        raw_leverage = panel["leverage"].copy()
        raw_leverage.name = self.name
        return raw_leverage

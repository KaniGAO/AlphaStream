"""Raw Value Factor implementation."""

from __future__ import annotations

import pandas as pd
import numpy as np

from factors.base import Factor


class ValueFactor(Factor):
    """Company-value exposure derived from the price-to-book ratio.

    Raw definition
    --------------
    ``value(t, i) = -log(pb(t, i))``

    A lower price-to-book ratio means a stock is cheaper relative to book
    value.  The negative sign makes a cheaper stock receive a *higher* value
    exposure, which is the intended economic direction.

    Point-in-time rule
    ------------------
    ``pb`` in the standard panel has already been backward-asof aligned by the
    loader.  Therefore the value exposure on Date=t may use only the PB value
    whose descriptor effective date is <= t.  Do not shift it forward or
    backward again in this factor.

    Missing and invalid values
    --------------------------
    PB must be strictly positive before taking a logarithm.  Missing, zero,
    and negative PB values must become NaN; do not replace them with zero.
    """

    name = "value"
    required_columns = ("pb",)

    def _compute(self, panel: pd.DataFrame) -> pd.Series:

        # 1. Select the raw PB Series with ``panel["pb"]``.
        raw_pb = panel['pb']
       
        # 2. Keep only strictly positive PB values using ``Series.where``.
        #    This must retain the original Date/Ticker index while converting
        #    zero and negative values to NaN.
        valid_pb = raw_pb.where(raw_pb > 0)
        # 3. Calculate ``-np.log(valid_pb)``.  Import numpy at module level
        #    rather than using a row-by-row lambda.
        res = -np.log(valid_pb)

        # 4. Set the returned Series name to ``self.name`` ("value").
        res.name = self.name

        return res
        

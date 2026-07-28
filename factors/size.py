"""Raw Size Factor implementation."""

import numpy as np
import pandas as pd

from factors.base import Factor


class SizeFactor(Factor):
    """Company-size exposure based on market capitalization.
    
    Raw Definition
    -------------------
    size(t,i) = log(market_cap(t,i))
    
    point-in-time
    --------------------
    Exposure at date t uses only the market capitalization observed at t.

    Missing and invalid values
    --------------------
    Missing or invalid market capitalization values are set to NaN.
    
    """
    name = "size"
    required_columns = ("market_cap",)

    def _compute(self, panel: pd.DataFrame) -> pd.Series:
        """Return the natural log of strictly positive market capitalizations."""
        result = np.log(panel["market_cap"].where(panel["market_cap"] > 0))
        result.name = self.name
        return result

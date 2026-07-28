"""Tests for the raw Earnings-Yield factor."""

import numpy as np
import pandas as pd
import pytest

from factors.earn_yld import EarningsYieldFactor


@pytest.fixture
def panel() -> pd.DataFrame:
    index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2025-01-02"), "AAA"), (pd.Timestamp("2025-01-02"), "BBB")],
        names=["Date", "Ticker"],
    )
    return pd.DataFrame({"earn_yld": [0.08, -0.03]}, index=index)


def test_earnings_yield_preserves_raw_values_and_contract(panel: pd.DataFrame) -> None:
    actual = EarningsYieldFactor().compute(panel)

    pd.testing.assert_series_equal(actual, panel["earn_yld"].rename("earn_yld"))
    assert actual.index.equals(panel.index)


def test_earnings_yield_preserves_nan_and_does_not_mutate_input(panel: pd.DataFrame) -> None:
    panel.loc[(pd.Timestamp("2025-01-02"), "AAA"), "earn_yld"] = np.nan
    original = panel.copy(deep=True)

    actual = EarningsYieldFactor().compute(panel)

    assert pd.isna(actual.iloc[0])
    pd.testing.assert_frame_equal(panel, original)


def test_earnings_yield_rejects_missing_column(panel: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match=r"missing \['earn_yld'\]"):
        EarningsYieldFactor().compute(panel.rename(columns={"earn_yld": "wrong"}))

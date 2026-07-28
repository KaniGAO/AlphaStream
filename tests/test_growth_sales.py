"""Tests for the raw Sales-Growth factor."""

import numpy as np
import pandas as pd
import pytest

from factors.growth_sales import SalesGrowthFactor


@pytest.fixture
def panel() -> pd.DataFrame:
    index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2025-01-02"), "AAA"), (pd.Timestamp("2025-01-02"), "BBB")],
        names=["Date", "Ticker"],
    )
    return pd.DataFrame({"growth_sales": [0.15, -0.10]}, index=index)


def test_sales_growth_preserves_raw_values_and_contract(panel: pd.DataFrame) -> None:
    actual = SalesGrowthFactor().compute(panel)

    pd.testing.assert_series_equal(
        actual, panel["growth_sales"].rename("growth_sales")
    )
    assert actual.index.equals(panel.index)


def test_sales_growth_preserves_nan_and_does_not_mutate_input(panel: pd.DataFrame) -> None:
    panel.loc[(pd.Timestamp("2025-01-02"), "AAA"), "growth_sales"] = np.nan
    original = panel.copy(deep=True)

    actual = SalesGrowthFactor().compute(panel)

    assert pd.isna(actual.iloc[0])
    pd.testing.assert_frame_equal(panel, original)


def test_sales_growth_rejects_missing_column(panel: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match=r"missing \['growth_sales'\]"):
        SalesGrowthFactor().compute(
            panel.rename(columns={"growth_sales": "wrong"})
        )

"""Tests for the raw EPS-Growth factor."""

import numpy as np
import pandas as pd
import pytest

from factors.growth_eps import EPSGrowthFactor


@pytest.fixture
def panel() -> pd.DataFrame:
    index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2025-01-02"), "AAA"), (pd.Timestamp("2025-01-02"), "BBB")],
        names=["Date", "Ticker"],
    )
    return pd.DataFrame({"growth_eps": [0.25, -0.40]}, index=index)


def test_eps_growth_preserves_raw_values_and_contract(panel: pd.DataFrame) -> None:
    actual = EPSGrowthFactor().compute(panel)

    pd.testing.assert_series_equal(actual, panel["growth_eps"].rename("growth_eps"))
    assert actual.index.equals(panel.index)


def test_eps_growth_preserves_nan_and_does_not_mutate_input(panel: pd.DataFrame) -> None:
    panel.loc[(pd.Timestamp("2025-01-02"), "AAA"), "growth_eps"] = np.nan
    original = panel.copy(deep=True)

    actual = EPSGrowthFactor().compute(panel)

    assert pd.isna(actual.iloc[0])
    pd.testing.assert_frame_equal(panel, original)


def test_eps_growth_rejects_missing_column(panel: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match=r"missing \['growth_eps'\]"):
        EPSGrowthFactor().compute(panel.rename(columns={"growth_eps": "wrong"}))

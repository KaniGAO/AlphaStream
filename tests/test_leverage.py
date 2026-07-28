"""Tests for the raw Leverage factor."""

import numpy as np
import pandas as pd
import pytest

from factors.leverage import LeverageFactor


@pytest.fixture
def panel() -> pd.DataFrame:
    index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2025-01-02"), "AAA"), (pd.Timestamp("2025-01-02"), "BBB")],
        names=["Date", "Ticker"],
    )
    return pd.DataFrame({"leverage": [0.6, -0.3]}, index=index)


def test_leverage_preserves_raw_values_and_contract(panel: pd.DataFrame) -> None:
    actual = LeverageFactor().compute(panel)

    pd.testing.assert_series_equal(actual, panel["leverage"].rename("leverage"))
    assert actual.index.equals(panel.index)


def test_leverage_preserves_nan_and_does_not_mutate_input(panel: pd.DataFrame) -> None:
    panel.loc[(pd.Timestamp("2025-01-02"), "AAA"), "leverage"] = np.nan
    original = panel.copy(deep=True)

    actual = LeverageFactor().compute(panel)

    assert pd.isna(actual.iloc[0])
    pd.testing.assert_frame_equal(panel, original)


def test_leverage_rejects_missing_column(panel: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match=r"missing \['leverage'\]"):
        LeverageFactor().compute(panel.rename(columns={"leverage": "wrong"}))

"""Tests for the raw Beta factor."""

import numpy as np
import pandas as pd
import pytest

from factors.beta import BetaFactor


@pytest.fixture
def panel() -> pd.DataFrame:
    index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2025-01-02"), "AAA"), (pd.Timestamp("2025-01-02"), "BBB")],
        names=["Date", "Ticker"],
    )
    return pd.DataFrame({"beta": [1.2, -0.2]}, index=index)


def test_beta_preserves_raw_values_and_contract(panel: pd.DataFrame) -> None:
    actual = BetaFactor().compute(panel)

    pd.testing.assert_series_equal(actual, panel["beta"].rename("beta"))
    assert actual.index.equals(panel.index)


def test_beta_preserves_nan_and_does_not_mutate_input(panel: pd.DataFrame) -> None:
    panel.loc[(pd.Timestamp("2025-01-02"), "AAA"), "beta"] = np.nan
    original = panel.copy(deep=True)

    actual = BetaFactor().compute(panel)

    assert pd.isna(actual.iloc[0])
    pd.testing.assert_frame_equal(panel, original)


def test_beta_rejects_missing_column(panel: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match=r"missing \['beta'\]"):
        BetaFactor().compute(panel.rename(columns={"beta": "wrong"}))

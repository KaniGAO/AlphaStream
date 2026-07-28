"""Tests for the trailing historical Volatility factor."""

import numpy as np
import pandas as pd
import pytest

from factors.volatility import VolatilityFactor


class ShortVolatilityFactor(VolatilityFactor):
    lookback_days = 3
    annualization_days = 4


@pytest.fixture
def shuffled_panel() -> pd.DataFrame:
    index = pd.MultiIndex.from_tuples(
        [
            (pd.Timestamp("2025-01-04"), "BBB"),
            (pd.Timestamp("2025-01-01"), "AAA"),
            (pd.Timestamp("2025-01-03"), "AAA"),
            (pd.Timestamp("2025-01-02"), "BBB"),
            (pd.Timestamp("2025-01-04"), "AAA"),
            (pd.Timestamp("2025-01-01"), "BBB"),
            (pd.Timestamp("2025-01-02"), "AAA"),
            (pd.Timestamp("2025-01-03"), "BBB"),
        ],
        names=["Date", "Ticker"],
    )
    return pd.DataFrame(
        {"px_last": [50.0, 100.0, 99.0, 50.0, 118.8, 50.0, 110.0, 50.0]},
        index=index,
    )


def test_volatility_uses_trailing_returns_per_ticker(
    shuffled_panel: pd.DataFrame,
) -> None:
    result = ShortVolatilityFactor().compute(shuffled_panel)
    expected = np.std([0.10, -0.10, 0.20], ddof=0) * 2.0

    assert result.index.equals(shuffled_panel.index)
    assert result.name == "volatility"
    assert result.loc[(pd.Timestamp("2025-01-04"), "AAA")] == pytest.approx(expected)
    assert result.loc[(pd.Timestamp("2025-01-04"), "BBB")] == 0.0


def test_volatility_requires_complete_return_window(
    shuffled_panel: pd.DataFrame,
) -> None:
    panel = shuffled_panel.copy()
    panel.loc[(pd.Timestamp("2025-01-02"), "AAA"), "px_last"] = 0.0

    result = ShortVolatilityFactor().compute(panel)

    assert pd.isna(result.loc[(pd.Timestamp("2025-01-04"), "AAA")])
    assert result.loc[(pd.Timestamp("2025-01-04"), "BBB")] == 0.0


def test_volatility_does_not_read_future_prices(
    shuffled_panel: pd.DataFrame,
) -> None:
    baseline = ShortVolatilityFactor().compute(shuffled_panel)
    future_index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2025-01-05"), "AAA")],
        names=["Date", "Ticker"],
    )
    extended = pd.concat(
        [shuffled_panel, pd.DataFrame({"px_last": [1000.0]}, index=future_index)]
    )

    actual = ShortVolatilityFactor().compute(extended).reindex(shuffled_panel.index)

    pd.testing.assert_series_equal(actual, baseline)


def test_volatility_does_not_mutate_input(
    shuffled_panel: pd.DataFrame,
) -> None:
    original = shuffled_panel.copy(deep=True)

    ShortVolatilityFactor().compute(shuffled_panel)

    pd.testing.assert_frame_equal(shuffled_panel, original)

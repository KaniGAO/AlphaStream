"""Tests for the trailing trading-volume Liquidity factor."""

import numpy as np
import pandas as pd
import pytest

from factors.liquidity import LiquidityFactor


class ShortLiquidityFactor(LiquidityFactor):
    lookback_days = 3


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
        {"volume": [100.0, 10.0, 30.0, 100.0, 40.0, 100.0, 20.0, 100.0]},
        index=index,
    )


def test_liquidity_uses_trailing_average_volume_per_ticker(
    shuffled_panel: pd.DataFrame,
) -> None:
    result = ShortLiquidityFactor().compute(shuffled_panel)

    assert result.index.equals(shuffled_panel.index)
    assert result.name == "liquidity"
    assert result.loc[(pd.Timestamp("2025-01-03"), "AAA")] == pytest.approx(np.log(20.0))
    assert result.loc[(pd.Timestamp("2025-01-04"), "AAA")] == pytest.approx(np.log(30.0))
    assert result.loc[(pd.Timestamp("2025-01-04"), "BBB")] == pytest.approx(np.log(100.0))


def test_liquidity_requires_complete_positive_volume_window(
    shuffled_panel: pd.DataFrame,
) -> None:
    panel = shuffled_panel.copy()
    panel.loc[(pd.Timestamp("2025-01-02"), "AAA"), "volume"] = -1.0

    result = ShortLiquidityFactor().compute(panel)

    assert pd.isna(result.loc[(pd.Timestamp("2025-01-03"), "AAA")])
    assert pd.isna(result.loc[(pd.Timestamp("2025-01-04"), "AAA")])


def test_liquidity_does_not_read_future_volume(
    shuffled_panel: pd.DataFrame,
) -> None:
    baseline = ShortLiquidityFactor().compute(shuffled_panel)
    future_index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2025-01-05"), "AAA")],
        names=["Date", "Ticker"],
    )
    extended = pd.concat(
        [shuffled_panel, pd.DataFrame({"volume": [1e12]}, index=future_index)]
    )

    actual = ShortLiquidityFactor().compute(extended).reindex(shuffled_panel.index)

    pd.testing.assert_series_equal(actual, baseline)


def test_liquidity_does_not_mutate_input(
    shuffled_panel: pd.DataFrame,
) -> None:
    original = shuffled_panel.copy(deep=True)

    ShortLiquidityFactor().compute(shuffled_panel)

    pd.testing.assert_frame_equal(shuffled_panel, original)

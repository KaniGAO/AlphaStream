"""Tests for the raw 12-1 Momentum factor."""

import numpy as np
import pandas as pd
import pytest

from factors.momentum import MomentumFactor


class ShortMomentumFactor(MomentumFactor):
    """Use short windows to keep test data compact."""

    lookback_days = 3
    skip_days = 1


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
        {"px_last": [80.0, 10.0, 30.0, 40.0, 40.0, 20.0, 20.0, 60.0]},
        index=index,
    )


def test_momentum_is_calculated_per_ticker_and_restores_input_order(
    shuffled_panel: pd.DataFrame,
) -> None:
    result = ShortMomentumFactor().compute(shuffled_panel)

    assert result.index.equals(shuffled_panel.index)
    assert result.name == "momentum"
    assert result.loc[(pd.Timestamp("2025-01-04"), "AAA")] == pytest.approx(2.0)
    assert result.loc[(pd.Timestamp("2025-01-04"), "BBB")] == pytest.approx(2.0)


def test_first_lookback_observations_are_nan(
    shuffled_panel: pd.DataFrame,
) -> None:
    result = ShortMomentumFactor().compute(shuffled_panel)

    for ticker in ("AAA", "BBB"):
        chronological = result.xs(ticker, level="Ticker").sort_index()
        assert chronological.iloc[:3].isna().all()
        assert chronological.iloc[3:].notna().all()


@pytest.mark.parametrize("invalid_price", [0.0, -1.0, np.nan])
def test_invalid_required_price_produces_nan(
    shuffled_panel: pd.DataFrame,
    invalid_price: float,
) -> None:
    panel = shuffled_panel.copy()
    panel.loc[(pd.Timestamp("2025-01-01"), "AAA"), "px_last"] = invalid_price

    result = ShortMomentumFactor().compute(panel)

    assert pd.isna(result.loc[(pd.Timestamp("2025-01-04"), "AAA")])
    assert result.loc[(pd.Timestamp("2025-01-04"), "BBB")] == pytest.approx(2.0)


def test_momentum_does_not_mutate_input(
    shuffled_panel: pd.DataFrame,
) -> None:
    original = shuffled_panel.copy(deep=True)

    ShortMomentumFactor().compute(shuffled_panel)

    pd.testing.assert_frame_equal(shuffled_panel, original)


@pytest.mark.parametrize(
    ("lookback_days", "skip_days"),
    [(3, 3), (2, 3), (3, -1)],
)
def test_invalid_window_configuration_is_rejected(
    shuffled_panel: pd.DataFrame,
    lookback_days: int,
    skip_days: int,
) -> None:
    factor = ShortMomentumFactor()
    factor.lookback_days = lookback_days
    factor.skip_days = skip_days

    with pytest.raises(ValueError, match="Invalid configuration"):
        factor.compute(shuffled_panel)


def test_default_window_matches_constant_daily_growth() -> None:
    dates = pd.date_range("2024-01-01", periods=253, freq="D")
    index = pd.MultiIndex.from_product(
        [dates, ["AAA"]],
        names=["Date", "Ticker"],
    )
    panel = pd.DataFrame(
        {"px_last": 100.0 * np.power(1.01, np.arange(253))},
        index=index,
    )

    result = MomentumFactor().compute(panel)

    assert result.iloc[:252].isna().all()
    assert result.iloc[-1] == pytest.approx(1.01**231 - 1)

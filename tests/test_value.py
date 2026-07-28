"""Tests for the raw Value factor implementation."""

import numpy as np
import pandas as pd
import pytest

from factors.value import ValueFactor


@pytest.fixture
def value_panel() -> pd.DataFrame:
    """Return a valid panel containing representative PB values."""
    index = pd.MultiIndex.from_tuples(
        [
            (pd.Timestamp("2025-01-02"), "AAPL US Equity"),
            (pd.Timestamp("2025-01-02"), "MSFT US Equity"),
            (pd.Timestamp("2025-01-03"), "AAPL US Equity"),
            (pd.Timestamp("2025-01-03"), "MSFT US Equity"),
        ],
        names=["Date", "Ticker"],
    )
    return pd.DataFrame({"pb": [1.0, np.e, 0.5, 4.0]}, index=index)


def test_value_uses_negative_natural_log(value_panel: pd.DataFrame) -> None:
    result = ValueFactor().compute(value_panel)
    expected = (-np.log(value_panel["pb"])).rename("value")

    pd.testing.assert_series_equal(result, expected)


def test_lower_pb_has_higher_value_exposure(value_panel: pd.DataFrame) -> None:
    result = ValueFactor().compute(value_panel)

    lower_pb = (pd.Timestamp("2025-01-03"), "AAPL US Equity")
    higher_pb = (pd.Timestamp("2025-01-03"), "MSFT US Equity")
    assert result.loc[lower_pb] > result.loc[higher_pb]


def test_value_output_preserves_index_and_name(value_panel: pd.DataFrame) -> None:
    result = ValueFactor().compute(value_panel)

    assert result.index.equals(value_panel.index)
    assert result.name == "value"


@pytest.mark.parametrize("invalid_pb", [0.0, -1.0, np.nan])
def test_invalid_pb_becomes_nan(invalid_pb: float) -> None:
    index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2025-01-02"), "AAPL US Equity")],
        names=["Date", "Ticker"],
    )
    panel = pd.DataFrame({"pb": [invalid_pb]}, index=index)

    result = ValueFactor().compute(panel)

    assert pd.isna(result.iloc[0])


def test_value_does_not_mutate_input(value_panel: pd.DataFrame) -> None:
    original = value_panel.copy(deep=True)

    ValueFactor().compute(value_panel)

    pd.testing.assert_frame_equal(value_panel, original)


def test_missing_pb_column_is_rejected(value_panel: pd.DataFrame) -> None:
    panel = value_panel.rename(columns={"pb": "wrong_column"})

    with pytest.raises(ValueError, match=r"missing \['pb'\]"):
        ValueFactor().compute(panel)

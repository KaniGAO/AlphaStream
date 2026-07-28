"""Tests for the raw Size factor implementation."""

import numpy as np
import pandas as pd
import pytest

from factors.size import SizeFactor


@pytest.fixture
def size_panel() -> pd.DataFrame:
    """Return a valid panel containing representative market-cap values."""
    index = pd.MultiIndex.from_tuples(
        [
            (pd.Timestamp("2025-01-02"), "AAPL US Equity"),
            (pd.Timestamp("2025-01-02"), "MSFT US Equity"),
            (pd.Timestamp("2025-01-03"), "AAPL US Equity"),
            (pd.Timestamp("2025-01-03"), "MSFT US Equity"),
        ],
        names=["Date", "Ticker"],
    )
    return pd.DataFrame(
        {"market_cap": [1.0, np.e, 100.0, np.e**5]},
        index=index,
    )


def test_size_uses_natural_log(size_panel: pd.DataFrame) -> None:
    result = SizeFactor().compute(size_panel)
    expected = np.log(size_panel["market_cap"]).rename("size")

    pd.testing.assert_series_equal(result, expected)


def test_size_output_preserves_index_and_name(
    size_panel: pd.DataFrame,
) -> None:
    result = SizeFactor().compute(size_panel)

    assert result.index.equals(size_panel.index)
    assert result.name == "size"


@pytest.mark.parametrize(
    ("invalid_market_cap", "expected_is_nan"),
    [
        (0.0, True),
        (-1.0, True),
        (np.nan, True),
        (1.0, False),
    ],
)
def test_invalid_market_cap_handling(
    invalid_market_cap: float,
    expected_is_nan: bool,
) -> None:
    index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2025-01-02"), "AAPL US Equity")],
        names=["Date", "Ticker"],
    )
    panel = pd.DataFrame(
        {"market_cap": [invalid_market_cap]},
        index=index,
    )

    result = SizeFactor().compute(panel)

    assert bool(result.isna().iloc[0]) is expected_is_nan


def test_size_does_not_mutate_input(size_panel: pd.DataFrame) -> None:
    original = size_panel.copy(deep=True)

    SizeFactor().compute(size_panel)

    pd.testing.assert_frame_equal(size_panel, original)


def test_missing_market_cap_column_is_rejected(
    size_panel: pd.DataFrame,
) -> None:
    panel = size_panel.rename(columns={"market_cap": "wrong_column"})

    with pytest.raises(ValueError, match=r"missing \['market_cap'\]"):
        SizeFactor().compute(panel)


def test_invalid_index_contract_is_rejected(
    size_panel: pd.DataFrame,
) -> None:
    panel = size_panel.copy()
    panel.index = panel.index.set_names(["Date", "Code"])

    with pytest.raises(ValueError, match="index names"):
        SizeFactor().compute(panel)

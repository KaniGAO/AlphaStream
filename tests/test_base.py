"""Tests for the shared factor contract."""

import pandas as pd
import pytest

from factors.base import Factor


class DummyFactor(Factor):
    """Minimal valid factor used to test the base-class workflow."""

    name = "dummy"
    required_columns = ("signal",)

    def _compute(self, panel: pd.DataFrame) -> pd.Series:
        return panel["signal"].rename(self.name)


@pytest.fixture
def valid_panel() -> pd.DataFrame:
    """Return a small panel satisfying the common input contract."""
    index = pd.MultiIndex.from_product(
        [
            pd.to_datetime(["2025-01-02", "2025-01-03"]),
            ["AAPL US Equity", "MSFT US Equity"],
        ],
        names=["Date", "Ticker"],
    )
    return pd.DataFrame(
        {"signal": [1.0, 2.0, float("nan"), 4.0]},
        index=index,
    )


def test_valid_panel_computes_exposure(valid_panel: pd.DataFrame) -> None:
    result = DummyFactor().compute(valid_panel)

    assert isinstance(result, pd.Series)
    assert result.index.equals(valid_panel.index)
    assert result.name == "dummy"
    pd.testing.assert_series_equal(
        result,
        valid_panel["signal"].rename("dummy"),
    )


def test_missing_values_remain_nan(valid_panel: pd.DataFrame) -> None:
    result = DummyFactor().compute(valid_panel)

    assert result.isna().sum() == valid_panel["signal"].isna().sum()
    assert pd.isna(result.loc[(pd.Timestamp("2025-01-03"), "AAPL US Equity")])


def test_abstract_factor_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError, match="abstract"):
        Factor()


@pytest.mark.parametrize("invalid_panel", [None, [], {"signal": [1.0]}])
def test_non_dataframe_is_rejected(invalid_panel: object) -> None:
    with pytest.raises(TypeError, match="pandas DataFrame"):
        DummyFactor().compute(invalid_panel)  # type: ignore[arg-type]


def test_plain_index_is_rejected() -> None:
    panel = pd.DataFrame({"signal": [1.0]})

    with pytest.raises(ValueError, match="MultiIndex"):
        DummyFactor().compute(panel)


@pytest.mark.parametrize(
    "index_names",
    [
        ["Date", "Code"],
        ["Ticker", "Date"],
        [None, None],
    ],
)
def test_wrong_index_names_or_order_are_rejected(
    index_names: list[str | None],
) -> None:
    index = pd.MultiIndex.from_product(
        [
            pd.to_datetime(["2025-01-02"]),
            ["AAPL US Equity"],
        ],
        names=index_names,
    )
    panel = pd.DataFrame({"signal": [1.0]}, index=index)

    with pytest.raises(ValueError, match="index names"):
        DummyFactor().compute(panel)


def test_string_dates_are_rejected() -> None:
    index = pd.MultiIndex.from_tuples(
        [("2025-01-02", "AAPL US Equity")],
        names=["Date", "Ticker"],
    )
    panel = pd.DataFrame({"signal": [1.0]}, index=index)

    with pytest.raises(ValueError, match="datetime-like"):
        DummyFactor().compute(panel)


def test_duplicate_date_ticker_pair_is_rejected() -> None:
    observation = (pd.Timestamp("2025-01-02"), "AAPL US Equity")
    index = pd.MultiIndex.from_tuples(
        [observation, observation],
        names=["Date", "Ticker"],
    )
    panel = pd.DataFrame({"signal": [1.0, 2.0]}, index=index)

    with pytest.raises(ValueError, match="unique"):
        DummyFactor().compute(panel)


def test_missing_required_column_is_rejected(
    valid_panel: pd.DataFrame,
) -> None:
    panel = valid_panel.drop(columns="signal")

    with pytest.raises(ValueError, match=r"missing \['signal'\]"):
        DummyFactor().compute(panel)


def test_compute_does_not_mutate_panel(valid_panel: pd.DataFrame) -> None:
    original = valid_panel.copy(deep=True)

    DummyFactor().compute(valid_panel)

    pd.testing.assert_frame_equal(valid_panel, original)


def test_non_series_output_is_rejected(valid_panel: pd.DataFrame) -> None:
    class DataFrameFactor(DummyFactor):
        def _compute(self, panel: pd.DataFrame) -> pd.Series:
            return panel[["signal"]]  # type: ignore[return-value]

    with pytest.raises(TypeError, match="pandas Series"):
        DataFrameFactor().compute(valid_panel)


def test_output_with_different_index_is_rejected(
    valid_panel: pd.DataFrame,
) -> None:
    class ReorderedFactor(DummyFactor):
        def _compute(self, panel: pd.DataFrame) -> pd.Series:
            return panel["signal"].iloc[::-1].rename(self.name)

    with pytest.raises(ValueError, match="exactly match"):
        ReorderedFactor().compute(valid_panel)


def test_output_with_wrong_name_is_rejected(
    valid_panel: pd.DataFrame,
) -> None:
    class WrongNameFactor(DummyFactor):
        def _compute(self, panel: pd.DataFrame) -> pd.Series:
            return panel["signal"].rename("wrong_name")

    with pytest.raises(ValueError, match="exposure name"):
        WrongNameFactor().compute(valid_panel)


def test_non_numeric_output_is_rejected(valid_panel: pd.DataFrame) -> None:
    class TextFactor(DummyFactor):
        def _compute(self, panel: pd.DataFrame) -> pd.Series:
            return pd.Series(
                ["high"] * len(panel),
                index=panel.index,
                name=self.name,
            )

    with pytest.raises(TypeError, match="numeric dtype"):
        TextFactor().compute(valid_panel)

"""Tests for CSV loading and standard-panel construction."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factors.loaders import (
    STANDARD_INDEX_NAMES,
    _validate_csv_path,
    describe_csv,
    inspect_csv,
    load_raw_csv,
    standardize_long_panel,
)
from factors.size import SizeFactor


@pytest.fixture
def csv_path(tmp_path: Path) -> Path:
    """Create a representative raw CSV file."""
    path = tmp_path / "market_data.CSV"
    pd.DataFrame(
        {
            "raw_date": ["2025-01-03", "2025-01-02"],
            "raw_ticker": [" MSFT US Equity ", "AAPL US Equity"],
            "CUR_MKT_CAP": [np.nan, 100.0],
        }
    ).to_csv(path, index=False)
    return path


@pytest.fixture
def raw_panel_source() -> pd.DataFrame:
    """Create an unsorted long-form table for panel normalization."""
    return pd.DataFrame(
        {
            "raw_date": ["2025-01-03", "2025-01-02"],
            "raw_ticker": [" MSFT US Equity ", "AAPL US Equity"],
            "CUR_MKT_CAP": [np.nan, 100.0],
        }
    )


def test_validate_csv_path_accepts_string_and_path(csv_path: Path) -> None:
    assert _validate_csv_path(csv_path) == csv_path.resolve()
    assert _validate_csv_path(str(csv_path)) == csv_path.resolve()


def test_validate_csv_path_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        _validate_csv_path(tmp_path / "missing.csv")


def test_validate_csv_path_rejects_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="regular file"):
        _validate_csv_path(tmp_path)


def test_validate_csv_path_rejects_non_csv_file(tmp_path: Path) -> None:
    path = tmp_path / "market_data.txt"
    path.write_text("value\n1\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"\.csv suffix"):
        _validate_csv_path(path)


def test_inspect_csv_reads_only_requested_rows(csv_path: Path) -> None:
    preview = inspect_csv(csv_path, nrows=1)

    assert preview.shape == (1, 3)
    assert preview.columns.tolist() == [
        "raw_date",
        "raw_ticker",
        "CUR_MKT_CAP",
    ]


@pytest.mark.parametrize("invalid_nrows", [True, False, 0, -1, 1.5, "2"])
def test_inspect_csv_rejects_invalid_nrows(
    csv_path: Path,
    invalid_nrows: object,
) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        inspect_csv(csv_path, nrows=invalid_nrows)  # type: ignore[arg-type]


def test_inspect_csv_forwards_parser_options(tmp_path: Path) -> None:
    path = tmp_path / "semicolon.csv"
    path.write_text("a;b\n1;2\n", encoding="utf-8")

    preview = inspect_csv(path, sep=";")

    assert preview.columns.tolist() == ["a", "b"]
    assert preview.iloc[0].tolist() == [1, 2]


def test_describe_csv_summarizes_columns_and_nulls() -> None:
    preview = pd.DataFrame(
        {
            "number": [1.0, np.nan],
            "label": ["A", "B"],
        }
    )

    summary = describe_csv(preview)

    assert summary["column"].tolist() == ["number", "label"]
    assert summary["inferred_dtype"].tolist() == ["float64", "str"]
    assert summary["non_null_preview_rows"].tolist() == [1, 2]
    assert summary["null_preview_rows"].tolist() == [1, 0]


def test_describe_csv_rejects_non_dataframe() -> None:
    with pytest.raises(TypeError, match="DataFrame"):
        describe_csv(["not", "a", "dataframe"])  # type: ignore[arg-type]


def test_load_raw_csv_preserves_rows_columns_and_nan(
    csv_path: Path,
) -> None:
    raw = load_raw_csv(csv_path)

    assert raw.shape == (2, 3)
    assert raw.columns.tolist() == [
        "raw_date",
        "raw_ticker",
        "CUR_MKT_CAP",
    ]
    assert pd.isna(raw.loc[0, "CUR_MKT_CAP"])
    assert raw.loc[1, "CUR_MKT_CAP"] == 100.0


def test_standardize_long_panel_builds_expected_panel(
    raw_panel_source: pd.DataFrame,
) -> None:
    panel = standardize_long_panel(
        raw_panel_source,
        date_column="raw_date",
        ticker_column="raw_ticker",
        column_mapping={"CUR_MKT_CAP": "market_cap"},
    )

    assert panel.index.names == STANDARD_INDEX_NAMES
    assert panel.index.is_monotonic_increasing
    assert not panel.index.has_duplicates
    assert panel.columns.tolist() == ["market_cap"]
    assert panel.index[0] == (
        pd.Timestamp("2025-01-02"),
        "AAPL US Equity",
    )
    assert panel.loc[
        (pd.Timestamp("2025-01-02"), "AAPL US Equity"),
        "market_cap",
    ] == 100.0
    assert pd.isna(
        panel.loc[
            (pd.Timestamp("2025-01-03"), "MSFT US Equity"),
            "market_cap",
        ]
    )


def test_standardize_long_panel_does_not_mutate_input(
    raw_panel_source: pd.DataFrame,
) -> None:
    original = raw_panel_source.copy(deep=True)

    standardize_long_panel(
        raw_panel_source,
        date_column="raw_date",
        ticker_column="raw_ticker",
        column_mapping={"CUR_MKT_CAP": "market_cap"},
    )

    pd.testing.assert_frame_equal(raw_panel_source, original)


def test_standardized_panel_is_accepted_by_size_factor(
    raw_panel_source: pd.DataFrame,
) -> None:
    panel = standardize_long_panel(
        raw_panel_source,
        date_column="raw_date",
        ticker_column="raw_ticker",
        column_mapping={"CUR_MKT_CAP": "market_cap"},
    )

    exposure = SizeFactor().compute(panel)

    assert exposure.name == "size"
    assert exposure.index.equals(panel.index)


@pytest.mark.parametrize(
    ("date_column", "ticker_column"),
    [
        ("", "ticker"),
        ("date", ""),
        ("same", "same"),
        ("missing_date", "ticker"),
        ("date", "missing_ticker"),
    ],
)
def test_standardize_rejects_invalid_identifier_columns(
    date_column: str,
    ticker_column: str,
) -> None:
    raw = pd.DataFrame(
        {
            "date": ["2025-01-02"],
            "ticker": ["AAPL US Equity"],
            "same": ["value"],
        }
    )

    with pytest.raises(ValueError):
        standardize_long_panel(
            raw,
            date_column=date_column,
            ticker_column=ticker_column,
        )


def test_standardize_rejects_invalid_mapping_type(
    raw_panel_source: pd.DataFrame,
) -> None:
    with pytest.raises(TypeError, match="dict or None"):
        standardize_long_panel(
            raw_panel_source,
            date_column="raw_date",
            ticker_column="raw_ticker",
            column_mapping=[("CUR_MKT_CAP", "market_cap")],  # type: ignore[arg-type]
        )


def test_standardize_rejects_missing_mapping_source(
    raw_panel_source: pd.DataFrame,
) -> None:
    with pytest.raises(ValueError, match="not found"):
        standardize_long_panel(
            raw_panel_source,
            date_column="raw_date",
            ticker_column="raw_ticker",
            column_mapping={"MISSING": "market_cap"},
        )


def test_standardize_rejects_identifier_mapping(
    raw_panel_source: pd.DataFrame,
) -> None:
    with pytest.raises(ValueError, match="identifier columns"):
        standardize_long_panel(
            raw_panel_source,
            date_column="raw_date",
            ticker_column="raw_ticker",
            column_mapping={"raw_date": "another_date"},
        )


def test_standardize_rejects_output_column_collision() -> None:
    raw = pd.DataFrame(
        {
            "date": ["2025-01-02"],
            "ticker": ["AAPL US Equity"],
            "cap": [100.0],
            "market_cap": [200.0],
        }
    )

    with pytest.raises(ValueError, match="duplicate"):
        standardize_long_panel(
            raw,
            date_column="date",
            ticker_column="ticker",
            column_mapping={"cap": "market_cap"},
        )


@pytest.mark.parametrize(
    "raw",
    [
        pd.DataFrame(
            {
                "date": [None],
                "ticker": ["AAPL US Equity"],
            }
        ),
        pd.DataFrame(
            {
                "date": ["2025-01-02"],
                "ticker": [None],
            }
        ),
        pd.DataFrame(
            {
                "date": ["2025-01-02"],
                "ticker": ["   "],
            }
        ),
    ],
)
def test_standardize_rejects_missing_or_empty_identifiers(
    raw: pd.DataFrame,
) -> None:
    with pytest.raises(ValueError, match="missing or empty"):
        standardize_long_panel(
            raw,
            date_column="date",
            ticker_column="ticker",
        )


def test_standardize_rejects_non_string_ticker() -> None:
    raw = pd.DataFrame(
        {
            "date": ["2025-01-02"],
            "ticker": [123],
        }
    )

    with pytest.raises(TypeError, match="Ticker values"):
        standardize_long_panel(
            raw,
            date_column="date",
            ticker_column="ticker",
        )


def test_standardize_rejects_invalid_date() -> None:
    raw = pd.DataFrame(
        {
            "date": ["not-a-date"],
            "ticker": ["AAPL US Equity"],
        }
    )

    with pytest.raises(ValueError):
        standardize_long_panel(
            raw,
            date_column="date",
            ticker_column="ticker",
        )


def test_standardize_rejects_duplicate_date_ticker_pairs() -> None:
    raw = pd.DataFrame(
        {
            "date": ["2025-01-02", "2025-01-02"],
            "ticker": ["AAPL US Equity", "AAPL US Equity"],
        }
    )

    with pytest.raises(ValueError, match="unique"):
        standardize_long_panel(
            raw,
            date_column="date",
            ticker_column="ticker",
        )

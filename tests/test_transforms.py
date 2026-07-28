"""Tests for cross-sectional factor-exposure transformations."""

import numpy as np
import pandas as pd
import pytest

from factors.transforms import (
    _validate_exposures,
    neutralize_cross_sectional,
    orthogonalize_cross_sectional,
    winsorize_cross_sectional,
    zscore_cross_sectional,
)


@pytest.fixture
def exposures() -> pd.DataFrame:
    index = pd.MultiIndex.from_tuples(
        [
            (pd.Timestamp("2025-01-02"), "AAA"),
            (pd.Timestamp("2025-01-02"), "BBB"),
            (pd.Timestamp("2025-01-02"), "CCC"),
            (pd.Timestamp("2025-01-03"), "AAA"),
            (pd.Timestamp("2025-01-03"), "BBB"),
            (pd.Timestamp("2025-01-03"), "CCC"),
        ],
        names=["Date", "Ticker"],
    )
    return pd.DataFrame(
        {
            "size": [1.0, 2.0, 100.0, 10.0, 20.0, 30.0],
            "value": [3.0, 4.0, 5.0, 8.0, 9.0, 10.0],
        },
        index=index,
    )


def test_winsorize_is_daily_and_does_not_mutate_input(exposures: pd.DataFrame) -> None:
    original = exposures.copy(deep=True)

    actual = winsorize_cross_sectional(
        exposures, lower_quantile=0.0, upper_quantile=0.5
    )

    # Daily medians are different: this detects accidental cross-date clipping.
    assert actual.loc[(pd.Timestamp("2025-01-02"), "CCC"), "size"] == 2.0
    assert actual.loc[(pd.Timestamp("2025-01-03"), "CCC"), "size"] == 20.0
    assert actual.index.equals(exposures.index)
    assert actual.columns.equals(exposures.columns)
    pd.testing.assert_frame_equal(exposures, original)


def test_winsorize_preserves_nan(exposures: pd.DataFrame) -> None:
    exposures.loc[(pd.Timestamp("2025-01-02"), "BBB"), "value"] = float("nan")

    actual = winsorize_cross_sectional(exposures)

    assert pd.isna(actual.loc[(pd.Timestamp("2025-01-02"), "BBB"), "value"])


@pytest.mark.parametrize(
    ("lower_quantile", "upper_quantile", "error_type"),
    [
        (False, 0.99, TypeError),
        (0.01, True, TypeError),
        (0.99, 0.01, ValueError),
        (-0.01, 0.99, ValueError),
        (0.01, 1.01, ValueError),
    ],
)
def test_winsorize_rejects_invalid_quantiles(
    exposures: pd.DataFrame,
    lower_quantile: object,
    upper_quantile: object,
    error_type: type[Exception],
) -> None:
    with pytest.raises(error_type):
        winsorize_cross_sectional(  # type: ignore[arg-type]
            exposures,
            lower_quantile=lower_quantile,
            upper_quantile=upper_quantile,
        )


def test_zscore_has_daily_zero_mean_and_unit_population_std(
    exposures: pd.DataFrame,
) -> None:
    actual = zscore_cross_sectional(exposures, ddof=0)

    daily_means = actual.groupby(level="Date").mean()
    daily_stds = actual.groupby(level="Date").std(ddof=0)
    assert daily_means.abs().max().max() < 1e-12
    assert daily_stds.sub(1.0).abs().max().max() < 1e-12


def test_zscore_preserves_nan_and_masks_zero_dispersion() -> None:
    index = pd.MultiIndex.from_tuples(
        [
            (pd.Timestamp("2025-01-02"), "AAA"),
            (pd.Timestamp("2025-01-02"), "BBB"),
            (pd.Timestamp("2025-01-02"), "CCC"),
        ],
        names=["Date", "Ticker"],
    )
    source = pd.DataFrame(
        {"constant": [5.0, 5.0, 5.0], "sparse": [1.0, float("nan"), 3.0]},
        index=index,
    )

    actual = zscore_cross_sectional(source)

    assert actual["constant"].isna().all()
    assert pd.isna(actual.loc[(pd.Timestamp("2025-01-02"), "BBB"), "sparse"])
    assert actual.loc[(pd.Timestamp("2025-01-02"), "AAA"), "sparse"] == -1.0
    assert actual.loc[(pd.Timestamp("2025-01-02"), "CCC"), "sparse"] == 1.0


@pytest.mark.parametrize("ddof", [-1, 0.5, True])
def test_zscore_rejects_invalid_ddof(exposures: pd.DataFrame, ddof: object) -> None:
    with pytest.raises(ValueError):
        zscore_cross_sectional(exposures, ddof=ddof)  # type: ignore[arg-type]


def test_validate_exposures_rejects_duplicate_index(exposures: pd.DataFrame) -> None:
    duplicated = pd.concat([exposures, exposures.iloc[[0]]])

    with pytest.raises(ValueError, match="duplicate"):
        _validate_exposures(duplicated)


def test_validate_exposures_rejects_non_numeric_factor(exposures: pd.DataFrame) -> None:
    exposures["industry"] = "Technology"

    with pytest.raises(TypeError, match="Non-numeric"):
        _validate_exposures(exposures)


def test_neutralize_removes_daily_industry_and_size_effects() -> None:
    index = pd.MultiIndex.from_product(
        [[pd.Timestamp("2025-01-02")], list("ABCDEF")],
        names=["Date", "Ticker"],
    )
    market_cap = np.exp(np.arange(1.0, 7.0))
    industries = ["Tech", "Tech", "Tech", "Bank", "Bank", "Bank"]
    industry_effect = np.array([2.0 if value == "Tech" else -2.0 for value in industries])
    source = pd.DataFrame(
        {"factor": 5.0 + 3.0 * np.log(market_cap) + industry_effect},
        index=index,
    )
    panel = pd.DataFrame(
        {"market_cap": market_cap, "gics_sector": industries},
        index=index,
    )

    actual = neutralize_cross_sectional(source, panel)

    assert actual["factor"].abs().max() < 1e-12
    assert actual.index.equals(source.index)
    assert actual.columns.equals(source.columns)


def test_neutralize_preserves_nan_when_regressors_are_invalid() -> None:
    index = pd.MultiIndex.from_product(
        [[pd.Timestamp("2025-01-02")], list("ABCDE")],
        names=["Date", "Ticker"],
    )
    source = pd.DataFrame({"factor": np.arange(5.0)}, index=index)
    panel = pd.DataFrame(
        {
            "market_cap": [10.0, 20.0, 0.0, 40.0, 50.0],
            "gics_sector": ["Tech", "Tech", "Bank", None, "Bank"],
        },
        index=index,
    )

    actual = neutralize_cross_sectional(source, panel)

    assert pd.isna(actual.loc[(pd.Timestamp("2025-01-02"), "C"), "factor"])
    assert pd.isna(actual.loc[(pd.Timestamp("2025-01-02"), "D"), "factor"])


def test_neutralize_handles_multiple_dates() -> None:
    dates = [pd.Timestamp("2025-01-02"), pd.Timestamp("2025-01-03")]
    index = pd.MultiIndex.from_product(
        [dates, list("ABCDEF")],
        names=["Date", "Ticker"],
    )
    log_cap = np.tile(np.arange(1.0, 7.0), 2)
    industries = np.tile(["Tech", "Tech", "Tech", "Bank", "Bank", "Bank"], 2)
    source = pd.DataFrame(
        {"factor": 2.0 + 3.0 * log_cap + (industries == "Tech") * 4.0},
        index=index,
    )
    panel = pd.DataFrame(
        {"market_cap": np.exp(log_cap), "gics_sector": industries},
        index=index,
    )

    actual = neutralize_cross_sectional(source, panel)

    assert actual["factor"].abs().max() < 1e-12
    assert actual.index.equals(index)


def test_orthogonalize_only_changes_pairs_above_threshold() -> None:
    index = pd.MultiIndex.from_product(
        [[pd.Timestamp("2025-01-02")], list("ABCDEFGH")],
        names=["Date", "Ticker"],
    )
    first = np.arange(8.0)
    correlated = 2.0 * first + np.array([0.2, -0.1, 0.1, -0.2, 0.1, 0.0, -0.1, 0.2])
    independent = np.array([1.0, -1.0, 1.0, -1.0, 1.0, -1.0, 1.0, -1.0])
    source = pd.DataFrame(
        {
            "first": first,
            "correlated": correlated,
            "independent": independent,
        },
        index=index,
    )

    actual = orthogonalize_cross_sectional(
        source,
        correlation_threshold=0.70,
    )

    pd.testing.assert_series_equal(actual["first"], source["first"])
    pd.testing.assert_series_equal(actual["independent"], source["independent"])
    assert abs(actual["correlated"].corr(actual["first"])) < 1e-12

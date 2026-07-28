"""Tests for factor performance validation and admission decisions."""

import json

import numpy as np
import pandas as pd
import pytest

from factors.validate_factors import (
    FactorValidationConfig,
    newey_west_t_stat,
    validate_factors,
    write_validation_report,
)


@pytest.fixture
def validation_data() -> tuple[pd.DataFrame, pd.Series]:
    rng = np.random.default_rng(42)
    dates = pd.date_range("2024-01-01", periods=80, freq="B")
    tickers = [f"S{i:02d}" for i in range(25)]
    index = pd.MultiIndex.from_product(
        [dates, tickers],
        names=["Date", "Ticker"],
    )
    signal = rng.normal(size=len(index))
    noise = rng.normal(scale=0.7, size=len(index))
    exposures = pd.DataFrame(
        {
            "predictive": signal,
            "noise": rng.normal(size=len(index)),
        },
        index=index,
    )
    forward_returns = pd.Series(
        signal + noise,
        index=index,
        name="forward_return_21d",
    )
    return exposures, forward_returns


def test_validate_factors_computes_diagnostics_and_admissions(
    validation_data: tuple[pd.DataFrame, pd.Series],
) -> None:
    exposures, forward_returns = validation_data
    config = FactorValidationConfig(
        min_cross_section=20,
        min_dates=60,
        accepted_rank_ic=0.20,
        accepted_t_stat=2.0,
        candidate_rank_ic=0.05,
    )

    result = validate_factors(exposures, forward_returns, config)

    assert result.admissions["predictive"] == "accepted"
    assert result.admissions["noise"] == "rejected"
    assert result.metrics.loc["predictive", "mean_rank_ic"] > 0.5
    assert result.metrics.loc["predictive", "coverage"] == 1.0
    assert result.daily_ic.columns.names == ["Factor", "Metric"]
    assert result.quantile_returns["spread"].mean() > 0
    assert result.factor_correlations.shape == (2, 2)


def test_validation_preserves_low_coverage_in_decision(
    validation_data: tuple[pd.DataFrame, pd.Series],
) -> None:
    exposures, forward_returns = validation_data
    exposures.loc[exposures.index[:1500], "predictive"] = np.nan
    config = FactorValidationConfig(
        min_cross_section=5,
        min_dates=5,
        accepted_rank_ic=0.01,
        accepted_t_stat=0.0,
        accepted_coverage=0.70,
        candidate_rank_ic=0.01,
        candidate_coverage=0.50,
    )

    result = validate_factors(exposures, forward_returns, config)

    assert result.metrics.loc["predictive", "coverage"] == pytest.approx(0.25)
    assert result.admissions["predictive"] == "rejected"


def test_validate_factors_requires_exact_label_alignment(
    validation_data: tuple[pd.DataFrame, pd.Series],
) -> None:
    exposures, forward_returns = validation_data

    with pytest.raises(ValueError, match="exactly equal"):
        validate_factors(exposures, forward_returns.iloc[::-1])


def test_newey_west_t_stat_detects_positive_mean() -> None:
    values = pd.Series([0.01, 0.03, 0.02, 0.04, 0.01, 0.02, 0.03])

    assert newey_west_t_stat(values, lags=2) > 0


def test_write_validation_report_round_trip(
    validation_data: tuple[pd.DataFrame, pd.Series],
    tmp_path,
) -> None:
    exposures, forward_returns = validation_data
    config = FactorValidationConfig(
        min_cross_section=20,
        min_dates=20,
    )
    result = validate_factors(exposures, forward_returns, config)

    paths = write_validation_report(result, tmp_path)

    assert all(path.exists() for path in paths.values())
    summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
    assert summary["admissions"] == result.admissions
    pd.testing.assert_frame_equal(
        pd.read_parquet(paths["metrics"]),
        result.metrics,
    )

    with pytest.raises(FileExistsError):
        write_validation_report(result, tmp_path)

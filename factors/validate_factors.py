"""Out-of-sample diagnostics and admission rules for factor exposures.

This module consumes the finalized exposure matrix produced by ``pipeline.py``
and a separately constructed forward-return label. Forward returns are used
only for evaluation and must never flow back into factor construction.

Validation flow
---------------
1. Validate the exposure and return-label contracts.
2. Calculate daily Pearson IC and Spearman Rank IC.
3. Summarize Mean IC, Mean Rank IC, annualized ICIR, Newey-West t-statistics,
   and factor coverage.
4. Average daily cross-sectional factor-correlation matrices.
5. Calculate quantile-portfolio returns and the top-minus-bottom spread.
6. Classify every factor as accepted, candidate, or rejected.
7. Optionally persist detailed Parquet tables and a JSON summary.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

import numpy as np
import pandas as pd
from pandas.api.types import is_datetime64_any_dtype, is_numeric_dtype


@dataclass(frozen=True)
class FactorValidationConfig:
    """Configuration and admission thresholds for factor validation.

    Parameters
    ----------
    forward_horizon:
        Number of trading days represented by ``forward_returns``. This value
        is recorded as validation provenance; callers remain responsible for
        constructing the label without contaminating factor exposures.
    quantiles:
        Number of equal-count portfolios used by the quantile-return test.
        Five produces quintiles q1 through q5.
    newey_west_lags:
        Maximum autocovariance lag in the Bartlett-kernel Newey-West estimate.
        This corrects the Rank IC mean t-statistic for serial correlation.
    min_cross_section:
        Minimum number of securities with both exposure and forward return
        required to calculate a date/factor IC or quantile return.
    min_dates:
        Minimum number of valid daily Rank IC observations required before a
        factor can be accepted or marked as a candidate.
    annualization_periods:
        Number of validation observations per year used in
        ``ICIR = mean_rank_ic / std_rank_ic * sqrt(annualization_periods)``.
    accepted_rank_ic, accepted_t_stat, accepted_coverage:
        Absolute Mean Rank IC, absolute Newey-West t-stat, and coverage
        thresholds that must all pass for ``accepted`` status.
    candidate_rank_ic, candidate_coverage:
        Less stringent thresholds for ``candidate`` status. A factor that
        passes neither accepted nor candidate rules is ``rejected``.

    Notes
    -----
    Correlation and t-stat thresholds are evaluated in absolute value, so a
    stable negative factor can pass and its economic direction can be handled
    separately. Coverage thresholds must be between zero and one.
    """

    forward_horizon: int = 21
    quantiles: int = 5
    newey_west_lags: int = 5
    min_cross_section: int = 20
    min_dates: int = 60
    annualization_periods: int = 252
    accepted_rank_ic: float = 0.03
    accepted_t_stat: float = 2.0
    accepted_coverage: float = 0.70
    candidate_rank_ic: float = 0.01
    candidate_coverage: float = 0.50

    def __post_init__(self) -> None:
        """Validate all configuration values immediately after construction.

        Integer window/count fields reject booleans and values below their
        permitted minimums. Admission thresholds must be finite and
        non-negative, while coverage thresholds may not exceed one.
        """
        integer_fields = {
            "forward_horizon": self.forward_horizon,
            "quantiles": self.quantiles,
            "newey_west_lags": self.newey_west_lags,
            "min_cross_section": self.min_cross_section,
            "min_dates": self.min_dates,
            "annualization_periods": self.annualization_periods,
        }
        for name, value in integer_fields.items():
            minimum = 0 if name == "newey_west_lags" else 1
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < minimum
            ):
                raise ValueError(
                    f"{name} must be an integer >= {minimum}, got {value!r}."
                )
        if self.quantiles < 2:
            raise ValueError("quantiles must be at least 2.")

        threshold_fields = {
            "accepted_rank_ic": self.accepted_rank_ic,
            "accepted_t_stat": self.accepted_t_stat,
            "accepted_coverage": self.accepted_coverage,
            "candidate_rank_ic": self.candidate_rank_ic,
            "candidate_coverage": self.candidate_coverage,
        }
        for name, value in threshold_fields.items():
            if isinstance(value, bool) or not np.isfinite(value) or value < 0:
                raise ValueError(
                    f"{name} must be a finite non-negative number."
                )
        for name in ("accepted_coverage", "candidate_coverage"):
            if getattr(self, name) > 1:
                raise ValueError(f"{name} must not exceed 1.")


@dataclass(frozen=True)
class FactorValidationResult:
    """All diagnostics produced by one factor-validation run.

    Attributes
    ----------
    metrics:
        One row per factor containing Mean IC, Mean Rank IC, Rank IC standard
        deviation, annualized ICIR, Newey-West t-stat, coverage, valid-date
        count, and admission status.
    daily_ic:
        Date-indexed table with two columns per factor: ``ic`` and
        ``rank_ic``.
    quantile_returns:
        Date/Factor-indexed mean forward returns for q1 through qN plus the
        top-minus-bottom ``spread``.
    factor_correlations:
        Time average of daily cross-sectional factor-correlation matrices.
    admissions:
        Direct mapping from factor name to accepted/candidate/rejected.
    config:
        Exact configuration used to produce the result.
    """

    metrics: pd.DataFrame
    daily_ic: pd.DataFrame
    quantile_returns: pd.DataFrame
    factor_correlations: pd.DataFrame
    admissions: dict[str, str]
    config: FactorValidationConfig


def _validate_inputs(
    exposures: pd.DataFrame,
    forward_returns: pd.Series,
) -> None:
    """Validate exposure, index, alignment, and numeric-dtype contracts.

    ``exposures`` must be a non-empty numeric DataFrame with a unique
    two-level MultiIndex named exactly ``["Date", "Ticker"]`` and a
    datetime-like Date level. ``forward_returns`` must be a numeric Series
    whose index equals the exposure index in both values and order.

    Exact alignment is deliberate: silently reindexing labels could associate
    a security's exposure with the wrong future return. Missing numeric values
    are allowed and are removed pairwise by downstream statistics.
    """
    if not isinstance(exposures, pd.DataFrame):
        raise TypeError("exposures must be a pandas DataFrame.")
    if not isinstance(forward_returns, pd.Series):
        raise TypeError("forward_returns must be a pandas Series.")
    if not isinstance(exposures.index, pd.MultiIndex):
        raise ValueError("exposures must use a MultiIndex.")
    if exposures.index.nlevels != 2:
        raise ValueError("exposures index must have two levels.")
    if list(exposures.index.names) != ["Date", "Ticker"]:
        raise ValueError(
            "exposures index names must be exactly ['Date', 'Ticker']."
        )
    if exposures.index.has_duplicates:
        raise ValueError("exposures index must be unique.")
    if not is_datetime64_any_dtype(
        exposures.index.get_level_values("Date").dtype
    ):
        raise TypeError("the Date index level must be datetime-like.")
    if exposures.empty or exposures.columns.empty:
        raise ValueError("exposures must contain rows and factor columns.")
    non_numeric = [
        column
        for column in exposures.columns
        if not is_numeric_dtype(exposures[column])
    ]
    if non_numeric:
        raise TypeError(f"factor columns must be numeric: {non_numeric}")
    if not exposures.index.equals(forward_returns.index):
        raise ValueError(
            "forward_returns index must exactly equal exposures index."
        )
    if not is_numeric_dtype(forward_returns):
        raise TypeError("forward_returns must have a numeric dtype.")


def _daily_information_coefficients(
    exposures: pd.DataFrame,
    forward_returns: pd.Series,
    *,
    min_cross_section: int,
) -> pd.DataFrame:
    """Calculate daily Pearson IC and Spearman Rank IC for every factor.

    For each Date and factor, rows missing either exposure or forward return
    are removed. The function requires at least ``min_cross_section`` paired
    observations and variation in both variables.

    Pearson IC measures linear cross-sectional association:

    ``corr(exposure[t, :, factor], forward_return[t, :])``

    Spearman Rank IC applies Pearson correlation to the two rank vectors and
    therefore measures monotonic rather than strictly linear association.
    Dates that lack sufficient data or variation remain NaN.

    Returns
    -------
    pandas.DataFrame
        Date-indexed table with MultiIndex columns ``(Factor, Metric)``, where
        Metric is ``ic`` or ``rank_ic``.
    """
    dates = exposures.index.get_level_values("Date").unique()
    columns = pd.MultiIndex.from_product(
        [exposures.columns, ["ic", "rank_ic"]],
        names=["Factor", "Metric"],
    )
    result = pd.DataFrame(np.nan, index=dates, columns=columns, dtype=float)
    result.index.name = "Date"

    for date in dates:
        daily_x = exposures.xs(date, level="Date")
        daily_returns = forward_returns.xs(date, level="Date")
        for factor in exposures.columns:
            paired = pd.concat(
                [daily_x[factor], daily_returns.rename("forward_return")],
                axis=1,
            ).dropna()
            if len(paired) < min_cross_section:
                continue
            if (
                paired[factor].nunique() < 2
                or paired["forward_return"].nunique() < 2
            ):
                continue
            result.loc[date, (factor, "ic")] = paired[factor].corr(
                paired["forward_return"],
                method="pearson",
            )
            result.loc[date, (factor, "rank_ic")] = paired[factor].corr(
                paired["forward_return"],
                method="spearman",
            )

    return result


def newey_west_t_stat(values: pd.Series, *, lags: int) -> float:
    """Return the Bartlett-kernel Newey-West t-statistic of a sample mean.

    Missing observations are discarded. The long-run variance combines the
    sample variance with weighted autocovariances through ``lags``:

    ``LRV = gamma_0 + 2 * sum((1-lag/(L+1)) * gamma_lag)``.

    The statistic is ``mean(values) / sqrt(LRV / n)``. This is used on the
    daily Rank IC series because overlapping forward-return horizons commonly
    create serial correlation. Fewer than two observations, non-finite
    variance, or non-positive long-run variance returns NaN.
    """
    clean = values.dropna().to_numpy(dtype=float)
    count = len(clean)
    if count < 2:
        return float("nan")

    residuals = clean - clean.mean()
    max_lag = min(lags, count - 1)
    long_run_variance = float(residuals @ residuals / count)
    for lag in range(1, max_lag + 1):
        weight = 1.0 - lag / (max_lag + 1.0)
        autocovariance = float(
            residuals[lag:] @ residuals[:-lag] / count
        )
        long_run_variance += 2.0 * weight * autocovariance

    if not np.isfinite(long_run_variance) or long_run_variance <= 0:
        return float("nan")
    standard_error = np.sqrt(long_run_variance / count)
    return float(clean.mean() / standard_error)


def _factor_correlations(exposures: pd.DataFrame) -> pd.DataFrame:
    """Return the time average of daily factor-correlation matrices.

    A cross-sectional correlation matrix is calculated independently for each
    Date, preventing securities from different dates from being pooled.
    Corresponding matrix cells are then averaged across dates while ignoring
    unavailable correlations. This diagnostic identifies redundant or highly
    collinear factors after the exposure pipeline's transformations.
    """
    daily_correlations = [
        daily.corr()
        for _, daily in exposures.groupby(level="Date", sort=False)
    ]
    stacked = np.stack(
        [matrix.to_numpy(dtype=float) for matrix in daily_correlations],
        axis=0,
    )
    valid_counts = np.sum(~np.isnan(stacked), axis=0)
    totals = np.nansum(stacked, axis=0)
    average = np.divide(
        totals,
        valid_counts,
        out=np.full_like(totals, np.nan),
        where=valid_counts > 0,
    )
    return pd.DataFrame(
        average,
        index=exposures.columns.copy(),
        columns=exposures.columns.copy(),
    )


def _quantile_returns(
    exposures: pd.DataFrame,
    forward_returns: pd.Series,
    config: FactorValidationConfig,
) -> pd.DataFrame:
    """Calculate daily quantile returns and the top-minus-bottom spread.

    Within each Date and factor, securities with paired exposure and forward
    return are ranked and divided into ``config.quantiles`` near-equal groups.
    Ranking with ``method="first"`` makes tied exposures deterministic before
    ``qcut`` assigns portfolios.

    ``q1`` contains the lowest exposures and ``qN`` the highest. ``spread`` is
    defined as ``qN - q1``. Dates with fewer than both ``min_cross_section``
    observations and the requested number of quantiles are skipped.

    Returns
    -------
    pandas.DataFrame
        MultiIndex ``["Date", "Factor"]`` with q1...qN and spread columns.
    """
    records: list[dict[str, object]] = []
    required_count = max(config.min_cross_section, config.quantiles)

    for date, daily_x in exposures.groupby(level="Date", sort=False):
        daily_x = daily_x.droplevel("Date")
        daily_returns = forward_returns.xs(date, level="Date")
        for factor in exposures.columns:
            paired = pd.concat(
                [daily_x[factor], daily_returns.rename("forward_return")],
                axis=1,
            ).dropna()
            if len(paired) < required_count or paired[factor].nunique() < 2:
                continue

            ranks = paired[factor].rank(method="first")
            buckets = pd.qcut(
                ranks,
                q=config.quantiles,
                labels=False,
            )
            means = paired["forward_return"].groupby(buckets).mean()
            record: dict[str, object] = {
                "Date": date,
                "Factor": factor,
            }
            for bucket in range(config.quantiles):
                record[f"q{bucket + 1}"] = float(means.get(bucket, np.nan))
            record["spread"] = (
                record[f"q{config.quantiles}"] - record["q1"]
            )
            records.append(record)

    columns = [
        *(f"q{bucket}" for bucket in range(1, config.quantiles + 1)),
        "spread",
    ]
    if not records:
        empty_index = pd.MultiIndex.from_arrays(
            [[], []],
            names=["Date", "Factor"],
        )
        return pd.DataFrame(index=empty_index, columns=columns, dtype=float)

    return (
        pd.DataFrame.from_records(records)
        .set_index(["Date", "Factor"])
        .sort_index()[columns]
    )


def _classify_factor(
    *,
    mean_rank_ic: float,
    newey_west_t: float,
    coverage: float,
    valid_dates: int,
    config: FactorValidationConfig,
) -> str:
    """Apply deterministic accepted/candidate/rejected admission rules.

    ``accepted`` requires enough valid dates and simultaneous passage of the
    absolute Mean Rank IC, absolute Newey-West t-stat, and coverage thresholds.
    ``candidate`` requires enough valid dates plus its Rank IC and coverage
    thresholds. Every other factor is ``rejected``.
    """
    if (
        valid_dates >= config.min_dates
        and abs(mean_rank_ic) >= config.accepted_rank_ic
        and abs(newey_west_t) >= config.accepted_t_stat
        and coverage >= config.accepted_coverage
    ):
        return "accepted"
    if (
        valid_dates >= config.min_dates
        and abs(mean_rank_ic) >= config.candidate_rank_ic
        and coverage >= config.candidate_coverage
    ):
        return "candidate"
    return "rejected"


def validate_factors(
    exposures: pd.DataFrame,
    forward_returns: pd.Series,
    config: FactorValidationConfig | None = None,
) -> FactorValidationResult:
    """Calculate all diagnostics and factor-admission decisions.

    Parameters
    ----------
    exposures:
        Final point-in-time exposure matrix X with Date/Ticker MultiIndex and
        one numeric column per factor.
    forward_returns:
        Future-return label aligned exactly to X. It is evaluation data only.
    config:
        Validation windows, portfolio count, minimum sample sizes, annualizing
        frequency, and admission thresholds. Defaults are used when omitted.

    Calculated metrics
    ------------------
    ``mean_ic`` and ``mean_rank_ic`` are arithmetic means of valid daily ICs.
    ``rank_ic_std`` uses sample standard deviation with ``ddof=1``.
    Annualized ICIR is:

    ``mean_rank_ic / rank_ic_std * sqrt(annualization_periods)``.

    Coverage is the count of rows having both the factor exposure and an
    available forward return divided by the count of available return labels.
    Newey-West significance is calculated from the daily Rank IC series.

    Returns
    -------
    FactorValidationResult
        Metrics, daily IC history, quantile returns, averaged factor
        correlations, admission decisions, and the applied configuration.
    """
    config = config or FactorValidationConfig()
    if not isinstance(config, FactorValidationConfig):
        raise TypeError("config must be FactorValidationConfig.")
    _validate_inputs(exposures, forward_returns)

    validation_exposures = exposures.copy(deep=False)
    validation_exposures.attrs = {}
    validation_returns = forward_returns.copy(deep=False)
    validation_returns.attrs = {}

    daily_ic = _daily_information_coefficients(
        validation_exposures,
        validation_returns,
        min_cross_section=config.min_cross_section,
    )
    available_returns = validation_returns.notna()
    metric_records: list[dict[str, object]] = []
    admissions: dict[str, str] = {}

    for factor in validation_exposures.columns:
        ic = daily_ic[(factor, "ic")]
        rank_ic = daily_ic[(factor, "rank_ic")]
        valid_rank_ic = rank_ic.dropna()
        mean_ic = float(ic.mean())
        mean_rank_ic = float(rank_ic.mean())
        rank_ic_std = float(rank_ic.std(ddof=1))
        icir = (
            mean_rank_ic / rank_ic_std
            * np.sqrt(config.annualization_periods)
            if np.isfinite(rank_ic_std) and rank_ic_std > 0
            else float("nan")
        )
        nw_t_stat = newey_west_t_stat(
            rank_ic,
            lags=config.newey_west_lags,
        )
        eligible_count = int(available_returns.sum())
        joint_count = int(
            (validation_exposures[factor].notna() & available_returns).sum()
        )
        coverage = (
            float(joint_count / eligible_count)
            if eligible_count
            else 0.0
        )
        status = _classify_factor(
            mean_rank_ic=mean_rank_ic,
            newey_west_t=nw_t_stat,
            coverage=coverage,
            valid_dates=len(valid_rank_ic),
            config=config,
        )
        admissions[str(factor)] = status
        metric_records.append(
            {
                "factor": factor,
                "mean_ic": mean_ic,
                "mean_rank_ic": mean_rank_ic,
                "rank_ic_std": rank_ic_std,
                "icir": float(icir),
                "newey_west_t_stat": nw_t_stat,
                "coverage": coverage,
                "valid_dates": int(len(valid_rank_ic)),
                "status": status,
            }
        )

    metrics = pd.DataFrame.from_records(metric_records).set_index("factor")
    metrics.index.name = "Factor"
    return FactorValidationResult(
        metrics=metrics,
        daily_ic=daily_ic,
        quantile_returns=_quantile_returns(
            validation_exposures,
            validation_returns,
            config,
        ),
        factor_correlations=_factor_correlations(validation_exposures),
        admissions=admissions,
        config=config,
    )


def write_validation_report(
    result: FactorValidationResult,
    output_dir: str | Path,
    *,
    overwrite: bool = False,
) -> dict[str, Path]:
    """Persist Parquet statistics and a strict JSON validation summary.

    Files written
    -------------
    ``factor_metrics.parquet``
        One-row-per-factor aggregate statistics and admission status.
    ``daily_ic.parquet``
        Daily Pearson IC and Spearman Rank IC history.
    ``quantile_returns.parquet``
        Daily q1...qN portfolio returns and top-minus-bottom spread.
    ``factor_correlations.parquet``
        Time-averaged daily cross-sectional factor correlations.
    ``factor_validation.json``
        Configuration, admission mapping, and aggregate metrics. Missing
        statistics are serialized as JSON ``null``, never non-standard NaN.

    Safety
    ------
    Existing outputs raise ``FileExistsError`` unless ``overwrite=True``.
    Every artifact is fully serialized to a temporary file in the destination
    directory before ``os.replace`` moves it into its final name. Temporary
    files are removed if serialization or replacement fails.

    Returns
    -------
    dict[str, pathlib.Path]
        Mapping from artifact role to its resolved output path.
    """
    if not isinstance(result, FactorValidationResult):
        raise TypeError("result must be FactorValidationResult.")
    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    paths = {
        "metrics": destination / "factor_metrics.parquet",
        "daily_ic": destination / "daily_ic.parquet",
        "quantile_returns": destination / "quantile_returns.parquet",
        "factor_correlations": destination / "factor_correlations.parquet",
        "summary": destination / "factor_validation.json",
    }
    existing = [path for path in paths.values() if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(
            f"Validation outputs already exist: {[str(path) for path in existing]}"
        )

    temporary_paths: dict[str, Path] = {}
    try:
        for name, final_path in paths.items():
            with NamedTemporaryFile(
                dir=destination,
                prefix=f".{name}-",
                suffix=f"{final_path.suffix}.tmp",
                delete=False,
            ) as temporary:
                temporary_paths[name] = Path(temporary.name)

        result.metrics.to_parquet(temporary_paths["metrics"], engine="pyarrow")
        result.daily_ic.to_parquet(temporary_paths["daily_ic"], engine="pyarrow")
        result.quantile_returns.to_parquet(
            temporary_paths["quantile_returns"],
            engine="pyarrow",
        )
        result.factor_correlations.to_parquet(
            temporary_paths["factor_correlations"],
            engine="pyarrow",
        )
        metrics_records = (
            result.metrics.reset_index()
            .astype(object)
            .where(lambda frame: frame.notna(), None)
            .to_dict(orient="records")
        )
        summary = {
            "admissions": result.admissions,
            "config": {
                field: getattr(result.config, field)
                for field in result.config.__dataclass_fields__
            },
            "metrics": metrics_records,
        }
        temporary_paths["summary"].write_text(
            json.dumps(
                summary,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )

        for name, final_path in paths.items():
            os.replace(temporary_paths.pop(name), final_path)
    finally:
        for temporary_path in temporary_paths.values():
            temporary_path.unlink(missing_ok=True)

    return paths

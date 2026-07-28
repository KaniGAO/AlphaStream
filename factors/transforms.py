"""Cross-sectional transformations for raw factor exposures.

Data flow
---------
raw exposures X_raw
index = MultiIndex(["Date", "Ticker"])
        ↓
winsorize_cross_sectional
        ↓
zscore_cross_sectional
        ↓
neutralize_cross_sectional (optional)
        ↓
orthogonalize_cross_sectional (optional)
        ↓
standardized exposures X

Each transformation operates independently within one trading date.  It must
never use securities from another date, and must preserve the input index,
column order, and missing values.
"""

from __future__ import annotations

from numbers import Real

import numpy as np
import pandas as pd
import pandas.api.types as ptypes


STANDARD_INDEX_NAMES = ["Date", "Ticker"]


def _validate_exposures(exposures: pd.DataFrame) -> None:
    """Validate the common input/output contract for transformations.
    Why the checks belong here
    -------------------------
    Both public transforms require the same X contract.  Putting it here
    means winsorization and z-scoring fail in the same clear way when the
    upstream pipeline gives them malformed data.
    """
    # 1. Confirm exposures is a pandas DataFrame
    if not isinstance(exposures, pd.DataFrame):
        raise TypeError(f"exposures must be a pandas DataFrame, got {type(exposures).__name__}.")
    
    # 2. Confirm its index is a two-level MultiIndex
    if not isinstance(exposures.index, pd.MultiIndex) or exposures.index.nlevels != 2:
        raise ValueError("exposures index must be a two-level MultiIndex.")
    
    # 3. Confirm its index names exactly equal ["Date", "Ticker"]
    if exposures.index.names != ["Date", "Ticker"]:
        raise ValueError(f"exposures index names must be ['Date', 'Ticker'], got {exposures.index.names}.")
    
    # 4. Confirm the Date level has a datetime-like dtype
    date_level = exposures.index.get_level_values("Date")
    if not ptypes.is_datetime64_any_dtype(date_level):
        raise TypeError(f"The 'Date' index level must have a datetime-like dtype, got {date_level.dtype}.")
    
    # 5. Reject duplicate (Date, Ticker) observations
    if not exposures.index.is_unique:
        raise ValueError("exposures index contains duplicate (Date, Ticker) observations.")
    
    # 6. Reject an empty column set
    if exposures.columns.empty:
        raise ValueError("exposures must contain at least one factor column.")
    
    # 7. Confirm every factor column has a numeric dtype
    non_numeric_cols = [col for col in exposures.columns if not ptypes.is_numeric_dtype(exposures[col])]
    if non_numeric_cols:
        raise TypeError(f"All factor columns must have a numeric dtype. Non-numeric columns found: {non_numeric_cols}")


def winsorize_cross_sectional(
    exposures: pd.DataFrame,
    *,
    lower_quantile: float = 0.01,
    upper_quantile: float = 0.99,
) -> pd.DataFrame:
    """Clip each factor's extreme values independently within each Date.

    For a date t and a factor f, calculate the lower and upper cross-sectional
    quantiles among non-missing securities on t.  Values below/above those
    thresholds are clipped to the corresponding threshold.  NaN stays NaN.

    Example
    -------
    If a single day's raw size values are [1, 2, 3, 100], a chosen upper
    quantile may replace 100 with that day's upper boundary.  Tomorrow's
    boundary must be calculated from tomorrow's securities only.
    """
    # 1. Call ``_validate_exposures(exposures)``.
    _validate_exposures(exposures)
    # 2. Validate quantile arguments
    if (
        not isinstance(lower_quantile, Real)
        or isinstance(lower_quantile, bool)
        or not isinstance(upper_quantile, Real)
        or isinstance(upper_quantile, bool)
    ):
        raise TypeError("lower_quantile and upper_quantile must be numeric.")
    if not (0.0 <= lower_quantile < upper_quantile <= 1.0):
        raise ValueError(
            f"Quantiles must satisfy 0 <= lower_quantile < upper_quantile <= 1. "
            f"Got lower_quantile={lower_quantile}, upper_quantile={upper_quantile}."
        )
    
    #3. Make an explicit copy named ``result``.  Never mutate the caller's DataFrame.
    result = exposures.copy()
    # 4 & 5 & 6. Group by Date, compute cross-sectional quantiles, and clip values
    grouped = result.groupby(level = 'Date')
    lower_bounds = grouped.transform(lambda g: g.quantile(lower_quantile))
    upper_bounds = grouped.transform(lambda g: g.quantile(upper_quantile))

    # use Pandas vectorization clip（based on index）
    result = result.clip(lower=lower_bounds,upper=upper_bounds)

    # 7. Confirm the result index and columns match the original exposures
    if not result.index.equals(exposures.index) or not result.columns.equals(exposures.columns):
        raise ValueError("Result index or columns do not match the input exposures.")
    # 8. Return result without filling NaN or dropping rows
    return result

def zscore_cross_sectional(
    exposures: pd.DataFrame,
    *,
    ddof: int = 0,
) -> pd.DataFrame:
    """Standardize each factor independently within each Date.

    For every Date t and factor f:

    ``z[t, i, f] = (x[t, i, f] - mean_t,f) / std_t,f``

    The input should normally be the winsorized matrix.  A Date/factor with
    fewer than two usable observations, or zero cross-sectional dispersion,
    has no meaningful z-score; keep that Date/factor as NaN rather than
    inventing zero exposure.

    Checks to perform manually while learning
    -----------------------------------------
    For one Date and factor with enough non-missing values, its z-scores should
    have approximately mean 0 and standard deviation 1 under the selected
    ``ddof``.
    """

    # 1. Validate exposures.
    _validate_exposures(exposures)

    # 2. Confirm ddof is a non-negative integer
    if not isinstance(ddof, int) or isinstance(ddof, bool) or ddof < 0:
        raise ValueError(f"ddof must be a non-negative integer, got {ddof!r}.")

    # 3. Make a copy named result
    result = exposures.copy()

    # 4. Group by the Date index level
    grouped = result.groupby(level="Date")

    # 5. Compute per-Date, per-factor means
    means = grouped.transform("mean")

    # 6. Compute per-Date, per-factor standard deviations
    stds = grouped.transform("std", ddof=ddof)

    # 7. Replace zero standard deviations with NaN before division to prevent inf/-inf
    stds = stds.mask(stds == 0)

    # 8. Calculate (result - means) / stds
    result = (result - means) / stds

    # 9. Confirm result keeps the exact index and column order of the input
    if not (result.index.equals(exposures.index) and result.columns.equals(exposures.columns)):
        raise ValueError("Result index or columns do not match the input exposures.")

    # 10. Return the standardized matrix
    return result


def neutralize_cross_sectional(
    exposures: pd.DataFrame,
    panel: pd.DataFrame,
    *,
    industry_column: str = "gics_sector",
    market_cap_column: str = "market_cap",
    neutralize_industry: bool = True,
    neutralize_size: bool = True,
) -> pd.DataFrame:
    """Remove daily industry and log-market-cap effects with cross-sectional OLS.

    Regress each factor independently on an intercept, industry dummy
    variables, and log market capitalization. The returned exposure is the
    regression residual. Rows missing a required regressor remain NaN.
    """
    _validate_exposures(exposures)
    if not isinstance(panel, pd.DataFrame):
        raise TypeError(
            f"panel must be a pandas DataFrame, got {type(panel).__name__}."
        )
    if not panel.index.equals(exposures.index):
        raise ValueError(
            "panel and exposures must have exactly the same index."
        )
    if not isinstance(neutralize_industry, bool):
        raise TypeError("neutralize_industry must be a bool.")
    if not isinstance(neutralize_size, bool):
        raise TypeError("neutralize_size must be a bool.")
    if not neutralize_industry and not neutralize_size:
        return exposures.copy()

    required_columns = []
    if neutralize_industry:
        required_columns.append(industry_column)
    if neutralize_size:
        required_columns.append(market_cap_column)
    missing_columns = [
        column for column in required_columns if column not in panel.columns
    ]
    if missing_columns:
        raise ValueError(
            f"panel is missing neutralization columns: {missing_columns}"
        )

    result = pd.DataFrame(
        np.nan,
        index=exposures.index,
        columns=exposures.columns,
        dtype=float,
    )
    date_values = exposures.index.get_level_values("Date")

    for date in date_values.unique():
        date_mask = date_values == date
        daily_exposures = exposures.loc[date_mask]
        daily_panel = panel.loc[date_mask]

        design_parts = [
            pd.DataFrame(
                {"intercept": np.ones(len(daily_panel), dtype=float)},
                index=daily_panel.index,
            )
        ]
        valid_regressors = pd.Series(True, index=daily_panel.index)

        if neutralize_size:
            market_cap = pd.to_numeric(
                daily_panel[market_cap_column],
                errors="coerce",
            )
            log_market_cap = np.log(market_cap.where(market_cap > 0))
            design_parts.append(log_market_cap.rename("log_market_cap").to_frame())
            valid_regressors &= log_market_cap.notna()

        if neutralize_industry:
            industry = daily_panel[industry_column]
            valid_regressors &= industry.notna()
            industry_dummies = pd.get_dummies(
                industry,
                prefix="industry",
                drop_first=True,
                dtype=float,
            )
            design_parts.append(industry_dummies)

        design = pd.concat(design_parts, axis=1)

        for factor_name in exposures.columns:
            values = daily_exposures[factor_name]
            valid = valid_regressors & values.notna()
            if not valid.any():
                continue

            x = design.loc[valid].to_numpy(dtype=float)
            y = values.loc[valid].to_numpy(dtype=float)
            rank = np.linalg.matrix_rank(x)
            if len(y) <= rank:
                continue

            coefficients = np.linalg.lstsq(x, y, rcond=None)[0]
            valid_index = valid.index[valid.to_numpy()]
            result.loc[valid_index, factor_name] = y - x @ coefficients

    return result


def orthogonalize_cross_sectional(
    exposures: pd.DataFrame,
    *,
    correlation_threshold: float = 0.70,
) -> pd.DataFrame:
    """Orthogonalize highly correlated factors within each Date.

    Factors are processed in their existing column order. The first factor is
    preserved. For each later factor, calculate its pairwise correlation with
    previously processed factors on the same Date. If ``abs(correlation)`` is
    strictly greater than ``correlation_threshold``, regress the current
    factor on an intercept and those selected previous factors, then replace
    it with the OLS residual. Low-correlation pairs are left unchanged.

    Column order therefore defines economic priority: earlier factors retain
    their meaning, while later factors keep only incremental information not
    explained by strongly correlated predecessors.
    """
    _validate_exposures(exposures)
    if (
        not isinstance(correlation_threshold, Real)
        or isinstance(correlation_threshold, bool)
    ):
        raise TypeError("correlation_threshold must be numeric.")
    if not 0.0 <= correlation_threshold <= 1.0:
        raise ValueError(
            "correlation_threshold must be between 0 and 1."
        )

    result = exposures.copy()
    date_values = exposures.index.get_level_values("Date")

    for date in date_values.unique():
        date_mask = date_values == date
        daily_index = exposures.index[date_mask]

        for position, factor_name in enumerate(exposures.columns):
            if position == 0:
                continue

            current = result.loc[daily_index, factor_name]
            selected_factors: list[str] = []
            for previous_name in exposures.columns[:position]:
                previous = result.loc[daily_index, previous_name]
                paired = pd.concat([current, previous], axis=1).dropna()
                if len(paired) < 2:
                    continue
                correlation = paired.iloc[:, 0].corr(paired.iloc[:, 1])
                if (
                    pd.notna(correlation)
                    and abs(correlation) > correlation_threshold
                ):
                    selected_factors.append(previous_name)

            if not selected_factors:
                continue

            design = result.loc[daily_index, selected_factors]
            valid = current.notna() & design.notna().all(axis=1)
            if not valid.any():
                result.loc[daily_index, factor_name] = np.nan
                continue

            x = design.loc[valid].to_numpy(dtype=float)
            x = np.column_stack([np.ones(len(x), dtype=float), x])
            y = current.loc[valid].to_numpy(dtype=float)
            rank = np.linalg.matrix_rank(x)
            result.loc[daily_index, factor_name] = np.nan
            if len(y) <= rank:
                continue

            coefficients = np.linalg.lstsq(x, y, rcond=None)[0]
            valid_index = valid.index[valid.to_numpy()]
            result.loc[valid_index, factor_name] = y - x @ coefficients

    return result

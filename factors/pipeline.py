"""Orchestrate factors from a standard panel into the exposure matrix X.

Data flow
---------
standard panel
index = MultiIndex(["Date", "Ticker"])
        ↓
filter to Date <= as_of
        ↓
Factor.compute(panel) for each registered factor
        ↓
raw exposure matrix
        ↓
transforms.py: winsorize → z-score → optional neutralization/orthogonalization
        ↓
final exposure matrix X

Responsibility boundary
-----------------------
This module coordinates factors. It does not define an economic factor formula
and it does not implement a cross-sectional transformation itself.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from numbers import Real
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import numpy as np
import pandas as pd

from factors.base import Factor
from factors.transforms import (
    neutralize_cross_sectional,
    orthogonalize_cross_sectional,
    winsorize_cross_sectional,
    zscore_cross_sectional,
)


@dataclass(frozen=True)
class PipelineConfig:
    """Configuration for building and persisting factor exposures."""

    as_of: str | pd.Timestamp
    lower_quantile: float = 0.025
    upper_quantile: float = 0.975
    zscore_ddof: int = 0
    neutralize: bool = False
    industry_column: str = "gics_sector"
    market_cap_column: str = "market_cap"
    neutralize_industry: bool = True
    neutralize_size: bool = True
    orthogonalize: bool = False
    correlation_threshold: float = 0.70
    output_dir: Path = Path("Data/Processed")
    exposures_filename: str = "exposures.parquet"
    metadata_filename: str = "exposures_meta.json"
    universe_name: str | None = None
    overwrite: bool = False

    def __post_init__(self) -> None:
        """Reject invalid configuration before pipeline work begins."""
        if (
            not isinstance(self.lower_quantile, Real)
            or isinstance(self.lower_quantile, bool)
            or not isinstance(self.upper_quantile, Real)
            or isinstance(self.upper_quantile, bool)
        ):
            raise TypeError("Winsorization quantiles must be numeric.")
        if not (
            0.0 <= self.lower_quantile < self.upper_quantile <= 1.0
        ):
            raise ValueError(
                "Quantiles must satisfy "
                "0 <= lower_quantile < upper_quantile <= 1."
            )
        if (
            not isinstance(self.correlation_threshold, Real)
            or isinstance(self.correlation_threshold, bool)
        ):
            raise TypeError("correlation_threshold must be numeric.")
        if not 0.0 <= self.correlation_threshold <= 1.0:
            raise ValueError(
                "correlation_threshold must be between 0 and 1."
            )
        if (
            not isinstance(self.zscore_ddof, int)
            or isinstance(self.zscore_ddof, bool)
            or self.zscore_ddof < 0
        ):
            raise ValueError("zscore_ddof must be a non-negative integer.")

        boolean_fields = {
            "neutralize": self.neutralize,
            "neutralize_industry": self.neutralize_industry,
            "neutralize_size": self.neutralize_size,
            "orthogonalize": self.orthogonalize,
            "overwrite": self.overwrite,
        }
        invalid_booleans = [
            name for name, value in boolean_fields.items()
            if not isinstance(value, bool)
        ]
        if invalid_booleans:
            raise TypeError(
                f"Configuration flags must be bool: {invalid_booleans}"
            )
        if (
            self.neutralize
            and not self.neutralize_industry
            and not self.neutralize_size
        ):
            raise ValueError(
                "neutralize=True requires industry and/or size neutralization."
            )

        for name, value in {
            "industry_column": self.industry_column,
            "market_cap_column": self.market_cap_column,
            "exposures_filename": self.exposures_filename,
            "metadata_filename": self.metadata_filename,
        }.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string.")
        if not isinstance(self.output_dir, (str, Path)):
            raise TypeError("output_dir must be a string or pathlib.Path.")
        if self.universe_name is not None and (
            not isinstance(self.universe_name, str)
            or not self.universe_name.strip()
        ):
            raise ValueError(
                "universe_name must be None or a non-empty string."
            )
        _validate_as_of(self.as_of)


@dataclass(frozen=True)
class PipelineResult:
    """Artifacts produced by a completed factor pipeline run."""

    exposures: pd.DataFrame
    metadata: dict[str, Any]
    exposures_path: Path
    metadata_path: Path


def _validate_as_of(as_of: str | pd.Timestamp) -> pd.Timestamp:
    """Convert and validate the pipeline's no-look-ahead boundary."""
    if not isinstance(as_of, (str, pd.Timestamp)):
        raise TypeError(
            "as_of must be a date string or pandas.Timestamp, "
            f"got {type(as_of).__name__}"
        )

    try:
        timestamp = pd.Timestamp(as_of)
    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"Invalid as_of value: {as_of!r} cannot be parsed as a date."
        ) from exc

    if pd.isna(timestamp):
        raise ValueError("as_of must be a real date, not NaT.")

    if timestamp.tzinfo is not None:
        raise ValueError(
            "Timezone-aware dates are not supported. "
            "Please provide a timezone-naive date."
        )

    return timestamp.normalize()


def _filter_panel_as_of(
    panel: pd.DataFrame,
    as_of: pd.Timestamp,
) -> pd.DataFrame:
    """Return a non-mutating historical slice containing Date <= as_of."""
    if not isinstance(panel, pd.DataFrame):
        raise TypeError(
            "panel must be a pandas DataFrame, "
            f"got {type(panel).__name__}"
        )
    if not isinstance(panel.index, pd.MultiIndex):
        raise ValueError("panel index must be a MultiIndex")
    expected_names = ["Date", "Ticker"]
    if list(panel.index.names) != expected_names:
        raise ValueError(
            f"panel index names must be exactly {expected_names}, "
            f"got {list(panel.index.names)}"
        )

    dates = panel.index.get_level_values("Date")
    filtered = panel.loc[dates <= as_of]
    if filtered.empty:
        raise ValueError(
            f"Historical slice is empty. 'as_of' ({as_of}) predates all "
            "available data or the wrong dataset was supplied."
        )
    return filtered

def _validate_factors(factors: Sequence[Factor]) -> list[Factor]:
    """Validate and materialize factors before executing any formulas."""
    factors_list = list(factors)
    if not factors_list:
        raise ValueError("Factor list cannot be empty.")

    seen_names: set[str] = set()
    for factor in factors_list:
        if not isinstance(factor, Factor):
            raise TypeError(f"Item {factor!r} is not an instance of Factor.")
        if not isinstance(factor.name, str) or not factor.name.strip():
            raise ValueError(
                f"Factor {factor!r} must have a non-empty string 'name'."
            )
        if factor.name in seen_names:
            raise ValueError(
                f"Duplicate factor name detected: '{factor.name}'."
            )
        seen_names.add(factor.name)

    return factors_list


def _validate_required_columns(
    panel: pd.DataFrame,
    factors: Sequence[Factor],
) -> None:
    """Validate all factor inputs before any formula is executed."""
    missing_by_factor = {
        factor.name: sorted(set(factor.required_columns) - set(panel.columns))
        for factor in factors
    }
    missing_by_factor = {
        name: columns
        for name, columns in missing_by_factor.items()
        if columns
    }
    if missing_by_factor:
        details = "; ".join(
            f"{name}: {columns}"
            for name, columns in missing_by_factor.items()
        )
        raise ValueError(f"Panel is missing required factor columns: {details}")


def compute_raw_exposures(
    panel: pd.DataFrame,
    factors: Sequence[Factor],
) -> pd.DataFrame:
    """Run factor formulas and combine their raw exposures column-wise."""
    validated_factors = _validate_factors(factors)

    exposure_dict = {
        factor.name: factor.compute(panel)
        for factor in validated_factors
    }
    exposures_df = pd.DataFrame(exposure_dict, index=panel.index)
    if not exposures_df.index.equals(panel.index):
        raise ValueError("Result index does not match input panel index.")

    requested_order = [factor.name for factor in validated_factors]
    return exposures_df[requested_order]


def get_exposures(
    panel: pd.DataFrame,
    factors: Sequence[Factor],
    *,
    as_of: str | pd.Timestamp,
) -> pd.DataFrame:
    """Build winsorized and standardized factor exposures through ``as_of``."""
    validated_factors = _validate_factors(factors)
    validated_as_of = _validate_as_of(as_of)
    historical_panel = _filter_panel_as_of(panel, validated_as_of)

    raw_x = compute_raw_exposures(historical_panel, factors=validated_factors)
    x = winsorize_cross_sectional(raw_x)
    x = zscore_cross_sectional(x)

    if not x.index.equals(historical_panel.index):
        raise ValueError(
            "Final exposure matrix index does not match historical panel index."
        )

    expected_columns = [factor.name for factor in validated_factors]
    if list(x.columns) != expected_columns:
        raise ValueError(
            "Columns of X must exactly match expected factor names: "
            f"{expected_columns}"
        )

    non_numeric = [
        column
        for column in x.columns
        if not pd.api.types.is_numeric_dtype(x[column])
    ]
    if non_numeric:
        raise TypeError(
            f"Final exposure columns must be numeric: {non_numeric}"
        )

    return x.sort_index(level=["Date", "Ticker"])


def apply_transforms(
    raw_exposures: pd.DataFrame,
    panel: pd.DataFrame,
    config: PipelineConfig,
) -> pd.DataFrame:
    """Apply the configured cross-sectional transformations in order."""
    if not isinstance(config, PipelineConfig):
        raise TypeError(
            f"config must be PipelineConfig, got {type(config).__name__}"
        )
    if not isinstance(panel, pd.DataFrame):
        raise TypeError(
            f"panel must be a pandas DataFrame, got {type(panel).__name__}"
        )
    if not raw_exposures.index.equals(panel.index):
        raise ValueError(
            "raw_exposures and panel must have exactly the same index."
        )

    result = winsorize_cross_sectional(
        raw_exposures,
        lower_quantile=config.lower_quantile,
        upper_quantile=config.upper_quantile,
    )
    result = zscore_cross_sectional(
        result,
        ddof=config.zscore_ddof,
    )
    if config.neutralize:
        result = neutralize_cross_sectional(
            result,
            panel,
            industry_column=config.industry_column,
            market_cap_column=config.market_cap_column,
            neutralize_industry=config.neutralize_industry,
            neutralize_size=config.neutralize_size,
        )
    if config.orthogonalize:
        result = orthogonalize_cross_sectional(
            result,
            correlation_threshold=config.correlation_threshold,
        )

    if not result.index.equals(raw_exposures.index):
        raise ValueError("Transform chain changed the exposure index.")
    if not result.columns.equals(raw_exposures.columns):
        raise ValueError("Transform chain changed the factor columns.")

    return result


def validate_final_exposures(
    exposures: pd.DataFrame,
    historical_panel: pd.DataFrame,
    factors: Sequence[Factor],
    *,
    as_of: pd.Timestamp,
) -> None:
    """Validate the final exposure matrix before persistence."""
    if not isinstance(exposures, pd.DataFrame):
        raise TypeError(
            f"exposures must be a pandas DataFrame, "
            f"got {type(exposures).__name__}"
        )
    if not isinstance(exposures.index, pd.MultiIndex):
        raise ValueError("exposures index must be a MultiIndex.")
    if exposures.index.nlevels != 2:
        raise ValueError("exposures index must have exactly two levels.")
    if list(exposures.index.names) != ["Date", "Ticker"]:
        raise ValueError(
            "exposures index names must be exactly ['Date', 'Ticker']."
        )
    if exposures.index.has_duplicates:
        raise ValueError("exposures index contains duplicate observations.")

    expected_index = historical_panel.sort_index(
        level=["Date", "Ticker"]
    ).index
    if not exposures.index.equals(expected_index):
        raise ValueError(
            "exposures index must equal the sorted historical panel index."
        )

    dates = exposures.index.get_level_values("Date")
    if (dates > as_of).any():
        raise ValueError("exposures contains observations after as_of.")

    expected_columns = [factor.name for factor in factors]
    if list(exposures.columns) != expected_columns:
        raise ValueError(
            f"exposure columns must equal factor order {expected_columns}."
        )

    non_numeric = [
        column
        for column in exposures.columns
        if not pd.api.types.is_numeric_dtype(exposures[column])
    ]
    if non_numeric:
        raise TypeError(
            f"exposure columns must be numeric: {non_numeric}"
        )

    infinite_columns = [
        column
        for column in exposures.columns
        if np.isinf(
            exposures[column].to_numpy(dtype=float, na_value=np.nan)
        ).any()
    ]
    if infinite_columns:
        raise ValueError(
            f"exposure columns contain infinite values: {infinite_columns}"
        )


def build_exposures_metadata(
    exposures: pd.DataFrame,
    factors: Sequence[Factor],
    config: PipelineConfig,
) -> dict[str, Any]:
    """Build JSON-serializable provenance and validation metadata."""
    dates = exposures.index.get_level_values("Date")
    tickers = exposures.index.get_level_values("Ticker")
    as_of = _validate_as_of(config.as_of)

    factor_statistics: dict[str, dict[str, int | float]] = {}
    for column in exposures.columns:
        values = exposures[column]
        missing_count = int(values.isna().sum())
        finite_count = int(
            np.isfinite(values.to_numpy(dtype=float, na_value=np.nan)).sum()
        )
        factor_statistics[str(column)] = {
            "missing_count": missing_count,
            "missing_rate": (
                float(missing_count / len(values)) if len(values) else 0.0
            ),
            "finite_count": finite_count,
        }

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "as_of": as_of.date().isoformat(),
        "data_range": {
            "start": pd.Timestamp(dates.min()).date().isoformat(),
            "end": pd.Timestamp(dates.max()).date().isoformat(),
        },
        "row_count": int(len(exposures)),
        "ticker_count": int(tickers.nunique()),
        "universe_name": config.universe_name,
        "factors": [
            {
                "name": factor.name,
                "required_columns": list(factor.required_columns),
            }
            for factor in factors
        ],
        "transforms": {
            "winsorize": {
                "lower_quantile": float(config.lower_quantile),
                "upper_quantile": float(config.upper_quantile),
            },
            "zscore": {"ddof": int(config.zscore_ddof)},
            "neutralize": {
                "enabled": config.neutralize,
                "industry": (
                    config.neutralize and config.neutralize_industry
                ),
                "industry_column": config.industry_column,
                "size": config.neutralize and config.neutralize_size,
                "market_cap_column": config.market_cap_column,
            },
            "orthogonalize": {
                "enabled": config.orthogonalize,
                "correlation_threshold": float(
                    config.correlation_threshold
                ),
                "factor_order": list(exposures.columns),
            },
        },
        "factor_statistics": factor_statistics,
        "validation": {
            "index_valid": True,
            "columns_valid": True,
            "numeric_dtypes": True,
            "finite_values_only": True,
            "no_future_data": bool((dates <= as_of).all()),
        },
    }


def write_pipeline_artifacts(
    exposures: pd.DataFrame,
    metadata: dict[str, Any],
    config: PipelineConfig,
) -> tuple[Path, Path]:
    """Persist exposures.parquet and exposures_meta.json safely."""
    filenames = (config.exposures_filename, config.metadata_filename)
    for filename in filenames:
        candidate = Path(filename)
        if (
            not filename
            or candidate.is_absolute()
            or candidate.name != filename
        ):
            raise ValueError(
                f"Output filename must be a simple file name: {filename!r}"
            )

    output_dir = Path(config.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    exposures_path = output_dir / config.exposures_filename
    metadata_path = output_dir / config.metadata_filename

    existing = [
        path for path in (exposures_path, metadata_path) if path.exists()
    ]
    if existing and not config.overwrite:
        raise FileExistsError(
            f"Output artifacts already exist: {[str(path) for path in existing]}"
        )

    temporary_paths: list[Path] = []
    try:
        with NamedTemporaryFile(
            dir=output_dir,
            prefix=".exposures-",
            suffix=".parquet.tmp",
            delete=False,
        ) as temporary_exposures:
            temporary_exposures_path = Path(temporary_exposures.name)
        temporary_paths.append(temporary_exposures_path)

        with NamedTemporaryFile(
            dir=output_dir,
            prefix=".metadata-",
            suffix=".json.tmp",
            mode="w",
            encoding="utf-8",
            delete=False,
        ) as temporary_metadata:
            json.dump(
                metadata,
                temporary_metadata,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            temporary_metadata.write("\n")
            temporary_metadata_path = Path(temporary_metadata.name)
        temporary_paths.append(temporary_metadata_path)

        exposures.to_parquet(
            temporary_exposures_path,
            engine="pyarrow",
            compression="snappy",
        )
        os.replace(temporary_exposures_path, exposures_path)
        temporary_paths.remove(temporary_exposures_path)
        os.replace(temporary_metadata_path, metadata_path)
        temporary_paths.remove(temporary_metadata_path)
    finally:
        for temporary_path in temporary_paths:
            temporary_path.unlink(missing_ok=True)

    return exposures_path, metadata_path


def run_pipeline(
    panel: pd.DataFrame,
    factors: Sequence[Factor],
    config: PipelineConfig,
) -> PipelineResult:
    """Run the complete production factor-exposure pipeline."""
    if not isinstance(config, PipelineConfig):
        raise TypeError(
            f"config must be PipelineConfig, got {type(config).__name__}"
        )

    validated_factors = _validate_factors(factors)
    validated_as_of = _validate_as_of(config.as_of)
    historical_panel = _filter_panel_as_of(
        panel,
        validated_as_of,
    ).sort_index(level=["Date", "Ticker"])

    _validate_required_columns(historical_panel, validated_factors)
    raw_exposures = compute_raw_exposures(
        historical_panel,
        validated_factors,
    )
    exposures = apply_transforms(
        raw_exposures,
        historical_panel,
        config,
    ).sort_index(level=["Date", "Ticker"])

    validate_final_exposures(
        exposures,
        historical_panel,
        validated_factors,
        as_of=validated_as_of,
    )
    metadata = build_exposures_metadata(
        exposures,
        validated_factors,
        config,
    )
    exposures_path, metadata_path = write_pipeline_artifacts(
        exposures,
        metadata,
        config,
    )
    return PipelineResult(
        exposures=exposures,
        metadata=metadata,
        exposures_path=exposures_path,
        metadata_path=metadata_path,
    )

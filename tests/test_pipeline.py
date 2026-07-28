"""Tests for factor-pipeline orchestration and its public contracts."""

import json

import numpy as np
import pandas as pd
import pytest

from factors.base import Factor
from factors.pipeline import (
    PipelineConfig,
    _filter_panel_as_of,
    _validate_as_of,
    _validate_factors,
    _validate_required_columns,
    apply_transforms,
    build_exposures_metadata,
    compute_raw_exposures,
    get_exposures,
    run_pipeline,
    validate_final_exposures,
    write_pipeline_artifacts,
)
from factors.size import SizeFactor


@pytest.fixture
def panel() -> pd.DataFrame:
    index = pd.MultiIndex.from_tuples(
        [
            (pd.Timestamp("2025-01-02"), "AAA"),
            (pd.Timestamp("2025-01-02"), "BBB"),
            (pd.Timestamp("2025-01-03"), "AAA"),
            (pd.Timestamp("2025-01-03"), "BBB"),
        ],
        names=["Date", "Ticker"],
    )
    return pd.DataFrame({"market_cap": [100.0, 0.0, 400.0, 900.0]}, index=index)


class AnotherSizeFactor(SizeFactor):
    """A separate object with SizeFactor's name, for duplicate-name tests."""


def test_validate_as_of_returns_normalized_timestamp() -> None:
    actual = _validate_as_of("2025-01-03 14:30")

    assert actual == pd.Timestamp("2025-01-03")
    assert isinstance(actual, pd.Timestamp)


@pytest.mark.parametrize("value", [None, ["2025-01-03"], "not-a-date"])
def test_validate_as_of_rejects_invalid_values(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        _validate_as_of(value)  # type: ignore[arg-type]


def test_validate_as_of_rejects_timezone_aware_timestamp() -> None:
    with pytest.raises(ValueError, match="Timezone-aware"):
        _validate_as_of(pd.Timestamp("2025-01-03", tz="UTC"))


def test_filter_panel_as_of_keeps_history_without_mutating_source(panel: pd.DataFrame) -> None:
    original = panel.copy(deep=True)

    actual = _filter_panel_as_of(panel, pd.Timestamp("2025-01-02"))

    assert actual.index.equals(panel.index[:2])
    pd.testing.assert_frame_equal(panel, original)


def test_filter_panel_as_of_rejects_empty_history(panel: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="Historical slice is empty"):
        _filter_panel_as_of(panel, pd.Timestamp("2025-01-01"))


def test_validate_factors_rejects_duplicate_names() -> None:
    with pytest.raises(ValueError, match="Duplicate factor name"):
        _validate_factors([SizeFactor(), AnotherSizeFactor()])


def test_validate_factors_rejects_non_factor() -> None:
    with pytest.raises(TypeError, match="not an instance"):
        _validate_factors([SizeFactor(), object()])  # type: ignore[list-item]


def test_compute_raw_exposures_preserves_index_order_and_missing_values(panel: pd.DataFrame) -> None:
    actual = compute_raw_exposures(panel, [SizeFactor()])

    assert actual.index.equals(panel.index)
    assert list(actual.columns) == ["size"]
    assert pd.isna(actual.loc[(pd.Timestamp("2025-01-02"), "BBB"), "size"])


def test_get_exposures_returns_standardized_x_without_future_dates(
    panel: pd.DataFrame,
) -> None:
    actual = get_exposures(panel, [SizeFactor()], as_of="2025-01-03")

    assert actual.index.equals(panel.index)
    assert list(actual.columns) == ["size"]
    assert (actual.index.get_level_values("Date") <= pd.Timestamp("2025-01-03")).all()
    # On 2025-01-03, log(400) and log(900) standardize to -1 and +1.
    assert actual.loc[(pd.Timestamp("2025-01-03"), "AAA"), "size"] == -1.0
    assert actual.loc[(pd.Timestamp("2025-01-03"), "BBB"), "size"] == 1.0


def test_apply_transforms_uses_config_and_preserves_contract() -> None:
    index = pd.MultiIndex.from_product(
        [[pd.Timestamp("2025-01-02")], ["AAA", "BBB", "CCC"]],
        names=["Date", "Ticker"],
    )
    raw = pd.DataFrame({"size": [1.0, 2.0, 100.0]}, index=index)
    source_panel = pd.DataFrame({"market_cap": [1.0, 2.0, 3.0]}, index=index)
    config = PipelineConfig(
        as_of="2025-01-02",
        lower_quantile=0.0,
        upper_quantile=0.5,
        zscore_ddof=0,
    )

    actual = apply_transforms(raw, source_panel, config)

    expected = pd.DataFrame(
        {"size": [-1.414213562373095, 0.7071067811865476, 0.7071067811865476]},
        index=index,
    )
    pd.testing.assert_frame_equal(actual, expected)
    assert actual.index.equals(raw.index)
    assert actual.columns.equals(raw.columns)


def test_apply_transforms_rejects_misaligned_panel(panel: pd.DataFrame) -> None:
    raw = pd.DataFrame({"size": [1.0]}, index=panel.index[:1])
    config = PipelineConfig(as_of="2025-01-03")

    with pytest.raises(ValueError, match="same index"):
        apply_transforms(raw, panel, config)


def test_apply_transforms_validates_and_applies_optional_transforms(
    panel: pd.DataFrame,
) -> None:
    raw = pd.DataFrame({"size": [1.0, 2.0, 3.0, 4.0]}, index=panel.index)

    with pytest.raises(ValueError, match="gics_sector"):
        apply_transforms(
            raw,
            panel,
            PipelineConfig(as_of="2025-01-03", neutralize=True),
        )

    orthogonal_index = pd.MultiIndex.from_product(
        [[pd.Timestamp("2025-01-03")], list("ABCDEFGH")],
        names=["Date", "Ticker"],
    )
    first = np.arange(8.0)
    two_factor_raw = pd.DataFrame(
        {
            "size": first,
            "value": 2.0 * first
            + np.array([0.2, -0.1, 0.1, -0.2, 0.1, 0.0, -0.1, 0.2]),
        },
        index=orthogonal_index,
    )
    orthogonal_panel = pd.DataFrame(
        {"market_cap": np.exp(first + 1.0)},
        index=orthogonal_index,
    )
    actual = apply_transforms(
        two_factor_raw,
        orthogonal_panel,
        PipelineConfig(
            as_of="2025-01-03",
            lower_quantile=0.0,
            upper_quantile=1.0,
            orthogonalize=True,
            correlation_threshold=0.70,
        ),
    )

    for _, daily in actual.groupby(level="Date"):
        assert abs(daily["size"].corr(daily["value"])) < 1e-12


def test_validate_required_columns_reports_all_missing(
    panel: pd.DataFrame,
) -> None:
    without_market_cap = panel.drop(columns="market_cap")

    with pytest.raises(ValueError, match=r"size: \['market_cap'\]"):
        _validate_required_columns(without_market_cap, [SizeFactor()])


def test_validate_final_exposures_rejects_infinity(
    panel: pd.DataFrame,
) -> None:
    exposures = pd.DataFrame({"size": [1.0, 2.0, 3.0, np.inf]}, index=panel.index)

    with pytest.raises(ValueError, match="infinite"):
        validate_final_exposures(
            exposures,
            panel,
            [SizeFactor()],
            as_of=pd.Timestamp("2025-01-03"),
        )


def test_metadata_is_json_serializable(panel: pd.DataFrame) -> None:
    exposures = pd.DataFrame(
        {"size": [1.0, np.nan, -1.0, 1.0]},
        index=panel.index,
    )
    config = PipelineConfig(as_of="2025-01-03", universe_name="test")

    metadata = build_exposures_metadata(
        exposures,
        [SizeFactor()],
        config,
    )

    json.dumps(metadata)
    assert metadata["row_count"] == 4
    assert metadata["ticker_count"] == 2
    assert metadata["factor_statistics"]["size"]["missing_count"] == 1
    assert metadata["validation"]["no_future_data"] is True


def test_write_pipeline_artifacts_round_trip(
    panel: pd.DataFrame,
    tmp_path,
) -> None:
    exposures = pd.DataFrame({"size": [1.0, 2.0, 3.0, 4.0]}, index=panel.index)
    metadata = {"status": "ok"}
    config = PipelineConfig(as_of="2025-01-03", output_dir=tmp_path)

    exposures_path, metadata_path = write_pipeline_artifacts(
        exposures,
        metadata,
        config,
    )

    pd.testing.assert_frame_equal(pd.read_parquet(exposures_path), exposures)
    assert json.loads(metadata_path.read_text(encoding="utf-8")) == metadata

    with pytest.raises(FileExistsError):
        write_pipeline_artifacts(exposures, metadata, config)


def test_run_pipeline_writes_valid_artifacts(panel: pd.DataFrame, tmp_path) -> None:
    config = PipelineConfig(
        as_of="2025-01-03",
        output_dir=tmp_path,
        universe_name="unit-test",
    )

    result = run_pipeline(panel, [SizeFactor()], config)

    assert result.exposures_path.exists()
    assert result.metadata_path.exists()
    assert result.metadata["universe_name"] == "unit-test"
    assert list(result.exposures.columns) == ["size"]
    assert result.exposures.index.equals(panel.index)

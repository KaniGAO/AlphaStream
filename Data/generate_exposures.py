"""Generate Zeon's factor-exposure matrix X from the bridged panel.

Consumes :mod:`Data.build_panel` and Zeon's production pipeline to write
``Data/Processed/exposures.parquet`` + ``exposures_meta.json`` — the single
hand-off artifact that Kani's ``risk/`` module consumes.

This script does NOT modify any ``factors/`` code; it only drives the
public ``run_pipeline`` entry point following Zeon's documented usage.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the project root importable when run as a script.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from factors.beta import BetaFactor
from factors.earn_yld import EarningsYieldFactor
from factors.growth_eps import EPSGrowthFactor
from factors.growth_sales import SalesGrowthFactor
from factors.leverage import LeverageFactor
from factors.liquidity import LiquidityFactor
from factors.momentum import MomentumFactor
from factors.pipeline import PipelineConfig, run_pipeline
from factors.size import SizeFactor
from factors.value import ValueFactor
from factors.volatility import VolatilityFactor

from Data.build_panel import build_panel

# Keep factor ordering identical to Zeon's registration order.
FACTORS = [
    SizeFactor(),
    ValueFactor(),
    EarningsYieldFactor(),
    MomentumFactor(),
    VolatilityFactor(),
    BetaFactor(),
    LiquidityFactor(),
    SalesGrowthFactor(),
    EPSGrowthFactor(),
    LeverageFactor(),
]

AS_OF = "2025-12-31"
OUTPUT_DIR = Path("Data/Processed")


def main() -> None:
    panel = build_panel()
    print(f"[zeon] panel loaded: {panel.shape}, as_of={AS_OF}", flush=True)

    config = PipelineConfig(
        as_of=AS_OF,
        neutralize=True,
        neutralize_industry=True,
        neutralize_size=True,
        industry_column="gics_sector",
        market_cap_column="market_cap",
        orthogonalize=True,
        correlation_threshold=0.70,
        output_dir=OUTPUT_DIR,
        overwrite=True,
        universe_name="SPX (barra_research US)",
    )

    result = run_pipeline(panel, FACTORS, config)
    print(f"[zeon] exposures -> {result.exposures_path}", flush=True)
    print(f"[zeon] metadata   -> {result.metadata_path}", flush=True)
    print(f"[zeon] X shape: {result.exposures.shape}", flush=True)
    print(f"[zeon] factor cols: {list(result.exposures.columns)}", flush=True)


if __name__ == "__main__":
    main()

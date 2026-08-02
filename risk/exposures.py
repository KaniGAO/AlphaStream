"""Load Zeon's factor exposures and derive point-in-time stock returns.

This is the entry point for Kani's risk module. It reads the single hand-off
artifact produced by Zeon (``exposures.parquet`` + ``exposures_meta.json``)
and derives the daily stock returns ``r`` that the Barra model regresses
against the exposures ``X``.

Contracts
---------
* ``X``          : [Date, Ticker] MultiIndex, one column per factor (z-scored,
                   industry/size neutralized, orthogonalized).
* ``r``          : [Date, Ticker] MultiIndex, simple daily returns aligned to
                   the SAME trading dates as ``X``. ``r[t]`` uses only
                   information available on/before ``t`` (point-in-time).
* NaN policy     : Zeon leaves missing exposures as NaN; this module drops NaN
                   per trading day (cross-section) and never silently fills 0.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Data.build_panel import BARRA_ROOT, load_returns as _load_tr_panel  # noqa: E402

PROCESSED_DIR = PROJECT_ROOT / "Data" / "Processed"
EXPOSURES_PATH = PROCESSED_DIR / "exposures.parquet"
META_PATH = PROCESSED_DIR / "exposures_meta.json"

TRADING_DAYS = 252


def load_exposures(path: Path = EXPOSURES_PATH) -> pd.DataFrame:
    """Load the factor-exposure matrix ``X``.

    Returns a DataFrame with a [Date, Ticker] MultiIndex and one column per
    factor. The factor order follows ``exposures_meta.json``.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run `python Data/generate_exposures.py` first."
        )
    exposures = pd.read_parquet(path)
    exposures.index = exposures.index.set_names(["Date", "Ticker"])
    return exposures.sort_index(level=["Date", "Ticker"])


def load_factor_names(path: Path = META_PATH) -> list[str]:
    """Read the ordered factor names from ``exposures_meta.json``."""
    if not path.exists():
        raise FileNotFoundError(f"{path} not found.")
    with open(path) as fh:
        meta = json.load(fh)
    return [f["name"] for f in meta["factors"]]


def load_returns(
    exposures: pd.DataFrame | None = None,
    path: Path | None = None,
) -> pd.DataFrame:
    """Derive point-in-time daily stock returns ``r``.

    Returns are computed from the total-return index (``tr``) in the barra
    source via ``pct_change`` per ticker, then aligned to the trading dates of
    ``exposures`` (if supplied). The first available date per ticker is NaN
    because it has no prior observation (no look-ahead).

    Parameters
    ----------
    exposures : optional [Date, Ticker] matrix; when given, ``r`` is reindexed
        to its exact (Date, Ticker) pairs so X and r share an index.
    path : optional parquet path for the raw ``tr`` panel (testing).
    """
    tr = _load_tr_panel() if path is None else pd.read_parquet(path)
    tr = tr.sort_index(level=["Date", "Ticker"])

    # Simple daily returns per ticker, point-in-time.
    returns = (
        tr.groupby(level="Ticker", sort=False)["tr"]
        .transform(lambda s: s.pct_change())
        .to_frame("r")
    )
    returns.index = returns.index.set_names(["Date", "Ticker"])

    if exposures is not None:
        # Align to X's exact cross-section, preserving X's (date, ticker) set.
        returns = returns.reindex(exposures.index)

    return returns.sort_index(level=["Date", "Ticker"])


def latest_cross_section(
    exposures: pd.DataFrame, as_of: pd.Timestamp | str
) -> pd.DataFrame:
    """Return the single most-recent cross-section on/before ``as_of``."""
    as_of = pd.Timestamp(as_of)
    dates = exposures.index.get_level_values("Date")
    valid = dates[dates <= as_of]
    if len(valid) == 0:
        raise ValueError(f"No exposure cross-section on or before {as_of}.")
    last_date = valid.max()
    return exposures.xs(last_date, level="Date")


def aligned_panel(
    exposures: pd.DataFrame, returns: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return X and r with identical [Date, Ticker] index and per-day dropna.

    Each trading day drops tickers that are NaN in either X or r, matching the
    clean cross-section used by the Barra regression ``r = X f + eps``.
    """
    if not exposures.index.equals(returns.index):
        returns = returns.reindex(exposures.index)
    both = exposures.notna().all(axis=1) & returns["r"].notna()
    x_clean = exposures[both]
    r_clean = returns[both]
    return x_clean, r_clean

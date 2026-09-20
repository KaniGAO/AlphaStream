"""Build the standard [Date, Ticker] panel consumed by Zeon's factor pipeline.

This is Kani's data-bridge layer. It reads the barra_research US equity
parquet files and reshapes them into the exact wide-format panel that
``factors.pipeline.run_pipeline`` expects, so Zeon's ``exposures.parquet``
can be produced without a Bloomberg USE4 ``.xlsx`` workbook.

Source of truth (read-only, never copied into the repo):
    /Users/gaokanglin/Project/bbg_project/barra_research/markets/us/data/

Column contract (per factors/base.py Factor.required_columns):
    px_last            <- prices.close
    market_cap         <- descriptors_ts.CUR_MKT_CAP
    pb                 <- descriptors_ts.PX_TO_BOOK_RATIO
    earn_yld           <- descriptors_ts.EARN_YLD
    beta               <- descriptors_ts.BETA_ADJ_OVERRIDABLE
    volume             <- descriptors_ts.VOLUME
    growth_sales       <- descriptors_q_daily.SALES_GROWTH
    growth_eps         <- descriptors_q_daily.EPS_GROWTH
    leverage           <- descriptors_q_daily.TOT_DEBT_TO_COM_EQY
    gics_sector        <- industries.gics_sector
    gics_industry_group<- industries.gics_industry_grp
    gics_sub_industry  <- industries.gics_sub_ind
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

# --- Source data (read-only reference, configurable) -------------------------
# The barra_research tree has moved between machines and folders
# (Project/bbg_project -> Project/1/bbg_project), so the location is resolved at
# import time rather than hardcoded:
#   1. the BARRA_ROOT environment variable wins when set;
#   2. otherwise the first existing candidate directory is used.
# Override with:  export BARRA_ROOT=/path/to/barra_research/markets/us/data
BARRA_ROOT_CANDIDATES = (
    Path("~/Project/1/bbg_project/barra_research/markets/us/data").expanduser(),
    Path("~/Project/bbg_project/barra_research/markets/us/data").expanduser(),
)

BARRA_ROOT = Path(
    os.environ.get("BARRA_ROOT") or next(
        (p for p in BARRA_ROOT_CANDIDATES if p.is_dir()), BARRA_ROOT_CANDIDATES[0]
    )
).expanduser()

PRICES_PATH = BARRA_ROOT / "prices.parquet"
RETURNS_PATH = BARRA_ROOT / "returns.parquet"
DESC_TS_PATH = BARRA_ROOT / "descriptors_ts.parquet"
DESC_Q_PATH = BARRA_ROOT / "descriptors_q_daily.parquet"
INDUSTRIES_PATH = BARRA_ROOT / "industries.parquet"

# descriptor field -> target panel column (time-series daily descriptors)
TS_FIELD_MAP = {
    "CUR_MKT_CAP": "market_cap",
    "PX_TO_BOOK_RATIO": "pb",
    "EARN_YLD": "earn_yld",
    "BETA_ADJ_OVERRIDABLE": "beta",
    "VOLUME": "volume",
}

# descriptor field -> target panel column (quarterly descriptors, daily-aligned)
Q_FIELD_MAP = {
    "SALES_GROWTH": "growth_sales",
    "EPS_GROWTH": "growth_eps",
    "TOT_DEBT_TO_COM_EQY": "leverage",
}

# Long -> wide mapping for a descriptors frame with columns
# [date, ticker, field, value].
REQUIRED_DESCRIPTOR_COLUMNS = ("date", "ticker", "field", "value")


def _pivot_descriptors(
    df: pd.DataFrame, field_map: dict[str, str]
) -> pd.DataFrame:
    """Pivot a long descriptors frame to a wide [Date, Ticker] panel.

    Only ``field`` values present in ``field_map`` are kept; the resulting
    columns are renamed to the standard panel names.
    """
    missing = set(REQUIRED_DESCRIPTOR_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"descriptors frame missing columns: {sorted(missing)}")

    kept = df[df["field"].isin(field_map)].copy()
    kept["field"] = kept["field"].map(field_map)
    wide = kept.pivot_table(
        index=["date", "ticker"],
        columns="field",
        values="value",
    )
    wide.columns.name = None
    return wide


def build_panel() -> pd.DataFrame:
    """Assemble the standard market panel.

    Returns
    -------
    pd.DataFrame
        MultiIndex ["Date", "Ticker"], columns per the contract above,
        sorted by [Date, Ticker].
    """
    # 1. Prices -> px_last (also defines the canonical trading calendar)
    prices = pd.read_parquet(PRICES_PATH)
    px = prices.pivot_table(index=["date", "ticker"], values="close")
    px.columns = ["px_last"]
    px.columns.name = None

    # 2. Time-series descriptors
    ts = pd.read_parquet(DESC_TS_PATH)
    ts_wide = _pivot_descriptors(ts, TS_FIELD_MAP)

    # 3. Quarterly descriptors (already daily-aligned in barra_research)
    q = pd.read_parquet(DESC_Q_PATH)
    q_wide = _pivot_descriptors(q, Q_FIELD_MAP)

    # 4. Industries (static per ticker)
    ind = pd.read_parquet(INDUSTRIES_PATH)
    ind = ind.rename(
        columns={
            "gics_sector": "gics_sector",
            "gics_industry_grp": "gics_industry_group",
            "gics_sub_ind": "gics_sub_industry",
        }
    )
    ind = ind.set_index("ticker")[["gics_sector", "gics_industry_group", "gics_sub_industry"]]

    # 5. Join everything on the price index (date, ticker)
    panel = px.join(ts_wide, how="left").join(q_wide, how="left")
    # broadcast static industry labels across every date for each ticker
    panel = panel.join(ind, on="ticker", how="left")

    panel.index = panel.index.set_names(["Date", "Ticker"])
    panel = panel.sort_index(level=["Date", "Ticker"])

    # Defensive: ensure all contract columns exist even if a source field is absent
    contract_cols = (
        ["px_last"]
        + list(TS_FIELD_MAP.values())
        + list(Q_FIELD_MAP.values())
        + ["gics_sector", "gics_industry_group", "gics_sub_industry"]
    )
    for col in contract_cols:
        if col not in panel.columns:
            panel[col] = float("nan")

    return panel[contract_cols]


def load_returns() -> pd.DataFrame:
    """Load raw total-return index as a [Date, Ticker] panel.

    Returns the total return index (``tr``) untouched; daily returns are
    derived downstream in ``risk.exposures`` with proper point-in-time
    alignment.
    """
    returns = pd.read_parquet(RETURNS_PATH)
    tr = returns.pivot_table(index=["date", "ticker"], values="tr")
    tr.columns = ["tr"]
    tr.columns.name = None
    tr.index = tr.index.set_names(["Date", "Ticker"])
    return tr.sort_index(level=["Date", "Ticker"])


if __name__ == "__main__":
    p = build_panel()
    print(f"panel shape: {p.shape}")
    print(f"columns: {list(p.columns)}")
    print(f"date range: {p.index.get_level_values('Date').min()} -> "
          f"{p.index.get_level_values('Date').max()}")
    print(f"tickers: {p.index.get_level_values('Ticker').nunique()}")
    print(p.head())

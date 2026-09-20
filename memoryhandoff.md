# AlphaStream Memory Handoff

> Updated: 2026-09-20
>
> Purpose: a concise, source-of-truth handoff for the next developer or
> researcher. Read this before modifying the factor, risk, or backtest layers.

## 1. What this project is

AlphaStream is a multi-factor equity **risk-model research project**, not yet a
production alpha strategy.

The current main research line uses Bloomberg US/SPX data and produces a
Barra-style decomposition:

```text
raw market data
  -> standard [Date, Ticker] panel
  -> 10 factor exposures X
  -> daily cross-sectional factor-return regression
  -> factor covariance F + specific variance D
  -> asset covariance Sigma = X F X' + D
  -> constrained minimum-variance portfolios
  -> strict walk-forward OOS validation
```

The historical HK files and the web/email application are legacy or separate
workstreams. Do not mix HK results with the US/SPX factor model.

## 2. Ownership and boundaries

| Area | Owner / module | Responsibility |
|---|---|---|
| Data + factor exposures | Zeon / `factors/` | Build point-in-time X |
| Risk model | Kani / `risk/` | Estimate f, F, D and Sigma |
| Portfolio construction | shared / `portfolio/` | Constrained min-variance optimization |
| OOS validation | `step1_outsample_backtesting/` | Walk-forward backtests and risk diagnostics |

The explicit handoff artifact from Zeon to Kani is:

```text
Data/Processed/exposures.parquet
Data/Processed/exposures_meta.json
```

## 3. Current data and X contract

### US source

- Local source: `Data/Raw/us_market_raw.xlsx`.
- Universe: Bloomberg SPX data; 501 usable tickers in the current output.
- Date range: 2024-01-02 through 2025-12-31.
- Standard panel index: `MultiIndex(["Date", "Ticker"])`.
- Panel fields: `px_last`, `market_cap`, `pb`, `earn_yld`, `volume`, `beta`,
  `growth_sales`, `growth_eps`, `leverage`, and GICS industry fields.

### Final X

`Data/Processed/exposures.parquet` currently has **250,121 rows x 10 columns**:

```text
size, value, earn_yld, momentum, volatility,
beta, liquidity, growth_sales, growth_eps, leverage
```

Rules:

- Index is unique and sorted by `Date, Ticker`.
- Date=t uses data available at or before t.
- Missing values remain `NaN`; no silent zero filling.
- No infinities are allowed.
- Factor-column order is part of the contract and is recorded in metadata.

## 4. Factor pipeline

Key files:

```text
factors/base.py              common Factor input/output contract
factors/loaders.py           Bloomberg workbook -> standard panel
factors/{size,value,...}.py  individual raw factor definitions
factors/transforms.py        daily transforms
factors/pipeline.py          orchestration, validation, persistence
factors/validate_factors.py  IC / Rank IC / Newey-West / admission framework
Data/generate_exposures.py   production entry point for X
```

Raw definitions:

| Factor | Raw definition |
|---|---|
| `size` | `log(market_cap)` |
| `value` | `-log(pb)`; lower PB means higher value exposure |
| `earn_yld` | Bloomberg earnings yield |
| `momentum` | `P(t-21) / P(t-252) - 1` |
| `volatility` | 60-day return volatility, annualized |
| `beta` | Bloomberg adjusted beta |
| `liquidity` | `log(60-day mean volume)` |
| `growth_sales` | Bloomberg sales-growth descriptor |
| `growth_eps` | Bloomberg EPS-growth descriptor |
| `leverage` | Bloomberg debt-to-common-equity descriptor |

Production transforms, configured in `PipelineConfig`:

```text
daily winsorization: 2.5% / 97.5%
daily z-score: ddof=0
neutralization: GICS sector + log(market_cap)
orthogonalization: only where |cross-sectional correlation| > 0.70
```

## 5. Risk and portfolio layers

`risk/` implements the intended model:

```text
r = X f + eps
Sigma = X F X' + D
```

- `risk/exposures.py`: loads X and aligns stock returns.
- `risk/covariance.py`: daily cross-sectional regression, Ledoit-Wolf factor
  covariance, diagonal specific variance, and asset covariance construction.
- `risk/analytics.py`: portfolio exposures, risk decomposition, volatility
  self-check.
- `portfolio/optimizer.py`: long-only min-variance optimizer with position,
  turnover, factor, industry, and benchmark-deviation constraints.

The backtest implementation adds a **market constant factor internally** when
estimating risk. The official `exposures.parquet` still contains only the ten
Zeon style-factor columns.

## 6. Walk-forward validation

Key files:

```text
step1_outsample_backtesting/walk_forward.py
step1_outsample_backtesting/run_backtest.py
step1_outsample_backtesting/robustness.py
step1_outsample_backtesting/three_layer_validation.py
step1_outsample_backtesting/risk_calibration.py
```

At every rebalance date t:

```text
use only dates before t to estimate F, D, and Sigma
-> choose weights at t
-> apply them only to t+1 and later holding-period returns
-> deduct transaction costs
```

Current artifacts include `backtest_daily.parquet`, `backtest_weights.parquet`,
`backtest_metrics.json`, risk-calibration reports, bootstrap reports, and
three-layer validation reports.

The newest machine-readable baseline (`backtest_metrics.json`) has 219 OOS
daily observations. Its Barra minimum-variance result is approximately:

```text
annualized return       1.74%
annualized volatility  14.18%
Sharpe                  0.123
max drawdown           -9.94%
```

This does **not** outperform the current simple sample-covariance, equal-weight,
or market-cap-weighted benchmarks. The correct conclusion is that the pipeline
is operational, not that the strategy is investment-ready.

## 7. Known limitations and next priorities

1. **Only about two years of US history.** This is far too short for reliable
   risk-model calibration. Obtain same-definition US data for 2019-2023, then
   rebuild X and rerun all validation.
2. **Risk forecast validation has not passed.** The 60-day risk window is the
   best current candidate by median error, but forecast-realized correlation is
   weak. Do not label it production-ready.
3. **Run and persist factor admission results.** `validate_factors.py` exists,
   but a formal current IC / Rank IC / Newey-West admission artifact is not
   present in `Data/Processed/`.
4. **Make `Data/build_panel.py` portable.** It hard-codes Kani's local
   `/Users/gaokanglin/.../barra_research/...` path. Use a config value,
   environment variable, or function argument instead.
5. **Do not mix HK and US research.** HK is a separate validation branch with
   different fields and market structure.
6. **Delay API/web productization.** The legacy `Src/` web/email layer is not
   the current research bottleneck.

## 8. Test status on 2026-09-20

```text
153 passed, 4 failed
```

The four failures are integration tests in `tests/test_risk.py`, all caused by
the missing hard-coded external `barra_research` parquet directory. They are
not factor-formula failures. Once the data bridge is configurable, these tests
should be run again with an available source directory.

## 9. Recommended reading order

1. `COLLABORATION_PLAN.md` — ownership and X contract.
2. `factors/readme.md` — factor-module handoff and pipeline details.
3. `Data/generate_exposures.py` — production X entry point.
4. `risk/covariance.py` — Barra equations in code.
5. `step1_outsample_backtesting/BACKTEST_REPORT.md` — what current results do
   and do not prove.

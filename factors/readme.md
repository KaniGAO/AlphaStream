# AlphaStream Factors 模組交付文件

## 1. 交付結論

`factors/` 已達到可交付狀態，可以交由 Kani 的 `risk/` 模組消費。

本模組已完成：

- 從 Bloomberg USE4 Excel 工作簿建立標準 point-in-time panel。
- 計算 10 個 raw factor exposures。
- 逐日執行 Winsorize、Z-score、行業／市值中性化與選擇性正交化。
- 驗證並輸出最終因子暴露矩陣 `X`。
- 輸出資料來源、處理參數、資料範圍及驗證狀態 metadata。
- 計算 IC、Rank IC、ICIR、Newey-West t-stat、覆蓋率、分組收益及因子相關矩陣。
- 產生 `accepted / candidate / rejected` 因子准入結果。

`risk/` 的以下工作不屬於本交付範圍，由 Kani 實作：

```text
r = X · f + ε
Σ = X · F · X' + D
```

## 2. 模組邊界

```text
Bloomberg Excel
        │
        ▼
loaders.py
標準 Date/Ticker panel
        │
        ▼
10 個 Factor.compute(panel)
        │
        ▼
raw exposure matrix
        │
        ▼
transforms.py
Winsorize → Z-score → Neutralize → Orthogonalize
        │
        ▼
pipeline.py
驗證、排序、metadata、Parquet/JSON
        │
        ├──────────────► exposures.parquet
        └──────────────► exposures_meta.json
                               │
                               ▼
validate_factors.py
IC / Rank IC / ICIR / NW t-stat / 分組收益 / 准入
        │
        ▼
Kani risk/
```

責任邊界：

| 模組 | 責任 | 不負責 |
|---|---|---|
| `loaders.py` | 讀取 Excel、標準化欄位、建立 Date/Ticker panel | 因子公式及風險模型 |
| `base.py` | Factor 輸入輸出共同契約 | 具體因子公式 |
| 各因子文件 | point-in-time raw exposure | 統一截尾、中性化及落盤 |
| `transforms.py` | 可重用的逐日橫截面變換 | 經濟因子定義 |
| `pipeline.py` | 編排、驗證、落盤及 metadata | 因子收益與風險協方差 |
| `validate_factors.py` | 預測力、覆蓋率、共線性及准入評估 | 修改 exposure 以追求顯著 |
| Kani `risk/` | 因子收益、因子協方差及特異風險 | 重算或改寫因子暴露 |

## 3. 標準 panel 契約

輸入 panel 必須是 `pandas.DataFrame`：

```text
index  = MultiIndex(["Date", "Ticker"])
Date   = datetime-like
Ticker = 股票識別碼
每個 (Date, Ticker) 唯一
```

完整 USE4 loader 目前輸出欄位：

```text
px_last
market_cap
pb
earn_yld
volume
beta
growth_sales
growth_eps
leverage
gics_sector
gics_industry_group
gics_sub_industry
```

缺失資料必須保留為 `NaN`，不得靜默填成零或使用未來資料回填。

## 4. Point-in-time 因子定義

以下表格是本模組的無前視洩漏硬約束：

| 因子 | 標準輸入 | Raw exposure 定義 | Point-in-time 規則 |
|---|---|---|---|
| `size` | `market_cap` | `log(market_cap)` | 直接使用 t 日市值 |
| `value` | `pb` | `1 / pb` | 使用生效日期不晚於 t 的 Bloomberg descriptor |
| `earn_yld` | `earn_yld` | 原始盈利收益率 | 使用生效日期不晚於 t 的 descriptor |
| `momentum` | `px_last` | 252–21 日價格收益 | 只使用 t 日及以前價格 |
| `volatility` | `px_last` | 60 日收益標準差 × `sqrt(252)` | 只使用 t 日及以前價格 |
| `beta` | `beta` | Bloomberg beta descriptor | 直接使用已時點對齊 descriptor |
| `liquidity` | `volume` | `log(60 日平均成交量)` | 只使用 t 日及以前成交量 |
| `growth_sales` | `growth_sales` | Bloomberg 銷售成長 descriptor | 使用生效日期不晚於 t 的值 |
| `growth_eps` | `growth_eps` | Bloomberg EPS 成長 descriptor | 使用生效日期不晚於 t 的值 |
| `leverage` | `leverage` | Bloomberg槓桿 descriptor | 使用生效日期不晚於 t 的值 |

價格、成交量、shift 和 rolling 必須先按 `Ticker` 分組。窗口不足、輸入缺失、價格非正或成交量非正時保留 `NaN`。

## 5. 最終 exposure 處理契約

`PipelineConfig` 的生產預設：

```text
Winsorize             = 每日 2.5% / 97.5%
Z-score ddof          = 0
Industry neutralize   = gics_sector
Size neutralize       = log(market_cap)
Orthogonalize trigger = |ρ| > 0.70
```

統一順序：

```text
raw exposure
    ↓
每日 Winsorize
    ↓
每日 Z-score
    ↓
可選：行業及市值中性化
    ↓
可選：按因子列順序進行選擇性正交化
    ↓
final X
```

正交化保留列順序的經濟優先級。第一個因子保持不變；後序因子只在與前序因子的日截面相關性滿足 `|ρ| > 0.70` 時，才對相關前序因子回歸並取殘差。

## 6. 交付給 Kani 的 X 契約

正式輸出文件：

```text
exposures.parquet
exposures_meta.json
```

`exposures.parquet`：

```text
type    = pandas.DataFrame
index   = MultiIndex(["Date", "Ticker"])
columns = [
    "size",
    "value",
    "earn_yld",
    "momentum",
    "volatility",
    "beta",
    "liquidity",
    "growth_sales",
    "growth_eps",
    "leverage",
]
```

交付保證：

- Index 已按 `Date, Ticker` 排序且唯一。
- 不包含 `Date > as_of` 的資料。
- 所有 factor columns 都是 numeric dtype。
- 不包含 `+inf` 或 `-inf`。
- 缺失 exposure 保持 `NaN`。
- 列順序固定，metadata 同時記錄該順序。

Kani 使用時必須：

- 以 `Date/Ticker` 顯式對齊股票收益和 `X`。
- 不可把缺失 exposure 自動填成零，除非 risk 模組另有已記錄的處理契約。
- 不可改變因子列名或列順序而不同步更新 metadata。
- 估計每個日期的因子收益前，先確認當日有效股票數及矩陣秩。

## 7. 產生正式 exposure 產物

```python
from pathlib import Path

from factors.beta import BetaFactor
from factors.earn_yld import EarningsYieldFactor
from factors.growth_eps import EPSGrowthFactor
from factors.growth_sales import SalesGrowthFactor
from factors.leverage import LeverageFactor
from factors.liquidity import LiquidityFactor
from factors.loaders import load_us_market_workbook
from factors.momentum import MomentumFactor
from factors.pipeline import PipelineConfig, run_pipeline
from factors.size import SizeFactor
from factors.value import ValueFactor
from factors.volatility import VolatilityFactor


panel = load_us_market_workbook("Data/Raw/us_market_raw.xlsx")

factors = [
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

result = run_pipeline(
    panel,
    factors,
    PipelineConfig(
        as_of="2025-12-31",
        neutralize=True,
        orthogonalize=True,
        correlation_threshold=0.70,
        output_dir=Path("Data/Processed/factors"),
        universe_name="SPX Index",
        overwrite=False,
    ),
)

print(result.exposures_path)
print(result.metadata_path)
```

第一次正式執行建議使用 `overwrite=False`。需要覆蓋既有正式產物時，應由操作者明確改為 `overwrite=True`。

## 8. 因子驗證

`forward_returns` 是驗證 label，只能使用未來價格建立，不得回流到 exposure pipeline：

```python
from factors.validate_factors import (
    FactorValidationConfig,
    validate_factors,
    write_validation_report,
)


prices = panel["px_last"].sort_index(level=["Ticker", "Date"])
forward_returns = (
    prices.groupby(level="Ticker", sort=False)
    .shift(-21)
    .div(prices)
    .sub(1)
    .reindex(result.exposures.index)
    .rename("forward_return_21d")
)

validation = validate_factors(
    result.exposures,
    forward_returns,
    FactorValidationConfig(
        forward_horizon=21,
        quantiles=5,
        newey_west_lags=5,
        min_cross_section=20,
        min_dates=60,
    ),
)

report_paths = write_validation_report(
    validation,
    "Data/Processed/factor_validation",
    overwrite=False,
)
```

驗證產物：

```text
factor_metrics.parquet
daily_ic.parquet
quantile_returns.parquet
factor_correlations.parquet
factor_validation.json
```

准入規則預設：

| 狀態 | 規則 |
|---|---|
| `accepted` | 有效日期達標，`abs(mean_rank_ic) >= 0.03`、`abs(NW t) >= 2.0`、coverage ≥ 70% |
| `candidate` | 有效日期達標，`abs(mean_rank_ic) >= 0.01`、coverage ≥ 50% |
| `rejected` | 未通過以上門檻 |

准入結果是研究診斷，不應由 risk 模組硬編碼成永久因子清單。

## 9. 完整 Excel 驗收結果

驗收資料：

```text
Data/Raw/us_market_raw.xlsx
```

最近一次完整端到端結果：

| 項目 | 結果 |
|---|---:|
| 原始 Universe | 503 |
| 有價格觀察的 Ticker | 501 |
| 標準 panel | 250,121 × 12 |
| 最終 X | 250,121 × 10 |
| 日期範圍 | 2024-01-02 至 2025-12-31 |
| 21 日未來收益覆蓋率 | 95.79% |
| Loader 耗時 | 約 7 秒 |
| 10 因子完整 pipeline | 約 122 秒 |
| 因子驗證 | 約 6.5 秒 |
| 完整流程 | 約 135 秒 |

正交化後，每日最大絕對因子相關性的全樣本最大值為約 `0.6903`，低於 `0.70` 門檻。

最近一次驗收生成並成功回讀：

```text
exposures.parquet
exposures_meta.json
factor_metrics.parquet
daily_ic.parquet
quantile_returns.parquet
factor_correlations.parquet
factor_validation.json
```

## 10. 測試與驗收命令

執行全部單元測試：

```bash
python -m pytest -q
```

目前基線：

```text
143 passed
```

測試覆蓋：

- Factor 公共輸入輸出契約。
- 每個 raw factor 的公式及缺失值處理。
- 多股票隔離和亂序索引。
- Point-in-time／不讀取未來資料。
- Winsorize、Z-score、中性化和正交化。
- 多日期中性化。
- Pipeline schema、as_of、落盤及 metadata。
- IC、Rank IC、ICIR、Newey-West、分組收益和准入。
- Parquet/JSON 寫入、回讀和防意外覆蓋。

## 11. 已知限制及交付注意事項

1. 原始 Universe 有 503 只股票，但價格 observation grid 實際包含 501 只。`X` 只包含有價格記錄的股票；Kani 不應假設每天固定有 503 行。
2. Momentum 需要 252 日 lookback，在約兩年歷史中自然具有較高缺失率。
3. Volatility 需要 60 個日收益，Liquidity 需要 60 個成交量觀察，初始窗口保留 `NaN`。
4. Fundamental descriptor 的 point-in-time 語義依本項目已確認的 Bloomberg 歷史資料契約處理。若未來更換資料源，必須重新驗證 effective/availability date。
5. 完整 25 萬行 pipeline 目前約需兩分鐘；功能已通過，但逐日 OLS 仍有向量化優化空間。
6. 測試中的端到端產物使用臨時目錄並自動刪除。正式交付文件需由第 7 節命令寫入指定 `Data/Processed` 目錄。
7. `factors/` 不估計因子收益、因子協方差或特異風險；這些工作由 Kani 的 `risk/` 模組完成。

## 12. 交付狀態

```text
Factor definitions                 PASS
Point-in-time contracts            PASS
10-factor raw exposure matrix      PASS
Cross-sectional transforms         PASS
Industry/size neutralization       PASS
Selective orthogonalization        PASS
Parquet and metadata output        PASS
Factor validation and admission    PASS
Full Excel end-to-end test         PASS
Unit test suite                     143 passed
Risk model handoff                  READY
```

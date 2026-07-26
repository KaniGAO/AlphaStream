# AlphaStream 协作方案：分工与协调（Zeon × Kani）

> 背景：Kani 看了 `OPTIMIZATION_PLAN.md` 后认可方向，提出两点：
> 1. 先确认**数据够不够用**；
> 2. **数据存储 / 清洗 / 因子构建 / 风险分析要拆到不同文件夹，用 `.py` 而不是 `.ipynb`**；
>    并明确分工：**Kani 做风险分析（Barra 等），Zeon 做因子构建**。
>
> 本文档：① 对"数据够不够用"的回答（可直接转发 Kani）；② **详细协调手册**——X 契约精确规格、双方代码骨架、分阶段时间表、git 流程、接口防错。

> ⚠️ **市场变更（2026-07-26）**：原项目基于港股（`hk_market_raw.parquet`，字段薄）。经评估，因子构建改用 **Bloomberg `USE4` 美股模板**（SPX 503 只，日频 2024–2025，字段齐全且 point-in-time 友好）。下文所有口径（Ticker 格式、因子定义、股票池、话术）已同步切到美股；方法学 / X 契约 / 架构不变。

---

## 一、给 Kani 的回答：数据够不够用？

**结论：换成 Bloomberg `USE4` 美股模板后，字段广度已不再是瓶颈——市值 / PB / 盈利收益率 / 行业 / 成长 / 杠杆全部齐备，且 point-in-time 内建；剩下的真实约束只剩「2 年样本偏短」和「依赖 BBG 终端刷新」。**

### 1. 数据现状（已核实，USE4 美股模板）
| 项 | 实际情况 |
|---|---|
| 来源 | Bloomberg `USE4` 批量拉数模板（Bloomberg 时间序列，逐证券独立公式） |
| 范围 | `SPX Index`，**503 只美股**，日频，**2024-01-01 → 2025-12-31**（约 2 年） |
| Prices | 每券 `[日期, PX_LAST]`，共 503×2 列 → Momentum / Volatility / Beta 可由价格派生 |
| Descriptors | 每券块 8 字段：`CUR_MKT_CAP`(市值) / `PX_TO_BOOK_RATIO`(PB) / `EARN_YLD`(盈利收益率) / `VOLUME` / `BETA_ADJ_OVERRIDABLE` / `SALES_GROWTH` / `EPS_GROWTH` / `TOT_DEBT_TO_COM_EQY`(杠杆) |
| 行业 | `Industries` 页给 GICS 三级分类（行业中性化 / 行业哑变量可用） |
| 时点性 | Descriptor 每个观测**自带生效日期**（财报期），天然 point-in-time，无需 `shift(60)` 近似 |

### 2. 真正的缺口（按重要性排序）
- **样本只有 2 年（2024–2025）**：因子 IC/IR、walk-forward 回测偏薄（通常想要 5–10 年）。做学习原型、跑通 X **够**；要严谨结论需把 `history_start` 往前扩或改 `PERIOD='M'`。→ 见 §2.4 Phase 0 与 Phase 2.5。
- **依赖 BBG 终端刷新**：模板数值来自一次拉取，换日期/标的需在 Bloomberg Excel `Ctrl+Alt+F` 刷新。刷新不了则数据冻结在 2024–2025、503 只（仍够原型）。
- **Quality（盈利/ROE）暂缺**：Descriptor 无 ROE/ROA/净利率，真·质量因子做不了。可暂缓，或日后补拉 `RETURN_ON_EQUITY` 等字段。其余维度（价值/成长/杠杆/规模/波动/流动/动量/行业）均已覆盖。
- **协方差需收缩**：即便全市场 503 只，2 年日频对因子协方差 `F` 仍偏短 → 因子收益 `f` 的时序必须用 **Ledoit-Wolf 收缩**（见 §2.3 / 方法学修正）。

### 2.5 补数据行动项（明确 owner + 状态）
- [ ] **扩样本区间**（把 `history_start` 往前，或 `PERIOD='M'` 降负载）—— owner：**Zeon**，deadline：Phase 2.5 前，状态：未开始
- [ ] **（可选）补 Quality 字段** `RETURN_ON_EQUITY` / `RETURN_ON_ASSET` —— owner：**Zeon**，状态：未开始（不影响首版 10 因子）
- [ ] 在 `exposures_meta.json` 显式标注因子覆盖与数据区间，避免 Kani 误判维度完整性。

### 3. 一句话回 Kani
> "美股 `USE4` 模板字段齐全（市值/PB/盈利收益率/行业/成长/杠杆），point-in-time 内建，全市场 503 只——撑得起 Barra 风险模型，10 个因子直接能建。两个前提：(1) 样本仅 2024–2025 两年，回测偏薄，我会在 Phase 2.5 用 walk-forward + 样本外验证；(2) 数据靠 BBG 模板刷新，刷新不了就冻结在这区间。协方差交给你时我用 Ledoit-Wolf 收一下。"

---

# 二、详细协调手册（下一步 + 怎么协调）

## 2.1 核心洞察：你们只在"因子暴露矩阵 X"上握手

这是整个协作的支点，先讲透。

Barra 的收益模型是：

```
r = X · f + ε
```

- `r`：个股的收益率向量
- `X`：**因子暴露矩阵**（每行一只股票，每列一个因子，值是该股票对该因子的暴露度）
- `f`：因子收益（各因子的回报）
- `ε`：个股特异收益（不能被因子解释的残差）

协方差分解：

```
Σ = X · F · X' + D
```

- `F`：因子协方差矩阵（由 `f` 估计）
- `D`：特异方差对角矩阵（由 `ε` 估计）

**关键：这个 `X` 就是 Zeon 建出来的因子暴露矩阵。** Zeon 负责把原始数据变成 `X`，Kani 负责把 `X` 变成 `Σ`。两人之间**只有一个交接物 `X`**，没有别的耦合。所以：

> **协作的本质 = 先把 `X` 的规格钉死，然后各写各的，最后在 `X` 上对接。**

谁写错 `X` 的格式，对接就会崩；所以 **X 契约先于一切实现**。

---

## 2.2 X 契约的精确规格（必须最先对齐）

### 2.2.1 物理形态
- 落地文件：`data/processed/exposures.parquet`
- 索引：`MultiIndex([Date, Ticker])`，按 Date 升序
- 列：每个因子一列，列名用 snake_case 因子名（见 §2.2.3，共 10 个：`size` / `value` / `earn_yld` / `momentum` / `volatility` / `beta` / `liquidity` / `growth_sales` / `growth_eps` / `leverage`）
- Ticker 格式：统一 `XXXX US Equity`（如 `AAPL US Equity`）

**一个具体的切片长这样**（注意：值是横截面 z-score，无量纲）：

| Date | Ticker | size | value | earn_yld | momentum | volatility | beta | liquidity | growth_sales | growth_eps | leverage |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2025-06-30 | AAPL US Equity | 1.95 | 0.11 | 0.05 | 1.10 | -0.55 | 0.30 | 0.42 | 0.20 | 0.15 | -0.10 |
| 2025-06-30 | MSFT US Equity | 1.80 | 0.05 | 0.04 | 0.95 | -0.40 | 0.25 | 0.38 | 0.18 | 0.12 | -0.08 |
| 2025-06-30 | JPM US Equity | 1.20 | -0.20 | 0.09 | 0.60 | 0.10 | 0.80 | 0.25 | 0.05 | 0.10 | 0.30 |
| … | … | … | … | … | … | … | … | … | … | … | … |
| 2025-07-01 | AAPL US Equity | 1.93 | 0.10 | 0.05 | 1.08 | -0.53 | 0.29 | 0.41 | 0.19 | 0.14 | -0.10 |

### 2.2.2 每个值的计算规则（写进 `factors/pipeline.py`，两边都要信）
1. **Winsorize**：每个因子在每个交易日做横截面截尾（2.5% / 97.5%），去掉极端值。
2. **z-score**：截尾后，每个交易日对该因子横截面标准化（减均值÷标准差）。
2.5 **行业中性化 / 正交化**（推荐）：z-score 后，对每个因子在每日截面对行业哑变量（或已确定的其他因子）回归取残差，剔除行业 / 其他因子干扰，使暴露更纯净。Barra 风格风险模型尤其需要。若暂无行业分类数据，先跳过并在 `exposures_meta.json` 标注。
3. **Point-in-time**：`Date=t` 的值只允许用 `≤t` 的信息。各因子的具体取法见下表。

### 2.2.3 每个因子的 point-in-time 取法（这是"无前视泄漏"的硬约束）

| 因子 | 原始输入 | point-in-time 处理 | 现在数据能否做 |
|---|---|---|---|
| `size` | `CUR_MKT_CAP` | 直接用 t 日市值（市值本身即时点） | ✅ 可做 |
| `value` | `PX_TO_BOOK_RATIO` | 取 descriptor 生效日期（财报期）≤ t 的值，无需 `shift(60)` | ✅ 可做（BP，point-in-time 内建） |
| `earn_yld` | `EARN_YLD` | 同上，取生效日期 ≤ t | ✅ 可做（盈利收益率，point-in-time 内建） |
| `momentum` | `PX_LAST` | 用 t 日及之前的价格算"12-1 月"收益率（不含 t 之后） | ✅ 可做（由价格派生） |
| `volatility` | `PX_LAST` | 用 t 日及之前的日收益算滚动波动率（如 60 日） | ✅ 可做（由价格派生） |
| `beta` | `BETA_ADJ_OVERRIDABLE` | 直接用 descriptor（BBG 已时点对齐） | ✅ 可做 |
| `liquidity` | `VOLUME` | 用 t 日及之前的成交量（或金额成交量） | ✅ 可做 |
| `growth_sales` | `SALES_GROWTH` | 取生效日期 ≤ t 的财报成长值 | ✅ 可做（point-in-time 内建） |
| `growth_eps` | `EPS_GROWTH` | 同上 | ✅ 可做（point-in-time 内建） |
| `leverage` | `TOT_DEBT_TO_COM_EQY` | 取生效日期 ≤ t 的杠杆值 | ✅ 可做（point-in-time 内建） |
| `quality` | ROE/ROA | 需 point-in-time 盈利数据 | ❌ 当前 Descriptor 无，暂缓（可补拉 `RETURN_ON_EQUITY`） |

> **对 Kani 的含义**：现在能稳定交付上表 10 个因子（价值家族含 `value`+`earn_yld` 两个子因子）。`quality` 因缺 ROE 暂不做；行业维度由 `Industries` 页提供，用于中性化而非进 X。每个因子进 X 前须过 §2.2.6 准入门槛。

### 2.2.4 NaN 与版本
- 某股票某日因子为 NaN（如新股无足够历史算 momentum）：**Zeon 在 X 里留 NaN，不偷偷填 0**。
- Kani 读 X 时，**对该交易日截面丢弃任何含 NaN 的股票**（文档化此规则），保证进模型的截面完整。
- 配套 `data/processed/exposures_meta.json`：
  ```json
  { "generated_at": "2026-07-23T00:30:00", "as_of_max": "2025-12-31",
    "factors": ["size","value","earn_yld","momentum","volatility","beta","liquidity","growth_sales","growth_eps","leverage"], "universe_size": 503 }
  ```
  这样 Kani 一眼知道这份 X 覆盖了哪些因子、到哪天、多少只股票。

### 2.2.5 Point-in-time 验证（防前视泄漏）
X 里每个值都声明了"只用 ≤t 的信息"，但声明不等于真的没有泄漏，必须验证：
- **信息流向检验**：对每个因子，构造"用 t 日因子预测 t+1 日收益"的 IC；若改用 t+1 日才可得的信息 IC 显著更高，说明原处理有泄漏。
- **生效日期对齐检验**：对带财报期的 descriptor（`value`/`earn_yld`/`growth_*`/`leverage`），抽样核对其生效日期 ≤ t，确认无未来信息泄漏（美股模板已内建，验证即可，无需再 `shift(60)`）。
- **结论写进 meta**：通过 / 近似通过（标注代理方式）/ 不通过（该因子暂不进 X）。

### 2.2.6 因子准入门槛（防 K 过大 + 防共线）⚠️ 重要
进 X 的每一列都必须二选一成立，否则不进 B：
1. **有清晰经济含义**（本方案 10 因子全部映射到 Barra 风格家族：Size / Value / Momentum / Volatility / Beta / Liquidity / Growth / Leverage，满足）；**且**
2. **通过统计显著性**：用 **Fama-MacBeth**（§28，风险溢价存在性，比截面 IC 更硬）或至少 Newey-West t 的 IC 检验，要求 `|t| > 2`。

具体处置：
- **相关因子对正交化（§15.4）**：`value`↔`earn_yld`（同属价值）、`growth_sales`↔`growth_eps`（同属成长）、`volatility`↔`beta`（同测风险）、`size`↔`liquidity`（小盘常低流动）存在中等相关。进 X 前对相关性超阈值（两两 `|ρ| > 0.7`）的因子对做正交化（对被解释因子回归取残差），隔离重叠维度；证明无独立溢价的子因子直接砍。
- **K 上限 + Δ 对角（防 T<N 塌方）**：因子数 `K` 设上限 **≤ 15**（当前 T≈500 交易日，K 逼近 50+ 才需 PCA §9）；协方差分解 `Σ = X·F·Xᵀ + D` 中 **`D` 必须只估对角**（每只股票残差方差），**禁止估全 N×N 残差协方差**——因子模型本身就是 T<N 的解药，塌方只来自错误实现。因子协方差 `F`（K×K）用 Ledoit-Wolf（§10）/ EWMA（§24）收缩作为后手保险。

*括号中的 § 编号对应 Zeon 的方法论文档：§9=PCA 降维 / §10=Ledoit-Wolf 收缩 / §15.4=正交化 / §24=EWMA / §28=Fama-MacBeth。*

---

## 2.3 双方代码骨架（让对接零歧义）

### Zeon 侧（`factors/`）

`factors/base.py` —— 因子基类 + 注册表：
```python
from abc import ABC, abstractmethod
import pandas as pd

class Factor(ABC):
    name: str                       # 如 "momentum"
    @abstractmethod
    def compute(self, panel: pd.DataFrame) -> pd.Series:
        """输入标准面板[index=Date,Ticker]，返回该因子的原始序列（未标准化）。"""
        ...

REGISTRY: dict[str, type[Factor]] = {}
def register(cls): REGISTRY[cls.name] = cls; return cls
```

`factors/pipeline.py` —— 产出 X（交接物）：
```python
import pandas as pd
from .base import REGISTRY
from ..data.loaders import load_panel
from ..data.schema import WINSOR_LO, WINSOR_HI

def _winsorize_zscore(series: pd.Series) -> pd.Series:
    lo, hi = series.quantile(WINSOR_LO), series.quantile(1 - WINSOR_HI)
    s = series.clip(lo, hi)
    return (s - s.mean()) / s.std()

def get_exposures(as_of) -> pd.DataFrame:
    panel = load_panel()                       # [Date,Ticker] 标准面板
    panel = panel[panel.index.get_level_values('Date') <= as_of]
    cols = {}
    for name, cls in REGISTRY.items():
        raw = cls().compute(panel)              # 各因子自行保证 point-in-time
        cols[name] = raw.groupby(level='Date').transform(_winsorize_zscore)
    X = pd.DataFrame(cols)
    return X.sort_index()
```

### Kani 侧（`risk/`）

`risk/exposures.py` —— 读 X，转成协方差：
```python
import pandas as pd
from sklearn.covariance import LedoitWolf
from pathlib import Path

def build_covariance() -> pd.DataFrame:
    X = pd.read_parquet("data/processed/exposures.parquet")
    # 对该截面丢弃含 NaN 的股票
    latest = X.xs(X.index.get_level_values('Date').max(), level='Date').dropna(how='any')
    # Barra: Σ = X·F·X' + D ；这里先用 Ledoit-Wolf 收缩特异部分
    lw = LedoitWolf().fit(latest.values)
    cov = pd.DataFrame(lw.covariance_, index=latest.index, columns=latest.index)
    return cov
```

> 上面是最小可用版。Kani 的"真·Barra"会在 `risk/covariance.py` 里把 `F`（因子协方差）和 `D`（特异方差）分开估，再合成 `Σ`——但**入口永远是读这份 X**。

> ⚠️ **方法学待修正（重要）**：上面最小可用版直接对暴露矩阵 `X`（横截面 z-score 标准化后、无量纲）做 Ledoit-Wolf，得到的是"**暴露的协方差**"，并非 Barra 定义的因子收益协方差 `F`。正确流程应是：① 取得个股收益 `r`（需在 X 的交接之外单独定义与传递，见下）；② 用 `r = X·f + ε` 回归估计因子收益 `f` 与特异收益 `ε`；③ 对 `f` 的时序做 Ledoit-Wolf 收缩得 `F`、对 `ε` 得 `D`；④ `Σ = X·F·Xᵀ + D`。`X` 本身是暴露不是收益，不能直接收缩。Phase 2 落实时按此修正，并在 `exposures_meta.json` 注明协方差来源。

### 集成入口（`main.py`）
```python
from factors.pipeline import get_exposures
from risk.exposures import build_covariance
from portfolio.optimizer import min_variance

X = get_exposures(as_of="2025-12-31")
cov = build_covariance()          # Kani 的消费点
w = min_variance(cov, max_pos=0.3)   # 组合层
print(w[w > 0.01].round(4))
```

---

## 2.4 分阶段时间表（谁在什么时候交什么）

### Phase 0 —— 对齐契约（30 分钟会议，第 1 天）
**目标：把 2.2 的 X 契约拍板，写入本文档即生效。**
会议必须产出以下决定，缺一个不开写：
- [ ] X 的列名清单（定 10 因子：`size`/`value`/`earn_yld`/`momentum`/`volatility`/`beta`/`liquidity`/`growth_sales`/`growth_eps`/`leverage`；`quality` 待补 ROE 后加）
- [ ] z-score / winsorize 参数（默认 2.5%/97.5%）
- [ ] NaN 处理规则（Kani 侧按日截面丢弃；备选：缺失因子用行业均值软填充，避免大范围丢股票，需在 meta 标注采用哪种）
- [ ] `as_of` 约定（用数据最新日；回测时由调用方传入）
- [ ] 股票池定义（`SPX Index`，503 只，写进 `config.py`，**不**硬编码子集）
- [ ] 因子相关性 / 冗余上限（如两两 |ρ| < 0.7，超出则砍 / 合并，避免 B 共线）
- [ ] 行业中性化约定（是否在 z-score 前对行业哑变量回归取残差；暂无行业数据则跳过并标注）
- [ ] 补数据 action：PB / 盈利(EPS·ROE) / 股息率 / 行业分类的 owner 与 deadline

### Phase 1 —— Zeon：数据 + 因子 + 验证（约 1 周）
交付物：
1. `data/loaders.py` + `data/schema.py`（标准面板，替代 notebook Cell 2–7）
2. `factors/base.py` + 各因子文件（`size.py` / `value.py` / `earn_yld.py` / `momentum.py` / `volatility.py` / `beta.py` / `liquidity.py` / `growth_sales.py` / `growth_eps.py` / `leverage.py`）
3. `factors/pipeline.py` 的 `get_exposures(as_of)`
4. **`validate_factors.py`**：每个因子输出 IC、IR、Newey-West t 值表
5. `tests/test_factors.py`
6. 把 `exposures.parquet` + `exposures_meta.json` 生成出来，发给 Kani 作为交接凭证

**Zeon 的自检门槛**：任何因子 IC 不显著（|t| < 2）就别进 X，先调或砍。另需输出**因子相关性矩阵**，两两 |ρ| 超过阈值（如 0.7）的因子对需说明或合并，避免 B 共线导致 Σ 病态。

### Phase 2 —— Kani：风险模型（约 1 周，可与 Phase 1 后半并行）
交付物：
1. `risk/exposures.py`（读 X）
2. `risk/covariance.py`（Barra：`Σ = X·F·X' + D`，Ledoit-Wolf 收缩 D）
3. `risk/analytics.py`（风险分解 / 归因）
4. `tests/test_risk.py`

**Kani 的自检门槛**：用历史收益回测，风险模型估的波动率要和真实实现波动率对得上（误差在合理范围）。

### Phase 2.5 —— 回测与验证（walk-forward + 样本外 + 成本，第 2 周中）
> 在动手集成前，先验证"因子 → 风险 → 组合"整条链路在历史样本外能否跑赢 / 控风险。这是结论可信度的硬门槛。
交付物 / 动作：
1. **walk-forward 滚动窗口**：每个窗口独立用截至 t 的 X 估 Σ、优化、在 t+1 持有，杜绝偷看未来。
2. **样本内 + 样本外都报**：年化收益、波动、Sharpe、最大回撤、换手率。
3. **内置交易成本模型**：佣金 + 印花税 + 市场冲击 + 滑点，回测必须扣除（否则收益虚高）。
4. **Deflated Sharpe Ratio**：校正多重检验 / 过拟合后的夏普，防伪显著。
5. 产出一份**历史回测报告**（区别于 Phase 3 的集成冒烟测试）。
自检门槛：样本外 Sharpe 显著为正且 ≤ 样本内（不过拟合）；换手成本未吞噬收益。

### Phase 3 —— 集成 + 组合（第 2 周末）
交付物：
1. `portfolio/optimizer.py`（min-variance，吃 Kani 的 Σ；**必须支持交易成本 / 换手率约束（turnover penalty），否则回测收益虚高**——成本在 Phase 2.5 的回测中扣除）
2. `main.py` 端到端跑通
3. 一个**集成冒烟测试**：在 fixtures 上 `data→factors→risk→portfolio` 跑通，断言各环节 shape 正确
4. 替换掉 notebook 里硬编码 10 只 + 样本协方差的旧逻辑

---

## 2.5 git 与工程流程（逐步）

1. **主干保护**：`main` 只接受 PR，不直接 push。
2. **分支约定**：
   - Zeon：`factor/zeon`（因子相关全在这）
   - Kani：`risk/kani`
   - 集成：`integrate`（Phase 3 开）
3. **PR 模板**（双方都要填）：
   ```
   改动模块：factors / risk / data / portfolio
   对接 X 契约？是/否（若改 X 格式，必须先在文档 2.2 更新并通知对方）
   测试：本地 pytest 通过
   自测门槛：因子 IC |t|>2 / 风险模型波动率对齐
   ```
4. **CI 冒烟测试**（Phase 3 后加）：每次 PR 跑 `pytest`，含端到端 `main.py` 小样本。
5. **数据不进 git**：`data/raw/*.parquet`、`data/processed/*.parquet` 写进 `.gitignore`；processed 由代码重算，任何人 `python main.py` 能复现。

---

## 2.6 接口防错（X 上最容易出的 5 个坑）

| 坑 | 现象 | 防法 |
|---|---|---|
| **列名不一致** | Zeon 写 `mom`，Kani 读 `momentum` | 列名以 `REGISTRY` + `exposures_meta.json` 为准，Kani 不硬编码字符串 |
| **日期错位** | Zeon 用收盘日，Kani 用公告日 | 全链路统一 `Date` = 交易日；point-in-time 由各因子内部处理 |
| **NaN  silently 填 0** | 新股被当"零暴露"拉低波动 | Zeon 留 NaN；Kani 按日截面 `dropna`，写入文档 |
| **截面不完整** | 某日只有 30 只，Kani 当全市场估 F | Kani 读 `exposures_meta.json` 的 `universe_size`，不足则告警 |
| **X 过期** | Zeon 改了因子但没重算 parquet | `exposures_meta.json` 带 `generated_at`；集成测试校验新鲜度 |

---

## 2.7 决策记录与异步协调

- 所有"改 X 契约 / 改股票池 / 加因子"的决定，**只改本文档对应小节**，不私下口头定。
- 文档即单一事实源（single source of truth）；PR 描述里贴文档章节链接。
- 卡住时：先在文档对应 section 下加 `## 待决` 条目，写明选项和各自利弊，对方在 PR 或评论里拍板，再回填结论。

---

## 2.8 给 Kani 的协调话术（直接发）

> "我按你说的把代码 `.py` 化、按 data/factors/risk 拆目录了。我们俩的唯一交接面是**因子暴露矩阵 X**（[Date,Ticker] 索引、横截面 z-score、point-in-time），我负责产出、你负责吃进 Barra。
> 数据我换成 Bloomberg `USE4` 美股模板（SPX 503 只，2024–2025）：字段齐全（市值/PB/盈利收益率/行业/成长/杠杆），point-in-time 内建，10 个因子直接能建，不用再补拉。两个前提你知悉：(1) 样本仅两年，回测偏薄，我会在 Phase 2.5 用 walk-forward + 样本外验证；(2) 数据靠 BBG 模板刷新，刷新不了就冻结在这区间。
> 开始前先对一下 X 的列（我拟了 10 个：size/value/earn_yld/momentum/volatility/beta/liquidity/growth_sales/growth_eps/leverage）和格式，我把 `get_exposures(as_of)` 定好就先写因子 + Fama-MacBeth / IC-IR 验证。股票池用全市场 503 只，不提前切子集。"

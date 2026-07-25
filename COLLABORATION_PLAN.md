# AlphaStream 协作方案：分工与协调（Zeon × Kani）

> 背景：Kani 看了 `OPTIMIZATION_PLAN.md` 后认可方向，提出两点：
> 1. 先确认**数据够不够用**；
> 2. **数据存储 / 清洗 / 因子构建 / 风险分析要拆到不同文件夹，用 `.py` 而不是 `.ipynb`**；
>    并明确分工：**Kani 做风险分析（Barra 等），Zeon 做因子构建**。
>
> 本文档：① 对"数据够不够用"的回答（可直接转发 Kani）；② **详细协调手册**——X 契约精确规格、双方代码骨架、分阶段时间表、git 流程、接口防错。

---

## 一、给 Kani 的回答：数据够不够用？

**结论：原始数据量足够，但瓶颈不在"行数"，而在"字段广度"和"怎么切分使用"。**

### 1. 数据现状（已核实）
| 项 | 实际情况 |
|---|---|
| 体量 | `hk_market_raw.parquet` ≈ 44 万行，区间 **2022–2025**（约 3–4 年日频） |
| 字段 | 仅 `PX_LAST`(价) / `CUR_MKT_CAP`(市值) / `PE_RATIO`(市盈率) / `PX_VOLUME`(量) |
| 股票池 | 因子模型用**全市场截面**（每天 ≥50 只）；优化器却**硬编码只取 10 只手选股** |
| 时点性 | PE 用 `shift(60)`（≈3 个月滞后）近似，非真·point-in-time |

### 2. 真正的缺口（按重要性排序）
- **字段太薄**：目前只能稳建 **size(市值) + value(PE) + 一个 volume 代理 + momentum(可由价格派生)**。要做 Barra 风格风险模型，还缺：
  - `PB` / 账面价值、盈利(EPS/ROE)、股息率 → 价值与质量因子必需；
  - **行业分类** → Barra 风险模型的核心维度（行业哑变量）；
  - 更多风格因子（quality / low-vol 需要盈利或波动率序列）。
- **股票池被提前切成 10 只**：这是最致命的。Barra 协方差 `Σ = X·F·X' + D` 必须在**全市场**上估计因子协方差 `F` 和特异方差 `D`。10 只手选股（且是"妖股/压舱石"叙事筛选）既样本太小、又有选择偏差，**撑不起风险模型**。→ **数据层必须保留全市场，10 只的切片交给组合层决定，不要提前切**。
- **时点性只是近似**：`shift(60)` 是粗暴代理。严谨做法是用公告日对齐的 point-in-time 基本面，或至少验证 60 天滞后无前视泄漏。这一点对 Zeon 的因子 IC 和 Kani 的风险模型都同样重要。
- **协方差需收缩**：即便用全市场，3–4 年日频对几十上百只股票仍偏短，样本协方差噪声大 → 必须用 **Ledoit-Wolf 收缩**（这正是 Zeon 的因子暴露 与 Kani 的风险模型交汇之处）。

### 2.5 补数据行动项（明确 owner + 状态）
把"字段太薄"从问题描述变成可追踪的动作：
- [ ] **补充 PB / 账面价值 / EPS·ROE / 股息率**（价值与质量因子必需）—— owner：**Zeon**，deadline：Phase 0 后一周内，状态：未开始
- [ ] **补充行业分类**（Barra 行业维度核心，也用于行业中性化）—— owner：**Kani**（风险侧需求方提出），deadline：同上，状态：未开始
- [ ] 若无法补充，则在 `exposures_meta.json` 显式标注"因子覆盖 = size/value/momentum/lowvol，缺 quality/行业"，避免 Kani 误以为维度完整。

### 3. 一句话回 Kani
> "量够（44 万行 / 3–4 年 / 全市场截面）。但要支持你的 Barra 风险模型，需要做三件事：(1) 数据层保留**全市场**，别提前切成 10 只；(2) 确认能否补 `PB`、盈利、股息、行业分类这几个字段——没有的话质量/价值因子和 industries 维度建不全；(3) 全链路强制 point-in-time。协方差那边交给你时我会用 Ledoit-Wolf 收一下。"

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
- 列：每个因子一列，列名用 snake_case 因子名（如 `size`, `value`, `momentum`, `lowvol`）
- Ticker 格式：统一 `XXXX HK Equity`

**一个具体的切片长这样**（注意：值是横截面 z-score，无量纲）：

| Date | Ticker | size | value | momentum | lowvol |
|---|---|---|---|---|---|
| 2025-06-30 | 1 HK Equity | 0.42 | -0.31 | 1.10 | -0.55 |
| 2025-06-30 | 5 HK Equity | -0.88 | 0.62 | -0.20 | 0.33 |
| 2025-06-30 | 66 HK Equity | 1.95 | 0.11 | 0.05 | -0.10 |
| … | … | … | … | … | … |
| 2025-07-01 | 1 HK Equity | 0.40 | -0.29 | 1.08 | -0.53 |

### 2.2.2 每个值的计算规则（写进 `factors/pipeline.py`，两边都要信）
1. **Winsorize**：每个因子在每个交易日做横截面截尾（2.5% / 97.5%），去掉极端值。
2. **z-score**：截尾后，每个交易日对该因子横截面标准化（减均值÷标准差）。
2.5 **行业中性化 / 正交化**（推荐）：z-score 后，对每个因子在每日截面对行业哑变量（或已确定的其他因子）回归取残差，剔除行业 / 其他因子干扰，使暴露更纯净。Barra 风格风险模型尤其需要。若暂无行业分类数据，先跳过并在 `exposures_meta.json` 标注。
3. **Point-in-time**：`Date=t` 的值只允许用 `≤t` 的信息。各因子的具体取法见下表。

### 2.2.3 每个因子的 point-in-time 取法（这是"无前视泄漏"的硬约束）

| 因子 | 原始输入 | point-in-time 处理 | 现在数据能否做 |
|---|---|---|---|
| `size` | `CUR_MKT_CAP` | 直接用 t 日市值（市值本身即时点） | ✅ 可做 |
| `value` | `PE_RATIO` | 取 `shift(60)`（约 3 个月滞后），避免用未来盈利 | ✅ 可做（PE 版）；若补 `PB`/`EPS` 同理滞后 |
| `momentum` | `PX_LAST` | 用 t 日及之前的价格算"12-1 月"收益率（不含 t 之后） | ✅ 可做（由价格派生） |
| `lowvol` | `PX_LAST` | 用 t 日及之前的日收益算滚动波动率（如 60 日） | ✅ 可做（由价格派生） |
| `quality` | 盈利/ROE | 需 point-in-time 盈利数据 | ❌ 缺数据，暂不做 |

> **对 Kani 的含义**：现在能稳定交付 `size / value / momentum / lowvol` 四个因子。如果他要 `quality` 或行业维度，必须先补数据（见第一部分第 2 点）。

### 2.2.4 NaN 与版本
- 某股票某日因子为 NaN（如新股无足够历史算 momentum）：**Zeon 在 X 里留 NaN，不偷偷填 0**。
- Kani 读 X 时，**对该交易日截面丢弃任何含 NaN 的股票**（文档化此规则），保证进模型的截面完整。
- 配套 `data/processed/exposures_meta.json`：
  ```json
  { "generated_at": "2026-07-23T00:30:00", "as_of_max": "2025-12-31",
    "factors": ["size","value","momentum","lowvol"], "universe_size": 320 }
  ```
  这样 Kani 一眼知道这份 X 覆盖了哪些因子、到哪天、多少只股票。

### 2.2.5 Point-in-time 验证（防前视泄漏）
X 里每个值都声明了"只用 ≤t 的信息"，但声明不等于真的没有泄漏，必须验证：
- **信息流向检验**：对每个因子，构造"用 t 日因子预测 t+1 日收益"的 IC；若改用 t+1 日才可得的信息（如未滞后的 PE）IC 显著更高，说明原处理有泄漏。
- **滞后对齐检验**：对 `shift(60)` 类代理（如 value），抽样核对是否与对应公告日逻辑一致；无法拿到真·point-in-time 基本面时，至少验证 60 天滞后未引入未来盈利。
- **结论写进 meta**：通过 / 近似通过（标注代理方式）/ 不通过（该因子暂不进 X）。

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
- [ ] X 的列名清单（先定 `size/value/momentum/lowvol`，quality 待定）
- [ ] z-score / winsorize 参数（默认 2.5%/97.5%）
- [ ] NaN 处理规则（Kani 侧按日截面丢弃；备选：缺失因子用行业均值软填充，避免大范围丢股票，需在 meta 标注采用哪种）
- [ ] `as_of` 约定（用数据最新日；回测时由调用方传入）
- [ ] 股票池定义（全市场 / 恒生综指，写进 `config.py`，**不**硬编码 10 只）
- [ ] 因子相关性 / 冗余上限（如两两 |ρ| < 0.7，超出则砍 / 合并，避免 B 共线）
- [ ] 行业中性化约定（是否在 z-score 前对行业哑变量回归取残差；暂无行业数据则跳过并标注）
- [ ] 补数据 action：PB / 盈利(EPS·ROE) / 股息率 / 行业分类的 owner 与 deadline

### Phase 1 —— Zeon：数据 + 因子 + 验证（约 1 周）
交付物：
1. `data/loaders.py` + `data/schema.py`（标准面板，替代 notebook Cell 2–7）
2. `factors/base.py` + `size/value/momentum/lowvol.py`
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
> 开始前先对一下 X 的列（你要哪几个因子）和格式，我把 `get_exposures(as_of)` 定好就先写因子 + IC/IR 验证。
> 数据那边有个前提：原始 44 万行量够，但字段只有价/市值/PE/量，撑不起完整 Barra——尤其缺行业分类和 PB/盈利。要不要先确认能不能补这几个字段？另外优化器现在硬编码 10 只手选股，我建议数据层保留全市场、10 只交给组合层决定，不然风险模型样本太小。"

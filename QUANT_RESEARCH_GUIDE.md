# Quant Research 工作流程 · 学习路线 · 知识地图

> 写给正在把 AlphaStream 往"研究级"推进的你（学生视角）。
> 本文分三部分：**① 工作流程**（一个 quant researcher 每天在干什么）、**② 学习路线**（按顺序该学什么）、**③ 知识地图**（每一步用到哪些数学，含你问的随机过程 + 时间序列）。
> 最后附一节 **AlphaStream 现状对照**，告诉你项目卡在流程的哪一环。

---

## 第一部分：Quant Research 的工作流程

量化研究不是"写个模型跑一下"，而是一条**从假说到实盘、再折返迭代的闭环**。九个阶段：

下图为正版 QR 主链路（修正版）：在原有九步基础上补齐「风险模型构建 B/V/Δ」「样本内 + 样本外回测（含交易成本）」「模拟盘」三步，并把组合优化明确为 walk-forward。

<svg viewBox="0 0 680 640" width="100%" role="img">
  <title>修正后的量化研究主链路</title>
  <desc>在用户原图基础上补齐风险模型构建、样本内回测、交易成本、模拟盘，并明确 walk-forward 与衰减回假说。</desc>
  <defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
    </marker>
  </defs>

  <text x="40" y="34" font-size="14" font-weight="500" fill="#2C2C2A">修正版 QR 主链路（〔新增〕为相对你原图的补充）</text>

  <rect x="150" y="64" width="380" height="36" rx="8" fill="#B5D4F4" stroke="#185FA5" stroke-width="0.5"/>
  <text x="340" y="82" text-anchor="middle" font-size="13" font-weight="500" fill="#042C53">① 研究假说</text>

  <rect x="150" y="114" width="380" height="36" rx="8" fill="#B5D4F4" stroke="#185FA5" stroke-width="0.5"/>
  <text x="340" y="132" text-anchor="middle" font-size="13" font-weight="500" fill="#042C53">② 数据获取与清洗</text>

  <rect x="150" y="164" width="380" height="36" rx="8" fill="#B5D4F4" stroke="#185FA5" stroke-width="0.5"/>
  <text x="340" y="182" text-anchor="middle" font-size="13" font-weight="500" fill="#042C53">③ 因子构建（标准化 / 中性化）</text>

  <rect x="150" y="214" width="380" height="36" rx="8" fill="#CECBF6" stroke="#534AB7" stroke-width="0.5"/>
  <text x="340" y="232" text-anchor="middle" font-size="13" font-weight="500" fill="#26215C">④ 因子验证（IC · 衰减 · 防过拟合）</text>

  <rect x="150" y="264" width="380" height="36" rx="8" fill="#CECBF6" stroke="#534AB7" stroke-width="0.5"/>
  <text x="340" y="282" text-anchor="middle" font-size="13" font-weight="500" fill="#26215C">⑤ 风险模型构建（B · V · Δ）〔新增〕</text>

  <rect x="150" y="314" width="380" height="36" rx="8" fill="#9FE1CB" stroke="#0F6E56" stroke-width="0.5"/>
  <text x="340" y="332" text-anchor="middle" font-size="13" font-weight="500" fill="#04342C">⑥ 组合优化（walk-forward）</text>

  <rect x="150" y="364" width="380" height="36" rx="8" fill="#9FE1CB" stroke="#0F6E56" stroke-width="0.5"/>
  <text x="340" y="382" text-anchor="middle" font-size="13" font-weight="500" fill="#04342C">⑦ 回测：样本内 + 样本外（含交易成本）〔新增〕</text>

  <rect x="150" y="414" width="380" height="36" rx="8" fill="#FAC775" stroke="#854F0B" stroke-width="0.5"/>
  <text x="340" y="432" text-anchor="middle" font-size="13" font-weight="500" fill="#412402">⑧ 风险归因</text>

  <rect x="150" y="464" width="380" height="36" rx="8" fill="#FAC775" stroke="#854F0B" stroke-width="0.5"/>
  <text x="340" y="482" text-anchor="middle" font-size="13" font-weight="500" fill="#412402">⑨ 模拟盘 paper trading〔新增〕</text>

  <rect x="150" y="514" width="380" height="36" rx="8" fill="#FAC775" stroke="#854F0B" stroke-width="0.5"/>
  <text x="340" y="532" text-anchor="middle" font-size="13" font-weight="500" fill="#412402">⑩ 上线实盘</text>

  <rect x="150" y="564" width="380" height="36" rx="8" fill="#FAC775" stroke="#854F0B" stroke-width="0.5"/>
  <text x="340" y="582" text-anchor="middle" font-size="13" font-weight="500" fill="#412402">⑪ 监控迭代 → 衰减回 ①</text>

  <g stroke="#2C2C2A" stroke-width="1.2" marker-end="url(#arrow)">
    <line x1="340" y1="102" x2="340" y2="112"/>
    <line x1="340" y1="152" x2="340" y2="162"/>
    <line x1="340" y1="202" x2="340" y2="212"/>
    <line x1="340" y1="252" x2="340" y2="262"/>
    <line x1="340" y1="302" x2="340" y2="312"/>
    <line x1="340" y1="352" x2="340" y2="362"/>
    <line x1="340" y1="402" x2="340" y2="412"/>
    <line x1="340" y1="452" x2="340" y2="462"/>
    <line x1="340" y1="502" x2="340" y2="512"/>
    <line x1="340" y1="552" x2="340" y2="562"/>
  </g>

  <line x1="125" y1="590" x2="125" y2="82" stroke="#993C1D" stroke-width="1.4" stroke-dasharray="5 3" marker-end="url(#arrow)"/>
  <line x1="125" y1="590" x2="150" y2="590" stroke="#993C1D" stroke-width="1.4"/>
  <line x1="125" y1="82" x2="150" y2="82" stroke="#993C1D" stroke-width="1.4"/>
  <text x="44" y="340" font-size="12" fill="#712B13">因子衰减</text>
  <text x="44" y="356" font-size="12" fill="#712B13">↻ 回假说</text>
</svg>


| # | 阶段 | 一句话任务 | 关键产出 |
|---|---|---|---|
| ① | 研究假说 | 想清楚"我赌哪一类异常收益、为什么它该存在" | 一个可证伪的假设 |
| ② | 数据清洗 | 去幸存者偏差、point-in-time 对齐、截尾、标准化 | 干净、无前视偏差的数据集 |
| ③ | 因子构建 | 把原始数据变成能预测收益的 alpha 信号 | 因子暴露矩阵（factor exposures） |
| ④ | 因子验证 | 检验因子真的有预测力，不是噪声 | IC / IR / t 统计 / 分层回测 |
| ⑤ | 组合优化 | 在风险约束下求最优权重 | 目标持仓权重 w |
| ⑥ | 样本外回测 | 用"模型没见过的数据"验证，walk-forward | 样本外净值曲线、Sharpe |
| ⑦ | 风险归因 | 把收益/风险拆成各因子的贡献 | 归因报表、回撤分析 |
| ⑧ | 上线实盘 | 把信号变成真实交易（含成本、滑点） | 交易系统 / 调度 |
| ⑨ | 监控迭代 | 盯实盘 vs 回测的偏离，衰减了就回 ① | 监控看板、再研究 |

**新手最容易犯的错**：跳过 ④⑥⑦ 直接看 ⑤ 的"年化收益"。这样得到的收益是**拟合出来的（in-sample），不是预测出来的（out-of-sample）**——这是量化研究和"调参炫技"的分水岭。

---

## 第二部分：学习路线（按顺序，先地基后上层）

分四个梯队，**从下往上学**。每一层给出"学到什么程度算够用"。

### 梯队 0 · 编程与数据基础（先能干活）
- **Python**：`numpy` 向量化、`pandas`（多重索引、`groupby`、时间索引 resample）
- **可视化**：`matplotlib` / `plotly` 画净值曲线、因子分布
- **数据 IO**：`parquet`（AlphaStream 用的就是它）、SQL 基础
- ✅ 够用标准：能独立把一份原始行情清洗成"日期 × 股票 × 特征"的面板数据

### 梯队 1 · 数学地基（理解模型为什么成立）
- **线性代数**：矩阵运算、特征值/特征向量、协方差矩阵、二次型 `wᵀΣw`
- **概率论**：分布、期望/方差、协方差与相关、条件期望
- **数理统计**：假设检验、t 检验、p 值、置信区间、最大似然
- **最优化**：凸优化、拉格朗日乘子、二次规划（QP）、KKT 条件
- ✅ 够用标准：看到 `min wᵀΣw s.t. Σw=1` 知道这是二次规划，能手推为什么协方差矩阵是半正定

### 梯队 2 · 量化专业核心（真正的护城河）
- **时间序列分析**：AR/MA/ARIMA、平稳性（ADF 检验）、自相关 ACF/PACF、GARCH（波动率聚集）
- **随机过程**：随机游走、鞅、马尔可夫链、布朗运动、Ito 引理（做衍生品/连续时间必备）
- **回归与因子模型**：横截面回归、Fama-MacBeth、多因子模型、IC/IR、Newey-West 稳健标准误
- **投资组合理论**：Markowitz 均值-方差、CAPM、协方差收缩（Ledoit-Wolf）、Black-Litterman
- **回测方法论**：walk-forward、purged/embargo 交叉验证、过拟合检测、交易成本建模
- ✅ 够用标准：能独立设计一个"无前视 + 样本外 + 含成本"的回测框架

### 梯队 3 · 工程与前沿（让研究能落地/进阶）
- **机器学习**：树模型（XGBoost/LightGBM 做非线性因子）、正则化、特征重要性、SHAP
- **工程化**：因子库、实验管理（MLflow）、调度、风控监控
- **前沿（可选）**：深度学习做序列预测、强化学习做执行、另类数据（另类 alpha）
- ✅ 够用标准：能把一个研究 notebook 工程化成可复现、可监控的 pipeline

> **给你的路线建议**：你已有 PyTorch 基础（梯队 3 的一部分），但**量化的地基在梯队 1-2**。别急着上 ML，先把**时间序列 + 因子验证 + 回测方法论**这三块补扎实——这才是 quant researcher 和"会调 ML 的工程师"的区别。

---

## 第三部分：知识地图（每一步用到什么数学）

直接回答你的问题：**会，随机过程和时间序列都会用到，而且是核心。** 下表把每个数学工具对应到具体的工作阶段和用途。

| 数学领域 | 具体工具 | 用在哪一步 | 在 AlphaStream 里对应 |
|---|---|---|---|
| **线性代数** | 协方差矩阵、二次型、特征分解 | ⑤ 组合优化 | `min wᵀΣw`（Cell 19 SLSQP） |
| **概率论** | 分布、协方差、条件期望 | ③④ 因子/验证 | 残差 ε 的协方差 |
| **数理统计** | t 检验、OLS、稳健标准误 | ③④ 因子验证 | 横截面回归（Cell 11） |
| **时间序列** | 平稳性、自相关、**GARCH**、滚动窗口 | ②⑥ 数据/回测 | 滚动估协方差、波动率（**目前缺 GARCH**） |
| **随机过程** | **随机游走、布朗运动、Cholesky 相关模拟、蒙特卡洛** | ⑥ 风险模拟 | Cell 里的蒙特卡洛路径模拟 |
| **最优化** | 凸优化、二次规划、拉格朗日/KKT | ⑤ 组合优化 | SLSQP 求解器 |
| **投资组合理论** | Markowitz、协方差收缩、成本项 | ⑤ 优化 | 最小方差组合（**收缩/成本待补**） |
| **机器学习**（进阶） | 树模型、正则化、交叉验证 | ③⑥ 因子/回测 | 尚未使用 |

### 你问的两块，展开讲

**① 时间序列（Time Series）——量化的"母语"**
- 金融数据本质是时间序列：价格、收益、波动都随时间演化。
- **平稳性**：价格通常非平稳（随机游走），但收益率近似平稳——所以建模几乎都用收益率，不用价格。这是最基本的直觉。
- **自相关**：动量因子的理论基础就是"收益有正自相关"；均值回归则赌"负自相关"。
- **GARCH / 波动率聚集**："大波动后面跟大波动"是市场铁律。AlphaStream 现在用 `df.cov()*252` 静态估协方差，**没有考虑波动聚集**——这是一个可以升级的点（换成 EWMA 或 GARCH 加权）。

**② 随机过程（Stochastic Process）——风险模拟与定价的引擎**
- **随机游走 / 布朗运动**：股价的经典假设 `dS = μS dt + σS dW`，是蒙特卡洛模拟和期权定价（Black-Scholes）的地基。
- **Cholesky 分解 + 相关随机数**：AlphaStream 的蒙特卡洛就是用这个技巧生成"相关的多资产路径"——把独立正态噪声乘上协方差的 Cholesky 因子，得到相关的随机漫步。这就是随机过程在项目里的实际落点。
- **鞅 / 马尔可夫性**：有效市场假说的数学表述（"未来只依赖现在，不依赖过去"），是很多模型的隐含前提。
- 若你以后做**衍生品或高频执行**，随机微积分（Ito 引理）会变成硬需求；做**选股/组合**则以上够用。

---

## 第四部分：AlphaStream 现状对照（你现在站在流程哪一环）

| 阶段 | 状态 | 说明 |
|---|---|---|
| ① 研究假说 | ⚠️ 部分 | 有"压低特异风险"的目标，但没写成可证伪假设 |
| ② 数据清洗 | ✅ 已实作 | 截尾 2.5%/97.5% + z-score，习惯正确 |
| ③ 因子构建 | ⚠️ 部分 | 只用市值/PE/成交量三个原始特征，非真正因子集 |
| ④ 因子验证 | ❌ 缺失 | 没有 IC/IR、没有显著性检验 |
| ⑤ 组合优化 | ⚠️ 部分 | SLSQP 真在跑，但**协方差未收缩、零交易成本** |
| ⑥ 样本外回测 | ❌ 缺失 | Cell 18 是"用答案训答案"的 in-sample，收益不可信 |
| ⑦ 风险归因 | ❌ 缺失 | 无 |
| ⑧ 上线实盘 | ⚠️ 部分 | `app.py` 是 mock 假权重，没接真引擎 |
| ⑨ 监控迭代 | ❌ 缺失 | 无 |

**一句话诊断**：AlphaStream 是一份"架构对、会跑、但结论不可信"的**教育级原型**。致命缺口在 **④ 因子验证、⑥ 样本外回测、⑤ 协方差收缩/交易成本**。

### 建议的完善顺序（P0 → P2）
- **P0 · 先让结论可信**
  1. ⑤ 协方差换 `sklearn.covariance.LedoitWolf`（一行，立刻降噪）
  2. ⑥ 改 walk-forward：用 t 日前数据估协方差+优化，用 t 日后收益评估
  3. ⑤ 优化目标加交易成本项 `wᵀΣw + λ·|w − w_prev|`
- **P1 · 让它像个真风险模型**
  4. ③ 因子集扩到 value / momentum / quality / size / low-vol
  5. ④ 每个因子算 IC / IR + t 检验验证
- **P2 · 让它能交付**
  6. ⑧ 拔掉 `app.py` 的 mock，接真正的 `AlphaStreamEngine`
  7. ⑦⑨ 加因子归因报表 + 实盘监控

---

## 学习资源（按梯队精选）

- **时间序列**：《Analysis of Financial Time Series》(Ruey Tsay) — 金融时序圣经
- **随机过程/随机微积分**：《Stochastic Calculus for Finance》(Steven Shreve) 卷一/卷二
- **因子投资**：《Active Portfolio Management》(Grinold & Kahn) — IC/IR 的出处
- **实战方法论**：《Advances in Financial Machine Learning》(Marcos López de Prado) — purged CV、过拟合检测
- **投资组合**：Ledoit & Wolf 的协方差收缩原论文（"Honey, I Shrunk the Sample Covariance Matrix"）

---

*本文档随项目演进更新。下一步动手建议：从 P0 的"协方差收缩 + walk-forward 回测"开始——改动最小、对结论可信度提升最大。*

---

## 一、QR 常用术语速查表

> 标 ⭐ 的是高频必会词。

### ① 收益与风险基础
- ⭐ **Alpha (α)**：超额收益，模型解释不了的"截距/残差收益"
- ⭐ **Beta (β)**：对某因子的敏感度/系数（不是收益，是缩放权重）
- ⭐ **Factor / 因子**：系统性收益来源（市场、价值、动量…）
- ⭐ **Exposure / 暴露**：股票对因子的 loading，即因子暴露矩阵 B 里的元素
- **Volatility / 波动率**：收益的标准差
- ⭐ **Sharpe / 夏普**：每单位总风险的超额收益
- **Sortino / 索提诺**：只对下行波动计价的夏普
- **Drawdown / 回撤**：从峰值到谷值的最大跌幅
- **Max DD / 最大回撤**：回测期内最深的回撤

### ② 因子类
- **Style factor / 风格因子**：价值、动量、规模、质量、低波、流动性
- **Industry factor / 行业因子**：行业哑变量（K−1 列）
- **Market factor / 市场因子**：全市场收益（全 1 列）
- ⭐ **Factor return (f)**：因子组合（多空）收益
- **Factor premium / 因子溢价**：该因子长期平均收益
- ⭐ **IC (Information Coefficient)**：因子预测方向与真实收益的相关系数（Pearson）
- ⭐ **Rank IC**：用排名算的 IC（Spearman），更稳健
- ⭐ **ICIR**：IC 的信息比率（均值/标准差），看 IC 稳不稳定
- **t-stat / t 值**：显著性（|t| > 2 通常算显著）
- ⭐ **Factor decay / 因子衰减**：因子效力随时间下降（流程闭环的触发点）
- **Neutralization / 中性化**：回归剔除行业/其他因子影响
- **Orthogonalization / 正交化**：让因子彼此不相关
- **Winsorize / 去极值**：截尾处理异常值
- **Z-score / 标准化**：均值 0、标准差 1

### ③ 组合类
- ⭐ **Portfolio optimization / 组合优化**：在约束下求最优权重
- ⭐ **Minimum variance / 最小方差**：`min wᵀΣw`
- **Mean-variance / 均值方差**：Markowitz 框架
- **Risk parity / 风险平价**：各因子风险贡献相等
- **Long-short / 多空**：做多高分、做空低分
- **Turnover / 换手率**：调仓交易量（直接影响成本）
- **Constraint / 约束**：权重上下限、行业中性、交易成本

### ④ 风险模型类
- ⭐ **Covariance Σ**：N×N 收益协方差
- ⭐ **Factor covariance V**：K×K 因子协方差
- ⭐ **Specific variance Δ**：个股特异方差（对角阵）
- **Idiosyncratic / 特异收益**：非系统性、可分散
- ⭐ **Ledoit-Wolf shrinkage / 协方差收缩**：防过拟合的正则化
- ⭐ **Risk attribution / 风险归因**：把组合风险拆回各因子（用 B）

### ⑤ 回测与验证类
- ⭐ **In-sample / 样本内**：调参用的数据
- ⭐ **Out-of-sample (OOS) / 样本外**：检验泛化能力的数据
- ⭐ **Walk-forward / 滚动窗口**：滚动"训练→测试"，防偷看未来
- ⭐ **Overfitting / 过拟合**：在样本内记忆噪声
- ⭐ **Transaction cost / 交易成本**：佣金 + 印花税
- **Slippage / 滑点**：实际成交价与信号的偏差
- **Market impact / 市场冲击**：大单砸出的价格移动
- **Paper trading / 模拟盘**：实盘前的小资金/仿真验证
- **Live trading / 实盘**
- **Multiple testing / 多重检验**：同时测很多因子导致伪显著
- **Deflated Sharpe Ratio**：校正过拟合后的夏普
- **Capacity / 容量**：策略能容纳的资金上限

### ⑥ 统计 / 结构
- ⭐ **Cross-sectional / 横截面**：同一时点、跨股票（因子暴露多在此计算）
- ⭐ **Time-series / 时序**：同一股票、跨时间（beta 回归多在此）
- **Hypothesis / 研究假说**：你相信某个现象能持续产生收益的前提

---

## 二、Parquet：列式存储格式（量化数据为何用它）

> 关联：项目 `Data/` 目录已全面采用 parquet；对应的读写工具见 `Src/data_io.py`。

### 1. 它是什么
Apache Parquet 是一种**开源的列式存储（columnar storage）二进制文件格式**，最初为 Hadoop/Spark 大数据生态设计，现在 Python / pandas / DuckDB / Spark 全都原生支持。它和 CSV 最大的区别是：**数据按"列"存，而不是按"行"存**。

### 2. 行式 vs 列式
- **行式（CSV）**：一行一行连续存。想读"收盘价"这一列，必须扫描每一行，慢。
- **列式（Parquet）**：一列一列连续存。同列数据类型一致，读取某列时直接取一整块，快且省 IO。这也是它能"列裁剪"（只读需要的列）的前提。

### 3. 为什么量化 / 数据分析爱用它
| 维度 | CSV（行式） | Parquet（列式） |
|---|---|---|
| 存储方式 | 一行一行连续存 | 一列一列连续存 |
| 压缩率 | 低（混合类型） | 高（同列同类型，常小 5–10×） |
| 读某几列 | 要扫描整张表，慢 | 只取对应列块，快（列裁剪） |
| 数据类型 | 全是字符串，读回要自己 cast | **自带 schema**，int/float/date/category 原样保留 |
| 可读性 | 记事本能直接看 | 二进制，不能直接看 |
| 跨语言 | 通用但脆弱 | Python/Java/R/Go 都能读同一份 |

核心优势一句话：**同列数据类型一致 → 压缩率高、只读需要的列极快、且不会丢失类型信息。**

### 4. Python 里怎么用
```python
import pandas as pd

df = pd.read_parquet("prices.parquet")                 # 读
df.to_parquet("prices.parquet", engine="pyarrow")      # 写
# 只读某几列，IO 极小，这是 parquet 的杀手锏
df = pd.read_parquet("prices.parquet", columns=["date", "close"])
```
首次使用需要装引擎：`pip install pyarrow`（或 `fastparquet`）。

### 5. 落到 AlphaStream
- 港股日频 / 分钟级行情、因子暴露矩阵 B（N×K 大矩阵）、因子值表——都适合存成 `.parquet`：省空间、读写快、类型不丢。
- 临时小表或要给人肉眼看 / 交付时，才用 CSV。
- 项目 `Data/` 已全面采用 parquet（`hk_market_raw.parquet`、`factor_returns.parquet`、`idiosyncratic_alpha.parquet`）；对应的落盘 / 读取逻辑已收口到 `Src/data_io.py`（含 CSV→Parquet 清洗、列裁剪读取、批量转换）。

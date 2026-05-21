# AlphaStream

> 港股多因子风险模型与最小方差组合优化系统

## Pipeline 总览

```
┌─────────────────────────────────────────────────────────────────────────┐
│  1. 数据加载    2. 特征工程    3. 因子模型    4. 组合优化    5. 风险管理   │
│   Raw Parquet → Winsor+Std → OLS截面回归 → 马科维茨优化 → Monte Carlo   │
│                                              ↑ AI辅助生成，持续研究中    │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 1. 数据加载与预处理

- 加载港股全市场日频数据（~44 万行），字段包括收盘价、市值、PE、成交量、历史波动率、行业分类
- 按 Ticker / Date 排序，计算 T+1 前瞻收益率 `Return_T1`
- 剔除缺失值，清洗截面样本数不足的交易日

## 2. 特征工程

- **Winsorize 缩尾**：每个截面对市值、PE、成交量做 2.5%/97.5% 缩尾（PE 极端值从 2768 → 229）
- **截面标准化**：在每个交易日对因子做 z-score 标准化（μ=0, σ=1）

## 3. 因子模型（日频截面回归）

```
Return_T1 = α + β1·CUR_MKT_CAP + β2·PE_RATIO_LAGGED + β3·PX_VOLUME + ε
```

每日对港股全市场跑 OLS 截面回归，提取：
- **因子收益（Factor Returns）**：每个因子的日度纯因子溢价
- **特质 Alpha（Idiosyncratic Alpha）**：残差 ε，剥离系统性风险后的个股超额收益

### 📈 因子累计收益 (2022–2025)

![Factor Cumulative Payoffs](images/chart_01.png)

> const（截距）为虚线基准，其余为实线。y=1.0 为盈亏平衡线。

## 4. 组合优化 — ⚠️ AI 辅助生成，持续研究中

> 以下马科维茨优化及后续风险管理模块目前为 **AI 辅助编写**，本人正在深入理解数学推导并重新实现更稳健的版本（如 Black-Litterman、Robust Optimization 等）。

- 使用 SLSQP 求解器做 **最小方差优化**：`min wᵀΣw`
- 约束条件：∑w=1，0 ≤ wᵢ ≤ 30%，从 10 只候选股票中选优
- 组合年化特异性波动率：~7.27%

### 📈 Monte Carlo 模拟（10000 路径 × 252 天）

![Monte Carlo Simulation](images/chart_02.png)

> Cholesky 分解注入持仓相关性，展示尾部风险分布，标注 99% VaR。

### 📈 组合因子暴露

![Factor Exposure](images/chart_03.png)

> 最优组合在 SIZE / PE / VOLUME 三个因子上的截面暴露（z-score 度量）。

## 5. 交易成本与绩效核算

| 指标 | 数值 |
|------|------|
| 单边换手率 | 40.15% |
| 单次换仓成本 (0.23% BPS) | 0.0923% |
| 年化超额收益 | -3.36% |
| 夏普比率 | -0.46 |
| 最大回撤 | -17.44% |
| 扣除月换仓摩擦后净夏普 | -0.61 |

> ⚠️ 当前因子模型暂未取得正 Alpha，是后续研究重点。

## 6. 生产化封装

- `AlphaStreamEngine` 类：将完整 pipeline 封装为面向对象接口，4 行代码调用
- `schedule` 定时任务：每日 16:30 自动触发换仓

## 项目结构

```
AlphaStream/
├── Data/
│   ├── Raw/hk_market_raw.parquet          # 港股原始行情
│   └── Processed/
│       ├── factor_returns.parquet         # 日频因子收益
│       └── idiosyncratic_alpha.parquet    # 特质Alpha残差
├── Notebooks/
│   └── alpha_stream_v1.ipynb              # 核心研究Notebook
├── Src/
│   ├── app.py                             # FastAPI Web服务
│   ├── report_automator.py                # Excel报表 + 邮件
│   └── templates/index.html               # 前端控制台
├── images/                                # README图表
└── AlphaStream_Report.xlsx                # 生成的多因子风险报告
```

## 运行

```bash
# Jupyter 研究
cd Notebooks && jupyter notebook alpha_stream_v1.ipynb

# Web 服务
cd Src && python app.py   # http://localhost:8080
```

## 已知局限 / TODO

- [ ] 因子模型暂未取得正 Alpha，需探索更多有效因子
- [ ] 组合优化模块需从 SLSQP 最小方差 → Black-Litterman / Robust Optimization
- [ ] 交易成本过高（月换仓年化 23.27%），需引入换手约束
- [ ] 当前为静态回测，缺少 Walk-forward 交叉验证

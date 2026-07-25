# AlphaStream 优化方案（Quant Researcher 视角）

> 作者定位：以 quant researcher 身份完善本项目。
> 目标：把一份「会跑、架构对、但结论不可信」的教育级原型，提升到「结论可信、可交付」的研究级产出。
> 配套文档：`QUANT_RESEARCH_GUIDE.md`（工作流程 + 学习路线 + 知识地图）。本文件是**落地执行清单**。

---

## 0. 一句话诊断

AlphaStream 目前实现了 quant 工作流的 **②③⑤ 半途**（数据清洗 / 因子构建 / 组合优化），但决定「结论可不可信」的 **④因子验证 / ⑥样本外回测 / ⑦风险归因** 全部缺失。当前所有漂亮数字（年化 7.27%、夏普）都是 **in-sample 拟合** 出来的。

**优化优先级：先让结论可信（P0），再让模型像风险模型（P1），最后工程化交付（P2）。不要颠倒顺序——P2 在 P0 之前做是给假结论套漂亮壳。**

---

## 1. 现状代码锚点（改之前先知道改哪）

| 位置 | 现状 | 问题 |
|---|---|---|
| `Notebooks/...v1.ipynb` Cell 11 | 横截面 OLS 回歸 `Return_T1 ~ 市值+PE+成交量`，取残差 ε | 只用了 3 个原始特征，非真正因子集；PE 有 lag（好），但无系统性防前视验证 |
| Cell 14 / 19 | `cov_matrix = df_target.cov() * 252` | 样本协方差未收缩，10 档样本小 → 杂讯极大、权重极端 |
| Cell 18 | `historical_port_returns = df_target.dot(aligned_weights)`，df_target 正是估协方差的同批数据 | 用「答案」训「答案」，in-sample 回测，绩效虚高 |
| Cell 19 `AlphaStreamEngine` | 封装 `load_and_clean_data()` + `optimize()`，真正在跑 SLSQP | 没接 web、没接 walk-forward、协方差未收缩 |
| `Src/app.py` L37-41 | `mock_weights = {3288:0.30, 3328:0.19, 66:0.12}` 硬编码 | 网页服务是演示壳，没接真引擎 |
| `Src/app.py` L46 | `sender_password="habu rqjh ffnk dqld"` 硬编码 Gmail 密码 | **严重安全漏洞**，任何拿到代码的人都能用此邮箱发信 |

---

## 2. P0 — 让结论可信（最高优先级，先做这三项）

### P0-1 协方差收缩（LedoitWolf 一行替换）

**问题**：`df_target.cov() * 252` 是样本协方差。样本只有 10 档、历史有限时，估计误差巨大，SLSQP 会把权重压到极少数字（数值不稳定）。

**目标**：用收缩估计器降低杂讯，得到更稳定、更分散的权重。

**改法**（替换 Cell 14 / `AlphaStreamEngine.load_and_clean_data` 里的那行）：

```python
from sklearn.covariance import LedoitWolf

# 旧：cov_matrix = df_target.cov() * 252
# 新：
lw = LedoitWolf().fit(df_target.values)
cov_matrix = pd.DataFrame(
    lw.covariance_ * 252,
    index=df_target.columns,
    columns=df_target.columns
)
```

**验收**：
- [ ] 权重分布更分散（无单票长期贴 30% 上限）
- [ ] 组合年化特异性波动率的估计更稳定（同数据多次重跑结果一致）

> 进阶：若想给近期波动更高权重，可换 `sklearn.covariance.OAS` 或自写指数加权协方差 `Σ_t = λ·Σ_{t-1} + (1-λ)·r_t·r_t.T`。

---

### P0-2 漫步前向回测（Walk-Forward / Rolling Window）

**问题**：Cell 18 用「估协方差的同一批数据」算绩效 → 典型 in-sample overfit。

**目标**：用 t 日**之前**的窗口估协方差并优化，再用 t 日**之后**的实际残差评绩效。滚动进行，得到样本外曲线。

**改法**（新增 cell，封装成函数，替换 Cell 18 的逻辑）：

```python
def walk_forward_backtest(df_target, window=252, rebalance=21, max_pos=0.3, shrink=True):
    """
    df_target: Date×Ticker 残差宽表
    window:    训练窗口（交易日）
    rebalance: 调仓周期（交易日）
    返回: 样本外组合每日收益 Series
    """
    from sklearn.covariance import LedoitWolf
    from scipy.optimize import minimize

    dates = df_target.index
    port_rets = []
    for end in range(window, len(dates) - rebalance, rebalance):
        train = df_target.iloc[end - window:end]
        test  = df_target.iloc[end:end + rebalance]

        # 用「过去」估协方差
        if shrink:
            cov = LedoitWolf().fit(train.values).covariance_ * 252
        else:
            cov = train.cov().values * 252

        # 用「过去」优化权重
        n = train.shape[1]
        cons = ({'type': 'eq', 'fun': lambda w: w.sum() - 1.0})
        bnds = tuple((0.0, max_pos) for _ in range(n))
        res = minimize(lambda w: w @ cov @ w, np.ones(n) / n,
                       method='SLSQP', bounds=bnds, constraints=cons)
        w = res.x

        # 用「未来」评绩效（这才是样本外）
        port_rets.append(test.values @ w)

    return pd.Series(np.concatenate(port_rets))
```

调用后照 Cell 18 的方式算年化/夏普/回撤，但输入换成这个 `walk_forward_backtest` 的返回值。

**验收**：
- [ ] 样本外夏普 < 样本内夏普（预期，真实信号不会那么美）
- [ ] 报告里同时披露 in-sample 与 out-of-sample 两个数字，差距可接受（如 out-of-sample 夏普 ≥ 0.5）

---

### P0-3 交易成本约束（Turnover Penalty）

**问题**：Cell 14/19 优化只约束 `Σw=1`、只做多、单票 ≤30%，**零成本** → 高换手组合纸面富贵。

**目标**：目标函数加入换手惩罚，让优化自己权衡「降风险」与「少交易」。

**改法**（在 `AlphaStreamEngine.optimize` 注入 `w_prev`）：

```python
def optimize(self, w_prev=None, turnover_lambda=0.001):
    n = len(self.target_tickers)
    w0 = np.ones(n) / n if w_prev is None else w_prev
    cons = ({'type': 'eq', 'fun': lambda w: w.sum() - 1.0})
    bnds = tuple((0.0, self.max_position) for _ in range(n))

    def obj(w):
        var = w @ self.cov_matrix.values @ w
        cost = turnover_lambda * np.sum(np.abs(w - w0))   # 换手惩罚
        return var + cost

    res = minimize(obj, w0, method='SLSQP', bounds=bnds, constraints=cons)
    ...
```

在 P0-2 的滚动回测里，每次把上一期权重作为 `w_prev` 传入，自然模拟真实换手。

**验收**：
- [ ] `turnover_lambda` 调大 → 权重变化更平缓、换手册降低
- [ ] 净夏普（扣成本后）成为主汇报指标，替代毛夏普

---

## 3. P1 — 让模型成为真正的多因子风险模型

### P1-1 扩展因子集（替代单一原始特征）

**问题**：Cell 11 只用了 市值 / PE / 成交量 三个原始特征，更接近「特征」而非学术意义的「因子」。

**目标**：构建标准风格因子，让风险模型有可解释的经济含义。

**改法**（扩展 Cell 11 的 `FACTORS_TO_WINSORIZE` 与构造逻辑）：

| 因子 | 构造 | 含义 |
|---|---|---|
| Size | log(市值) | 小盘效应 |
| Value | -PE（或 EP = 1/PE） | 低估值溢价 |
| Momentum | 过去 6~12 月收益（跳过近 1 月） | 惯性 |
| Quality | ROE / 负债率 等 | 质地 |
| Low-Vol | 过去波动率（取负） | 低波溢价 |

```python
FACTORS = {
    'size':      np.log(df['mkt_cap']),
    'value':     -df['pe_ttm'],                 # 已 lag，防前视
    'momentum':  df['ret_12_1'],                # 12月减1月动量
    'quality':   df['roe'],
    'low_vol':   -df['vol_60d'],
}
```

**验收**：
- [ ] 每个因子都能单独出 IC/IR 报表（见 P1-2）
- [ ] 至少 2~3 个因子 IC 显著非零

---

### P1-2 因子验证（IC / IR + 稳健标准误）

**问题**：当前没有任何「这个因子到底有没有预测力」的检验。

**目标**：给每个因子量化信息系数与信息比率，作为入选门槛。

**改法**（新增 cell）：

```python
def factor_ic(factor_matrix, forward_ret):
    """factor_matrix, forward_ret: 同索引 Date×Ticker"""
    ics = []
    for d in factor_matrix.index:
        f = factor_matrix.loc[d]
        r = forward_ret.loc[d]
        if f.notna().sum() > 5:
            ics.append(f.rank().corr(r.rank()))   # Spearman rank IC
    ics = pd.Series(ics)
    ic = ics.mean()
    ir = ics.mean() / ics.std()                   # Information Ratio
    # Newey-West 稳健 t 值（自相关下标准误更可靠）
    from statsmodels.tsa.stattools import acovf
    n = len(ics); lags = 6
    g0 = ics.var()
    gamma = [acovf(ics, nlag=lags, fft=False)[k] for k in range(1, lags+1)]
    nw_var = g0 + 2*sum((1-k/(lags+1))*gamma[k-1] for k in range(1, lags+1))
    t_stat = ic / np.sqrt(nw_var/n)
    return ic, ir, t_stat
```

**验收**：
- [ ] 输出因子 IC/IR 表，`|t_stat| > 2` 才算显著入选
- [ ] 落选因子不进入后续协方差建模

---

### P1-3 完整风险模型结构（因子协方差 + 特异方差）

**问题**：当前直接用残差协方差 `wᵀΣu w`，没有「因子暴露」这一层，组合暴露在哪些因子上不可见。

**目标**：标准多因子风险模型 `Σ = B·F·B.T + D`
- `B`：股票 × 因子暴露矩阵（Cell 11 回归系数）
- `F`：因子收益协方差（由 `df_factor_returns` 估计，建议也 LedoitWolf 收缩）
- `D`：特异方差对角阵（残差方差）

**改法**：

```python
# B 来自 Cell 11 每日横截面回归的因子载荷（对每档股票取时间均值或最新值）
# F = LedoitWolf().fit(df_factor_returns.values).covariance_ * 252
# D = diag(残差方差)
cov_structured = B.values @ F.values @ B.values.T + np.diag(D.values)
```

**验收**：
- [ ] 优化用 `cov_structured` 替代纯残差协方差
- [ ] 能输出「组合因子暴露」向量（见 P2-2 归因）

---

## 4. P2 — 工程化交付（让项目真的能跑、能看、能信）

### P2-1 拔掉 mock，接真引擎（修 `Src/app.py`）

**问题**：L37-41 的 `mock_weights` 是假的，网页服务形同演示。

**改法**：把 `heavy_quant_pipeline_worker` 改成调用 `AlphaStreamEngine` + `walk_forward_backtest`：

```python
def heavy_quant_pipeline_worker(email: str):
    engine = AlphaStreamEngine(target_tickers=demons + ballasts, max_position=0.3)
    engine.load_and_clean_data(r"../Data/Processed/idiosyncratic_alpha.parquet")
    engine.optimize()                                   # 最新一期权重
    oos_rets = walk_forward_backtest(engine.df_target)  # 样本外曲线
    # 用真权重 + 样本外指标生成报表
    reporter = AlphaStreamReporter(
        sender_email=os.environ["GMAIL_USER"],
        sender_password=os.environ["GMAIL_APP_PASSWORD"],
    )
    ...
```

**验收**：
- [ ] 网页触发后，邮件里是真实优化权重 + 样本外绩效，而非写死的 3 档

---

### P2-2 安全：Gmail 密码出 git（紧急）

**问题**：L46 硬编码 `habu rqjh ffnk dqld`，已泄露，应视为作废。

**改法**：
1. 立刻去 Google 账号 **撤销该 App Password**（它已公开在代码里）。
2. 新建 App Password，存到 `Src/.env`（并加进 `.gitignore`）：
   ```
   GMAIL_USER=gaokanglin6@gmail.com
   GMAIL_APP_PASSWORD=新的16位密码
   ```
3. 代码改为 `os.environ.get("GMAIL_APP_PASSWORD")`，并 `pip install python-dotenv`。
4. 在仓库根加 `.gitignore`：
   ```
   Src/.env
   __pycache__/
   *.parquet
   ```

**验收**：
- [ ] `.env` 不在 git 跟踪中（`git status` 不可见）
- [ ] 旧密码已从 Google 撤销

---

### P2-3 因子归因报表（风险归因）

**问题**：Cell 18 只有组合层夏普/回撤，不知道收益来自哪个因子。

**改法**：组合收益按因子分解
```python
# 组合因子暴露 B_port = B.T · w（各因子敞口）
# 因子收益 F_ret = df_factor_returns
# 归因 = B_port · F_ret  → 每因子贡献多少收益
attribution = pd.DataFrame({
    fac: B[fac] @ w * df_factor_returns[fac]
    for fac in factor_names
})
```
把这张表加进 Excel 报表。

**验收**：
- [ ] 报表含「因子贡献」sheet，组合收益可加总回因子

---

### P2-4 实验 / 参数管理

**目标**：不同窗口、λ、因子集的结果可复现、可对比。

**改法**（轻量）：
- 把关键超参写进 `config.yaml`（window / rebalance / max_pos / turnover_lambda / 因子列表）
- 每次跑回测把结果 + 配置写入 `Results/runs/<timestamp>.json`
- 进阶可引入 `mlflow` 或 `hydra`，但 P2 阶段用 json 落盘即可

---

### P2-5 监控迭代（闭环回到 ①）

**目标**：实盘/样本外信号衰减能被发现。

**改法**：
- 跟踪因子 IC 随时间滑动窗口是否跌破阈值（如 6 月滚动 IR < 0.3 告警）
- 跟踪实盘权重 vs 回测权重偏离度
- 这部分可在 `app.py` 加一个 `/health` 路由返回最新 IC/IR

---

## 5. 实施排期（建议里程碑）

| 里程碑 | 包含 | 退出标准 |
|---|---|---|
| **M1（1~2 天）** | P0-1 协方差收缩 + P0-2 walk-forward + P0-3 成本项 | 报告同时有 in/out-of-sample 夏普，且 out ≥ 0.5 |
| **M2（2~3 天）** | P1-1 因子集扩展 + P1-2 IC/IR 验证 | 至少 2~3 因子显著，落选因子剔除 |
| **M3（2~3 天）** | P1-3 结构化风险模型 | 优化用 BFB'+D，输出因子暴露 |
| **M4（1~2 天）** | P2-1 接真引擎 + P2-2 安全 + P2-3 归因 | 网页出真权重报表、密码出 git |
| **M5（持续）** | P2-4 实验管理 + P2-5 监控 | 配置可复现、IC 衰减可告警 |

> 顺序铁律：**M1 → M2 → M3 → M4 → M5**。任何把 M4 提前到 M1 之前的行为，都是在给不可信结论套漂亮外壳。

---

## 6. 风险与注意事项

1. **数据泄漏是头号敌人**：任何 `Return_T1` 用到 t 日及之后的信息都算前视。PE/动量必须 lag。
2. **幸存者偏差**：`hk_market_raw.parquet` 若只含「现在还在上市」的股票，回测会虚高。需 point-in-time  Universe 或明确标注局限。
3. **小样本**：10 档 + 有限历史，所有统计检验功率低，结论要保守，勿过度拟合。
4. **协方差收缩不是银弹**：LedoitWolf 改善稳定性，但不创造信息；因子本身无效时，收缩只是让错误更平滑。
5. **成本假设要现实**：港股实际成本含佣金+印花税（卖出 0.1%）+ 滑点，P0-3 的 λ 要标定到接近真实单边成本（~0.2%~0.3%）。

---

## 7. 验收总清单（项目「毕业」标准）

- [ ] 协方差用收缩估计（非样本协方差）
- [ ] 回测为 walk-forward，明确披露 out-of-sample 数字
- [ ] 优化含交易成本惩罚，汇报净夏普
- [ ] 每个入选因子有 IC/IR + Newey-West t 值
- [ ] 风险模型为结构化（因子协方差 + 特异方差）
- [ ] 网页服务调用真引擎，无 mock
- [ ] 无硬编码密钥，`.env` 已 gitignore，旧密码已撤销
- [ ] 报表含因子归因
- [ ] 配置可复现、IC 衰减可监控

达到以上全部，AlphaStream 才从「作业」变成「研究」。

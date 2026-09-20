# AlphaStream Workbench · 风险模型观测台

一个**研究仪器**，不是产品页。

它不回答"该买什么"，它回答三个当前真正卡住项目的问题：

1. **这个数字是怎么来的？** —— 屏幕上任何数字都属于某个不可变的 Run。
2. **这个数字能不能信？** —— 每个结论旁边挂着计算出来的"证据徽章"。
3. **我们俩为什么跑出不同的数？** —— 对账是一等页面，不是聊天记录。

## 启动

```bash
venv/bin/python -m uvicorn workbench.app:app --host 127.0.0.1 --port 8090
# 浏览器打开 http://127.0.0.1:8090
```

依赖见根目录 `requirements.txt`（核心是 fastapi / uvicorn / pandas / pyarrow / scipy / scikit-learn）。
前端图表用 Plotly（CDN），页面本身是静态文件，无需构建步骤。

## 四个页面

| 页面 | 作用 | 数据来源 |
|---|---|---|
| **Runs** | 发起 / 浏览 / 检视 Run；下载产物与 manifest | `runs/<id>/run_manifest.json` |
| **Calibration** | 相对误差时序、分布、分季度中位数、模型 vs 已实现波动率 | `selfcheck_report.csv` |
| **Risk** | 因子暴露、因子风险贡献、因子/特异分解、权重方案对比、Σ 条件数 | `asset_covariance_latest.parquet` + `factor_cov` + 该 Run 的 X 输入 |
| **Compare** | 两个 Run 的参数 / 输入指纹 / 形状 / 指标逐项对账 + 误差序列叠加 | 两个 manifest + 两份自检报告 |

## 设计原则

### ① Run 是一等公民

一次 Run = 一次不可变的 `scripts/run_risk_pipeline.py` 执行，落在 `runs/<run_id>/`：

```
status.json                     由观测台写入：running / finished / failed
run.log                         该次运行的完整输出
run_manifest.json               由 runner 写入：参数、输入指纹、产物、检查项
factor_returns.parquet          f
factor_cov.parquet              F (K×K)
specific_variance.parquet       D (N×N，仅对角非零)
asset_covariance_latest.parquet Σ（最新截面）
selfcheck_report.csv            逐日校准报告
```

**网页触发执行的就是 runner 本身**（`subprocess` 调同一个 CLI），所以浏览器跑和终端跑没有任何差别——网页只是入口，不是另一条实现。

### ② 证据徽章是算出来的，不是装饰

`analytics.evidence()` 的每一条徽章都对应一种"这个模型曾经误导过人"的方式：

- **缺常数市场因子** —— X 只有风格因子列时，`r = Xf + ε` 没有市场项，市场共同波动被计入残差，
  等权组合年化波动会低到 1.5% 这种荒谬水平；此时组合波动**不可用作风险估计**。
- **样本内检查** —— F 与 D 用全样本估计一次再回溯套用，因此 self-check 是样本内诊断，
  **不是**样本外验证，真实预测误差应更差。
- **可用检验日数** —— 可用截面 ≈ 原始交易日 − 252（momentum 的预热），样本偏短时中位数本身不稳定。
- **矩阵正定性** / **输入可追溯**（文件大小与 mtime 指纹）。

### ③ 对账优先

`Compare` 页把参数、输入指纹、形状、检查项、检验指标逐项并排，并**只在两个 Run 的重合日期上**
比较误差中位数——否则"窗口不同"这个干扰项会淹没真正的差异。

## 已知取舍

- **最小方差用 FISTA 而非 SLSQP**：在这类 Σ 上 SLSQP 要花约 17 秒做 463 维数值微分，
  而加速投影梯度约 0.2 秒即可达到**略优**的目标值。风险页同时显示 Σ 的条件数，
  因为最小方差解的稳定性完全由它决定。
- **风险视图按 Run 缓存**（键 = run + scheme + Σ 的 mtime），首次加载约 0.5 秒，之后即时。
- **不做**：用户注册、支付、荐股、邮件推送——`Src/` 那套是遗留演示层，`memoryhandoff.md`
  明确要求推迟产品化。观测台的价值在于让**不可信可见**，而不是把未验证的结论包装成产品。

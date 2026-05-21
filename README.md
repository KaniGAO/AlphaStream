# AlphaStream

HK Equity Multi-Factor Risk Model & Min-Variance Portfolio Optimization

## Pipeline

```
Raw Data → Feature Eng → Factor Model → Optimization → Risk Mgmt → Report
   ↓           ↓              ↓              ↓*             ↓           ↓
 Parquet   Winsor/Std    OLS Daily      Markowitz    Monte Carlo   Excel/Email
```

\* Optimization module (SLSQP solver) — **AI-assisted, under active research**

---

## Core Components

### 1. Data & Feature Engineering
- Load HK market data (~440k rows): price, mkt cap, PE, volume
- Cross-sectional winsorization (2.5%/97.5%) + z-score standardization

### 2. Factor Model
Daily cross-sectional regression:
```
Return_T1 = α + β₁·MKT_CAP + β₂·PE_LAGGED + β₃·VOLUME + ε
```
Outputs: factor returns matrix + idiosyncratic alpha residuals

![Factor Cumulative Returns](images/chart_01.png)

### 3. Portfolio Optimization ⚠️
> **AI-generated code** — I'm refactoring this section with deeper mathematical understanding.

- Minimize portfolio variance: `min wᵀΣw`
- Constraints: Σw=1, 0≤w≤30%, long-only
- Current result: 7.27% annualized idiosyncratic volatility

![Monte Carlo Simulation](images/chart_02.png)

![Factor Exposure](images/chart_03.png)

---

## Web Service & Automation ⚠️

> **RESTful API + Email automation** — AI-generated scaffolding.

### FastAPI Backend (`Src/app.py`)
- `POST /trigger` — Async pipeline execution
- Returns `job_id` immediately, runs optimization in background

### Web Console
Simple HTML interface for non-technical users:
- Input investor email
- Trigger pipeline with one click
- Auto-generates & sends report

### Automated Email (`Src/report_automator.py`)
- Generates Excel tear sheet with optimal weights
- Embeds portfolio chart (Base64 inline)
- Sends via Gmail SMTP with attachment

![Web Console](images/Screenshot%202026-05-21%20at%203.28.19%E2%80%AFPM.png)
![Email Report](images/Screenshot%202026-05-21%20at%203.28.34%E2%80%AFPM.png)

---

## Project Structure

```
AlphaStream/
├── Data/               # Raw & processed parquet files
├── Notebooks/          # Research notebook (factor model core)
├── Src/
│   ├── app.py          # FastAPI server (⚠️ AI)
│   ├── report_automator.py  # Excel + email (⚠️ AI)
│   └── templates/      # Web UI
└── images/             # Charts for README
```

## Run

```bash
# Jupyter research
jupyter notebook Notebooks/alpha_stream_v1.ipynb

# Web service
python Src/app.py   # http://localhost:8080
```

## Status

| Module | Status |
|--------|--------|
| Data pipeline | ✅ Hand-written |
| Factor model | ✅ Hand-written |
| Optimization | ⚠️ AI-assisted, refactoring |
| REST API | ⚠️ AI-generated |
| Email automation | ⚠️ AI-generated |

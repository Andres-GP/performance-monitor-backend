# 📊 Performance Monitor Backend

[![CI](https://github.com/Andres-GP/performance-monitor-backend/actions/workflows/ci.yml/badge.svg)](https://github.com/Andres-GP/performance-monitor-backend/actions/workflows/ci.yml)
[![CD](https://github.com/Andres-GP/performance-monitor-backend/actions/workflows/cd.yml/badge.svg)](https://github.com/Andres-GP/performance-monitor-backend/actions/workflows/cd.yml)
[![Render](https://img.shields.io/badge/Deployed%20on-Render-46E3B7?logo=render)](https://render.com/)
[![Supabase](https://img.shields.io/badge/Database-Supabase-3ECF8E?logo=supabase)](https://supabase.com/)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python)](https://python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110-009688?logo=fastapi)](https://fastapi.tiangolo.com/)

A **backend API** for monitoring trading strategy performance across **MetaTrader 5 (MT5)** and **NinjaTrader 8 (NT8)** platforms. Built with **FastAPI**, **Supabase**, and **WebSockets**, it provides trade ingestion, performance analytics, health monitoring, and alerts. Availability of individual metrics depends on the events and baseline data supplied by the connected EAs and broker.

Before pushing from a local clone, run `sh scripts/install-git-hooks.sh`. The pre-push hook requires the full pytest suite to pass. GitHub Actions also runs the test matrix on pushes and pull requests; deployments to Render wait for the full test suite and critical lint checks to pass.

---

## 🚀 Live Endpoints

- **Staging API**: [https://performance-monitor-backend-staging.onrender.com](https://performance-monitor-backend-staging.onrender.com)
- **Production API**: [https://performance-monitor-backend-prod.onrender.com](https://performance-monitor-backend-prod.onrender.com)
- **API Documentation**: `https://your-api.onrender.com/docs` (FastAPI Swagger UI)

---

## ✨ Features

### 📈 Strategy Management

- **Start/Stop strategies** with automatic reactivation.
- **Strategy state tracking** (Running, Stopped, Edge Decay).
- **Heartbeat monitoring** for MT5 strategies (120-second timeout).
- **Health status** detection (healthy, unhealthy, edge_decay).

### 💰 Trade Tracking

- **Receive closed trades** from MT5 and NT8.
- **Automatic strategy creation** if instrument doesn't exist.
- **Trade metrics**: PnL, win rate, profit factor, max drawdown, Sharpe ratio.
- **Historical trade data** with filtering by strategy and date.

### 📊 Analytics & Monitoring

- **Performance metrics** calculated daily (win rate, profit factor, drawdown, Sharpe).
- **Edge health analysis** (OOS degradation, efficiency ratio, skewness).
- **Market regime detection** (trend, fear, volatility, breadth, strength).
- **Portfolio-level metrics** (correlation, concentration, transaction costs, ruin probability).
- **Connected portfolio EDA dashboard** (frontend repository) with normalized portfolio equity, correlations, strategy status, and each strategy's expected and latest observed account mode (demo or real capital).
- **Weekly live-vs-backtest review** with block-bootstrap percentiles, equity cones, market-regime context, return heatmaps, provisional EHI scores, a human SOP checklist, and an HTML email artifact.

### 🔔 Alerts & Notifications

- **Health alerts** for frozen orders, connection issues, inactive strategies.
- **Email notifications** via Resend for critical alerts.
- **Strategy health status** automatically updated.
- **Alert history** stored for audit and review.

### 📡 Real-time Communication

- **WebSocket server** for low-latency data ingestion.
- **REST API** for standard HTTP requests.
- **Authentication** with API secret key (Bearer token).

### 🗄️ Database & Storage

- **Supabase PostgreSQL** for all data persistence.
- **Tables**: strategies, trades, performance_metrics, edge_metrics, health_alerts, market_regime, portfolio_metrics, portfolio_weights, backtest_data, accounts.

### 🧭 Portfolio EDA and weekly SOP

The weekly report is generated from the registered strategies and the monitoring API. To generate a report from live monitoring data, configure `MONITOR_API_URL` and `MONITOR_API_TOKEN`, then run:

```bash
python -m reports.weekly --week auto
```

For an offline workflow check, run `python -m reports.weekly --week auto --fixture reports/fixtures/simulator_week.json`. Fixture runs never send the SOP email.

Each ISO-week folder under `reports/weekly/` contains:

- `summary.json`: strategy metrics, live-vs-backtest comparison, regime context, EHI components, account modes, and review status.
- `report.md`, `sop_checklist.md`, `check_vs_backtest.json`, and `check_regime.json`: the deterministic review and its supporting checks.
- `ehi.csv` and `charts/`: machine-readable scores and charts when their required data exists.
- `sop_email.html`: branded email content used by the weekly workflow.

The authenticated read-only endpoint `GET /weekly/reports/latest` returns the newest valid `summary.json`. Set `WEEKLY_REPORTS_ROOT` if reports are stored outside `reports/weekly` in the API process.

#### EHI interpretation

The EHI is **provisional**, ranges from 0 to 100, and combines two equally weighted components:

1. The mean bootstrap percentile of live expectancy, profit factor, and win rate against the selected backtest window (`last_50_trades`).
2. A regime score. Unconfirmed strategy hypotheses use a neutral 50; informational-only strategies also use 50.

Bands are provisionally red below 30, amber from 30 to below 70, and green from 70. EHI stays unavailable when the backtest comparison or market regime data is missing or insufficient. These scores support review and do not trigger or change trades. Weights and thresholds live in [`config/ehi.yaml`](config/ehi.yaml); regime hypotheses are in [`config/regimes.yaml`](config/regimes.yaml), where `hypothesis_confirmed` must remain false until the strategy evidence has been reviewed.

For a strategy to be compared with a backtest, place a CSV named `data/backtests/<STRATEGY_ID>.csv`. It must contain `entry_time_utc`, `exit_time_utc`, `pnl_pct`, and `type`. Fewer than 20 eligible live trades produce an insufficient-data state rather than a statistical verdict. Do not use simulator fixture results as performance evidence.

#### Demo versus real capital

`config/strategies.yaml` records `expected_mode: demo|live` for each strategy. Portfolio views and weekly reports also display the latest observed `current_mode` from a `strategy_started` event, its observation timestamp, and whether it matches the expected mode. Without a mode event the account is **unconfirmed**; the configured expected mode is not evidence that the broker account is currently in that mode. A mismatch is raised for human review.

#### SOP email delivery

The scheduled GitHub Actions workflow sends the weekly SOP email to **andresgarciapedreros@gmail.com** through Resend after a real-data report completes. Configure the repository secrets `RESEND_API_KEY` and `RESEND_FROM_EMAIL`; the sender must be verified with Resend. `WEEKLY_DASHBOARD_URL` is optional and adds a dashboard link. `SOP_EMAIL_TO` defaults to the requested address. If the Resend API key is absent, the workflow logs that delivery was skipped. A generated email artifact does not by itself mean an email was delivered; check the workflow run for delivery confirmation.

The email styling follows the local Alphaca Capital landing-page palette (forest green and lime). It includes the portfolio and strategy, expected/observed account mode, EHI and review signals, data limitations, and the SOP checklist. It never changes trading operations. See [`docs/monitoring/RUNBOOK.md`](docs/monitoring/RUNBOOK.md) for operating procedures.

#### Scope and known limitations

- The received initial task text describes steps through 17, while referencing later report/dashboard outputs. Steps 18, 19, and 21 are implemented; the text does not define step 20, so no requirements have been inferred for it.
- All current registry strategies declare demo as their expected mode. Runtime mode can only be shown after the monitoring API receives a `strategy_started` event with a recognizable `mode` or `data_type`.
- Baseline CSVs, complete trade execution fields, and broker-verified market context must be supplied before every requested live-vs-backtest or execution analysis can be populated. Missing data remains explicitly unavailable rather than being estimated.

---

## 🧰 Tech Stack

| Category               | Technology                                      |
| ---------------------- | ----------------------------------------------- |
| **Framework**          | FastAPI 0.110                                   |
| **Language**           | Python 3.11+                                    |
| **Database**           | Supabase (PostgreSQL)                           |
| **Authentication**     | Bearer Token (API_SECRET_KEY)                   |
| **Email Service**      | Resend                                          |
| **WebSocket Server**   | websockets 12.0                                 |
| **Task Scheduler**     | APScheduler 3.10                                |
| **Data Analysis**      | Pandas, NumPy, SciPy                            |
| **Market Data**        | yfinance                                        |
| **Visualization**      | Matplotlib, Seaborn, Plotly                     |
| **Technical Analysis** | ta (Technical Analysis Library)                 |
| **Testing**            | pytest, pytest-asyncio, pytest-cov, pytest-mock |
| **Linting & Security** | flake8, bandit                                  |
| **Deployment**         | Render                                          |
| **CI/CD**              | GitHub Actions                                  |

---

## 🔗 API Endpoints

### 📌 Authentication

All endpoints (except `/health`) require a Bearer token:

## 📌 Strategy Management

| Endpoint                           | Method   | Description                       |
| ---------------------------------- | -------- | --------------------------------- |
| `/strategies/start`                | `POST`   | Register or reactivate a strategy |
| `/strategies/stop`                 | `POST`   | Stop a strategy                   |
| `/strategies`                      | `GET`    | List all strategies with metrics  |
| `/strategies/{strategy_id}/trades` | `GET`    | Get trades for a strategy         |
| `/strategies/{strategy_id}`        | `DELETE` | Delete a stopped strategy         |

## 📌 Trades

| Endpoint  | Method | Description            |
| --------- | ------ | ---------------------- |
| `/trades` | `POST` | Receive a closed trade |

## 📌 Health & Alerts

| Endpoint     | Method | Description                |
| ------------ | ------ | -------------------------- |
| `/alerts`    | `POST` | Receive a health alert     |
| `/alerts`    | `GET`  | Get recent alerts          |
| `/heartbeat` | `POST` | Receive strategy heartbeat |

## 📌 Performance & Analytics

| Endpoint                             | Method | Description                    |
| ------------------------------------ | ------ | ------------------------------ |
| `/performance/metrics/{strategy_id}` | `GET`  | Get strategy metrics over time |
| `/market/regime`                     | `GET`  | Get current market regime      |
| `/portfolio/metrics`                 | `GET`  | Get portfolio-level metrics    |
| `/portfolio/weights`                 | `POST` | Set portfolio weights          |
| `/portfolio/weights`                 | `GET`  | Get portfolio weights          |

## 📌 Normalized Portfolio Monitoring

| Endpoint                               | Method | Description                                                  |
| -------------------------------------- | ------ | ------------------------------------------------------------ |
| `/monitor/events`                      | `POST` | Ingest a normalized monitoring event                         |
| `/portfolios`                          | `GET`  | List registered portfolios and latest metrics                |
| `/portfolios/{portfolio_id}`           | `GET`  | Read portfolio strategies, alerts, equity curve, and mode    |
| `/portfolios/{portfolio_id}/correlation` | `GET` | Read rolling strategy correlation checks                     |
| `/strategies/{strategy_id}`            | `GET`  | Read strategy metrics, alerts, and configuration              |
| `/strategies/{strategy_id}/equity`     | `GET`  | Read paginated equity samples                                 |
| `/strategies/{strategy_id}/trades`     | `GET`  | Read paginated trades                                          |
| `/weekly/reports/latest`               | `GET`  | Read the latest weekly EDA summary for the connected frontend |

## 📌 Capital Management

| Endpoint           | Method | Description            |
| ------------------ | ------ | ---------------------- |
| `/capital/report`  | `POST` | Report account capital |
| `/capital/summary` | `GET`  | Get capital summary    |

## 📌 Backtest Data

| Endpoint           | Method | Description          |
| ------------------ | ------ | -------------------- |
| `/backtest/upload` | `POST` | Upload backtest data |

## 📌 WebSocket

| Endpoint          | Protocol    | Description              |
| ----------------- | ----------- | ------------------------ |
| `/ws/performance` | `WebSocket` | Real-time data ingestion |

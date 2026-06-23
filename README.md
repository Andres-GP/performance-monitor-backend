# 📊 Performance Monitor Backend

[![CI](https://github.com/Andres-GP/performance-monitor-backend/actions/workflows/ci.yml/badge.svg)](https://github.com/Andres-GP/performance-monitor-backend/actions/workflows/ci.yml)
[![CD](https://github.com/Andres-GP/performance-monitor-backend/actions/workflows/cd.yml/badge.svg)](https://github.com/Andres-GP/performance-monitor-backend/actions/workflows/cd.yml)
[![Render](https://img.shields.io/badge/Deployed%20on-Render-46E3B7?logo=render)](https://render.com/)
[![Supabase](https://img.shields.io/badge/Database-Supabase-3ECF8E?logo=supabase)](https://supabase.com/)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python)](https://python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110-009688?logo=fastapi)](https://fastapi.tiangolo.com/)

A production-ready **backend API** for monitoring trading strategy performance across **MetaTrader 5 (MT5)** and **NinjaTrader 8 (NT8)** platforms. Built with **FastAPI**, **Supabase**, and **WebSockets**, it provides real-time trade tracking, performance analytics, health monitoring, and automated alerts.

---

## 🚀 Live Endpoints

- **Staging API**: [https://performance-monitor-backend-staging.onrender.com](https://performance-monitor-backend-staging.onrender.com)
- **Production API**: [https://performance-monitor-backend.onrender.com](https://performance-monitor-backend.onrender.com)
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

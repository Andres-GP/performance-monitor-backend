# Reconocimiento del backend

## Stack
- Python 3.11; FastAPI 0.110, Uvicorn y WebSockets.
- Supabase/PostgreSQL remoto; cliente `supabase-py`. No hay migraciones ni esquema SQL en el repo.
- Dependencias en `requirements.txt`; pruebas con pytest, pytest-asyncio, pytest-cov. Frontend no encontrado.
- Ingesta por REST autenticada con Bearer token y WebSocket `/ws/performance` (auth por mensaje).

## Persistencia encontrada
- Tablas referenciadas en código: `strategies`, `trades`, `performance_snapshots`, `health_alerts`, `accounts`, `backtest_data`, `performance_metrics`, `edge_metrics`, `market_regime`, `portfolio_metrics`, `portfolio_weights`.
- El esquema real vive en Supabase; no se encontraron definiciones/migraciones locales.

## Contrato MT5 revisado
- `PerformanceReporter.mqh` no está en el working tree; se leyó la versión de `HEAD` sin restaurarla.
- `ReportStrategyStarted` → `POST /strategies/start`: `strategy_id`, `name`, `instrument`, `instrument_type="Future"`, `timeframe`, `data_type`, `platform`, `sizing`, `start_date`, `state="Running"`.
- `ReportTradeClosed` → `POST /trades`: `strategy_id`, `instrument`, `entry_time`, `exit_time`, `quantity` (lotes, dos decimales), precios, `pnl`, `direction` (`Long`/`Short`), `cost` (comisión). El argumento `ticket` no se serializa; `profit` es enviado como `pnl`.
- `ReportHealthAlert` → `POST /alerts`: `strategy_id`, `timestamp`, `problem_type`, `details`, `severity`.
- `ReportCapital` → `POST /capital/report`: `strategy_id`, `account_type` (`demo`/`real`), `capital`, `currency`.
- `SendHeartbeat` → `POST /heartbeat`: solo `strategy_id`; se omite hasta `ReportStrategyStarted`.
- `OnBarUpdate` no envía barras; incrementa contador local y emite `Inactive strategy` al superar `m_maxBarsWithoutTrade`.
- `OnOrderRejected`, `OnOrderFrozen`, `OnPartialFill`, `OnConnectionLost` emiten alertas genéricas mediante `ReportHealthAlert`.
- Todos los POST llevan JSON y `Authorization: Bearer`; horas se forman con sufijo literal `Z` a partir de `TimeCurrent()`.
- El parámetro `sizing` del constructor se guarda como `m_sizing` y se envía en start; comentario: tamaño de contrato (lote × 100), no el campo `param=100` de la especificación nueva.

## Diferencias frente al contrato objetivo
- El reporter revisado no contiene `equity`/`UpdateEquity`, evento `bar_update`, alerta libre `SendAlert` ni endpoint de orden rechazada separado; tampoco envía `ticket` en el cierre.
- Los nombres reales son `name/instrument/quantity/pnl/direction/cost` y los tipos de alerta son texto libre (`problem_type/details`), no el esquema normalizado de la solicitud.
- No se encontró `PerformanceReporter.mqh` en la copia de trabajo; confirmar este contrato contra el reporter vigente antes de implementar ingesta. Diferencias y campos ausentes se consolidarán en `GAPS.md` en su paso.

## Endpoints principales
- POST: `/strategies/start`, `/strategies/stop`, `/trades`, `/alerts`, `/heartbeat`, `/capital/report`, `/backtest/upload`.
- GET: `/health`, `/strategies`, `/strategies/{strategy_id}/trades`, `/alerts`, `/performance/metrics/{strategy_id}`, `/portfolio/metrics`, `/market/regime`.
- WebSocket: `/ws/performance`; admite `strategy_started`, `strategy_stopped`, `trade_closed`, `performance_snapshot` y `ping`.

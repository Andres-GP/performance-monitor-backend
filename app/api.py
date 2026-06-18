# api.py
import json
import os
from datetime import datetime, timedelta
from typing import Optional

import resend
from fastapi import FastAPI, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from supabase import create_client, Client

from .config import settings
from .models import StrategyInfo, TradeRecord
from .utils.logger import setup_logger

logger = setup_logger(__name__)
security = HTTPBearer()

supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

# Resend configuration
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev")
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO")

if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY
    logger.info("Resend configured for email alerts")
else:
    logger.warning("RESEND_API_KEY not set. Email alerts disabled.")

def send_alert_email(subject: str, body: str):
    if not RESEND_API_KEY or not ALERT_EMAIL_TO:
        logger.warning("Email not configured. Skipping alert email.")
        return
    try:
        r = resend.Emails.send({
            "from": RESEND_FROM_EMAIL,
            "to": [ALERT_EMAIL_TO],
            "subject": subject,
            "html": f"<pre>{body}</pre>"
        })
        logger.info(f"Alert email sent via Resend: {r}")
    except Exception as e:
        logger.error(f"Failed to send email via Resend: {e}")

def verify_token(creds: HTTPAuthorizationCredentials = Depends(security)):
    if creds.credentials != settings.API_SECRET_KEY:
        raise HTTPException(status_code=401, detail="Invalid token")
    return creds.credentials

def parse_datetime(dt_str: str) -> datetime:
    if dt_str.endswith('Z'):
        dt_str = dt_str[:-1] + '+00:00'
    return datetime.fromisoformat(dt_str)

def create_app() -> FastAPI:
    app = FastAPI(title="Performance Monitor API", version="2.0")

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        logger.info(f"Request: {request.method} {request.url.path}")
        response = await call_next(request)
        logger.info(f"Response: {response.status_code}")
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        body = await request.body()
        logger.error(f"Validation error: {exc.errors()}")
        logger.error(f"Request body: {body.decode('utf-8')}")
        return JSONResponse(status_code=422, content={"detail": exc.errors(), "body": body.decode("utf-8")})

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    # ---- Strategy lifecycle ----
    @app.post("/strategies/start", dependencies=[Depends(verify_token)])
    async def strategy_started(data: dict):
        logger.info(f"Strategy start: {data}")
        try:
            start_date = parse_datetime(data["start_date"])
        except Exception as e:
            logger.warning(f"Date parse error: {e}, using UTC now")
            start_date = datetime.utcnow()
        strategy = StrategyInfo(
            strategy_id=data["strategy_id"],
            name=data["name"],
            instrument=data["instrument"],
            instrument_type=data.get("instrument_type"),
            timeframe=data.get("timeframe"),
            data_type=data.get("data_type"),
            platform=data.get("platform"),
            sizing=data.get("sizing"),
            start_date=start_date,
            state=data.get("state", "Running"),
            health_status="healthy"
        )
        strategy_dict = strategy.dict()
        strategy_dict["start_date"] = strategy_dict["start_date"].isoformat()
        supabase.table("strategies").upsert(strategy_dict, on_conflict="strategy_id").execute()
        return {"status": "ok"}

    @app.post("/strategies/stop", dependencies=[Depends(verify_token)])
    async def strategy_stopped(data: dict):
        logger.info(f"Strategy stop: {data}")
        supabase.table("strategies").update({
            "state": "Stopped",
            "updated_at": datetime.utcnow().isoformat()
        }).eq("strategy_id", data["strategy_id"]).execute()
        return {"status": "ok"}

    @app.post("/trades", dependencies=[Depends(verify_token)])
    async def trade_closed(data: dict):
        logger.info(f"Trade received: {data}")
        try:
            entry_time = parse_datetime(data["entry_time"])
            exit_time = parse_datetime(data["exit_time"]) if data.get("exit_time") else None
        except Exception as e:
            logger.warning(f"Date parse error: {e}, using UTC now")
            entry_time = exit_time = datetime.utcnow()
        trade = TradeRecord(
            strategy_id=data["strategy_id"],
            instrument=data["instrument"],
            entry_time=entry_time,
            exit_time=exit_time,
            quantity=data["quantity"],
            entry_price=data["entry_price"],
            exit_price=data.get("exit_price"),
            pnl=data.get("pnl"),
            direction=data.get("direction", "Long")
        )
        trade_dict = trade.dict()
        trade_dict["entry_time"] = trade_dict["entry_time"].isoformat()
        if trade_dict["exit_time"]:
            trade_dict["exit_time"] = trade_dict["exit_time"].isoformat()
        supabase.table("trades").insert(trade_dict).execute()
        return {"status": "ok"}

    # ---- Health alerts ----
    @app.post("/alerts", dependencies=[Depends(verify_token)])
    async def receive_alert(alert: dict):
        logger.warning(f"Health alert: {alert['problem_type']} - {alert['details']}")
        timestamp_str = alert.get("timestamp")
        if isinstance(timestamp_str, datetime):
            timestamp_str = timestamp_str.isoformat()
        elif not isinstance(timestamp_str, str):
            timestamp_str = datetime.utcnow().isoformat()

        # Get strategy name for email
        strategy_name = alert.get("strategy_id")
        try:
            result = supabase.table("strategies").select("name").eq("strategy_id", alert["strategy_id"]).execute()
            if result.data:
                strategy_name = result.data[0]["name"]
        except Exception as e:
            logger.error(f"Error fetching strategy name: {e}")

        record = {
            "strategy_id": alert["strategy_id"],
            "timestamp": timestamp_str,
            "problem_type": alert["problem_type"],
            "details": alert["details"],
            "severity": alert.get("severity", "high")
        }
        supabase.table("health_alerts").insert(record).execute()

        # Update health_status
        if "healthy" in alert["problem_type"].lower():
            supabase.table("strategies").update({"health_status": "healthy"}).eq("strategy_id", alert["strategy_id"]).execute()
        else:
            supabase.table("strategies").update({"health_status": "unhealthy"}).eq("strategy_id", alert["strategy_id"]).execute()

        if not ("healthy" in alert["problem_type"].lower()):
            subject = f"[Performance Monitor] {alert['problem_type']}"
            body = f"Strategy: {strategy_name}\nProblem: {alert['problem_type']}\nDetails: {alert['details']}\nTimestamp: {timestamp_str}"
            send_alert_email(subject, body)

        return {"status": "alert received"}

    # ---- Capital ----
    @app.post("/capital/report", dependencies=[Depends(verify_token)])
    async def report_capital(data: dict):
        account_type = data.get("account_type", "real")
        capital = data.get("capital")
        currency = data.get("currency", "USD")
        if capital is None:
            raise HTTPException(status_code=400, detail="Missing capital")
        existing = supabase.table("accounts").select("id").eq("account_type", account_type).execute()
        if existing.data:
            supabase.table("accounts").update({
                "capital": capital,
                "currency": currency,
                "updated_at": datetime.utcnow().isoformat()
            }).eq("id", existing.data[0]["id"]).execute()
        else:
            supabase.table("accounts").insert({
                "account_type": account_type,
                "capital": capital,
                "currency": currency
            }).execute()
        logger.info(f"Capital updated for {account_type}: {capital} {currency}")
        return {"status": "updated"}

    @app.get("/capital/summary", dependencies=[Depends(verify_token)])
    async def get_capital_summary():
        result = supabase.table("accounts").select("account_type", "capital", "currency").execute()
        accounts = result.data
        summary = {
            "total": sum(acc["capital"] for acc in accounts),
            "by_type": {}
        }
        for acc in accounts:
            acc_type = acc["account_type"]
            if acc_type not in summary["by_type"]:
                summary["by_type"][acc_type] = {"total": 0, "accounts": []}
            summary["by_type"][acc_type]["total"] += acc["capital"]
            summary["by_type"][acc_type]["accounts"].append({
                "capital": acc["capital"],
                "currency": acc.get("currency", "USD")
            })
        return summary

    # ---- Backtest upload ----
    @app.post("/backtest/upload", dependencies=[Depends(verify_token)])
    async def upload_backtest(data: dict):
        strategy_id = data.get("strategy_id")
        if not strategy_id:
            raise HTTPException(status_code=400, detail="strategy_id required")
        strategy = supabase.table("strategies").select("id").eq("strategy_id", strategy_id).execute()
        if not strategy.data:
            raise HTTPException(status_code=404, detail="Strategy not found")
        record = {
            "strategy_id": strategy_id,
            "period_start": data.get("period_start"),
            "period_end": data.get("period_end"),
            "expected_pnl": data.get("expected_pnl"),
            "expected_sharpe": data.get("expected_sharpe"),
            "expected_drawdown": data.get("expected_drawdown"),
            "parameters": data.get("parameters", {})
        }
        supabase.table("backtest_data").insert(record).execute()
        logger.info(f"Backtest data uploaded for strategy {strategy_id}")
        return {"status": "uploaded"}

    # ---- Query endpoints (UNIFICADO) ----
    @app.get("/strategies", dependencies=[Depends(verify_token)])
    async def get_strategies():
        """Get all strategies with their performance metrics, edge health, and backtest data."""
        strategies = supabase.table("strategies").select("*").execute()
        result = []
        
        for strategy in strategies.data:
            strategy_id = strategy["strategy_id"]
            
            # Get latest performance metrics
            metrics = supabase.table("performance_metrics").select("*").eq("strategy_id", strategy_id).order("date", desc=True).limit(1).execute()
            
            # Get latest edge health metrics
            edge_metrics = supabase.table("edge_metrics").select("*").eq("strategy_id", strategy_id).order("date", desc=True).limit(1).execute()
            
            # Get latest backtest data
            backtest = supabase.table("backtest_data").select("*").eq("strategy_id", strategy_id).order("period_start", desc=True).limit(1).execute()
            
            # Get trades count
            trades_count = supabase.table("trades").select("id", count="exact").eq("strategy_id", strategy_id).execute()
            
            # Get alerts last 30 days
            thirty_days_ago = (datetime.utcnow() - timedelta(days=30)).isoformat()
            alerts = supabase.table("health_alerts").select("id", count="exact").eq("strategy_id", strategy_id).gte("timestamp", thirty_days_ago).execute()
            
            # Build enriched strategy object
            strategy_data = {
                **strategy,
                "metrics": metrics.data[0] if metrics.data else None,
                "edge_health": edge_metrics.data[0] if edge_metrics.data else None,
                "backtest": backtest.data[0] if backtest.data else None,
                "trades_count": trades_count.count if hasattr(trades_count, 'count') else 0,
                "alerts_30d": alerts.count if hasattr(alerts, 'count') else 0,
            }
            result.append(strategy_data)
        
        return result

    @app.get("/performance/metrics/{strategy_id}", dependencies=[Depends(verify_token)])
    async def get_strategy_metrics(strategy_id: str, days: int = 30):
        """Get historical performance metrics for a specific strategy."""
        days_ago = (datetime.utcnow() - timedelta(days=days)).isoformat()
        result = supabase.table("performance_metrics").select("*").eq("strategy_id", strategy_id).gte("date", days_ago).order("date", desc=True).execute()
        return result.data

    @app.get("/strategies/{strategy_id}/trades", dependencies=[Depends(verify_token)])
    async def get_strategy_trades(strategy_id: str):
        result = supabase.table("trades").select("*").eq("strategy_id", strategy_id).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="No trades found")
        return result.data

    @app.get("/alerts", dependencies=[Depends(verify_token)])
    async def get_alerts(limit: int = 100):
        result = supabase.table("health_alerts").select("*").order("timestamp", desc=True).limit(limit).execute()
        return result.data

    @app.delete("/strategies/{strategy_id}", dependencies=[Depends(verify_token)])
    async def delete_strategy(strategy_id: str):
        strategy = supabase.table("strategies").select("state").eq("strategy_id", strategy_id).execute()
        if not strategy.data:
            raise HTTPException(status_code=404, detail="Strategy not found")
        if strategy.data[0]["state"] != "Stopped":
            raise HTTPException(status_code=400, detail="Strategy must be Stopped before deletion")
        # Delete related data
        supabase.table("health_alerts").delete().eq("strategy_id", strategy_id).execute()
        supabase.table("trades").delete().eq("strategy_id", strategy_id).execute()
        supabase.table("performance_metrics").delete().eq("strategy_id", strategy_id).execute()
        supabase.table("edge_metrics").delete().eq("strategy_id", strategy_id).execute()
        supabase.table("backtest_data").delete().eq("strategy_id", strategy_id).execute()
        result = supabase.table("strategies").delete().eq("strategy_id", strategy_id).execute()
        logger.info(f"Strategy {strategy_id} deleted.")
        return {"status": "deleted"}

    # ---- WebSocket (legacy) ----
    @app.websocket("/ws/performance")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        logger.info("WebSocket client connected")
        try:
            while True:
                data = await websocket.receive_text()
                logger.info(f"WebSocket received: {data}")
                await websocket.send_text(json.dumps({"type": "pong"}))
        except WebSocketDisconnect:
            logger.info("WebSocket disconnected")

    return app
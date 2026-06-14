import json
import os
from datetime import datetime
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

# Initialize Supabase
supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

# Initialize Resend
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL")
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO")

if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY
    logger.info("Resend configured for email alerts")
else:
    logger.warning("RESEND_API_KEY not set, email alerts disabled")

def send_alert_email(subject: str, body: str):
    """Send email via Resend (if configured)."""
    if not RESEND_API_KEY or not RESEND_FROM_EMAIL or not ALERT_EMAIL_TO:
        logger.warning("Email not configured. Skipping alert email.")
        return
    try:
        r = resend.Emails.send({
            "from": RESEND_FROM_EMAIL,
            "to": [ALERT_EMAIL_TO],
            "subject": subject,
            "html": f"<p>{body}</p>"
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
            start_date=start_date,
            state=data.get("state", "Running")
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
        record = {
            "strategy_id": alert["strategy_id"],
            "timestamp": timestamp_str,
            "problem_type": alert["problem_type"],
            "details": alert["details"],
            "severity": alert.get("severity", "high")
        }
        supabase.table("health_alerts").insert(record).execute()
        # Send email via Resend
        if RESEND_API_KEY and RESEND_FROM_EMAIL and ALERT_EMAIL_TO:
            subject = f"[Performance Monitor] {alert['problem_type']}"
            body = f"Strategy: {alert['strategy_id']}\nProblem: {alert['problem_type']}\nDetails: {alert['details']}\nTimestamp: {timestamp_str}"
            send_alert_email(subject, body)
        return {"status": "alert received"}

    # ---- Query and deletion endpoints ----
    @app.get("/strategies", dependencies=[Depends(verify_token)])
    async def get_strategies():
        result = supabase.table("strategies").select("*").execute()
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
        # Delete dependent data first (foreign keys)
        supabase.table("health_alerts").delete().eq("strategy_id", strategy_id).execute()
        supabase.table("trades").delete().eq("strategy_id", strategy_id).execute()
        result = supabase.table("strategies").delete().eq("strategy_id", strategy_id).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Strategy not found")
        logger.info(f"Strategy {strategy_id} and its associated data deleted.")
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
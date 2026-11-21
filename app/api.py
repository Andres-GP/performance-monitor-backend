# api.py
import json
import os
import re
import jwt
import requests
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional
from jwt.exceptions import PyJWTError

import resend
from fastapi import FastAPI, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from supabase import create_client, Client
from starlette.concurrency import run_in_threadpool

from .config import settings
from .models import StrategyInfo, TradeRecord
from .monitoring.ingestion import EventValidationError, SupabaseMonitoringRepository, ingest_event
from .monitoring.alert_lifecycle import SupabaseAlertLifecycleRepository, acknowledge_alert
from .monitoring.strategies import load_registry
from .monitoring.activity_rules import normalize_mode
from .utils.logger import setup_logger

logger = setup_logger(__name__)
security = HTTPBearer()
WEEKLY_REPORTS_ROOT = Path(os.getenv("WEEKLY_REPORTS_ROOT", "reports/weekly"))

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

# Clerk configuration (con PyJWT)
CLERK_JWKS_URL = os.getenv("CLERK_JWKS_URL", "https://your-clerk-project.clerk.accounts.dev/.well-known/jwks.json")
CLERK_ISSUER = os.getenv("CLERK_ISSUER", "https://your-clerk-project.clerk.accounts.dev")
_jwks_cache = None
_jwks_cache_time = None

def get_jwks():
    """Obtiene y cachea las claves JWKS de Clerk."""
    global _jwks_cache, _jwks_cache_time
    # Cache por 1 hora
    if _jwks_cache and (datetime.utcnow() - _jwks_cache_time).seconds < 3600:
        return _jwks_cache
    try:
        response = requests.get(CLERK_JWKS_URL)
        response.raise_for_status()
        _jwks_cache = response.json()
        _jwks_cache_time = datetime.utcnow()
        return _jwks_cache
    except Exception as e:
        logger.error(f"Failed to fetch JWKS: {e}")
        return None

def verify_clerk_token(token: str):
    """Verifica un token JWT de Clerk usando JWKS."""
    try:
        jwks = get_jwks()
        if not jwks:
            raise Exception("JWKS not available")
        
        # Obtener el kid del header
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get('kid')
        if not kid:
            raise Exception("No kid in token header")
        
        # Buscar la clave correspondiente
        key_data = None
        for key in jwks.get('keys', []):
            if key.get('kid') == kid:
                key_data = key
                break
        
        if not key_data:
            raise Exception("No matching key found in JWKS")
        
        # Construir la clave pública RSA
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key_data))
        
        # Verificar el token
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            issuer=CLERK_ISSUER,
            options={"verify_aud": False}  # Si no usas audiencia específica
        )
        return payload
    except PyJWTError as e:
        raise Exception(f"Invalid token: {e}")

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

# 🔐 AUTENTICACIÓN DUAL: Clerk (frontend) + API Key (NT8/MT5)
def verify_token(creds: HTTPAuthorizationCredentials = Depends(security)):
    token = creds.credentials
    
    # 1️⃣ Intentar validar como token de Clerk
    try:
        payload = verify_clerk_token(token)
        user_id = payload.get("sub")
        logger.info(f"Authenticated via Clerk: user_id={user_id}")
        return {"user_id": user_id, "auth_type": "clerk"}
    except Exception as e:
        logger.debug(f"Clerk validation failed: {e}")
        # Si falla, continuar con API key
    
    # 2️⃣ Validar como API_SECRET_KEY (legacy para NT8/MT5)
    if token == settings.API_SECRET_KEY:
        logger.debug("Authenticated via API_SECRET_KEY")
        return {"auth_type": "api_key"}
    
    # 3️⃣ Si ninguna funciona, rechazar
    raise HTTPException(status_code=401, detail="Invalid authentication credentials")

def parse_datetime(dt_str: str) -> datetime:
    if dt_str.endswith('Z'):
        dt_str = dt_str[:-1] + '+00:00'
    return datetime.fromisoformat(dt_str)


def _monitoring_page(query, *, limit: int, offset: int):
    response = query.range(offset, offset + limit - 1).execute()
    data = response.data or []
    total = getattr(response, "count", None)
    if not isinstance(total, int):
        total = None
    return {"items": data, "limit": limit, "offset": offset, "total": total}


def _datetime_filter(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()

def create_app() -> FastAPI:
    monitoring_registry = load_registry()
    monitoring_ready = False

    @asynccontextmanager
    async def lifespan(app):
        nonlocal monitoring_ready
        try:
            monitoring_ready = await run_in_threadpool(
                SupabaseMonitoringRepository(supabase).sync_registry,
                monitoring_registry,
            )
        except Exception:
            # The legacy API can run before migration 0001 is applied; normalized ingestion
            # becomes available once the operator installs the migration.
            logger.warning("Monitoring registry sync skipped; monitoring schema may be unapplied", exc_info=True)
        yield

    app = FastAPI(title="Performance Monitor API", version="2.0", lifespan=lifespan)

    def record_monitoring_event(event_type: str, payload: dict):
        """Keep legacy EA routes working while also recording the normalized event."""
        if not monitoring_ready:
            return None
        try:
            return ingest_event(
                event_type,
                payload,
                SupabaseMonitoringRepository(supabase),
                monitoring_registry,
            )
        except EventValidationError as exc:
            logger.warning("Monitoring event rejected after raw capture (%s): %s", event_type, exc)
        except Exception:
            logger.exception("Monitoring event persistence failed for %s", event_type)
        return None

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
        now = datetime.now(timezone.utc)
        try:
            rows = (
                supabase.table("event_raw").select("received_at")
                .order("received_at", desc=True).limit(1).execute().data or []
            )
            if not isinstance(rows, list):
                rows = []
            received_at = rows[0].get("received_at") if rows else None
            if received_at:
                parsed = datetime.fromisoformat(received_at.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                age_seconds = max(0, (now - parsed.astimezone(timezone.utc)).total_seconds())
                ingestion_status = "fresh" if age_seconds <= 300 else "stale"
            else:
                age_seconds, ingestion_status = None, "empty"
            return {
                "status": "ok",
                "ingestion": {
                    "status": ingestion_status,
                    "last_received_at": received_at,
                    "age_seconds": age_seconds,
                    "stale_after_seconds": 300,
                },
            }
        except Exception:
            logger.warning("Monitoring freshness check unavailable", exc_info=True)
            return {"status": "ok", "ingestion": {"status": "unavailable"}}

    @app.get("/weekly/reports/latest", dependencies=[Depends(verify_token)])
    async def latest_weekly_report():
        """Serve the newest generated weekly summary as a read-only dashboard feed."""
        candidates = sorted(
            (path for path in WEEKLY_REPORTS_ROOT.glob("????-W??/summary.json")
             if re.fullmatch(r"\d{4}-W\d{2}", path.parent.name)),
            key=lambda path: path.parent.name,
            reverse=True,
        )
        if not candidates:
            raise HTTPException(status_code=404, detail="No weekly review is available")
        try:
            payload = json.loads(candidates[0].read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.exception("Latest weekly summary could not be read")
            raise HTTPException(status_code=503, detail="Latest weekly review is unreadable") from exc
        if not isinstance(payload, dict) or payload.get("week") != candidates[0].parent.name:
            raise HTTPException(status_code=503, detail="Latest weekly review is invalid")
        return payload

    @app.post("/monitor/events", dependencies=[Depends(verify_token)])
    async def ingest_monitoring_event(request: Request):
        try:
            envelope = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
        if not isinstance(envelope, dict):
            raise HTTPException(status_code=422, detail="Event envelope must be a JSON object")
        event_type = envelope.get("event_type") or envelope.get("type")
        payload = envelope.get("payload")
        if not isinstance(event_type, str) or not isinstance(payload, dict):
            raise HTTPException(status_code=422, detail="event_type and object payload are required")
        try:
            return await run_in_threadpool(
                ingest_event,
                event_type,
                payload,
                SupabaseMonitoringRepository(supabase),
                monitoring_registry,
                idempotency_key=envelope.get("idempotency_key"),
            )
        except EventValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Monitoring event ingestion failed")
            raise HTTPException(status_code=503, detail="Monitoring ingestion unavailable") from exc

    @app.get("/portfolios", dependencies=[Depends(verify_token)])
    async def read_portfolios(
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ):
        portfolios = monitoring_registry.portfolios[offset:offset + limit]
        items = []
        for portfolio in portfolios:
            latest = (
                supabase.table("daily_stats").select("*")
                .eq("portfolio_id", portfolio.id).order("ts", desc=True).limit(1).execute().data or []
            )
            items.append({**portfolio.model_dump(mode="json"), "metrics": latest[0] if latest else None})
        return {"items": items, "limit": limit, "offset": offset, "total": len(monitoring_registry.portfolios)}

    @app.get("/portfolios/{portfolio_id}", dependencies=[Depends(verify_token)])
    async def read_portfolio(portfolio_id: str):
        portfolio = next((item for item in monitoring_registry.portfolios if item.id == portfolio_id), None)
        if portfolio is None:
            raise HTTPException(status_code=404, detail="Portfolio not found")
        latest = (
            supabase.table("daily_stats").select("*")
            .eq("portfolio_id", portfolio_id).order("ts", desc=True).limit(1).execute().data or []
        )
        alerts = (
            supabase.table("alert").select("*").eq("portfolio_id", portfolio_id)
            .in_("status", ["open", "ack"]).order("last_seen", desc=True).limit(100).execute().data or []
        )
        strategies = []
        for strategy in monitoring_registry.strategies:
            if strategy.portfolio_id != portfolio_id:
                continue
            stats = (
                supabase.table("daily_stats").select("*")
                .eq("strategy_id", strategy.id).order("ts", desc=True).limit(1).execute().data or []
            )
            strategy_alerts = (
                supabase.table("alert").select("*").eq("strategy_id", strategy.id)
                .in_("status", ["open", "ack"]).order("last_seen", desc=True).limit(100).execute().data or []
            )
            heartbeat = (
                supabase.table("heartbeat").select("ts").eq("strategy_id", strategy.id)
                .order("ts", desc=True).limit(1).execute().data or []
            )
            starts = (
                supabase.table("event_raw").select("payload,received_at").eq("strategy_id", strategy.id)
                .eq("event_type", "strategy_started").order("received_at", desc=True).limit(1).execute().data or []
            )
            start_payload = (starts[0].get("payload") or {}) if starts else {}
            observed_mode = normalize_mode(start_payload.get("mode") or start_payload.get("data_type"))
            alerts.extend(strategy_alerts)
            strategies.append({
                **strategy.model_dump(mode="json"),
                "current_mode": observed_mode,
                "mode_status": "unconfirmed" if observed_mode is None else "matches_expected" if observed_mode == strategy.expected_mode else "mode_mismatch",
                "mode_observed_at": starts[0].get("received_at") if starts else None,
                "metrics": stats[0] if stats else None,
                "alerts": strategy_alerts,
                "last_heartbeat_at": heartbeat[0].get("ts") if heartbeat else None,
            })
        member_ids = [item.id for item in monitoring_registry.strategies if item.portfolio_id == portfolio_id]
        samples = []
        if member_ids:
            samples = (
                supabase.table("equity_sample").select("strategy_id,ts,equity")
                .in_("strategy_id", member_ids)
                .gte("ts", (datetime.now(timezone.utc) - timedelta(days=90)).isoformat())
                .order("ts", desc=True).range(0, 9999).execute().data or []
            )
        # Build a portfolio curve by summing each strategy's latest sample per minute.
        # Picking one latest sample globally would mislabel a strategy's equity as portfolio equity.
        by_strategy_minute = {}
        for sample in samples:
            ts = datetime.fromisoformat(sample["ts"].replace("Z", "+00:00"))
            minute = ts.replace(second=0, microsecond=0).isoformat()
            key = (sample["strategy_id"], minute)
            if key not in by_strategy_minute or ts >= by_strategy_minute[key]["ts"]:
                by_strategy_minute[key] = {"ts": ts, "equity": float(sample["equity"])}
        by_minute = {}
        for (_, minute), row in by_strategy_minute.items():
            aggregate = by_minute.setdefault(minute, {"ts": row["ts"], "equity": 0.0})
            aggregate["equity"] += row["equity"]
            aggregate["ts"] = max(aggregate["ts"], row["ts"])
        equity_curve = [
            {"ts": row["ts"].isoformat(), "equity": row["equity"]}
            for row in sorted(by_minute.values(), key=lambda value: value["ts"])
        ]
        return {
            "portfolio": portfolio.model_dump(mode="json"),
            "metrics": latest[0] if latest else None,
            "strategies": strategies,
            "alerts": alerts,
            "equity_curve": equity_curve,
        }

    @app.get("/strategies/{strategy_id}", dependencies=[Depends(verify_token)])
    async def read_strategy(strategy_id: str):
        strategy = next((item for item in monitoring_registry.strategies if item.id == strategy_id), None)
        if strategy is None:
            raise HTTPException(status_code=404, detail="Strategy not found")
        stats = (
            supabase.table("daily_stats").select("*")
            .eq("strategy_id", strategy_id).order("ts", desc=True).limit(1).execute().data or []
        )
        alerts = (
            supabase.table("alert").select("*").eq("strategy_id", strategy_id)
            .in_("status", ["open", "ack"]).order("last_seen", desc=True).limit(100).execute().data or []
        )
        return {
            "strategy": strategy.model_dump(mode="json"),
            "metrics": stats[0] if stats else None,
            "alerts": alerts,
        }

    @app.get("/strategies/{strategy_id}/equity", dependencies=[Depends(verify_token)])
    async def read_strategy_equity(
        strategy_id: str,
        from_: datetime | None = Query(None, alias="from"),
        to: datetime | None = None,
        limit: int = Query(500, ge=1, le=2000),
        offset: int = Query(0, ge=0),
    ):
        if not any(item.id == strategy_id for item in monitoring_registry.strategies):
            raise HTTPException(status_code=404, detail="Strategy not found")
        if from_ and to and from_ > to:
            raise HTTPException(status_code=422, detail="from must be earlier than or equal to to")
        query = supabase.table("equity_sample").select("*", count="exact").eq("strategy_id", strategy_id)
        if from_:
            query = query.gte("ts", _datetime_filter(from_))
        if to:
            query = query.lte("ts", _datetime_filter(to))
        query = query.order("ts", desc=True)
        return _monitoring_page(query, limit=limit, offset=offset)

    @app.get("/portfolios/{portfolio_id}/trades", dependencies=[Depends(verify_token)])
    async def read_portfolio_trades(
        portfolio_id: str,
        from_: datetime | None = Query(None, alias="from"),
        to: datetime | None = None,
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ):
        if not any(item.id == portfolio_id for item in monitoring_registry.portfolios):
            raise HTTPException(status_code=404, detail="Portfolio not found")
        if from_ and to and from_ > to:
            raise HTTPException(status_code=422, detail="from must be earlier than or equal to to")
        strategy_ids = [
            item.id for item in monitoring_registry.strategies
            if item.portfolio_id == portfolio_id
        ]
        if not strategy_ids:
            return {"items": [], "limit": limit, "offset": offset, "total": 0}
        query = (
            supabase.table("trade").select("*", count="exact")
            .in_("strategy_id", strategy_ids)
        )
        if from_:
            query = query.gte("exit_time", _datetime_filter(from_))
        if to:
            query = query.lte("exit_time", _datetime_filter(to))
        query = query.order("exit_time", desc=True)
        return _monitoring_page(query, limit=limit, offset=offset)

    @app.get("/portfolios/{portfolio_id}/correlation", dependencies=[Depends(verify_token)])
    async def read_portfolio_correlation(
        portfolio_id: str,
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ):
        portfolio = next((item for item in monitoring_registry.portfolios if item.id == portfolio_id), None)
        if portfolio is None:
            raise HTTPException(status_code=404, detail="Portfolio not found")
        members = {item.id for item in monitoring_registry.strategies if item.portfolio_id == portfolio_id}
        rows = (
            supabase.table("rule_state").select("scope_id,state,last_evaluated_at")
            .eq("rule_key", "CORR_HIGH").eq("scope_type", "strategy")
            .order("last_evaluated_at", desc=True).execute().data or []
        )
        pairs = []
        for row in rows:
            state = row.get("state") or {}
            if state.get("strategy_a") in members or state.get("strategy_b") in members:
                pairs.append({**state, "last_evaluated_at": row.get("last_evaluated_at")})
        return {
            "portfolio_id": portfolio_id,
            "items": pairs[offset:offset + limit],
            "limit": limit,
            "offset": offset,
            "total": len(pairs),
        }

    @app.post("/alerts/{alert_id}/ack", dependencies=[Depends(verify_token)])
    async def acknowledge_monitoring_alert(alert_id: int):
        rows = (
            supabase.table("alert").select("id,status").eq("id", alert_id).limit(1).execute().data or []
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Alert not found")
        if rows[0]["status"] == "resolved":
            raise HTTPException(status_code=409, detail="Resolved alert cannot be acknowledged")
        if rows[0]["status"] == "open":
            acknowledge_alert(
                SupabaseAlertLifecycleRepository(supabase),
                alert_id,
                now=datetime.now(timezone.utc),
            )
        return {"id": alert_id, "status": "ack"}

    # ---- Strategy lifecycle ----
    @app.post("/strategies/start", 
              dependencies=[Depends(verify_token)],
              openapi_extra={
                  "requestBody": {
                      "content": {
                          "application/json": {
                              "examples": {
                                  "mt5": {
                                      "summary": "MT5 Strategy",
                                      "value": {
                                          "strategy_id": "1782168806_TestStrategyMT5",
                                          "name": "TestStrategyMT5",
                                          "instrument": "US100Cash",
                                          "instrument_type": "Future",
                                          "timeframe": "PERIOD_M1",
                                          "data_type": "Simulation",
                                          "platform": "MT5",
                                          "sizing": 10,
                                          "start_date": "2026-06-22T22:53:26Z",
                                          "state": "Running"
                                      }
                                  },
                                  "nt8": {
                                      "summary": "NT8 Strategy",
                                      "value": {
                                          "strategy_id": "392667451",
                                          "name": "TestStrategy",
                                          "instrument": "GC AUG26",
                                          "instrument_type": "Future",
                                          "timeframe": "1 Minute",
                                          "data_type": "Simulation",
                                          "platform": "NT8",
                                          "sizing": 5,
                                          "start_date": "2026-06-22T18:21:48.725Z",
                                          "state": "Running"
                                      }
                                  }
                              }
                          }
                      }
                  }
              })
    async def strategy_started(data: dict):
        logger.info(f"Strategy start: {data}")
        record_monitoring_event("strategy_started", data)
        
        strategy_name = data["name"]
        instrument = data["instrument"]
        platform = data.get("platform", "NT8")
        new_strategy_id = data["strategy_id"]
        
        # Search for existing strategy by name + instrument + platform
        existing = supabase.table("strategies").select("*")\
            .eq("name", strategy_name)\
            .eq("instrument", instrument)\
            .eq("platform", platform).execute()
        
        if existing.data:
            existing_id = existing.data[0]["strategy_id"]
            current_state = existing.data[0].get("state", "Unknown")
            logger.info(f"Strategy '{strategy_name}' on '{instrument}' already exists (ID: {existing_id}, state: {current_state}). Reactivating.")
            
            supabase.table("strategies").update({
                "state": "Running",
                "updated_at": datetime.utcnow().isoformat(),
                "instrument_type": data.get("instrument_type"),
                "timeframe": data.get("timeframe"),
                "data_type": data.get("data_type"),
                "sizing": data.get("sizing"),
                "last_heartbeat": datetime.utcnow().isoformat(),
                "health_status": "healthy"
            }).eq("strategy_id", existing_id).execute()
            
            logger.info(f"Strategy reactivated with existing ID: {existing_id}. New ID {new_strategy_id} ignored.")
            return {"status": "ok", "strategy_id": existing_id, "action": "reactivated"}
        
        else:
            try:
                start_date = parse_datetime(data["start_date"])
            except Exception as e:
                logger.warning(f"Date parse error: {e}, using UTC now")
                start_date = datetime.utcnow()
                
            strategy = StrategyInfo(
                strategy_id=new_strategy_id,
                name=strategy_name,
                instrument=instrument,
                instrument_type=data.get("instrument_type"),
                timeframe=data.get("timeframe"),
                data_type=data.get("data_type"),
                platform=platform,
                sizing=data.get("sizing"),
                start_date=start_date,
                state=data.get("state", "Running"),
                health_status="healthy"
            )
            strategy_dict = strategy.dict()
            strategy_dict["start_date"] = strategy_dict["start_date"].isoformat()
            supabase.table("strategies").upsert(strategy_dict, on_conflict="strategy_id").execute()
            logger.info(f"New strategy created: {strategy_name} on {instrument} (ID: {new_strategy_id})")
            return {"status": "ok", "strategy_id": new_strategy_id, "action": "created"}

    @app.post("/strategies/stop", 
              dependencies=[Depends(verify_token)],
              openapi_extra={
                  "requestBody": {
                      "content": {
                          "application/json": {
                              "examples": {
                                  "example": {
                                      "summary": "Stop a strategy",
                                      "value": {
                                          "strategy_id": "1782168806_TestStrategyMT5",
                                          "state": "Stopped",
                                          "stopped_at": "2026-06-22T23:00:00Z"
                                      }
                                  }
                              }
                          }
                      }
                  }
              })
    async def strategy_stopped(data: dict):
        logger.info(f"Strategy stop: {data}")
        supabase.table("strategies").update({
            "state": "Stopped",
            "updated_at": datetime.utcnow().isoformat()
        }).eq("strategy_id", data["strategy_id"]).execute()
        return {"status": "ok"}

    @app.post("/trades", 
        dependencies=[Depends(verify_token)],
        openapi_extra={
            "requestBody": {
                "content": {
                    "application/json": {
                        "examples": {
                            "example": {
                                "summary": "Closed trade from MT5",
                                "value": {
                                    "strategy_id": "1782168806_TestStrategyMT5",
                                    "instrument": "US100Cash",
                                    "entry_time": "2026-06-22T22:55:29Z",
                                    "exit_time": "2026-06-22T22:55:59Z",
                                    "quantity": 0,
                                    "entry_price": 30333.7,
                                    "exit_price": 30316.86,
                                    "pnl": 0.0,
                                    "direction": "Long",
                                    "cost": 0.0
                                }
                            }
                        }
                    }
                }
            }
        })
    async def trade_closed(request: Request):
        # --- LOG 1: Cuerpo crudo recibido ---
        raw_body = await request.body()
        body_str = raw_body.decode('utf-8').strip()
        logger.info(f"🔍 RAW BODY RECEIVED: {body_str}")
        logger.info(f"🔍 RAW BODY LENGTH: {len(body_str)} chars")
        
        try:
            # --- LOG 2: Limpieza y parseo ---
            body_str = body_str.rstrip('\x00')
            # Si hay múltiples objetos JSON, tomar solo el primero
            if body_str.count('{') > 1:
                depth = 0
                end_idx = 0
                for i, ch in enumerate(body_str):
                    if ch == '{':
                        depth += 1
                    elif ch == '}':
                        depth -= 1
                        if depth == 0:
                            end_idx = i + 1
                            break
                if end_idx > 0:
                    body_str = body_str[:end_idx]
                    logger.info(f"🔍 CLEANED BODY: {body_str}")
            data = json.loads(body_str)
            logger.info(f"🔍 PARSED DATA: {data}")
        except json.JSONDecodeError as e:
            logger.error(f"❌ Invalid JSON received: {e}")
            logger.error(f"❌ Problematic string: {body_str[:200]}...")
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        
        logger.info(f"✅ Trade received: {data}")
        record_monitoring_event("trade_closed", data)
        
        strategy_id = data["strategy_id"]
        instrument = data["instrument"]
        platform = "MT5"
        
        # --- 1. Buscar o crear la estrategia (lógica existente) ---
        strategy = supabase.table("strategies").select("strategy_id").eq("strategy_id", strategy_id).execute()
        
        if not strategy.data:
            logger.warning(f"Strategy {strategy_id} not found. Looking for strategy on instrument '{instrument}' with platform '{platform}'...")
            existing = supabase.table("strategies").select("strategy_id, name").eq("instrument", instrument).eq("platform", platform).eq("state", "Running").execute()
            if existing.data:
                strategy_id = existing.data[0]["strategy_id"]
                strategy_name = existing.data[0]["name"]
                logger.info(f"Found existing strategy for {instrument}: {strategy_name} (ID: {strategy_id}). Using this ID.")
            else:
                existing = supabase.table("strategies").select("strategy_id, name").eq("instrument", instrument).eq("platform", platform).execute()
                if existing.data:
                    strategy_id = existing.data[0]["strategy_id"]
                    strategy_name = existing.data[0]["name"]
                    logger.info(f"Found Stopped strategy for {instrument}: {strategy_name} (ID: {strategy_id}). Reactivating...")
                    supabase.table("strategies").update({
                        "state": "Running",
                        "updated_at": datetime.utcnow().isoformat(),
                        "last_heartbeat": datetime.utcnow().isoformat(),
                        "health_status": "healthy"
                    }).eq("strategy_id", strategy_id).execute()
                else:
                    logger.warning(f"No strategy found for instrument '{instrument}'. Creating on the fly...")
                    strategy_name = f"MT5_{instrument}"
                    try:
                        supabase.table("strategies").insert({
                            "strategy_id": strategy_id,
                            "name": strategy_name,
                            "instrument": instrument,
                            "platform": platform,
                            "state": "Running",
                            "start_date": datetime.utcnow().isoformat(),
                            "health_status": "healthy",
                            "last_heartbeat": datetime.utcnow().isoformat()
                        }).execute()
                        logger.info(f"Strategy created on the fly: {strategy_id} for {instrument}")
                    except Exception as e:
                        logger.error(f"Failed to create strategy on the fly: {e}")
                        raise HTTPException(status_code=500, detail="Failed to create strategy")
        
        # --- 2. Extraer datos del payload ---
        entry_price = data.get("entry_price")
        exit_price = data.get("exit_price")
        quantity = data.get("quantity", 1.0)
        
        # 🔥 DIRECCIÓN: se toma del payload enviado por MetaTrader
        direction_raw = data.get("direction", "")
        direction = direction_raw.lower()
        logger.info(f"➡️ DIRECTION RAW from payload: '{direction_raw}'")
        logger.info(f"➡️ DIRECTION normalized: '{direction}'")
        
        # Fallback de quantity
        if quantity == 0:
            quantity = 1.0
            logger.warning(f"⚠️ Quantity was 0, using fallback 1 for strategy {strategy_id}")
        
        # --- 3. Calcular PnL (si no viene o es 0) ---
        pnl = data.get("pnl", 0.0)
        if pnl == 0 and entry_price and exit_price:
            # Si no hay dirección válida, deducir de los precios (fallback)
            if direction not in ["long", "short"]:
                if exit_price > entry_price:
                    direction = "long"
                    logger.info(f"Deduced direction: Long (exit {exit_price} > entry {entry_price})")
                else:
                    direction = "short"
                    logger.info(f"Deduced direction: Short (exit {exit_price} < entry {entry_price})")
            
            # Calcular PnL según dirección
            if direction == "long":
                pnl = (exit_price - entry_price) * quantity
            else:  # short
                pnl = (entry_price - exit_price) * quantity
            
            logger.info(f"💰 Calculated PnL: {pnl} (direction={direction}, qty={quantity})")
        else:
            # Si ya viene PnL, normalizar dirección
            direction = "long" if direction == "long" else "short"
        
        # --- 4. Parsear fechas ---
        try:
            entry_time = parse_datetime(data["entry_time"])
            exit_time = parse_datetime(data["exit_time"]) if data.get("exit_time") else None
        except Exception as e:
            logger.warning(f"📅 Date parse error: {e}, using UTC now")
            entry_time = exit_time = datetime.utcnow()
        
        # --- 5. Guardar el trade en la base de datos ---
        trade = TradeRecord(
            strategy_id=strategy_id,
            instrument=instrument,
            entry_time=entry_time,
            exit_time=exit_time,
            quantity=quantity,
            entry_price=entry_price,
            exit_price=exit_price,
            pnl=pnl,
            direction=direction.capitalize(),
            cost=data.get("cost", 0.0)
        )
        trade_dict = trade.dict()
        trade_dict["entry_time"] = trade_dict["entry_time"].isoformat()
        if trade_dict["exit_time"]:
            trade_dict["exit_time"] = trade_dict["exit_time"].isoformat()
        
        # Eliminar campos que no se guardan
        fields_to_remove = ["trade_id"]  
        for field in fields_to_remove:
            if field in trade_dict:
                del trade_dict[field]
        
        supabase.table("trades").insert(trade_dict).execute()
        logger.info(f"✅ Trade saved: {strategy_id} | {instrument} | {direction} | PnL: {pnl}")
        return {"status": "ok"}


    # ---- Health alerts ----
    @app.post("/alerts", 
            dependencies=[Depends(verify_token)],
            openapi_extra={
                "requestBody": {
                    "content": {
                        "application/json": {
                            "examples": {
                                "example": {
                                    "summary": "Frozen order alert",
                                    "value": {
                                        "strategy_id": "1782168806_TestStrategyMT5",
                                        "timestamp": "2026-06-22T22:55:00Z",
                                        "problem_type": "Frozen order",
                                        "details": "Order LongEntry has been Submitted for 6.6 seconds. Cancelling.",
                                        "severity": "high"
                                    }
                                }
                            }
                        }
                    }
                }
            })
    async def receive_alert(alert: dict):
        record_monitoring_event("health_alert", alert)
        logger.warning(f"Health alert: {alert['problem_type']} - {alert['details']}")
        timestamp_str = alert.get("timestamp")
        if isinstance(timestamp_str, datetime):
            timestamp_str = timestamp_str.isoformat()
        elif not isinstance(timestamp_str, str):
            timestamp_str = datetime.utcnow().isoformat()

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

        if "healthy" in alert["problem_type"].lower():
            supabase.table("strategies").update({"health_status": "healthy"}).eq("strategy_id", alert["strategy_id"]).execute()
        else:
            supabase.table("strategies").update({"health_status": "unhealthy"}).eq("strategy_id", alert["strategy_id"]).execute()

        if not ("healthy" in alert["problem_type"].lower()):
            subject = f"[Performance Monitor] {alert['problem_type']}"
            body = f"Strategy: {strategy_name}\nProblem: {alert['problem_type']}\nDetails: {alert['details']}\nTimestamp: {timestamp_str}"
            send_alert_email(subject, body)

        return {"status": "alert received"}

    # ---- Heartbeat (CORREGIDO: lectura manual de JSON) ----
    @app.post("/heartbeat", 
              dependencies=[Depends(verify_token)],
              openapi_extra={
                  "requestBody": {
                      "content": {
                          "application/json": {
                              "examples": {
                                  "example": {
                                      "summary": "Heartbeat from MT5 strategy",
                                      "value": {
                                          "strategy_id": "1782168806_TestStrategyMT5"
                                      }
                                  }
                              }
                          }
                      }
                  }
              })
    async def receive_heartbeat(request: Request):
        try:
            raw_body = await request.body()
            body_str = raw_body.decode('utf-8').strip()
            body_str = body_str.rstrip('\x00')
            # Si hay múltiples objetos, tomar solo el primero
            if body_str.count('{') > 1:
                depth = 0
                end_idx = 0
                for i, ch in enumerate(body_str):
                    if ch == '{':
                        depth += 1
                    elif ch == '}':
                        depth -= 1
                        if depth == 0:
                            end_idx = i + 1
                            break
                if end_idx > 0:
                    body_str = body_str[:end_idx]
            data = json.loads(body_str)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON received: {e}")
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        
        strategy_id = data.get("strategy_id")
        record_monitoring_event("heartbeat", data)
        if not strategy_id:
            raise HTTPException(status_code=400, detail="strategy_id required")
        
        strategy = supabase.table("strategies").select("strategy_id").eq("strategy_id", strategy_id).execute()
        if not strategy.data:
            logger.warning(f"Heartbeat for unknown strategy: {strategy_id}. Ignoring.")
            return {"status": "ignored", "reason": "strategy not found"}
        
        supabase.table("strategies").update({
            "last_heartbeat": datetime.utcnow().isoformat()
        }).eq("strategy_id", strategy_id).execute()
        
        logger.info(f"Heartbeat received for strategy: {strategy_id}")
        return {"status": "ok"}

    # ---- Capital ----
    @app.post("/capital/report", 
              dependencies=[Depends(verify_token)],
              openapi_extra={
                  "requestBody": {
                      "content": {
                          "application/json": {
                              "examples": {
                                  "example": {
                                      "summary": "Report account capital",
                                      "value": {
                                          "strategy_id": "1782168806_TestStrategyMT5",
                                          "account_type": "demo",
                                          "capital": 99846.02,
                                          "currency": "USD"
                                      }
                                  }
                              }
                          }
                      }
                  }
              })
    async def report_capital(data: dict):
        record_monitoring_event("capital", data)
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
    @app.post("/backtest/upload", 
              dependencies=[Depends(verify_token)],
              openapi_extra={
                  "requestBody": {
                      "content": {
                          "application/json": {
                              "examples": {
                                  "example": {
                                      "summary": "Upload backtest data",
                                      "value": {
                                          "strategy_id": "1782168806_TestStrategyMT5",
                                          "period_start": "2025-01-01",
                                          "period_end": "2025-12-31",
                                          "expected_pnl": 15000,
                                          "expected_sharpe": 1.8,
                                          "expected_drawdown": 8.0,
                                          "parameters": {"fast": 10, "slow": 25}
                                      }
                                  }
                              }
                          }
                      }
                  }
              })
    async def upload_backtest(data: dict):
        strategy_id = data.get("strategy_id")
        if not strategy_id:
            raise HTTPException(status_code=400, detail="strategy_id required")
        strategy = supabase.table("strategies").select("strategy_id").eq("strategy_id", strategy_id).execute()
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

    # ---- Query endpoints ----
    @app.get("/strategies", dependencies=[Depends(verify_token)])
    async def get_strategies():
        strategies = supabase.table("strategies").select("*").execute()
        result = []
        
        for strategy in strategies.data:
            strategy_id = strategy["strategy_id"]
            
            metrics = supabase.table("performance_metrics").select("*").eq("strategy_id", strategy_id).order("date", desc=True).limit(1).execute()
            edge_metrics = supabase.table("edge_metrics").select("*").eq("strategy_id", strategy_id).order("date", desc=True).limit(1).execute()
            backtest = supabase.table("backtest_data").select("*").eq("strategy_id", strategy_id).order("period_start", desc=True).limit(1).execute()
            trades_count = supabase.table("trades").select("id", count="exact").eq("strategy_id", strategy_id).execute()
            thirty_days_ago = (datetime.utcnow() - timedelta(days=30)).isoformat()
            alerts = supabase.table("health_alerts").select("id", count="exact").eq("strategy_id", strategy_id).gte("timestamp", thirty_days_ago).execute()
            
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
        days_ago = (datetime.utcnow() - timedelta(days=days)).isoformat()
        result = supabase.table("performance_metrics").select("*").eq("strategy_id", strategy_id).gte("date", days_ago).order("date", desc=True).execute()
        return result.data

    @app.get("/strategies/{strategy_id}/trades", dependencies=[Depends(verify_token)])
    async def get_strategy_trades(
        strategy_id: str,
        from_: datetime | None = Query(None, alias="from"),
        to: datetime | None = None,
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
    ):
        if not any(item.id == strategy_id for item in monitoring_registry.strategies):
            raise HTTPException(status_code=404, detail="Strategy not found")
        if from_ and to and from_ > to:
            raise HTTPException(status_code=422, detail="from must be earlier than or equal to to")
        query = supabase.table("trade").select("*", count="exact").eq("strategy_id", strategy_id)
        if from_:
            query = query.gte("exit_time", _datetime_filter(from_))
        if to:
            query = query.lte("exit_time", _datetime_filter(to))
        query = query.order("exit_time", desc=True)
        return _monitoring_page(query, limit=limit, offset=offset)

    @app.get("/alerts", dependencies=[Depends(verify_token)])
    async def get_alerts(
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        status: str | None = None,
        severity: str | None = None,
        from_: datetime | None = Query(None, alias="from"),
        to: datetime | None = None,
    ):
        if status is not None and status not in {"open", "ack", "resolved"}:
            raise HTTPException(status_code=422, detail="status must be open, ack, or resolved")
        if severity is not None and severity not in {"critical", "high", "medium", "info"}:
            raise HTTPException(status_code=422, detail="invalid severity")
        if from_ and to and from_ > to:
            raise HTTPException(status_code=422, detail="from must be earlier than or equal to to")
        query = supabase.table("alert").select("*", count="exact")
        if status:
            query = query.eq("status", status)
        if severity:
            query = query.eq("severity", severity)
        if from_:
            query = query.gte("first_seen", _datetime_filter(from_))
        if to:
            query = query.lte("first_seen", _datetime_filter(to))
        query = query.order("last_seen", desc=True)
        return _monitoring_page(query, limit=limit, offset=offset)

    # ---- Market regime endpoint ----
    @app.get("/market/regime", dependencies=[Depends(verify_token)])
    async def get_market_regime(limit: int = 1):
        result = supabase.table("market_regime").select("*").order("created_at", desc=True).limit(limit).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="No market regime data available")
        return result.data[0] if limit == 1 else result.data

    @app.delete("/strategies/{strategy_id}", dependencies=[Depends(verify_token)])
    async def delete_strategy(strategy_id: str):
        strategy = supabase.table("strategies").select("state").eq("strategy_id", strategy_id).execute()
        if not strategy.data:
            raise HTTPException(status_code=404, detail="Strategy not found")
        if strategy.data[0]["state"] != "Stopped":
            raise HTTPException(status_code=400, detail="Strategy must be Stopped before deletion")
        supabase.table("health_alerts").delete().eq("strategy_id", strategy_id).execute()
        supabase.table("trades").delete().eq("strategy_id", strategy_id).execute()
        supabase.table("performance_metrics").delete().eq("strategy_id", strategy_id).execute()
        supabase.table("edge_metrics").delete().eq("strategy_id", strategy_id).execute()
        supabase.table("backtest_data").delete().eq("strategy_id", strategy_id).execute()
        result = supabase.table("strategies").delete().eq("strategy_id", strategy_id).execute()
        logger.info(f"Strategy {strategy_id} deleted.")
        return {"status": "deleted"}
    
    # ---- Portfolio management ----
    @app.get("/portfolio/metrics", dependencies=[Depends(verify_token)])
    async def get_portfolio_metrics(limit: int = 1):
        """Get the latest portfolio metrics."""
        result = supabase.table("portfolio_metrics").select("*").order("created_at", desc=True).limit(limit).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="No portfolio metrics available")
        return result.data[0] if limit == 1 else result.data

    @app.post("/portfolio/weights", 
              dependencies=[Depends(verify_token)],
              openapi_extra={
                  "requestBody": {
                      "content": {
                          "application/json": {
                              "examples": {
                                  "weight_40": {
                                      "summary": "Set 40% weight",
                                      "value": {
                                          "strategy_id": "1782168806_TestStrategyMT5",
                                          "target_weight": 40
                                      }
                                  },
                                  "weight_60": {
                                      "summary": "Set 60% weight",
                                      "value": {
                                          "strategy_id": "another_strategy_id",
                                          "target_weight": 60
                                      }
                                  }
                              }
                          }
                      }
                  }
              })
    async def set_portfolio_weights(data: dict):
        """Set or update target weights for a strategy."""
        strategy_id = data.get("strategy_id")
        target_weight = data.get("target_weight")
        if not strategy_id or target_weight is None:
            raise HTTPException(status_code=400, detail="strategy_id and target_weight required")
        strategy = supabase.table("strategies").select("strategy_id").eq("strategy_id", strategy_id).execute()
        if not strategy.data:
            raise HTTPException(status_code=404, detail="Strategy not found")
        supabase.table("portfolio_weights").upsert({
            "strategy_id": strategy_id,
            "target_weight": target_weight,
            "updated_at": datetime.utcnow().isoformat()
        }, on_conflict="strategy_id").execute()
        logger.info(f"Portfolio weight set for {strategy_id}: {target_weight}%")
        return {"status": "updated"}

    @app.get("/portfolio/weights", dependencies=[Depends(verify_token)])
    async def get_portfolio_weights():
        """Get all portfolio weights."""
        result = supabase.table("portfolio_weights").select("*").execute()
        return result.data

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

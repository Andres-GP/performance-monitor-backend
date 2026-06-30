# api.py
import json
import os
import jwt
import requests
from datetime import datetime, timedelta
from typing import Optional
from jwt.exceptions import PyJWTError

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

    # ---- Trades ----
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
    async def trade_closed(data: dict):
        logger.info(f"Trade received: {data}")
        
        strategy_id = data["strategy_id"]
        instrument = data["instrument"]
        platform = "MT5"
        
        strategy = supabase.table("strategies").select("strategy_id").eq("strategy_id", strategy_id).execute()
        
        if not strategy.data:
            logger.warning(f"Strategy {strategy_id} not found. Looking for strategy on instrument '{instrument}' with platform '{platform}'...")
            
            existing = supabase.table("strategies").select("strategy_id, name")\
                .eq("instrument", instrument)\
                .eq("platform", platform)\
                .eq("state", "Running").execute()
            
            if existing.data:
                strategy_id = existing.data[0]["strategy_id"]
                strategy_name = existing.data[0]["name"]
                logger.info(f"Found existing strategy for {instrument}: {strategy_name} (ID: {strategy_id}). Using this ID.")
            else:
                existing = supabase.table("strategies").select("strategy_id, name")\
                    .eq("instrument", instrument)\
                    .eq("platform", platform).execute()
                
                if existing.data:
                    strategy_id = existing.data[0]["strategy_id"]
                    strategy_name = existing.data[0]["name"]
                    logger.info(f"Found Stopped strategy for {instrument}: {strategy_name} (ID: {strategy_id}). Reactivating and using this ID.")
                    
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
        
        try:
            entry_time = parse_datetime(data["entry_time"])
            exit_time = parse_datetime(data["exit_time"]) if data.get("exit_time") else None
        except Exception as e:
            logger.warning(f"Date parse error: {e}, using UTC now")
            entry_time = exit_time = datetime.utcnow()
            
        trade = TradeRecord(
            strategy_id=strategy_id,
            instrument=instrument,
            entry_time=entry_time,
            exit_time=exit_time,
            quantity=data.get("quantity", 0),
            entry_price=data.get("entry_price", 0.0),
            exit_price=data.get("exit_price"),
            pnl=data.get("pnl", 0.0),
            direction=data.get("direction", "Long"),
            cost=data.get("cost", 0.0)
        )
        trade_dict = trade.dict()
        trade_dict["entry_time"] = trade_dict["entry_time"].isoformat()
        if trade_dict["exit_time"]:
            trade_dict["exit_time"] = trade_dict["exit_time"].isoformat()

        fields_to_remove = ["trade_id"]  
        for field in fields_to_remove:
            if field in trade_dict:
                del trade_dict[field]
        
        supabase.table("trades").insert(trade_dict).execute()
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

    # ---- Heartbeat ----
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
    async def receive_heartbeat(data: dict):
        """Receives heartbeat from a strategy (MetaTrader)."""
        strategy_id = data.get("strategy_id")
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
    async def get_strategy_trades(strategy_id: str):
        result = supabase.table("trades").select("*").eq("strategy_id", strategy_id).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="No trades found")
        return result.data

    @app.get("/alerts", dependencies=[Depends(verify_token)])
    async def get_alerts(limit: int = 100):
        result = supabase.table("health_alerts").select("*").order("timestamp", desc=True).limit(limit).execute()
        return result.data

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
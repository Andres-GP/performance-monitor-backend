import json
import time

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings
from .market_data import market_data
from .models import ManualOrderRequest, StrategyConfigUpdate
from .risk_manager import RiskManager
from .supabase_client import ORDERS_TABLE, STRATEGY_CONFIGS_TABLE, supabase
from .utils.logger import setup_logger
from .websocket_server import WebSocketServer

logger = setup_logger(__name__)
security = HTTPBearer()

_ninja_socket_ws = None
pending_mt5_commands = []


def verify_token(creds: HTTPAuthorizationCredentials = Depends(security)):
    if creds.credentials != settings.API_SECRET_KEY:
        raise HTTPException(status_code=401, detail="Invalid token")
    return creds.credentials


def create_app(ws_server: WebSocketServer, risk_manager: RiskManager) -> FastAPI:
    app = FastAPI(title="Signal Engine API", version="1.0")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/strategies", dependencies=[Depends(verify_token)])
    async def get_strategies():
        result = supabase.table(STRATEGY_CONFIGS_TABLE).select("*").execute()
        return result.data

    @app.put("/strategies/{strategy_id}", dependencies=[Depends(verify_token)])
    async def update_strategy(strategy_id: int, update: StrategyConfigUpdate):
        data = {}
        if update.params:
            data["params"] = update.params
        if update.is_active is not None:
            data["is_active"] = update.is_active
        data["updated_at"] = "now()"

        result = supabase.table(STRATEGY_CONFIGS_TABLE).update(data).eq("id", strategy_id).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Strategy not found")
        logger.info(f"Strategy {strategy_id} updated")
        return result.data[0]

    @app.get("/debug/ws_status", dependencies=[Depends(verify_token)])
    async def ws_status():
        return {"ninja_connected": _ninja_socket_ws is not None}

    @app.post("/data/bar")
    async def receive_bar(data: dict):
        platform = data.get("platform")
        symbol = data.get("symbol")
        timeframe = data.get("timeframe")
        bar = {
            "open": data.get("open"),
            "high": data.get("high"),
            "low": data.get("low"),
            "close": data.get("close"),
            "volume": data.get("volume"),
            "time": data.get("time"),
        }
        if platform and symbol and timeframe and bar["close"]:
            market_data.update_bar(platform, symbol, timeframe, bar)
            logger.info(f"Bar received: {platform} {symbol} {timeframe} O:{bar['open']} C:{bar['close']}")
            return {"status": "ok"}

        logger.warning(f"Incomplete bar data: {data}")
        return {"status": "error", "reason": "missing fields"}, 400

    @app.post("/send_order_mt5", dependencies=[Depends(verify_token)])
    async def send_order_mt5(order: ManualOrderRequest):
        if order.platform != "MT5":
            raise HTTPException(status_code=400, detail="Only MT5 platform is accepted")
        cmd = {
            "type": order.command_type,
            "symbol": order.instrument,
            "action": order.action,
            "volume": order.volume,
            "ticket": order.ticket,
        }
        pending_mt5_commands.append(cmd)
        logger.info(f"MT5 command queued: {cmd}")
        return {"status": "queued", "queue_length": len(pending_mt5_commands)}

    @app.get("/get_next_order")
    async def get_next_order():
        if pending_mt5_commands:
            return pending_mt5_commands.pop(0)
        raise HTTPException(status_code=204)

    @app.post("/orders/manual", dependencies=[Depends(verify_token)])
    async def manual_order(order: ManualOrderRequest):
        global _ninja_socket_ws
        logger.info(
            f"POST /orders/manual - platform={order.platform}, "
            f"instrument={order.instrument}, action={order.action}"
        )

        new_order = {
            "instrument": order.instrument,
            "action": order.action,
            "volume": order.volume,
            "price": order.price,
            "platform": order.platform,
            "status": "pending",
        }
        result = supabase.table(ORDERS_TABLE).insert(new_order).execute()
        order_id = result.data[0]["id"]

        if order.platform == "NT8":
            if _ninja_socket_ws is None:
                supabase.table(ORDERS_TABLE).update({"status": "failed_no_bridge"}).eq("id", order_id).execute()
                logger.error("NinjaSocket is not connected")
                raise HTTPException(status_code=503, detail="NinjaSocket not connected")
            command = f"{order.action} {order.instrument} {order.volume}"
            try:
                await _ninja_socket_ws.send_text(command)
                logger.info(f"Order sent to NinjaSocket: {command}")
                supabase.table(ORDERS_TABLE).update({"status": "sent"}).eq("id", order_id).execute()
                return {"order_id": order_id, "status": "sent_via_ninjasocket", "command": command}
            except Exception as e:
                supabase.table(ORDERS_TABLE).update({"status": "failed"}).eq("id", order_id).execute()
                raise HTTPException(status_code=500, detail=f"Error sending to NT8: {str(e)}")

        if order.platform == "MT5":
            cmd = {
                "type": order.command_type,
                "symbol": order.instrument,
                "action": order.action,
                "volume": order.volume,
                "ticket": order.ticket,
            }
            pending_mt5_commands.append(cmd)
            logger.info(f"MT5 command queued: {cmd}")
            supabase.table(ORDERS_TABLE).update({"status": "queued"}).eq("id", order_id).execute()
            return {"order_id": order_id, "status": "queued_for_mt5"}

        sent = await ws_server.send_order_to_bridge(order.platform, order.dict())
        if not sent:
            supabase.table(ORDERS_TABLE).update({"status": "failed_no_bridge"}).eq("id", order_id).execute()
            raise HTTPException(status_code=503, detail="No bridge available")
        supabase.table(ORDERS_TABLE).update({"status": "sent"}).eq("id", order_id).execute()
        return {"order_id": order_id, "status": "sent"}

    @app.get("/risk/status", dependencies=[Depends(verify_token)])
    async def risk_status():
        return {
            "kill_switch_engaged": risk_manager.kill_switch_engaged,
            "daily_pnl": risk_manager.daily_pnl,
            "start_equity": risk_manager.start_equity,
        }

    @app.post("/risk/reset", dependencies=[Depends(verify_token)])
    async def reset_risk():
        risk_manager.reset_daily()
        return {"message": "Risk manager reset daily"}

    @app.websocket("/ws/client1")
    async def ninja_socket_endpoint(websocket: WebSocket):
        global _ninja_socket_ws
        await websocket.accept()
        _ninja_socket_ws = websocket
        logger.info("NinjaSocket connected to Signal Engine")
        try:
            while True:
                data = await websocket.receive_text()
                try:
                    msg = json.loads(data)
                    if msg.get("type") == "ping":
                        await websocket.send_text(json.dumps({"type": "pong"}))
                    elif msg.get("type") == "tick":
                        market_data.update_tick(
                            platform="nt8",
                            symbol=msg.get("symbol"),
                            price=msg.get("last", 0.0),
                            volume=msg.get("volume", 0),
                            timestamp=time.time(),
                        )
                    else:
                        logger.info(f"Unhandled JSON message: {msg}")
                except json.JSONDecodeError:
                    logger.info(f"Plain-text order received: {data}")
        except WebSocketDisconnect:
            _ninja_socket_ws = None
            logger.info("NinjaSocket disconnected")

    return app

# api.py
from fastapi import FastAPI, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from .supabase_client import supabase, STRATEGY_CONFIGS_TABLE, ORDERS_TABLE
from .models import StrategyConfigUpdate, ManualOrderRequest
from .websocket_server import WebSocketServer
from .risk_manager import RiskManager
from .config import settings
from .utils.logger import setup_logger
import json

logger = setup_logger(__name__)
security = HTTPBearer()

# Variable global a nivel de módulo (visible en toda la aplicación)
_ninja_socket_ws = None

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
    
    # Endpoint de diagnóstico para verificar el estado de la conexión
    @app.get("/debug/ws_status", dependencies=[Depends(verify_token)])
    async def ws_status():
        global _ninja_socket_ws
        return {"connected": _ninja_socket_ws is not None}
    
    @app.post("/orders/manual", dependencies=[Depends(verify_token)])
    async def manual_order(order: ManualOrderRequest):
        global _ninja_socket_ws
        logger.info(f"POST /orders/manual - platform={order.platform}, instrument={order.instrument}")
        logger.info(f"Valor de _ninja_socket_ws = {_ninja_socket_ws}")
        
        new_order = {
            "instrument": order.instrument,
            "action": order.action,
            "volume": order.volume,
            "price": order.price,
            "platform": order.platform,
            "status": "pending"
        }
        result = supabase.table(ORDERS_TABLE).insert(new_order).execute()
        order_id = result.data[0]["id"]
        
        if order.platform == "NT8":
            if _ninja_socket_ws is None:
                supabase.table(ORDERS_TABLE).update({"status": "failed_no_bridge"}).eq("id", order_id).execute()
                logger.error("_ninja_socket_ws es None, no se puede enviar la orden")
                raise HTTPException(status_code=503, detail="NinjaSocket not connected")
            
            command = f"{order.action} {order.instrument} {order.volume}"
            try:
                await _ninja_socket_ws.send_text(command)
                logger.info(f"Orden enviada a NinjaSocket: {command}")
                supabase.table(ORDERS_TABLE).update({"status": "sent"}).eq("id", order_id).execute()
                return {"order_id": order_id, "status": "sent_via_ninjasocket", "command": command}
            except Exception as e:
                supabase.table(ORDERS_TABLE).update({"status": "failed"}).eq("id", order_id).execute()
                raise HTTPException(status_code=500, detail=f"Error enviando: {str(e)}")
        else:
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
            "start_equity": risk_manager.start_equity
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
        logger.info("✅ NinjaSocket conectado al Signal Engine")
        logger.info(f"Variable global _ninja_socket_ws asignada = {_ninja_socket_ws}")
        try:
            while True:
                data = await websocket.receive_text()
                logger.info(f"Mensaje desde NinjaSocket: {data}")
                # Responder pong a los pings
                try:
                    msg = json.loads(data)
                    if msg.get("type") == "ping":
                        await websocket.send_text(json.dumps({"type": "pong"}))
                except:
                    pass  # no es JSON, ignorar
        except WebSocketDisconnect:
            _ninja_socket_ws = None
            logger.info("❌ NinjaSocket desconectado")
    
    return app
import asyncio
import json
import websockets
from websockets.server import WebSocketServerProtocol
from typing import Dict, Callable
from .utils.logger import setup_logger
from .risk_manager import RiskManager
from .config import settings

logger = setup_logger(__name__)

class BridgeConnection:
    def __init__(self, websocket: WebSocketServerProtocol, platform: str = "unknown"):
        self.websocket = websocket
        self.platform = platform
        self.is_authenticated = False

class WebSocketServer:
    def __init__(self, risk_manager: RiskManager):
        self.connections: Dict[WebSocketServerProtocol, BridgeConnection] = {}
        self.risk_manager = risk_manager
        self.order_callbacks: list = []

    async def handle_connection(self, websocket: WebSocketServerProtocol, path: str):
        conn = BridgeConnection(websocket)
        self.connections[websocket] = conn
        logger.info(f"Bridge conectado desde {websocket.remote_address} (path: {path})")
        
        try:
            async for message in websocket:
                await self._handle_message(websocket, message)
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Bridge desconectado: {conn.platform}")
        finally:
            self.connections.pop(websocket, None)

    async def _handle_message(self, websocket: WebSocketServerProtocol, message: str):
        conn = self.connections.get(websocket)
        if not conn:
            return
        
        try:
            msg = json.loads(message)
            msg_type = msg.get("type")
            
            if msg_type == "auth":
                token = msg.get("token", "")
                if token == settings.API_SECRET_KEY:
                    conn.is_authenticated = True
                    conn.platform = msg.get("platform", "unknown")
                    await websocket.send(json.dumps({"type": "auth_ok"}))
                    logger.info(f"Bridge autenticado: {conn.platform}")
                else:
                    await websocket.send(json.dumps({"type": "auth_error", "reason": "Invalid token"}))
                    await websocket.close()
            
            elif msg_type == "order_update":
                if conn.is_authenticated:
                    logger.info(f"Order update from {conn.platform}: {msg}")
                    for cb in self.order_callbacks:
                        cb(msg)
                    await websocket.send(json.dumps({"type": "update_received", "status": "ok"}))
            
            elif msg_type == "position_snapshot":
                if conn.is_authenticated:
                    logger.info(f"Position snapshot from {conn.platform}")
                    await websocket.send(json.dumps({"type": "snapshot_received", "status": "ok"}))
            
            else:
                logger.warning(f"Mensaje desconocido: {msg_type}")
                
        except json.JSONDecodeError:
            logger.error("Mensaje no válido (JSON inválido)")
            await websocket.send(json.dumps({"type": "error", "reason": "Invalid JSON"}))
        except Exception as e:
            logger.error(f"Error procesando mensaje: {e}")
            await websocket.send(json.dumps({"type": "error", "reason": str(e)}))

    async def send_order_to_bridge(self, platform: str, order: dict) -> bool:
        for websocket, conn in self.connections.items():
            if conn.platform == platform and conn.is_authenticated:
                try:
                    await websocket.send(json.dumps({
                        "type": "execute_order",
                        "order": order
                    }))
                    logger.info(f"Orden enviada a {platform}: {order}")
                    return True
                except Exception as e:
                    logger.error(f"Error enviando orden a {platform}: {e}")
                    return False
        logger.error(f"No hay bridge conectado para {platform}")
        return False

    def register_order_callback(self, callback: Callable):
        self.order_callbacks.append(callback)

async def start_websocket_server(risk_manager: RiskManager):
    ws_server = WebSocketServer(risk_manager)
    
    # Handler con un solo argumento (websocket) según la API moderna de websockets
    async def handler(websocket):
        # Obtener path del atributo del websocket (disponible en versiones recientes)
        path = websocket.path if hasattr(websocket, 'path') else ""
        await ws_server.handle_connection(websocket, path)
    
    server = await websockets.serve(
        handler,
        settings.HOST,
        settings.WEBSOCKET_PORT,
        compression=None
    )
    logger.info(f"WebSocket server listening on {settings.HOST}:{settings.WEBSOCKET_PORT}")
    return server, ws_server
import asyncio
import json
from typing import Dict, Set
from picows import ws_create_server, WSListener, WSTransport, WSFrame, WSMsgType
from .utils.logger import setup_logger
from .risk_manager import RiskManager
from .config import settings

logger = setup_logger(__name__)

class BridgeConnection:
    """Representa un bridge conectado (NT8 o MT5)"""
    def __init__(self, transport: WSTransport, platform: str):
        self.transport = transport
        self.platform = platform
        self.is_authenticated = False

class SignalEngineWSListener(WSListener):
    def __init__(self, risk_manager: RiskManager):
        super().__init__()
        self.connections: Dict[WSTransport, BridgeConnection] = {}
        self.risk_manager = risk_manager
        self.order_callbacks = []  # para notificar a la API/DB
    
    def on_ws_connected(self, transport: WSTransport):
        logger.info(f"Nuevo bridge conectado desde {transport.get_remote_addr()}")
        # Temporalmente sin autenticar, esperamos primer mensaje con identificación
        self.connections[transport] = BridgeConnection(transport, platform="unknown")
    
    def on_ws_frame(self, transport: WSTransport, frame: WSFrame):
        if frame.msg_type == WSMsgType.TEXT:
            try:
                msg = json.loads(frame.get_payload_as_ascii_text())
                self._handle_message(transport, msg)
            except Exception as e:
                logger.error(f"Error procesando mensaje: {e}")
                self._send_error(transport, "Invalid JSON")
        elif frame.msg_type == WSMsgType.CLOSE:
            self.on_ws_disconnected(transport)
    
    def _handle_message(self, transport: WSTransport, msg: dict):
        conn = self.connections.get(transport)
        if not conn:
            return
        
        msg_type = msg.get("type")
        
        if msg_type == "auth":
            # autenticación simple (token)
            token = msg.get("token", "")
            if token == settings.API_SECRET_KEY:
                conn.is_authenticated = True
                conn.platform = msg.get("platform", "unknown")
                self._send(transport, {"type": "auth_ok"})
                logger.info(f"Bridge autenticado: {conn.platform}")
            else:
                self._send(transport, {"type": "auth_error", "reason": "Invalid token"})
                transport.disconnect()
        
        elif msg_type == "order_update":
            # Actualización de estado de orden desde el bridge (confirmación)
            if conn.is_authenticated:
                logger.info(f"Order update from {conn.platform}: {msg}")
                # Aquí podrías guardar en DB y notificar a API
                # Llamar callbacks registrados
                for cb in self.order_callbacks:
                    cb(msg)
                self._send(transport, {"type": "update_received", "status": "ok"})
        
        elif msg_type == "position_snapshot":
            # Envío de posiciones actuales (por si se desincroniza)
            logger.info(f"Position snapshot from {conn.platform}")
            # Actualizar estado interno
        
        else:
            logger.warning(f"Mensaje desconocido: {msg_type}")
    
    def on_ws_disconnected(self, transport: WSTransport):
        if transport in self.connections:
            logger.info(f"Bridge desconectado: {self.connections[transport].platform}")
            del self.connections[transport]
    
    def _send(self, transport: WSTransport, data: dict):
        transport.send_text(json.dumps(data))
    
    def _send_error(self, transport: WSTransport, reason: str):
        self._send(transport, {"type": "error", "reason": reason})
    
    async def send_order_to_bridge(self, platform: str, order: dict) -> bool:
        """Envía una orden al bridge de la plataforma especificada"""
        for transport, conn in self.connections.items():
            if conn.platform == platform and conn.is_authenticated:
                self._send(transport, {
                    "type": "execute_order",
                    "order": order
                })
                logger.info(f"Orden enviada a {platform}: {order}")
                return True
        logger.error(f"No hay bridge conectado para {platform}")
        return False
    
    def register_order_callback(self, callback):
        self.order_callbacks.append(callback)

async def start_websocket_server(risk_manager: RiskManager):
    listener = SignalEngineWSListener(risk_manager)
    server = await ws_create_server(
        lambda: listener,
        settings.HOST,
        settings.WEBSOCKET_PORT
    )
    logger.info(f"WebSocket server listening on {settings.HOST}:{settings.WEBSOCKET_PORT}")
    return server, listener
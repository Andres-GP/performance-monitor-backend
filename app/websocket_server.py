import json
from typing import Dict, Set
import websockets
from websockets.server import WebSocketServerProtocol
from .config import settings
from .supabase_client import upsert_strategy, insert_trade, insert_snapshot
from .models import StrategyInfo, TradeRecord, PerformanceSnapshot
from .utils.logger import setup_logger
from datetime import datetime

logger = setup_logger(__name__)

class PerformanceWebSocketServer:
    def __init__(self):
        self.connections: Dict[WebSocketServerProtocol, dict] = {}  # store connection info

    async def handle_connection(self, websocket: WebSocketServerProtocol, path: str):
        """Handle new WebSocket connection."""
        conn_info = {"platform": "unknown", "authenticated": False}
        self.connections[websocket] = conn_info
        logger.info(f"New connection from {websocket.remote_address} on path {path}")

        try:
            async for message in websocket:
                await self._handle_message(websocket, message)
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Connection closed: {websocket.remote_address}")
        finally:
            self.connections.pop(websocket, None)

    async def _handle_message(self, websocket: WebSocketServerProtocol, message: str):
        conn = self.connections[websocket]
        try:
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == "auth":
                token = data.get("token", "")
                if token == settings.API_SECRET_KEY:
                    conn["authenticated"] = True
                    conn["platform"] = data.get("platform", "unknown")
                    await websocket.send(json.dumps({"type": "auth_ok"}))
                    logger.info(f"Authenticated: {conn['platform']}")
                else:
                    await websocket.send(json.dumps({"type": "auth_error", "reason": "Invalid token"}))
                    await websocket.close()
                return

            if not conn["authenticated"]:
                await websocket.send(json.dumps({"type": "error", "reason": "Not authenticated"}))
                return

            # Handle performance related messages
            if msg_type == "strategy_started":
                strategy = StrategyInfo(
                    strategy_id=data["strategy_id"],
                    name=data["name"],
                    instrument=data["instrument"],
                    start_date=datetime.fromisoformat(data["start_date"].replace("Z", "+00:00")),
                    state="Running",
                    last_heartbeat=datetime.utcnow()
                )
                upsert_strategy(strategy)
                await websocket.send(json.dumps({"type": "strategy_registered", "status": "ok"}))

            elif msg_type == "strategy_stopped":
                # Update state to Stopped in DB
                strategy = StrategyInfo(
                    strategy_id=data["strategy_id"],
                    name="", instrument="", start_date=datetime.utcnow(), state="Stopped"
                )
                upsert_strategy(strategy)
                await websocket.send(json.dumps({"type": "strategy_updated", "status": "ok"}))

            elif msg_type == "trade_closed":
                trade = TradeRecord(
                    strategy_id=data["strategy_id"],
                    instrument=data["instrument"],
                    entry_time=datetime.fromisoformat(data["entry_time"].replace("Z", "+00:00")),
                    exit_time=datetime.fromisoformat(data["exit_time"].replace("Z", "+00:00")) if data.get("exit_time") else None,
                    quantity=data["quantity"],
                    entry_price=data["entry_price"],
                    exit_price=data.get("exit_price"),
                    pnl=data.get("pnl"),
                    direction=data["direction"]
                )
                insert_trade(trade)
                await websocket.send(json.dumps({"type": "trade_recorded", "status": "ok"}))

            elif msg_type == "performance_snapshot":
                for strat_data in data["strategies"]:
                    snapshot = PerformanceSnapshot(
                        strategy_id=strat_data["strategy_id"],
                        timestamp=datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00")),
                        total_trades=strat_data["total_trades"],
                        total_pnl=strat_data["total_pnl"]
                    )
                    insert_snapshot(snapshot)
                await websocket.send(json.dumps({"type": "snapshot_received", "status": "ok"}))

            elif msg_type == "ping":
                await websocket.send(json.dumps({"type": "pong"}))
            else:
                logger.warning(f"Unknown message type: {msg_type}")

        except json.JSONDecodeError:
            logger.error("Invalid JSON received")
            await websocket.send(json.dumps({"type": "error", "reason": "Invalid JSON"}))
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            await websocket.send(json.dumps({"type": "error", "reason": str(e)}))

async def start_websocket_server():
    ws_server = PerformanceWebSocketServer()
    async def handler(websocket, path):
        await ws_server.handle_connection(websocket, path)

    server = await websockets.serve(
        handler,
        settings.HOST,
        settings.WEBSOCKET_PORT,
        compression=None
    )
    logger.info(f"WebSocket server listening on {settings.HOST}:{settings.WEBSOCKET_PORT}")
    return server, ws_server
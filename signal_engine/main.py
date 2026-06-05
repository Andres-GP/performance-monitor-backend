import asyncio
import uvicorn
from .config import settings
from .utils.logger import setup_logger
from .risk_manager import RiskManager
from .websocket_server import start_websocket_server
from .strategies.engine import StrategyEngine
from .api import create_app

logger = setup_logger(__name__)

async def main():
    risk_manager = RiskManager()
    # start_websocket_server retorna (server_asyncio, ws_server_object)
    _, ws_engine = await start_websocket_server(risk_manager)
    
    strategy_engine = StrategyEngine(ws_engine, risk_manager)
    await strategy_engine.start()
    
    app = create_app(ws_engine, risk_manager)
    
    config = uvicorn.Config(
        app,
        host=settings.HOST,
        port=settings.API_PORT,
        log_level="info",
        loop="uvloop"
    )
    server = uvicorn.Server(config)
    api_task = asyncio.create_task(server.serve())
    
    logger.info(f"Signal Engine fully started. WebSocket on {settings.HOST}:{settings.WEBSOCKET_PORT}, API on {settings.API_PORT}")
    
    await api_task
    # No cerramos el WebSocket server explícitamente aquí, pero se puede añadir limpieza si es necesario

if __name__ == "__main__":
    asyncio.run(main())
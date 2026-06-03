import asyncio
import uvicorn
from .config import settings
from .utils.logger import setup_logger
from .risk_manager import RiskManager
from .websocket_server import start_websocket_server
from .strategies.engine import StrategyEngine
from .api import create_app
from .database import engine, Base

logger = setup_logger(__name__)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def main():
    await init_db()

    risk_manager = RiskManager()

    ws_server, ws_listener = await start_websocket_server(risk_manager)

    strategy_engine = StrategyEngine(ws_listener, risk_manager)
    await strategy_engine.start()

    app = create_app(ws_listener, risk_manager)
    
    config = uvicorn.Config(
        app,
        host=settings.HOST,
        port=settings.API_PORT,
        log_level="info",
        loop="uvloop"
    )
    server = uvicorn.Server(config)
    
    api_task = asyncio.create_task(server.serve())
    
    logger.info(f"Signal Engine fully started. WebSocket on {settings.WEBSOCKET_PORT}, API on {settings.API_PORT}")
    
    await api_task
    ws_server.close()
    strategy_engine.active = False

if __name__ == "__main__":
    asyncio.run(main())
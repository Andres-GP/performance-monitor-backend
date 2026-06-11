import asyncio

import uvicorn

from .api import create_app
from .config import settings
from .risk_manager import RiskManager
from .strategies.engine import StrategyEngine
from .utils.logger import setup_logger
from .websocket_server import start_websocket_server

logger = setup_logger(__name__)


async def main():
    risk_manager = RiskManager()
    _, ws_engine = await start_websocket_server(risk_manager)

    strategy_engine = StrategyEngine(ws_engine, risk_manager)
    await strategy_engine.start()

    app = create_app(ws_engine, risk_manager)

    config = uvicorn.Config(
        app,
        host=settings.HOST,
        port=settings.API_PORT,
        log_level="info",
        loop="uvloop",
    )
    server = uvicorn.Server(config)
    api_task = asyncio.create_task(server.serve())

    logger.info(
        f"Signal Engine started. WebSocket on {settings.HOST}:{settings.WEBSOCKET_PORT}, "
        f"API on {settings.API_PORT}"
    )

    await api_task


if __name__ == "__main__":
    asyncio.run(main())

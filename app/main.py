# main.py
import asyncio
import uvicorn
from .config import settings
from .websocket_server import start_websocket_server
from .api import create_app
from .monitor import PerformanceMonitor
from .scheduler import Scheduler
from .supabase_client import supabase
from .utils.logger import setup_logger

logger = setup_logger(__name__)

async def main():
    ws_server, ws_handler = await start_websocket_server()
    logger.info(f"WebSocket server started on port {settings.WEBSOCKET_PORT}")

    app = create_app()
    config = uvicorn.Config(
        app,
        host=settings.HOST,
        port=settings.API_PORT,
        log_level="info"
    )
    server = uvicorn.Server(config)
    api_task = asyncio.create_task(server.serve())

    monitor = PerformanceMonitor(supabase)
    scheduler = Scheduler(monitor)
    scheduler.start()
    logger.info("Performance Monitor Scheduler started")

    logger.info(
        f"Performance Monitor fully started. "
        f"API on http://{settings.HOST}:{settings.API_PORT}, "
        f"WebSocket on ws://{settings.HOST}:{settings.WEBSOCKET_PORT}/ws/performance"
    )

    await api_task

if __name__ == "__main__":
    asyncio.run(main())
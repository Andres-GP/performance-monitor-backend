import asyncio
import uvicorn
from .config import settings
from .websocket_server import start_websocket_server
from .api import create_app
from .utils.logger import setup_logger

logger = setup_logger(__name__)

async def main():
    # Start WebSocket server for receiving performance data
    ws_server, ws_handler = await start_websocket_server()
    logger.info(f"WebSocket server started on port {settings.WEBSOCKET_PORT}")

    # Start FastAPI REST server
    app = create_app()
    config = uvicorn.Config(
        app,
        host=settings.HOST,
        port=settings.API_PORT,
        log_level="info"
    )
    server = uvicorn.Server(config)
    api_task = asyncio.create_task(server.serve())

    logger.info(f"Performance Monitor started. API on http://{settings.HOST}:{settings.API_PORT}, WebSocket on ws://{settings.HOST}:{settings.WEBSOCKET_PORT}/ws/performance")

    await api_task

if __name__ == "__main__":
    asyncio.run(main())
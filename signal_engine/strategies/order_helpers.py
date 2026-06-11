from ..api import _ninja_socket_ws, pending_mt5_commands
from ..utils.logger import setup_logger

logger = setup_logger(__name__)


async def send_order_to_mt5(platform: str, symbol: str, action: str, volume: float) -> bool:
    cmd = {
        "type": "order",
        "symbol": symbol,
        "action": action,
        "volume": volume,
        "ticket": None,
    }
    pending_mt5_commands.append(cmd)
    logger.info(f"MT5 order queued: {action} {volume} {symbol}")
    return True


async def send_order_to_nt8(platform: str, symbol: str, action: str, volume: float) -> bool:
    if _ninja_socket_ws is None:
        logger.error("NinjaSocket is not connected, cannot send order to NT8")
        return False
    command = f"{action} {symbol} {volume}"
    await _ninja_socket_ws.send_text(command)
    logger.info(f"NT8 order sent: {command}")
    return True

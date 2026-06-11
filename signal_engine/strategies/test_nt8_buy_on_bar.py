import asyncio
import json
import signal_engine.api as api
from ..market_data import market_data
from ..utils.logger import setup_logger

logger = setup_logger(__name__)

class NT8BuyOnBarStrategy:
    """
    Generic strategy for NinjaTrader 8:
    - Subscribes to a given symbol and timeframe (in minutes).
    - Sends a market buy order (quantity) on each new bar.
    """

    def __init__(self, send_order_func, symbol: str, timeframe: int, quantity: int):
        """
        Args:
            send_order_func: async function (platform, symbol, action, quantity)
            symbol: instrument name (e.g., "ES 06-26")
            timeframe: bar period in minutes (e.g., 1, 5, 15)
            quantity: number of contracts to buy
        """
        self.send_order = send_order_func
        self.symbol = symbol
        self.timeframe = str(timeframe)
        self.quantity = quantity
        self.last_bar_time = None
        self.active = True

    async def _wait_and_subscribe(self):
        while api._ninja_socket_ws is None:
            logger.info("⏳ Waiting for NT8 WebSocket connection...")
            await asyncio.sleep(2)
        logger.info("✅ NT8 WebSocket connected. Sending subscription...")
        msg = {
            "type": "subscribe",
            "symbol": self.symbol,
            "timeframe": int(self.timeframe),
        }
        try:
            await api._ninja_socket_ws.send_text(json.dumps(msg))
            logger.info(f"📨 Subscription sent: {msg}")
        except Exception as e:
            logger.error(f"Error sending subscription: {e}")

    async def run(self):
        logger.info(
            f"🧪 NT8 strategy: {self.symbol} {self.timeframe} min, "
            f"quantity {self.quantity}, checking every 30s"
        )
        await self._wait_and_subscribe()

        while self.active:
            bar = market_data.get_last_bar("nt8", self.symbol, self.timeframe)
            if bar and bar.get("time"):
                bar_time = bar["time"]
                if bar_time != self.last_bar_time:
                    self.last_bar_time = bar_time
                    logger.info(
                        f"📊 New bar - {self.symbol} {self.timeframe} min, close={bar['close']}"
                    )
                    await self.send_order("nt8", self.symbol, "buy", self.quantity)
            await asyncio.sleep(30)
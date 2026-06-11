import asyncio
from ..market_data import market_data
from ..utils.logger import setup_logger

logger = setup_logger(__name__)

class MT5BuyOnBarStrategy:
    """
    Generic strategy for MetaTrader 5:
    - Waits for new bars from the /data/bar endpoint.
    - Sends a market buy order (volume) on each new bar.
    """

    def __init__(self, send_order_func, symbol: str, timeframe: int, volume: float):
        """
        Args:
            send_order_func: async function (platform, symbol, action, volume)
            symbol: instrument name (e.g., "EURUSD")
            timeframe: bar period in minutes (e.g., 15)
            volume: lot size (e.g., 0.01)
        """
        self.send_order = send_order_func
        self.symbol = symbol
        self.timeframe = str(timeframe)
        self.volume = volume
        self.last_bar_time = None
        self.active = True

    async def run(self):
        logger.info(
            f"🧪 MT5 strategy: {self.symbol} {self.timeframe} min, volume {self.volume}"
        )
        while self.active:
            bar = market_data.get_last_bar("mt5", self.symbol, self.timeframe)
            if bar and bar.get("time"):
                bar_time = bar["time"]
                if bar_time != self.last_bar_time:
                    self.last_bar_time = bar_time
                    logger.info(
                        f"📊 New bar - {self.symbol} {self.timeframe} min, close={bar['close']}"
                    )
                    await self.send_order("mt5", self.symbol, "buy", self.volume)
            await asyncio.sleep(30)
from collections import defaultdict
from datetime import datetime
from typing import Dict, Optional

from .utils.logger import setup_logger

logger = setup_logger(__name__)


class MarketDataStore:
    """In-memory store for the latest bars per platform, symbol, and timeframe."""

    def __init__(self):
        self.data: Dict[str, Dict] = {"nt8": {}, "mt5": {}}
        self.bar_builders = defaultdict(lambda: defaultdict(dict))

    def update_tick(self, platform: str, symbol: str, price: float, volume: int, timestamp: float):
        """Aggregate ticks into 1-minute bars."""
        if symbol not in self.data[platform]:
            self.data[platform][symbol] = {}
        self.data[platform][symbol]["last_tick"] = {"price": price, "time": timestamp}

        timeframe = 1
        bar_key = f"{symbol}_{timeframe}"
        builder = self.bar_builders[platform][bar_key]
        minute_start = int(timestamp // 60) * 60

        if builder.get("minute_start") != minute_start:
            if "open" in builder:
                self._publish_bar(platform, symbol, timeframe, builder)
            builder["minute_start"] = minute_start
            builder["open"] = price
            builder["high"] = price
            builder["low"] = price
            builder["close"] = price
            builder["volume"] = volume
        else:
            builder["high"] = max(builder["high"], price)
            builder["low"] = min(builder["low"], price)
            builder["close"] = price
            builder["volume"] += volume

    def _publish_bar(self, platform: str, symbol: str, timeframe: int, builder: dict):
        bar = {
            "open": builder["open"],
            "high": builder["high"],
            "low": builder["low"],
            "close": builder["close"],
            "volume": builder["volume"],
            "time": datetime.fromtimestamp(builder["minute_start"]).isoformat(),
        }
        if symbol not in self.data[platform]:
            self.data[platform][symbol] = {}
        self.data[platform][symbol][str(timeframe)] = bar
        logger.debug(f"Bar built: {platform} {symbol} {timeframe}m O:{bar['open']} C:{bar['close']}")

    def update_bar(self, platform: str, symbol: str, timeframe: str, bar: dict):
        if symbol not in self.data[platform]:
            self.data[platform][symbol] = {}
        self.data[platform][symbol][timeframe] = {
            "open": bar.get("open"),
            "high": bar.get("high"),
            "low": bar.get("low"),
            "close": bar.get("close"),
            "volume": bar.get("volume"),
            "time": bar.get("time"),
            "timestamp": datetime.utcnow(),
        }
        logger.debug(f"[{platform}] {symbol} {timeframe} updated: close={bar.get('close')}")

    def get_last_bar(self, platform: str, symbol: str, timeframe: str) -> Optional[dict]:
        return self.data.get(platform, {}).get(symbol, {}).get(str(timeframe))


market_data = MarketDataStore()

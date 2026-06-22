from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List, Dict, Any

class StrategyInfo(BaseModel):
    strategy_id: str
    name: str
    instrument: str
    instrument_type: Optional[str] = None
    timeframe: Optional[str] = None
    data_type: Optional[str] = None
    platform: Optional[str] = None
    sizing: Optional[int] = None
    start_date: datetime
    state: str
    last_heartbeat: Optional[datetime] = None
    health_status: Optional[str] = "healthy"

class TradeRecord(BaseModel):
    trade_id: Optional[str] = None  # ✅ Opcional (NinjaTrader puede enviarlo)
    strategy_id: str
    instrument: str
    entry_time: datetime
    exit_time: Optional[datetime]
    quantity: int
    entry_price: float
    exit_price: Optional[float]
    pnl: Optional[float]
    direction: str  # "Long" or "Short"
    cost: Optional[float] = None

class PerformanceSnapshot(BaseModel):
    strategy_id: str
    timestamp: datetime
    total_trades: int
    total_pnl: float
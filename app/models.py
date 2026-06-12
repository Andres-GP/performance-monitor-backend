from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List

class StrategyInfo(BaseModel):
    strategy_id: str
    name: str
    instrument: str
    start_date: datetime
    state: str
    last_heartbeat: Optional[datetime] = None

class TradeRecord(BaseModel):
    trade_id: Optional[str] = None
    strategy_id: str
    instrument: str
    entry_time: datetime
    exit_time: Optional[datetime]
    quantity: int
    entry_price: float
    exit_price: Optional[float]
    pnl: Optional[float]
    direction: str  # "Long" or "Short"

class PerformanceSnapshot(BaseModel):
    strategy_id: str
    timestamp: datetime
    total_trades: int
    total_pnl: float

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
    strategy_id: str
    instrument: str
    entry_time: datetime
    exit_time: Optional[datetime]
    quantity: float 
    entry_price: float
    exit_price: Optional[float]
    pnl: float
    direction: str
    cost: Optional[float] = 0.0

class PerformanceSnapshot(BaseModel):
    strategy_id: str
    timestamp: datetime
    total_trades: int
    total_pnl: float
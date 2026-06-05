from pydantic import BaseModel
from typing import Dict, Any, Optional
from datetime import datetime

class StrategyConfigUpdate(BaseModel):
    params: Dict[str, Any]
    is_active: Optional[bool] = None

class ManualOrderRequest(BaseModel):
    instrument: str
    action: str
    volume: float
    platform: str
    price: Optional[float] = None
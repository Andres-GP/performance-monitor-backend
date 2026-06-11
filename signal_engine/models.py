from typing import Any, Dict, Optional

from pydantic import BaseModel


class StrategyConfigUpdate(BaseModel):
    params: Dict[str, Any]
    is_active: Optional[bool] = None


class ManualOrderRequest(BaseModel):
    instrument: str
    action: str
    volume: float
    platform: str
    price: Optional[float] = None
    ticket: Optional[int] = None
    command_type: Optional[str] = "order"

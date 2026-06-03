from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text
from sqlalchemy.sql import func
from .database import Base
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime

# --- SQLAlchemy ORM models ---
class StrategyConfig(Base):
    __tablename__ = "strategy_configs"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    params = Column(Text)  # JSON string
    is_active = Column(Boolean, default=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

class OrderRecord(Base):
    __tablename__ = "orders"
    
    id = Column(Integer, primary_key=True, index=True)
    ticket = Column(Integer, nullable=True)
    instrument = Column(String)
    action = Column(String)  # buy, sell, modify, cancel
    volume = Column(Float)
    price = Column(Float, nullable=True)
    status = Column(String)  # pending, filled, rejected, cancelled
    platform = Column(String)  # NT8, MT5
    created_at = Column(DateTime, server_default=func.now())

class RiskEvent(Base):
    __tablename__ = "risk_events"
    
    id = Column(Integer, primary_key=True, index=True)
    rule_name = Column(String)
    reason = Column(Text)
    triggered_at = Column(DateTime, server_default=func.now())

# --- Pydantic schemas for API ---
class StrategyConfigUpdate(BaseModel):
    params: Dict[str, Any]
    is_active: Optional[bool] = None

class ManualOrderRequest(BaseModel):
    instrument: str
    action: str  # buy, sell, cancel
    volume: float
    platform: str  # NT8, MT5
    price: Optional[float] = None
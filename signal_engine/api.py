from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from typing import List, Dict
import json
from .database import get_db
from .models import StrategyConfig, StrategyConfigUpdate, ManualOrderRequest, OrderRecord
from .websocket_server import SignalEngineWSListener
from .risk_manager import RiskManager
from .config import settings
from .utils.logger import setup_logger

logger = setup_logger(__name__)

security = HTTPBearer()

def verify_token(creds: HTTPAuthorizationCredentials = Depends(security)):
    if creds.credentials != settings.API_SECRET_KEY:
        raise HTTPException(status_code=401, detail="Invalid token")
    return creds.credentials

def create_app(ws_listener: SignalEngineWSListener, risk_manager: RiskManager) -> FastAPI:
    app = FastAPI(title="Signal Engine API", version="1.0")
    
    @app.get("/health")
    async def health():
        return {"status": "ok"}
    
    @app.get("/strategies", dependencies=[Depends(verify_token)])
    async def get_strategies(db: Session = Depends(get_db)):
        configs = db.query(StrategyConfig).all()
        return [{"id": c.id, "name": c.name, "params": json.loads(c.params), "is_active": c.is_active} for c in configs]
    
    @app.put("/strategies/{strategy_id}", dependencies=[Depends(verify_token)])
    async def update_strategy(strategy_id: int, update: StrategyConfigUpdate, db: Session = Depends(get_db)):
        config = db.query(StrategyConfig).filter(StrategyConfig.id == strategy_id).first()
        if not config:
            raise HTTPException(status_code=404, detail="Strategy not found")
        if update.params:
            config.params = json.dumps(update.params)
        if update.is_active is not None:
            config.is_active = update.is_active
        db.commit()
        db.refresh(config)
        logger.info(f"Strategy {config.name} updated")
        return {"id": config.id, "name": config.name, "params": json.loads(config.params), "is_active": config.is_active}
    
    @app.post("/orders/manual", dependencies=[Depends(verify_token)])
    async def manual_order(order: ManualOrderRequest, db: Session = Depends(get_db)):
        # Guardar en DB como pendiente
        db_order = OrderRecord(
            instrument=order.instrument,
            action=order.action,
            volume=order.volume,
            price=order.price,
            platform=order.platform,
            status="pending"
        )
        db.add(db_order)
        db.commit()
        db.refresh(db_order)
        
        # Enviar orden al bridge
        order_dict = {
            "action": order.action,
            "instrument": order.instrument,
            "volume": order.volume,
            "price": order.price,
            "order_type": "market" if order.action in ["buy", "sell"] else "limit"
        }
        sent = await ws_listener.send_order_to_bridge(order.platform, order_dict)
        if not sent:
            db_order.status = "failed_no_bridge"
            db.commit()
            raise HTTPException(status_code=503, detail="No bridge available for platform")
        
        db_order.status = "sent"
        db.commit()
        return {"ticket": None, "status": "sent", "db_id": db_order.id}
    
    @app.get("/risk/status", dependencies=[Depends(verify_token)])
    async def risk_status():
        return {
            "kill_switch_engaged": risk_manager.kill_switch_engaged,
            "daily_pnl": risk_manager.daily_pnl,
            "start_equity": risk_manager.start_equity
        }
    
    @app.post("/risk/reset", dependencies=[Depends(verify_token)])
    async def reset_risk():
        risk_manager.reset_daily()
        return {"message": "Risk manager reset daily"}
    
    return app
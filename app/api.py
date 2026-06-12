from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from .config import settings
from .supabase_client import get_all_strategies, get_trades_by_strategy
from .utils.logger import setup_logger

logger = setup_logger(__name__)
security = HTTPBearer()

def verify_token(creds: HTTPAuthorizationCredentials = Depends(security)):
    if creds.credentials != settings.API_SECRET_KEY:
        raise HTTPException(status_code=401, detail="Invalid token")
    return creds.credentials

def create_app() -> FastAPI:
    app = FastAPI(title="Performance Monitor API", version="2.0")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/strategies", dependencies=[Depends(verify_token)])
    async def get_strategies():
        """List all strategies (active and stopped)."""
        return get_all_strategies()

    @app.get("/strategies/{strategy_id}/trades", dependencies=[Depends(verify_token)])
    async def get_strategy_trades(strategy_id: str):
        """Get all trades for a specific strategy."""
        trades = get_trades_by_strategy(strategy_id)
        if not trades:
            raise HTTPException(status_code=404, detail="No trades found for this strategy")
        return trades

    @app.get("/performance/latest", dependencies=[Depends(verify_token)])
    async def get_latest_snapshots():
        """Get latest performance snapshot per strategy (optional) - you can implement aggregation."""
        # For simplicity, we return all strategies with their last known total trades/pnl from strategies table
        return get_all_strategies()

    return app
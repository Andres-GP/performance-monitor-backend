import os
from typing import Optional, List
from supabase import create_client, Client
from .config import settings
from .models import StrategyInfo, TradeRecord, PerformanceSnapshot
from .utils.logger import setup_logger

logger = setup_logger(__name__)

supabase: Optional[Client] = None

try:
    if settings.SUPABASE_URL and settings.SUPABASE_SERVICE_ROLE_KEY:
        supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
        logger.info("Supabase client initialized successfully")
    else:
        logger.warning("Supabase credentials missing. Running without database.")
except Exception as e:
    logger.error(f"Failed to initialize Supabase: {e}")
    supabase = None

STRATEGIES_TABLE = "strategies"
TRADES_TABLE = "trades"
SNAPSHOTS_TABLE = "performance_snapshots"

def _check_supabase():
    if supabase is None:
        logger.warning("Supabase not available - operation skipped")
        return False
    return True

def upsert_strategy(strategy: StrategyInfo):
    if not _check_supabase():
        return []
    data = strategy.dict()
    result = supabase.table(STRATEGIES_TABLE).upsert(data, on_conflict="strategy_id").execute()
    return result.data

def insert_trade(trade: TradeRecord):
    if not _check_supabase():
        return []
    data = trade.dict()
    result = supabase.table(TRADES_TABLE).insert(data).execute()
    return result.data

def insert_snapshot(snapshot: PerformanceSnapshot):
    if not _check_supabase():
        return []
    data = snapshot.dict()
    result = supabase.table(SNAPSHOTS_TABLE).insert(data).execute()
    return result.data

def get_all_strategies() -> List[dict]:
    if not _check_supabase():
        return []
    result = supabase.table(STRATEGIES_TABLE).select("*").execute()
    return result.data

def get_trades_by_strategy(strategy_id: str) -> List[dict]:
    if not _check_supabase():
        return []
    result = supabase.table(TRADES_TABLE).select("*").eq("strategy_id", strategy_id).execute()
    return result.data
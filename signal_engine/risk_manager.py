import time
from collections import deque
from typing import Dict, Tuple
from .utils.logger import setup_logger
from .config import settings

logger = setup_logger(__name__)

class RiskManager:
    def __init__(self):
        self.daily_pnl = 0.0
        self.start_equity = None
        self.order_timestamps = deque(maxlen=settings.MAX_ORDERS_PER_MINUTE)
        self.kill_switch_engaged = False
    
    def update_equity(self, current_equity: float):
        if self.start_equity is None:
            self.start_equity = current_equity
        self.daily_pnl = current_equity - self.start_equity
    
    def check_daily_drawdown(self, current_equity: float) -> Tuple[bool, str]:
        if self.start_equity is None:
            return True, "No initial equity"
        drawdown_percent = (self.start_equity - current_equity) / self.start_equity * 100
        if drawdown_percent > settings.MAX_DAILY_DRAWDOWN_PERCENT:
            return False, f"Daily drawdown {drawdown_percent:.2f}% exceeds limit {settings.MAX_DAILY_DRAWDOWN_PERCENT}%"
        return True, "OK"
    
    def check_order_rate(self) -> Tuple[bool, str]:
        now = time.time()
        self.order_timestamps.append(now)
        if len(self.order_timestamps) == settings.MAX_ORDERS_PER_MINUTE:
            # si la diferencia entre la primera y la última es menor a 60 segundos
            if self.order_timestamps[-1] - self.order_timestamps[0] < 60:
                return False, f"Order rate exceeded: {settings.MAX_ORDERS_PER_MINUTE} orders per minute"
        return True, "OK"
    
    def check_position_size(self, volume: float) -> Tuple[bool, str]:
        if volume > settings.MAX_POSITION_SIZE:
            return False, f"Volume {volume} exceeds max {settings.MAX_POSITION_SIZE}"
        return True, "OK"
    
    def can_execute(self, instrument: str, action: str, volume: float, current_equity: float) -> Tuple[bool, str]:
        if self.kill_switch_engaged:
            return False, "Kill switch engaged globally"
        
        ok, msg = self.check_daily_drawdown(current_equity)
        if not ok:
            self.kill_switch_engaged = True
            return False, msg
        
        ok, msg = self.check_order_rate()
        if not ok:
            return False, msg
        
        ok, msg = self.check_position_size(volume)
        if not ok:
            return False, msg
        
        return True, "OK"
    
    def reset_daily(self):
        self.start_equity = None
        self.daily_pnl = 0.0
        self.order_timestamps.clear()
        self.kill_switch_engaged = False
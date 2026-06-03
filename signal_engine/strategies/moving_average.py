from .base import BaseStrategy
from typing import Dict

class MovingAverageCrossStrategy(BaseStrategy):
    """Ejemplo: cruce de medias móviles (rápida y lenta)"""
    
    def should_enter(self, market_data: Dict) -> tuple[bool, str, float]:
        # market_data debe contener 'fast_ma', 'slow_ma', 'close'
        fast = market_data.get('fast_ma', 0)
        slow = market_data.get('slow_ma', 0)
        prev_fast = market_data.get('prev_fast_ma', 0)
        prev_slow = market_data.get('prev_slow_ma', 0)
        
        if prev_fast <= prev_slow and fast > slow:
            return True, 'buy', self.params.get('volume', 0.01)
        elif prev_fast >= prev_slow and fast < slow:
            return True, 'sell', self.params.get('volume', 0.01)
        return False, '', 0
    
    def should_exit(self, position: Dict, market_data: Dict) -> tuple[bool, float]:
        # Salida cuando el precio cruza la media lenta
        slow = market_data.get('slow_ma', 0)
        close = market_data.get('close', 0)
        if position['action'] == 'buy' and close < slow:
            return True, close  # precio de mercado para cerrar
        if position['action'] == 'sell' and close > slow:
            return True, close
        return False, 0
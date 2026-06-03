from abc import ABC, abstractmethod
from typing import Dict, Any

class BaseStrategy(ABC):
    """Clase base para todas las estrategias."""
    
    def __init__(self, name: str, params: Dict[str, Any]):
        self.name = name
        self.params = params
        self.is_active = True
    
    @abstractmethod
    def should_enter(self, market_data: Dict) -> tuple[bool, str, float]:
        """Retorna (bool, acción, volume) donde acción es 'buy' o 'sell'"""
        pass
    
    @abstractmethod
    def should_exit(self, position: Dict, market_data: Dict) -> tuple[bool, float]:
        """Retorna (bool, take_profit_price) si se debe cerrar"""
        pass
    
    def update_params(self, new_params: Dict[str, Any]):
        """Actualiza parámetros en caliente."""
        self.params.update(new_params)
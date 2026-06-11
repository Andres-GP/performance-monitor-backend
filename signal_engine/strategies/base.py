from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseStrategy(ABC):
    def __init__(self, name: str, params: Dict[str, Any]):
        self.name = name
        self.params = params
        self.is_active = True

    @abstractmethod
    def should_enter(self, market_data: Dict) -> tuple[bool, str, float]:
        """Return (should_enter, action, volume) where action is 'buy' or 'sell'."""
        pass

    @abstractmethod
    def should_exit(self, position: Dict, market_data: Dict) -> tuple[bool, float]:
        """Return (should_exit, exit_price)."""
        pass

    def update_params(self, new_params: Dict[str, Any]):
        self.params.update(new_params)

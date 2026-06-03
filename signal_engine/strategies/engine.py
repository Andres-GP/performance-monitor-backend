import asyncio
from typing import Dict, List
from .base import BaseStrategy
from .moving_average import MovingAverageCrossStrategy
from ..utils.logger import setup_logger
from ..risk_manager import RiskManager
from ..websocket_server import SignalEngineWSListener
from ..config import settings
from ..database import SessionLocal
from ..models import StrategyConfig
import json

logger = setup_logger(__name__)

class StrategyEngine:
    def __init__(self, ws_listener: SignalEngineWSListener, risk_manager: RiskManager):
        self.strategies: Dict[str, BaseStrategy] = {}
        self.ws_listener = ws_listener
        self.risk_manager = risk_manager
        self.active = True
        self.refresh_interval = 60  # segundos para recargar configuraciones
    
    async def load_strategies_from_db(self):
        """Carga las estrategias activas desde la base de datos."""
        db = SessionLocal()
        try:
            configs = db.query(StrategyConfig).filter(StrategyConfig.is_active == True).all()
            for cfg in configs:
                if cfg.name == "MA_Cross":
                    params = json.loads(cfg.params)
                    strategy = MovingAverageCrossStrategy(cfg.name, params)
                    self.strategies[cfg.name] = strategy
                    logger.info(f"Estrategia cargada: {cfg.name} con params {params}")
        finally:
            db.close()
    
    async def refresh_configs(self):
        """Tarea periódica que recarga configuraciones desde DB."""
        while self.active:
            await asyncio.sleep(self.refresh_interval)
            logger.info("Refrescando configuraciones de estrategias...")
            await self.load_strategies_from_db()
    
    async def run_cycle(self):
        """Ciclo principal de ejecución: obtiene datos, evalúa estrategias, envía órdenes."""
        # Aquí deberías obtener datos de mercado (por ejemplo, desde otra fuente)
        # Por simplicidad, simulamos datos dummy.
        while self.active:
            # Simular obtención de datos (reemplazar con tu data feed real)
            market_data = {
                'EURUSD': {
                    'fast_ma': 1.1050,
                    'slow_ma': 1.1040,
                    'prev_fast_ma': 1.1045,
                    'prev_slow_ma': 1.1040,
                    'close': 1.1052
                }
            }
            
            for name, strategy in self.strategies.items():
                if not strategy.is_active:
                    continue
                # Suponemos la estrategia opera en EURUSD (hardcoded para ejemplo)
                data = market_data['EURUSD']
                should_enter, action, volume = strategy.should_enter(data)
                if should_enter:
                    # Validar riesgo
                    current_equity = 10000.0  # Obtener desde API de broker
                    ok, msg = self.risk_manager.can_execute('EURUSD', action, volume, current_equity)
                    if ok:
                        # Enviar orden al bridge de la plataforma correcta
                        order = {
                            'instrument': 'EURUSD',
                            'action': action,
                            'volume': volume,
                            'order_type': 'market'
                        }
                        # Elegir plataforma según instrument (configurable)
                        platform = 'NT8'  # o MT5
                        await self.ws_listener.send_order_to_bridge(platform, order)
                    else:
                        logger.warning(f"Riesgo rechazó orden: {msg}")
            
            await asyncio.sleep(5)  # ciclo cada 5 segundos (ajustable)
    
    async def start(self):
        await self.load_strategies_from_db()
        asyncio.create_task(self.refresh_configs())
        asyncio.create_task(self.run_cycle())
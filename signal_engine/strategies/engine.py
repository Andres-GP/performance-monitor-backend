# signal_engine/strategies/engine.py
import asyncio
from typing import Dict
from .base import BaseStrategy
from .moving_average import MovingAverageCrossStrategy
from ..utils.logger import setup_logger
from ..risk_manager import RiskManager
from ..websocket_server import WebSocketServer
from ..supabase_client import supabase, STRATEGY_CONFIGS_TABLE
# from ..bridge_manager import ninja_socket_ws   # Comentado temporalmente

logger = setup_logger(__name__)

class StrategyEngine:
    def __init__(self, ws_server: WebSocketServer, risk_manager: RiskManager):
        self.strategies: Dict[str, BaseStrategy] = {}
        self.ws_server = ws_server
        self.risk_manager = risk_manager
        self.active = True
        self.refresh_interval = 60

    async def load_strategies_from_db(self):
        result = supabase.table(STRATEGY_CONFIGS_TABLE).select("*").eq("is_active", True).execute()
        configs = result.data
        for cfg in configs:
            if cfg["name"] == "MA_Cross":
                params = cfg["params"]
                strategy = MovingAverageCrossStrategy(cfg["name"], params)
                self.strategies[cfg["name"]] = strategy
                logger.info(f"Estrategia cargada: {cfg['name']} con params {params}")

    async def refresh_configs(self):
        while self.active:
            await asyncio.sleep(self.refresh_interval)
            logger.info("Refrescando configuraciones de estrategias...")
            await self.load_strategies_from_db()

    async def run_cycle(self):
        while self.active:
            # Datos de mercado simulados (reemplazar por datos reales)
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
                data = market_data['EURUSD']
                should_enter, action, volume = strategy.should_enter(data)
                if should_enter:
                    current_equity = 10000.0
                    ok, msg = self.risk_manager.can_execute('EURUSD', action, volume, current_equity)
                    if ok:
                        # Decidir plataforma (por defecto NT8)
                        platform = "NT8"
                        # ### COMENTADO TEMPORALMENTE (para pruebas manuales) ###
                        # if platform == "NT8" and ninja_socket_ws is not None:
                        #     command = f"{action} EURUSD {volume}"
                        #     await ninja_socket_ws.send_text(command)
                        #     logger.info(f"Estrategia envió orden a NinjaSocket: {command}")
                        # else:
                        #     order = {
                        #         'instrument': 'EURUSD',
                        #         'action': action,
                        #         'volume': volume,
                        #         'order_type': 'market'
                        #     }
                        #     await self.ws_server.send_order_to_bridge(platform, order)
                        # ### FIN DEL COMENTARIO ###
                        logger.info(f"[SIMULACIÓN] Estrategia {name} generaría orden: {action} {volume} EURUSD")
                    else:
                        logger.warning(f"Riesgo rechazó orden: {msg}")
            await asyncio.sleep(5)

    async def start(self):
        await self.load_strategies_from_db()
        asyncio.create_task(self.refresh_configs())
        asyncio.create_task(self.run_cycle())
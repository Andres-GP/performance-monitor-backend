import asyncio

from ..risk_manager import RiskManager
from ..supabase_client import STRATEGY_CONFIGS_TABLE, supabase
from ..utils.logger import setup_logger
from ..websocket_server import WebSocketServer
from .order_helpers import send_order_to_mt5, send_order_to_nt8
from .test_mt5_buy_on_bar import MT5BuyOnBarStrategy
from .test_nt8_buy_on_bar import NT8BuyOnBarStrategy

logger = setup_logger(__name__)


# ============================================================================
# CONFIGURACIÓN DE ESTRATEGIAS DE PRUEBA
# ============================================================================
# Cada entrada es un diccionario con los parámetros de una estrategia.
# - "platform": "mt5" o "nt8"
# - "symbol": instrumento (ej. "EURUSD", "ES 06-26")
# - "timeframe": minutos (ej. 15, 1)
# - "size": cantidad (volumen para MT5, contratos para NT8)
#
# Para desactivar una estrategia, simplemente coméntala o elimínala de la lista.
# ============================================================================

TEST_STRATEGIES = [
    # MT5: EURUSD, 15 minutos, volumen 0.01
    {
        "platform": "mt5",
        "symbol": "EURUSD",
        "timeframe": 15,
        "size": 0.01,
    },
    # NT8: ES 06-26, 1 minuto, 2 contratos
    {
        "platform": "nt8",
        "symbol": "ES 06-26",
        "timeframe": 1,
        "size": 2,
    },
]


class StrategyEngine:
    def __init__(self, ws_server: WebSocketServer, risk_manager: RiskManager):
        self.ws_server = ws_server
        self.risk_manager = risk_manager
        self.active = True

    async def start(self):
        """Punto de entrada principal: lanza todas las estrategias configuradas."""
        logger.info("Starting Strategy Engine...")
        await self._start_test_strategies()
        # Si en el futuro hay estrategias desde base de datos, se añadirían aquí.
        # Por ahora, mantenemos el engine vivo (opcional, si no hay tareas de fondo).
        while self.active:
            await asyncio.sleep(3600)  # Bucle simple para mantener el engine vivo

    async def _start_test_strategies(self):
        """Crea y ejecuta cada estrategia definida en TEST_STRATEGIES."""
        if not TEST_STRATEGIES:
            logger.warning("No test strategies configured. Add entries to TEST_STRATEGIES.")
            return

        for cfg in TEST_STRATEGIES:
            platform = cfg["platform"]
            symbol = cfg["symbol"]
            timeframe = cfg["timeframe"]
            size = cfg["size"]

            if platform == "mt5":
                strategy = MT5BuyOnBarStrategy(
                    send_order_func=send_order_to_mt5,
                    symbol=symbol,
                    timeframe=timeframe,
                    volume=size,
                )
            elif platform == "nt8":
                strategy = NT8BuyOnBarStrategy(
                    send_order_func=send_order_to_nt8,
                    symbol=symbol,
                    timeframe=timeframe,
                    quantity=size,
                )
            else:
                logger.error(f"Unknown platform '{platform}' for strategy {symbol}. Skipping.")
                continue

            asyncio.create_task(strategy.run())
            logger.info(f"Test strategy started: {platform} {symbol} {timeframe}min size={size}")

        logger.info(f"All test strategies launched ({len(TEST_STRATEGIES)} active).")
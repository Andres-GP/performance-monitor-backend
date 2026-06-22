# scheduler.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from .monitor import PerformanceMonitor
from .utils.logger import setup_logger

logger = setup_logger(__name__)

class Scheduler:
    def __init__(self, monitor: PerformanceMonitor):
        self.monitor = monitor
        self.scheduler = AsyncIOScheduler()

    def start(self):
        # --- 1. Daily performance check (20:00) ---
        self.scheduler.add_job(
            self.monitor.run_daily_check,
            CronTrigger(hour=20, minute=0),
            id="daily_performance",
            name="Daily Performance Check"
        )
        logger.info("Scheduled daily performance check at 20:00")

        # --- 2. Weekly regime check (Monday 21:00) ---
        self.scheduler.add_job(
            self.monitor.run_weekly_check,
            CronTrigger(day_of_week=0, hour=21, minute=0),
            id="weekly_regime",
            name="Weekly Regime Check"
        )
        logger.info("Scheduled weekly regime check on Monday at 21:00")

        # --- 3. Monthly edge health check (1st at 22:00) ---
        self.scheduler.add_job(
            self.monitor.run_monthly_check,
            CronTrigger(day=1, hour=22, minute=0),
            id="monthly_edge",
            name="Monthly Edge Health Check"
        )
        logger.info("Scheduled monthly edge health check on 1st at 22:00")

        # --- 4. MT5 Heartbeat check (every 60 seconds) ---
        self.scheduler.add_job(
            self.monitor.check_mt5_heartbeats,
            IntervalTrigger(seconds=60),
            id="mt5_heartbeat_check",
            name="MT5 Heartbeat Check"
        )
        logger.info("Scheduled MT5 heartbeat check every 60 seconds")

        # --- Start the scheduler ---
        self.scheduler.start()
        logger.info("Performance Monitor Scheduler started")

    def shutdown(self):
        self.scheduler.shutdown()
        logger.info("Scheduler shut down")
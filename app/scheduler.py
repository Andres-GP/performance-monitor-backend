
import asyncio
from datetime import timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from .monitor import PerformanceMonitor
from .monitoring.activity_rules import run_activity_rules
from .monitoring.derived_metrics import run_metrics_job, server_daily_close_utc
from .monitoring.strategies import load_registry
from .utils.logger import setup_logger

logger = setup_logger(__name__)

class Scheduler:
    def __init__(self, monitor: PerformanceMonitor):
        self.monitor = monitor
        self.scheduler = AsyncIOScheduler()
        self.registry = load_registry()

    async def run_monitoring_metrics(self, portfolio_id: str | None = None):
        client = getattr(self.monitor, "supabase", None)
        if client is None:
            logger.warning("Derived monitoring metrics skipped: Supabase client unavailable")
            return
        try:
            result = await asyncio.to_thread(
                run_metrics_job,
                client,
                self.registry,
                portfolio_id=portfolio_id,
            )
            logger.info(
                "Derived metrics updated: %d strategies, %d portfolios",
                len(result["strategies"]),
                len(result["portfolios"]),
            )
        except Exception:
            logger.exception("Derived monitoring metrics job failed")
        try:
            alerts = await asyncio.to_thread(
                run_activity_rules,
                client,
                self.registry,
            )
            if alerts:
                logger.info("Evaluated life/activity rules; active signals: %d", len(alerts))
        except Exception:
            logger.exception("Life/activity rules job failed")

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

        # --- 5. Portfolio metrics update (every 6 hours) ---
        self.scheduler.add_job(
            self.monitor.run_portfolio_check,
            IntervalTrigger(hours=6),
            id="portfolio_metrics",
            name="Portfolio Metrics Update"
        )
        logger.info("Scheduled portfolio metrics update every 6 hours")

        self.scheduler.add_job(
            self.run_monitoring_metrics,
            IntervalTrigger(seconds=60),
            id="monitoring_metrics",
            name="Derived Monitoring Metrics",
            max_instances=1,
            coalesce=True,
        )
        logger.info("Scheduled derived monitoring metrics every 60 seconds")

        for portfolio in self.registry.portfolios:
            if not portfolio.server_time_to_utc_enabled:
                continue
            hour, minute = server_daily_close_utc(portfolio.server_utc_offset_hours)
            self.scheduler.add_job(
                self.run_monitoring_metrics,
                CronTrigger(hour=hour, minute=minute, timezone=timezone.utc),
                kwargs={"portfolio_id": portfolio.id},
                id=f"monitoring_daily_close_{portfolio.id}",
                name=f"Daily metrics close for {portfolio.id}",
                max_instances=1,
                coalesce=True,
            )
            logger.info(
                "Scheduled daily metrics close for %s at %02d:%02d UTC",
                portfolio.id,
                hour,
                minute,
            )

        # --- Start the scheduler ---
        self.scheduler.start()
        logger.info("Performance Monitor Scheduler started")

    def shutdown(self):
        self.scheduler.shutdown()
        logger.info("Scheduler shut down")

import pytest
from unittest.mock import MagicMock, patch
from app.scheduler import Scheduler
from app.monitor import PerformanceMonitor

@pytest.fixture
def mock_monitor():
    return MagicMock(spec=PerformanceMonitor)

def test_scheduler_start(mock_monitor):
    with patch('app.scheduler.AsyncIOScheduler') as MockScheduler:
        mock_scheduler_instance = MagicMock()
        MockScheduler.return_value = mock_scheduler_instance

        scheduler = Scheduler(mock_monitor)

        with patch('asyncio.get_event_loop') as mock_loop:
            mock_loop.return_value = MagicMock()
            scheduler.start()

        assert mock_scheduler_instance.add_job.call_count == 6
        mock_scheduler_instance.start.assert_called_once()

def test_scheduler_shutdown(mock_monitor):
    scheduler = Scheduler(mock_monitor)
    with patch('app.scheduler.AsyncIOScheduler') as MockScheduler:
        mock_scheduler_instance = MagicMock()
        MockScheduler.return_value = mock_scheduler_instance
        scheduler.scheduler = mock_scheduler_instance

        scheduler.shutdown()
        mock_scheduler_instance.shutdown.assert_called_once()

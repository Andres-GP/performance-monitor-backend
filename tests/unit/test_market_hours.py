from datetime import datetime, timezone

from app.monitoring.market_hours import (
    completed_trading_sessions,
    market_is_open,
    us_equity_holidays,
)


def test_crypto_calendar_is_open_on_weekends_and_overnight():
    assert market_is_open("CRYPTO_24_7", datetime(2026, 11, 21, 3, tzinfo=timezone.utc)) is True


def test_forex_calendar_opens_sunday_at_1700_new_york():
    # November is standard time: 22:00 UTC corresponds to 17:00 New York.
    assert market_is_open("FOREX_24_5", datetime(2026, 11, 22, 21, 59, tzinfo=timezone.utc)) is False
    assert market_is_open("FOREX_24_5", datetime(2026, 11, 22, 22, 0, tzinfo=timezone.utc)) is True


def test_us_equity_session_honors_regular_hours_holidays_and_early_closes():
    assert market_is_open("US_EQUITY", datetime(2026, 11, 19, 15, 0, tzinfo=timezone.utc)) is True  # 10:00 ET
    assert market_is_open("US_EQUITY", datetime(2026, 11, 19, 22, 0, tzinfo=timezone.utc)) is False  # 17:00 ET
    assert market_is_open("US_EQUITY", datetime(2026, 11, 26, 16, 0, tzinfo=timezone.utc)) is False  # Thanksgiving
    assert market_is_open("US_EQUITY", datetime(2026, 11, 27, 18, 15, tzinfo=timezone.utc)) is False  # 13:15 ET early close
    assert us_equity_holidays(2026) >= {datetime(2026, 11, 26).date()}


def test_completed_qqq_sessions_skip_weekends_and_exchange_holidays():
    start = datetime(2026, 11, 24, 22, 0, tzinfo=timezone.utc)  # Tuesday close
    now = datetime(2026, 11, 30, 22, 0, tzinfo=timezone.utc)   # Monday close
    # Wednesday and Monday are sessions; Thanksgiving is closed and Friday is early.
    assert completed_trading_sessions("US_EQUITY", start, now) == 3

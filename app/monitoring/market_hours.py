"""Market-session helpers for activity alerts and trading-day inactivity rules."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
NEW_YORK = ZoneInfo("America/New_York")


def _observed(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    shift = (weekday - first.weekday()) % 7
    return first + timedelta(days=shift + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        cursor = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        cursor = date(year, month + 1, 1) - timedelta(days=1)
    return cursor - timedelta(days=(cursor.weekday() - weekday) % 7)


def _easter_sunday(year: int) -> date:
    """Gregorian Easter date using the Meeus/Jones/Butcher algorithm."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def us_equity_holidays(year: int) -> set[date]:
    """Full-day US exchange closures used for the QQQ regular session."""
    holidays: set[date] = set()
    for holiday_year in (year - 1, year, year + 1):
        holidays.update({
            _observed(date(holiday_year, 1, 1)),
            _nth_weekday(holiday_year, 1, 0, 3),   # Martin Luther King Jr. Day
            _nth_weekday(holiday_year, 2, 0, 3),   # Washington's Birthday
            _easter_sunday(holiday_year) - timedelta(days=2),  # Good Friday
            _last_weekday(holiday_year, 5, 0),     # Memorial Day
            _observed(date(holiday_year, 7, 4)),
            _nth_weekday(holiday_year, 9, 0, 1),   # Labor Day
            _nth_weekday(holiday_year, 11, 3, 4),  # Thanksgiving
            _observed(date(holiday_year, 12, 25)),
        })
        if holiday_year >= 2022:
            holidays.add(_observed(date(holiday_year, 6, 19)))  # Juneteenth
    return holidays


def _us_equity_early_closes(year: int, holidays: set[date]) -> set[date]:
    thanksgiving = _nth_weekday(year, 11, 3, 4)
    candidates = {
        thanksgiving + timedelta(days=1),
        date(year, 12, 24),
        date(year, 7, 3),
    }
    return {day for day in candidates if day.weekday() < 5 and day not in holidays}


def us_equity_session_close(day: date) -> time:
    holidays = us_equity_holidays(day.year)
    if day in _us_equity_early_closes(day.year, holidays):
        return time(13, 0)
    return time(16, 0)


def market_is_open(calendar: str, now: datetime) -> bool | None:
    """Return whether a known market is open; None means no calendar is configured."""
    if now.tzinfo is None:
        raise ValueError("market calendar requires an aware timestamp")
    if calendar == "CRYPTO_24_7":
        return True
    local = now.astimezone(NEW_YORK)
    if calendar == "FOREX_24_5":
        if local.weekday() <= 3:
            return True
        if local.weekday() == 4:
            return local.time().replace(tzinfo=None) < time(17, 0)
        if local.weekday() == 6:
            return local.time().replace(tzinfo=None) >= time(17, 0)
        return False
    if calendar == "US_EQUITY":
        day = local.date()
        if day.weekday() >= 5 or day in us_equity_holidays(day.year):
            return False
        close = us_equity_session_close(day)
        current_time = local.time().replace(tzinfo=None)
        return time(9, 30) <= current_time < close
    return None


def completed_trading_sessions(calendar: str, start: datetime, now: datetime) -> int:
    """Count completed sessions after the start date through the current instant."""
    if start.tzinfo is None or now.tzinfo is None:
        raise ValueError("trading-session calculation requires aware timestamps")
    if calendar == "CRYPTO_24_7":
        return max(0, (now.astimezone(UTC).date() - start.astimezone(UTC).date()).days)
    if calendar == "FOREX_24_5":
        count = 0
        day = start.astimezone(NEW_YORK).date() + timedelta(days=1)
        last_day = now.astimezone(NEW_YORK).date()
        while day <= last_day:
            close_utc = datetime.combine(day, time(17, 0), tzinfo=NEW_YORK).astimezone(UTC)
            if day.weekday() < 5 and close_utc <= now.astimezone(UTC):
                count += 1
            day += timedelta(days=1)
        return count
    if calendar == "US_EQUITY":
        count = 0
        day = start.astimezone(NEW_YORK).date() + timedelta(days=1)
        last_day = now.astimezone(NEW_YORK).date()
        while day <= last_day:
            if day.weekday() < 5 and day not in us_equity_holidays(day.year):
                close_utc = datetime.combine(day, us_equity_session_close(day), tzinfo=NEW_YORK).astimezone(UTC)
                if close_utc <= now.astimezone(UTC):
                    count += 1
            day += timedelta(days=1)
        return count
    return 0

from datetime import date, datetime, timedelta, timezone

from app.monitoring.portfolio_layer import calculate_portfolio_layer
from app.monitoring.strategies import load_registry


UTC = timezone.utc
NOW = datetime(2026, 11, 19, 20, 0, tzinfo=UTC)


def _trade(day, profit, pct=None):
    return {
        "entry_time": datetime.combine(day, datetime.min.time(), tzinfo=UTC),
        "exit_time": datetime.combine(day, datetime.min.time(), tzinfo=UTC) + timedelta(hours=1),
        "profit": profit,
        "pnl_pct_equity": pct,
    }


def test_portfolio_layer_calculates_period_pnl_contributions_and_equity_curves():
    registry = load_registry()
    metrics = {
        "strategies": {
            "MONDAY_BTCJPY": {"_trades": [_trade(NOW.date(), 10), _trade(NOW.date() - timedelta(days=2), 5)]},
            "GOTOBI_USDJPY_AXI": {"_trades": [_trade(NOW.date(), -3)]},
        },
        "portfolios": {
            "P_AXI": {
                "equity": 10000,
                "daily_dd_pct": 1.2,
                "total_dd_pct": 2.3,
                "server_date": None,
                "_equity_curve": [{"ts": NOW, "equity": 10000, "reported_equity": 10010}],
            },
        },
    }
    result = calculate_portfolio_layer(registry, metrics, now=NOW)
    axi = result["portfolios"]["P_AXI"]
    assert axi["equity"] == 10000
    assert axi["pnl_daily_realized"] == 7
    assert axi["pnl_weekly_realized"] == 12
    assert axi["pnl_monthly_realized"] == 12
    assert axi["strategy_contribution_30d"] == {"MONDAY_BTCJPY": 15, "GOTOBI_USDJPY_AXI": -3, "WEEKLYMOM_ETHUSD": 0}
    assert axi["open_positions"] is None
    assert axi["equity_curve"][0]["equity"] == 10010


def test_rolling_correlation_needs_two_high_calculations_and_labels_same_edge():
    registry = load_registry()
    monday = []
    weekly = []
    for index in range(20):
        day = NOW.date() - timedelta(days=19 - index)
        value = 1 if index % 2 else -1
        monday.append(_trade(day, value, value))
        weekly.append(_trade(day, value * 2, value * 2))
    metrics = {"strategies": {
        "MONDAY_BTCJPY": {"_trades": monday},
        "WEEKLYMOM_ETHUSD": {"_trades": weekly},
    }}
    first = calculate_portfolio_layer(registry, metrics, now=NOW)
    pair = next(item for item in first["correlations"] if {item["strategy_a"], item["strategy_b"]} == {"MONDAY_BTCJPY", "WEEKLYMOM_ETHUSD"})
    assert pair["correlation"] == 1.0 and pair["band"] == "red" and not pair["same_edge"]
    assert not any(signal["rule_key"] == "CORR_HIGH" for signal in first["alerts"])
    second = calculate_portfolio_layer(registry, metrics, now=NOW, prior_high_counts=first["high_counts"])
    assert any(signal["rule_key"] == "CORR_HIGH" for signal in second["alerts"])

    axi = next(item for item in registry.strategies if item.id == "GOTOBI_USDJPY_AXI")
    dwx = next(item for item in registry.strategies if item.id == "GOTOBI_USDJPY_DWX")
    gotobi = calculate_portfolio_layer(registry, {"strategies": {
        axi.id: {"_trades": [_trade(NOW.date() - timedelta(days=1), 1, 1)]},
        dwx.id: {"_trades": [_trade(NOW.date() - timedelta(days=1), 1, 1)]},
    }}, now=NOW)
    same_edge = next(item for item in gotobi["correlations"] if {item["strategy_a"], item["strategy_b"]} == {axi.id, dwx.id})
    assert same_edge["same_edge"] is True


def test_gotobi_divergence_requires_opposite_signs_on_three_gotobi_days():
    registry = load_registry()
    days = [date(2026, 11, 5), date(2026, 11, 10), date(2026, 11, 15)]
    axi = [_trade(day, 1) for day in days]
    dwx = [_trade(day, -1) for day in days]
    result = calculate_portfolio_layer(registry, {"strategies": {
        "GOTOBI_USDJPY_AXI": {"_trades": axi},
        "GOTOBI_USDJPY_DWX": {"_trades": dwx},
    }}, now=NOW)
    signal = next(item for item in result["alerts"] if item["rule_key"] == "DIVERGENCE_GOTOBI")
    assert signal["severity"] == "medium"
    assert len(signal["context"]["opposite_sign_days"]) == 3

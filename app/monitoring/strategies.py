"""Typed loader and lookup helpers for the strategy registry."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Baselines(BaseModel):
    bt_win_rate: float | None = None
    bt_profit_factor: float | None = None
    bt_avg_trade_pct: float | None = None
    bt_max_dd_pct: float | None = None
    bt_trades_per_month: float | None = None
    bt_avg_hold_min: float | None = None


class Portfolio(BaseModel):
    id: str
    broker: str
    account_type: str | None = None
    daily_dd_limit_pct: float = Field(gt=0, le=100)
    total_dd_limit_pct: float = Field(gt=0, le=100)
    broker_hard_limit_pct: float | None = Field(default=None, gt=0, le=100)
    server_utc_offset_hours: float | None = Field(default=None, ge=-14, le=14)
    server_utc_offset_verified: bool = False

    @model_validator(mode="after")
    def offset_must_be_verified(self):
        if self.server_utc_offset_verified and self.server_utc_offset_hours is None:
            raise ValueError("a verified server offset must have a value")
        return self

    @property
    def server_time_to_utc_enabled(self) -> bool:
        return self.server_utc_offset_verified and self.server_utc_offset_hours is not None


class ExpectedSize(BaseModel):
    kind: Literal["equity_notional_fraction", "risk_per_trade_fraction"]
    value: float = Field(gt=0, le=1)
    note: str | None = None
    min_lot_can_exceed: bool = False


class EntryRule(BaseModel):
    model_config = ConfigDict(extra="allow")

    time: str | None = None
    timezone: Literal["UTC", "broker_server"] | None = None
    schedule: str
    filter: str | None = None
    gotobi_dates: list[int | Literal["end_of_month"]] | None = None
    calendar_adjustment: str | None = None
    excluded_dates: list[str] | None = None


class ExitRule(BaseModel):
    model_config = ConfigDict(extra="allow")

    schedule: str
    expected_duration_minutes: float | None = Field(default=None, gt=0)
    expected_duration_hours: float | None = Field(default=None, gt=0)
    expected_duration_days: float | None = Field(default=None, gt=0)
    expected_duration_bars: int | None = Field(default=None, gt=0)
    tolerance_minutes: float | None = Field(default=None, ge=0)
    schedule_tolerance_minutes: float | None = Field(default=None, ge=0)
    calibration_note: str | None = None


class KnownRisk(BaseModel):
    key: str
    message: str


class Strategy(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    portfolio_id: str
    strategy_name_prefix: str
    magic: int
    timeframe: str
    vehicle: str
    direction: Literal["long", "short"]
    expected_size: ExpectedSize
    entry: EntryRule
    exit: ExitRule
    contract_size: float | None = Field(default=None, gt=0)
    max_positions: int = Field(ge=1)
    entry_tolerance_minutes: int | None = Field(default=None, ge=0)
    max_bars_no_trade: int = Field(gt=0)
    strategy_dd_daily_limit_pct: float = Field(gt=0, le=100)
    strategy_dd_total_limit_pct: float = Field(gt=0, le=100)
    limits_review_required: bool = False
    edge_family: str | None = None
    risk_cluster: str | None = None
    known_risk: KnownRisk | None = None
    baselines: Baselines


class StrategyRegistry(BaseModel):
    version: int = Field(ge=1)
    portfolios: list[Portfolio]
    strategies: list[Strategy]

    @model_validator(mode="after")
    def validate_references_and_prefixes(self):
        portfolio_ids = [portfolio.id for portfolio in self.portfolios]
        strategy_ids = [strategy.id for strategy in self.strategies]
        prefixes = [strategy.strategy_name_prefix for strategy in self.strategies]
        if len(set(portfolio_ids)) != len(portfolio_ids):
            raise ValueError("portfolio ids must be unique")
        if len(set(strategy_ids)) != len(strategy_ids):
            raise ValueError("strategy ids must be unique")
        if len(set(prefixes)) != len(prefixes):
            raise ValueError("strategy name prefixes must be unique")
        unknown = sorted({s.portfolio_id for s in self.strategies} - set(portfolio_ids))
        if unknown:
            raise ValueError(f"strategies reference unknown portfolios: {unknown}")
        return self

    def match_strategy(self, strategy_name: str) -> Strategy | None:
        """Match a broker symbol (and optional suffix) after its registered prefix."""
        matches = [s for s in self.strategies if strategy_name.startswith(s.strategy_name_prefix)]
        if not matches:
            return None
        # Specific prefixes (e.g. GOTOBI_DWX) take precedence over family prefixes.
        return max(matches, key=lambda strategy: len(strategy.strategy_name_prefix))

    def effective_portfolio_limit(self, portfolio_id: str, limit: Literal["daily", "total"]) -> float:
        """Return the strictest portfolio/strategy DD limit for that portfolio."""
        portfolio = next((p for p in self.portfolios if p.id == portfolio_id), None)
        if portfolio is None:
            raise KeyError(f"unknown portfolio: {portfolio_id}")
        portfolio_limit = portfolio.daily_dd_limit_pct if limit == "daily" else portfolio.total_dd_limit_pct
        field = "strategy_dd_daily_limit_pct" if limit == "daily" else "strategy_dd_total_limit_pct"
        strategy_limits = [getattr(s, field) for s in self.strategies if s.portfolio_id == portfolio_id]
        return min([portfolio_limit, *strategy_limits])


def baseline_rule_enabled(strategy: Strategy, baseline_name: str) -> bool:
    """A baseline-derived rule is active only when its configured baseline exists."""
    if baseline_name not in Baselines.model_fields:
        raise KeyError(f"unknown baseline: {baseline_name}")
    return getattr(strategy.baselines, baseline_name) is not None


def load_registry(path: str | Path | None = None) -> StrategyRegistry:
    config_path = Path(path) if path is not None else Path(__file__).resolve().parents[2] / "config" / "strategies.yaml"
    with config_path.open(encoding="utf-8") as config_file:
        data = yaml.safe_load(config_file)
    return StrategyRegistry.model_validate(data)

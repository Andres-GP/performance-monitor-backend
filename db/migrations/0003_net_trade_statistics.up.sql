-- Persist sample statistics exposed by the normalized monitoring API.
ALTER TABLE public.daily_stats
    ADD COLUMN IF NOT EXISTS net_profit NUMERIC(24, 10),
    ADD COLUMN IF NOT EXISTS average_net_per_trade NUMERIC(24, 10),
    ADD COLUMN IF NOT EXISTS t_stat_net_per_trade NUMERIC(16, 8),
    ADD COLUMN IF NOT EXISTS trades_per_year_live_90d NUMERIC(16, 4),
    ADD COLUMN IF NOT EXISTS trades_per_year_expected NUMERIC(16, 4),
    ADD COLUMN IF NOT EXISTS frequency_vs_expected_pct NUMERIC(16, 4);

-- No observations is distinct from a measured zero loss streak.
ALTER TABLE public.daily_stats
    ALTER COLUMN current_loss_streak DROP NOT NULL,
    ALTER COLUMN max_loss_streak DROP NOT NULL;

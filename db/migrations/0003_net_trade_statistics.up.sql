-- Persist sample statistics exposed by the normalized monitoring API.
ALTER TABLE public.daily_stats
    ADD COLUMN IF NOT EXISTS net_profit NUMERIC(24, 10),
    ADD COLUMN IF NOT EXISTS average_net_per_trade NUMERIC(24, 10),
    ADD COLUMN IF NOT EXISTS t_stat_net_per_trade NUMERIC(16, 8);

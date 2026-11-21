-- Latest complete position state reported by each registered strategy EA.
CREATE TABLE IF NOT EXISTS public.position_snapshot (
    strategy_id TEXT PRIMARY KEY REFERENCES public.strategy(id) ON DELETE CASCADE,
    ts TIMESTAMPTZ NOT NULL,
    positions JSONB NOT NULL DEFAULT '[]',
    equity NUMERIC(24, 10) NOT NULL CHECK (equity > 0),
    margin_used NUMERIC(24, 10) NOT NULL CHECK (margin_used >= 0),
    free_margin NUMERIC(24, 10) NOT NULL CHECK (free_margin >= 0),
    currency TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS position_snapshot_ts_idx ON public.position_snapshot(ts);

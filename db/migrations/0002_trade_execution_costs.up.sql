-- Preserve execution costs as separate fields so reconciliation can compare
-- real costs with the strategy's modeled assumptions.
ALTER TABLE public.trade
    ADD COLUMN IF NOT EXISTS swap NUMERIC(24, 10),
    ADD COLUMN IF NOT EXISTS spread_cost NUMERIC(24, 10),
    ADD COLUMN IF NOT EXISTS slippage NUMERIC(24, 10),
    ADD COLUMN IF NOT EXISTS reference_price NUMERIC(24, 10),
    ADD COLUMN IF NOT EXISTS currency TEXT;

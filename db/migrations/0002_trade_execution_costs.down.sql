ALTER TABLE public.trade
    DROP COLUMN IF EXISTS reference_price,
    DROP COLUMN IF EXISTS currency,
    DROP COLUMN IF EXISTS slippage,
    DROP COLUMN IF EXISTS spread_cost,
    DROP COLUMN IF EXISTS swap;

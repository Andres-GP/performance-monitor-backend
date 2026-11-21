-- Preserve the EA-provided strategy ID when telemetry cannot yet be mapped
-- to a registered strategy. The backend has recorded this field since the
-- initial monitoring release, so add it safely to existing installations.
ALTER TABLE public.unregistered_source
    ADD COLUMN IF NOT EXISTS external_strategy_id TEXT;

CREATE INDEX IF NOT EXISTS unregistered_source_external_strategy_id_idx
    ON public.unregistered_source(external_strategy_id)
    WHERE external_strategy_id IS NOT NULL;

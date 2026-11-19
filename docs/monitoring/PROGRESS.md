# Progreso del sistema de monitoreo

- [x] Paso 0 — Reconocimiento. Stack y contrato actual documentados en `RECON.md`; reporter consultado desde `HEAD` porque está borrado localmente.
- [x] Paso 1 — Registro YAML completo, loader Pydantic, matching por prefijo, límites efectivos y baselines inactivos si son `null`.
- Nota: los EAs concretos no están disponibles; offsets de servidor y tamaños de contrato quedan `null` (conversión servidor→UTC desactivada).
- [x] Paso 2 — Migración reversible con tablas de monitoreo, restricciones e índices de series temporales.
- Nota: up/down se verifican con SQLite en memoria; la migración aún no se aplicó a Supabase.
- [x] Paso 3 — Ingesta raw primero, validación por tipo, dedupe/reintento, UTC, downsample de equity, trades, heartbeat, cashflow y fuentes desconocidas.
- Nota: timestamps de servidor quedan `received` hasta verificar offset; campos EA faltantes registrados en `GAPS.md`.
- [x] Paso 4 — Métricas deterministas por estrategia/portafolio y job cada minuto con cierre diario en hora de servidor.
- Nota: DD diario/fecha solo se persisten con offset verificado; equity actual del EA sigue ausente (ver `GAPS.md`).
- [x] Paso 5 — Reglas A: vida y actividad (heartbeat/equity stale, EAStopped, inactividad, reinicios y modo esperado).
- Nota: calendarios de cripto, FX y QQQ; `expected_mode` queda en demo según el estado actual del proyecto. Auto-resolución queda para el paso 10.
- [x] Paso 6 — Reglas B: drawdown diario/total por estrategia y portafolio, KillSwitch, límite duro del broker y `KNOWN_RISK_WEEKLYMOM`.
- Nota: DD diario se mantiene desactivado mientras el offset de servidor sea `null`; backtest queda desactivado con baselines `null`.
- [x] Paso 7 — Reglas C: conformidad de trades, rechazos y alertas operativas al ingerir eventos.
- Nota: tamaño, RSI2 hold y `MISSED_SLOT` quedan condicionados por datos faltantes/calendario; ver `GAPS.md`.
- [x] Paso 8 — Reglas D: deriva de win rate, profit factor, expectancy, frecuencia, costos y racha frente al backtest.
- Nota: las reglas no disparan con baselines `null`; `COST_DRIFT` requiere comisión, swap estimado y baseline.

# Progreso del sistema de monitoreo

- [x] Paso 0 — Reconocimiento. Stack y contrato actual documentados en `RECON.md`; reporter consultado desde `HEAD` porque está borrado localmente.
- [x] Paso 1 — Registro YAML completo, loader Pydantic, matching por prefijo, límites efectivos y baselines inactivos si son `null`.
- Nota: los EAs concretos no están disponibles; offsets de servidor y tamaños de contrato quedan `null` (conversión servidor→UTC desactivada).
- [x] Paso 2 — Migración reversible con tablas de monitoreo, restricciones e índices de series temporales.
- Nota: up/down se verifican con SQLite en memoria; la migración aún no se aplicó a Supabase.
- [x] Paso 3 — Ingesta raw primero, validación por tipo, dedupe/reintento, UTC, downsample de equity, trades, heartbeat, cashflow y fuentes desconocidas.
- Nota: timestamps de servidor quedan `received` hasta verificar offset; campos EA faltantes registrados en `GAPS.md`.
- [ ] Paso 4 — Métricas derivadas.

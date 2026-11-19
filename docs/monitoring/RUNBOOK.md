# Runbook de monitoreo

## Prioridad crítica

- `KILL_ACTIVE`: detener nuevas entradas, confirmar el kill switch en el terminal y revisar equity/DD. No cerrar la alerta al reiniciar; requiere ack humano.
- `DD_TOTAL_90`, `DD_DAILY_90`, `PORTFOLIO_DD_TOTAL_90`, `PORTFOLIO_DD_DAILY_90`: proteger la cuenta y verificar equity, zona horaria y muestras. El 90 % de límite es crítico; no reanudar hasta revisión humana.
- `BROKER_HARD_LIMIT`: confirmar el límite duro del broker, reducir riesgo según el procedimiento humano de la cuenta y comprobar que DD no siga aumentando.
- `DIR_VIOLATION`: bloquear nuevas operaciones de esa estrategia; confirmar dirección configurada, magic y símbolo antes de reactivarla.
- `HB_STALE` crítico (>4 h): comprobar terminal, VPS, conexión y logs. Comparar heartbeat recibido con eventos raw antes de reiniciar.

## Prioridad alta

- `HB_STALE` (>2 h), `EQUITY_STALE`: comprobar proceso EA, conexión y sesión del instrumento. Equity stale solo alerta cuando el calendario indica mercado abierto.
- `EA_STOPPED`, `RESTART_LOOP`: revisar logs de terminal y reinicios. Confirmar modo demo/real antes de reanudar.
- `INACTIVE`: comprobar calendario, filtro de señal, datos históricos y recepción de eventos; la falta de trades por sí sola no autoriza cambiar parámetros.
- `DD_TOTAL_70`, `DD_DAILY_70` y `PORTFOLIO_DD_*_70`: comparar equity y pico con el límite aplicable y revisar estrategias contribuyentes.
- `HOLD_DEVIATION`, `ENTRY_OFF_SCHEDULE`, `ENTRY_ON_FILTERED_DAY`, `CONCURRENCY`: cotejar timestamps UTC, horario del broker, trades solapados y filtros de calendario.
- `PF_DRIFT`, `EXPECTANCY_NEG`, `LOSS_STREAK`: revisar tamaño de muestra, trades y baseline. No cambiar estrategia por una sola alerta.
- `ORDER_REJECTED`, `REJECTS`: revisar retcode, margen, permisos, mercado y logs del broker; distinguir rechazo de entrada y de salida.
- `ZERO_LOTS`, `TICK_INVALID`, `NO_HISTORY`, `CALENDAR_EXPIRING`: corregir el dato o recurso indicado en el EA y verificar el siguiente evento.
- `UNREGISTERED_SOURCE`: comprobar identificador, prefijo, símbolo y magic; registrar en `config/strategies.yaml` solo tras validar su identidad.

## Revisión y resolución

1. Abrir el contexto y hora UTC de la alerta; comparar con `/health`, `/alerts` y el detalle de portfolio/estrategia.
2. Confirmar contra terminal, broker y eventos raw. Registrar evidencia y decisión humana fuera del agente.
3. Las condiciones evaluadas se resuelven tras dos evaluaciones limpias. `KILL_ACTIVE` requiere ack manual: `POST /alerts/{id}/ack`.
4. Si faltan datos o el offset no está verificado, no inferir DD, duración ni exposición; consultar `GAPS.md`.

## Baselines y registro

- Los baselines se obtienen del backtest/OOS aprobado, nunca de datos live. Editar `baselines` en `config/strategies.yaml`: `bt_win_rate`, `bt_profit_factor`, `bt_avg_trade_pct`, `bt_max_dd_pct`, `bt_trades_per_month`, `bt_avg_hold_min`; conservar `null` si no hay una fuente verificable.
- Para una estrategia nueva: añadir portfolio si hace falta, después la estrategia con ID único, prefijo exacto, magic, vehículo, horario, dirección, tamaño, límites, calendario, familia/clúster y baselines. Validar con `pytest -q tests/unit/test_strategy_registry.py` antes del despliegue.
- No inferir offsets del broker. Marcar `server_utc_offset_verified` solo con evidencia vigente; todos los timestamps normalizados se almacenan en UTC.

## Modo demo / capital real y SOP semanal

- Cada estrategia declara `expected_mode` (`demo` o `live`) en `config/strategies.yaml`. El portfolio también muestra el último modo observado en el evento `strategy_started`; si no existe evento, marca el modo como no confirmado. Si el observado difiere del esperado, revisar terminal/broker antes de continuar y no tratarlo como una confirmación de capital real.
- El workflow semanal genera `sop_email.html` y lo envía por Resend a `andresgarciapedreros@gmail.com` cuando existe `RESEND_API_KEY`. Configurar ese GitHub Secret y `RESEND_FROM_EMAIL` con un remitente validado en Resend. Los runs con fixture no envían correo. `WEEKLY_DASHBOARD_URL` es opcional; `SOP_EMAIL_TO` tiene ese destinatario como valor por defecto.
- La plantilla del correo usa la paleta local de la marca (verde bosque y lima), incluye estado por portfolio/estrategia, modo observado/esperado, señales y checklist SOP; no ejecuta ni cambia operaciones. Si el secreto de Resend falta, el workflow informa que omitió el envío.

## Entorno y simulación

- Requeridas para backend: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `API_SECRET_KEY`. Auth de usuario: `CLERK_JWKS_URL`, `CLERK_ISSUER`; webhook: `ALERT_WEBHOOK_URL`. Email legacy: `RESEND_API_KEY`, `RESEND_FROM_EMAIL`, `ALERT_EMAIL_TO`.
- Ejecutar `pytest -q`. Para eventos sintéticos usar `MONITOR_API_URL`, `MONITOR_API_TOKEN` y `python tools/replay.py --confirm-non-production`; el simulador rechaza hosts de producción conocidos.
- El replay de trade/equity puede devolver `pending_offset` hasta verificar el offset. Usar el simulador E2E local para probar esas reglas sin tocar una cuenta.

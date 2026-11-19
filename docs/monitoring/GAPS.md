# Gaps del contrato EA/backend

- **Offset del servidor**: los EAs concretos no están en el checkout y los templates no contienen `ServerToUTC`/`ServerOffsetHours`. `server_utc_offset_hours` sigue `null`; los eventos con hora de servidor se conservan como `received` y no se derivan hasta verificar el offset por portafolio.
- **Ticket de trade**: el `PerformanceReporter.mqh` revisado recibe `ticket`, pero no lo serializa en `/trades`. El backend deduplica el evento por una huella estable del cierre cuando falta.
- **Equity**: el reporter revisado no envía eventos `equity`; el endpoint normalizado los acepta cuando la EA los emita.
- **Posiciones abiertas**: el contrato no publica snapshots de posiciones. No se puede confirmar exposición abierta para discriminar cashflows con total certeza; se marca `cashflow_suspected` cuando no hay un cierre conocido en la ventana.
- **Otros campos ausentes**: swap separado, spread, slippage y motivo de `SKIP` por slot. Se mantienen como propuestas para el siguiente cambio de EA; no se modifica ningún `.mq5`.
- **Reglas de conformidad aún condicionadas**: `SIZE_DEVIATION` queda apagada con `contract_size: null`; duración de RSI2 está sin calibrar; `MISSED_SLOT` queda apagada hasta recibir alertas de entrada estructuradas (hoy `alert` es texto libre) y disponer del calendario CSV Gotobi ajustado.
- **Edge decay**: todos los baselines actuales están `null`, por lo que no se disparan reglas D. `COST_DRIFT` requiere `bt_cost_ratio` y `swap_estimate`; la EA no envía swap separado. `bt_max_loss_streak` también queda pendiente de baseline.
- **Capa/EDA de portafolio**: no llegan posiciones abiertas, balance, P&L flotante, margen, exposición, versión EA, tiempos de señal/orden, SL/TP, MAE/MFE, motivo de salida, spread/slippage, latencia/requotes ni calendario CSV Gotobi. Por eso posiciones, apalancamiento, `CLUSTER_EXPOSURE` y parte de la divergencia por spread quedan `null`/desactivados; el backlog EDA está en `EDA_BACKLOG.md`.

## Cambios de contrato EA propuestos (consolidado operativo)

Implementar y validar por etapas; no modificar EAs hasta aprobar el contrato y probar en demo.

- **Identidad y reconciliación**: `strategy_id`, versión/build del EA, magic, ticket/ID de orden y trade, símbolo exacto, lado y lotes; usar IDs estables para conciliar eventos y deduplicar.
- **Ciclo de orden/trade**: timestamps UTC de señal, envío, aceptación/rechazo, fill/entrada y salida; precio de señal/referencia y fill; spread al entrar; slippage = fill − referencia; motivo codificado de salida.
- **Costos y riesgo**: divisa de cuenta, comisión y swap separados, P&L bruto/neto; SL/TP iniciales, equity al abrir, riesgo monetario y porcentaje de equity, MAE/MFE y duración.
- **Estado de cuenta y posiciones**: snapshots de balance, equity, margen libre, margen usado y nivel de margen; posiciones abiertas con ID, símbolo, lado, lotes, nocional, precio medio, P&L flotante y SL/TP. Enviar al heartbeat o en un evento periódico idempotente.
- **Señales omitidas y calidad**: evento `SKIP` con hora, ventana/slot y razón enum; rechazos y requotes con retcode/contexto, latencia, reconexiones y gaps de datos.
- **Tiempo**: enviar hora del servidor y offset/IANA zone explícitos o timestamps UTC confiables. El literal `Z` no debe añadirse a una hora local sin conversión.

El EA actual no informa spread histórico, ATR/régimen ni calendario externo; esos datos pertenecen a fuentes de mercado del backend. Consultar `EDA_BACKLOG.md` para los análisis que se habilitarán con cada fuente.

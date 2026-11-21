# Gaps del contrato EA/backend

- **Offset del servidor**: los eventos nuevos del `PerformanceReporter.mqh` expresan fechas en UTC y llevan el offset observado del broker. Así se pueden procesar sin asumir una zona horaria fija; las estrategias antiguas siguen pendientes hasta verificar el offset.
- **Ticket de trade**: el `PerformanceReporter.mqh` revisado recibe `ticket`, pero no lo serializa en `/trades`. El backend deduplica el evento por una huella estable del cierre cuando falta.
- **Equity**: el reporter ya envía muestras cada intervalo de heartbeat.
- **Posiciones abiertas**: los EAs activos envían snapshots filtrados por magic number con posiciones, P&L flotante, swap y margen de cuenta. El backend los considera frescos por tres minutos; con datos viejos el estado vuelve a “sin muestra”.
- **Costes**: swap y comisión se envían por separado y el monitor de deriva acepta el nombre real `swap`. El spread de entrada y slippage medido siguen dependiendo de enriquecer cada evento de ejecución.
- **Reglas de conformidad aún condicionadas**: `SIZE_DEVIATION` queda apagada con `contract_size: null`; duración de RSI2 está sin calibrar; `MISSED_SLOT` queda apagada hasta recibir alertas de entrada estructuradas (hoy `alert` es texto libre) y disponer del calendario CSV Gotobi ajustado.
- **Edge decay**: todos los baselines actuales están `null`, por lo que no se disparan reglas D. `COST_DRIFT` requiere `bt_cost_ratio` y `swap_estimate`; la EA no envía swap separado. `bt_max_loss_streak` también queda pendiente de baseline.
- **Capa/EDA de portafolio**: snapshots nuevos habilitan conteo de posiciones, P&L flotante y margen usado/libre. El riesgo por stop, exposición nocional normalizada, versión EA, spread de entrada, MAE/MFE, latencia/requotes y calendario CSV Gotobi aún requieren campos o fuentes adicionales; esos indicadores deben seguir como “sin muestra”. El backlog está en `EDA_BACKLOG.md`.

## Cambios de contrato EA propuestos (consolidado operativo)

Implementar y validar por etapas; no modificar EAs hasta aprobar el contrato y probar en demo.

- **Identidad y reconciliación**: `strategy_id`, versión/build del EA, magic, ticket/ID de orden y trade, símbolo exacto, lado y lotes; usar IDs estables para conciliar eventos y deduplicar.
- **Ciclo de orden/trade**: timestamps UTC de señal, envío, aceptación/rechazo, fill/entrada y salida; precio de señal/referencia y fill; spread al entrar; slippage = fill − referencia; motivo codificado de salida.
- **Costos y riesgo**: divisa de cuenta, comisión y swap separados, P&L bruto/neto; SL/TP iniciales, equity al abrir, riesgo monetario y porcentaje de equity, MAE/MFE y duración.
- **Estado de cuenta y posiciones**: snapshots de balance, equity, margen libre, margen usado y nivel de margen; posiciones abiertas con ID, símbolo, lado, lotes, nocional, precio medio, P&L flotante y SL/TP. Enviar al heartbeat o en un evento periódico idempotente.
- **Señales omitidas y calidad**: evento `SKIP` con hora, ventana/slot y razón enum; rechazos y requotes con retcode/contexto, latencia, reconexiones y gaps de datos.
- **Tiempo**: enviar hora del servidor y offset/IANA zone explícitos o timestamps UTC confiables. El literal `Z` no debe añadirse a una hora local sin conversión.

El EA actual no informa spread histórico, ATR/régimen ni calendario externo; esos datos pertenecen a fuentes de mercado del backend. Consultar `EDA_BACKLOG.md` para los análisis que se habilitarán con cada fuente.

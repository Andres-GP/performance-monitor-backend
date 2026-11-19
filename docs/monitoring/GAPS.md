# Gaps del contrato EA/backend

- **Offset del servidor**: los EAs concretos no están en el checkout y los templates no contienen `ServerToUTC`/`ServerOffsetHours`. `server_utc_offset_hours` sigue `null`; los eventos con hora de servidor se conservan como `received` y no se derivan hasta verificar el offset por portafolio.
- **Ticket de trade**: el `PerformanceReporter.mqh` revisado recibe `ticket`, pero no lo serializa en `/trades`. El backend deduplica el evento por una huella estable del cierre cuando falta.
- **Equity**: el reporter revisado no envía eventos `equity`; el endpoint normalizado los acepta cuando la EA los emita.
- **Posiciones abiertas**: el contrato no publica snapshots de posiciones. No se puede confirmar exposición abierta para discriminar cashflows con total certeza; se marca `cashflow_suspected` cuando no hay un cierre conocido en la ventana.
- **Otros campos ausentes**: swap separado, spread, slippage y motivo de `SKIP` por slot. Se mantienen como propuestas para el siguiente cambio de EA; no se modifica ningún `.mq5`.

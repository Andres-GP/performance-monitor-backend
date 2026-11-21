# Contrato y liberación de producción

## Contrato esperado

- MetaTrader envía `POST /heartbeat` y `POST /monitor/events` al servicio FastAPI de Performance Monitor.
- La aplicación web llama al mismo servicio mediante su proxy de Next.js. El proxy conserva las rutas raíz del API, por ejemplo `GET /portfolios?limit=100` y `GET /alerts`.
- Las lecturas de la web llevan un JWT de Clerk. La ingesta de los EAs usa el token de API configurado en cada terminal.
- No añadir prefijos `/api/...` a estas rutas: ese prefijo pertenece a otro servicio y su listado de rutas no corresponde al contrato de este backend.

## Discrepancia detectada

- El código de `develop` incluye `GET /portfolios` y `POST /monitor/events`; las referencias locales `origin/main` y `origin/staging` no los incluyen todavía.
- El workflow de Render despliega producción desde `main` y staging desde `staging`.
- El README y el health check del workflow nombran `performance-monitor-backend.onrender.com`, mientras que el módulo compartido de MetaTrader define `performance-monitor-backend-prod.onrender.com` como host predeterminado.
- La respuesta `Route not found` con rutas `/api/sites`, `/api/organizations`, `/api/stripe`, etc. no coincide con FastAPI ni con las rutas del frontend. Indica que esa petición llegó a un servicio distinto o a una versión distinta del API.

## Pasos para cerrar la liberación

1. Confirmar en Render cuál servicio corresponde al backend FastAPI de monitoreo y cuál es su URL pública canónica. Mantener esa misma URL en frontend, EAs y health check de despliegue.
2. Promover el código de `develop` a la rama de despliegue elegida; confirmar que la instancia de producción contiene `GET /portfolios` y `POST /monitor/events` antes de abrir esas pantallas.
3. Aplicar las migraciones `db/migrations/0001_monitoring_core.up.sql` y `0002_trade_execution_costs.up.sql` a la base de producción antes de consumir los endpoints normalizados.
4. Verificar `/health`, `POST /heartbeat`, `POST /monitor/events` y las lecturas autenticadas `/portfolios`, `/alerts` y `/capital/summary` directamente contra el host confirmado.
5. Añadir ese host a la lista de URLs permitidas en WebRequest en cada terminal MetaTrader. El error MT5 `4014` sucede antes de que el backend pueda responder.
6. Después de validar el servicio, ejecutar la tarea pendiente de [QUEUE.md](QUEUE.md) en los EAs.

No se debe cambiar el contrato de rutas de la VPS para solucionar una URL de producción que apunta a otro servicio.

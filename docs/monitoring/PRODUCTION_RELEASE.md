# Contrato y liberación de producción

## Contrato esperado

- MetaTrader envía `POST /heartbeat` y `POST /monitor/events` al servicio FastAPI de Performance Monitor.
- La aplicación web llama al mismo servicio mediante su proxy de Next.js. El proxy conserva las rutas raíz del API, por ejemplo `GET /portfolios?limit=100` y `GET /alerts`.
- Las lecturas de la web llevan un JWT de Clerk. La ingesta de los EAs usa el token de API configurado en cada terminal.
- No añadir prefijos `/api/...` a estas rutas: ese prefijo pertenece a otro servicio y su listado de rutas no corresponde al contrato de este backend.

## Estado verificado

- El servicio `performance-monitor-backend-prod` de Render está conectado al repositorio `Andres-GP/performance-monitor-backend`, rama `main`, y desplegó el commit `542329a`.
- Ese release incluye `GET /portfolios` y `POST /monitor/events`; las referencias remotas `main`, `staging` y `develop` también contienen esas rutas.
- La URL pública canónica de producción confirmada en Render es `https://performance-monitor-backend-prod.onrender.com`. README, EAs y health check deben usar el mismo host.
- La respuesta `Route not found` con rutas `/api/sites`, `/api/organizations`, `/api/stripe`, etc. no coincide con FastAPI ni con las rutas de este frontend. La evidencia apunta a que se consultó otro hostname/servicio; el antiguo hostname sin `-prod` no debe usarse.

## Pasos para cerrar la liberación

1. Mantener la URL canónica `https://performance-monitor-backend-prod.onrender.com` en frontend, EAs y health check de despliegue.
2. Verificar que cada nuevo release de producción conserve `GET /portfolios` y `POST /monitor/events`.
3. Aplicar, en orden, las migraciones `0001_monitoring_core.up.sql` a `0004_position_snapshots.up.sql` a la base de producción antes de consumir los campos ampliados.
4. Verificar `/health`, `POST /heartbeat`, `POST /monitor/events` y las lecturas autenticadas `/portfolios`, `/alerts` y `/capital/summary` directamente contra el host canónico.
5. Añadir ese host a la lista de URLs permitidas en WebRequest en cada terminal MetaTrader. El error MT5 `4014` sucede antes de que el backend pueda responder.
6. Después de validar el servicio, ejecutar la tarea pendiente de [QUEUE.md](QUEUE.md) en los EAs.

No se debe cambiar el contrato de rutas de la VPS para solucionar una URL de producción que apunta a otro servicio.

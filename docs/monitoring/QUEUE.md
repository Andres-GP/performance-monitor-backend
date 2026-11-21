# Cola de trabajo de monitoreo

## Pendiente después de corregir y validar la conexión de producción

- [ ] Actualizar únicamente los valores predeterminados de telemetría en todas las estrategias EA activas: heartbeat cada 60 segundos y backend URL `https://performance-monitor-backend-prod.onrender.com`.
- Alcance: `Metatrader_base` y los scripts EA Demo de los portfolios Axi y Darwinex. No cambiar parámetros de trading, sizing, señales, gestión de órdenes ni otras partes de las estrategias.
- Criterio de cierre: todos los EAs afectados compilan, usan esos dos valores por defecto, y la URL queda permitida en WebRequest de MetaTrader; verificar el flujo contra el backend de monitoreo antes de desplegar a la VPS.
- Dependencia: resolver primero la discrepancia entre el host de producción del backend que responde al frontend y el servicio FastAPI que define `/portfolios`, `/monitor/events` y `/heartbeat`. No aplicar este cambio de EAs hasta confirmar cuál es el host correcto y que responde esas rutas.

# Backlog: EDA por portafolio y estrategia

## Objetivo

Entregar un análisis exploratorio interactivo y legible por cada portafolio, con una vista consolidada y navegación a cada estrategia. Debe ayudar a decidir qué revisar; mostrar siempre período, unidades, zona horaria, tamaño de muestra y calidad de datos; no completar valores `null` ni fabricar resultados de backtest.

## Encaje con el plan existente

Este backlog amplía los pasos ya previstos, sin crear una segunda implementación de sus métricas:

- Pasos 3–8: ingesta, métricas, reglas de riesgo/conformidad y edge decay son las fuentes canónicas.
- Paso 9: agregados, curvas y correlaciones de portafolio.
- Pasos 11–12: API de lectura y dashboard; aquí se entregan las vistas EDA por portafolio y estrategia.
- Pasos 16–19: comparación determinista live/backtest, régimen, EHI, gráficos y reporte semanal. El EDA consume esos resultados cuando existan.

## Datos adicionales que faltan

| Nivel | Ya cubierto en el plan | Añadir cuando haya fuente confiable |
|---|---|---|
| Trade | Estrategia, magic, símbolo, lado, volumen, tiempos/precios de entrada y salida, P&L, comisión y duración | Versión del EA; tiempos de señal y orden; precio de señal; spread de entrada; slippage; comisión/swap y P&L bruto/neto separados; SL/TP iniciales; riesgo monetario, porcentual y R inicial; MAE/MFE; motivo de salida |
| Serie de estrategia | Equity muestreada, trades realizados, drawdown y métricas móviles | Balance; P&L flotante; posiciones, nocional, margen usado y lotes abiertos; drawdown y días desde el último máximo |
| Portafolio | Equity/DD, contribución por estrategia, curva y correlación rolling | Margen libre y nivel de margen; exposición neta/bruta por activo, divisa y factor (cripto/JPY/USD); asignación de riesgo por estrategia; riesgo abierto agregado contra el hard limit |
| Mercado | Retornos/régimen de referencia y calendarios de sesión previstos en el paso 17 | Volatilidad ATR/realizada por instrumento; historial de spread/swap; calendario de eventos y festivos aplicable al instrumento/broker |
| Backtest | Win rate, PF, expectancy, frecuencia, drawdown y bootstrap/conos del paso 16 | Payoff y Sharpe esperados; curva OOS identificada y comparable con live |
| Ejecución | Rechazos y conciliación EA/motor previstas en pasos 7 y 16 | Requotes; latencia; gaps de datos; diferencias de trade/precio/lotes con estados faltante/extra claramente identificados |

## Análisis y gráficos requeridos

- Comparación live/backtest con bandas percentiles bootstrap para expectancy, win rate y DD; indicar `NO_BASELINE` o `INSUFFICIENT_DATA` cuando corresponda.
- Equity live/backtest/OOS superpuesta; DD y rachas live frente a distribución esperada; Sharpe rolling.
- Correlación rolling y contribución marginal al riesgo entre estrategias; concentración por activo/divisa/factor.
- Degradación de spread, slippage y costos reales frente a supuestos; separar comisión y swap cuando existan.
- Exposición/solapamiento por estrategia y escenarios de estrés legibles, incluidos límites duros y riesgo compartido.
- Vistas por portafolio con desglose por estrategia, y vista de estrategia con trades, ejecución, régimen y distribución backtest; gráficos con títulos, ejes, unidades y leyendas claros.

## Orden de implementación

1. Completar portafolio y correlación del paso 9; anotar explícitamente las métricas indisponibles.
2. Exponer las fuentes canónicas en la API del paso 11.
3. Incorporar las vistas EDA y gráficos livianos en el dashboard del paso 12. **Hecho parcialmente en Paso 12**: selector de portfolio, equity agregado, alertas/heartbeat por estrategia, correlación disponible, métricas live y trades recientes. Los demás análisis quedan para pasos 16–19 o hasta disponer de sus fuentes.
4. Reutilizar datos, cálculos y gráficos de los pasos 16–19; añadir solamente los campos/análisis adicionales de este documento.
5. Registrar nuevas carencias de contrato en `GAPS.md` y habilitar cada análisis solo cuando los datos necesarios sean verificables.

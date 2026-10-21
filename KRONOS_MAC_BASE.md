# ¿Kronos predice las velas?

Kronos-small usado tal como viene, sin reentrenar, sobre BTC, ETH y SOL (corrido en auto, datos de binance). Solo se evalúan resultados posteriores al **2025-09-01** (Kronos se publicó en agosto de 2025, así que no pudo verlos). Período: 2025-08-25 → 2026-10-20.

## Conclusiones

- **Hay indicios, pero no alcanzan:** en 15m→1h (51.1% de aciertos, p=0.025) acertó más que una moneda al aire, pero al corregir por haber probado 5 combinaciones hace falta p<0.010.
- **Qué hace Kronos en el fondo:** sus predicciones se parecen mucho a la regla simple "lo que subió, baja" (correlación promedio 0.40). Gran parte de lo que acierta lo acierta también esa regla.
- **Ojo:** en 1h→4h, 1h→1d todas las predicciones arrancan a la misma hora (00:00 UTC), así que el resultado vale para esa franja del día y no necesariamente para cualquier momento.
- **Con costos no sirve:** la mejor ganancia bruta por operación fue 0.044% (1h→4h, entre las combinaciones con suficientes datos), y entrar y salir cuesta 0.30%. Ninguna combinación le ganó a comprar y mantener después de costos de forma apreciable.

## ¿Acierta la dirección?

| Entrada → horizonte | Momentos independientes | Aciertos Kronos | p-valor | "Lo que subió, baja" | Seguir tendencia | "Siempre sube" | Parecido de Kronos a "lo que subió, baja" |
|---|---:|---:|---:|---:|---:|---:|---:|
| 15m → 1h | 2489 | 51.1% | 0.025 | 51.8% | 47.4% | 49.9% | 0.47 |
| 15m → 4h | 2490 | 51.2% | 0.061 | 52.9% | 46.8% | 50.2% | 0.49 |
| 1h → 4h | 414 | 53.7% | 0.129 | 52.6% | 47.1% | 51.0% | 0.29 |
| 1h → 1d | 415 | 48.0% | 0.653 | 50.6% | 49.4% | 49.6% | 0.52 |
| 1d → 1w | 60 | 43.9% | 0.953 | 58.3% | 41.7% | 42.2% | 0.25 |

## Operando con eso (retorno promedio por operación, con costos)

| Entrada → horizonte | Kronos | Kronos solo si espera más que los costos | % del tiempo operando | Seguir tendencia | Comprar y mantener | Kronos sin costos |
|---|---:|---:|---:|---:|---:|---:|
| 15m → 1h | -0.121% | -0.033% | 11% | -0.147% | 0.007% | 0.001% |
| 15m → 4h | -0.117% | -0.073% | 19% | -0.156% | -0.013% | -0.013% |
| 1h → 4h | -0.104% | -0.037% | 28% | -0.144% | 0.027% | 0.035% |
| 1h → 1d | -0.234% | -0.240% | 46% | -0.134% | -0.081% | -0.085% |
| 1d → 1w | -0.511% | -0.501% | 69% | -0.590% | -0.498% | -0.303% |

## Cómo leer esto

- **Aciertos**: % de veces que la dirección predicha (sube o baja) coincidió con la real. Una moneda al aire da 50%.
- **Momentos independientes**: BTC, ETH y SOL se mueven juntas, así que las tres predicciones de un mismo momento cuentan como una sola prueba.
- **p-valor**: probabilidad de acertar así de seguido por pura suerte. Como se probaron varias combinaciones, para ser significativo tiene que ser menor que 0.010.
- **Correlación**: qué tan bien ordena las subas grandes y chicas (0 = nada, 1 = perfecto). En finanzas, 0,02-0,05 ya se considera una señal.
- **Operando con eso**: comprar cuando Kronos predice suba y quedarse afuera cuando predice baja, pagando 0,15% al entrar y al salir.
- Configuración fija: NeoQuasar/Kronos-small, contexto 400 velas, promedio de 4 trayectorias, temperatura 1.0.

📊 Tablero: https://dcohenm.github.io/trading-arena/kronos_mac_base/

*Generado el 2026-10-21 00:52 UTC (métricas recalculadas) en 161 minutos. Todo es simulado; no es asesoramiento financiero.*

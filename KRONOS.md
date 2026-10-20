# ¿Kronos predice las velas?

Kronos-small usado tal como viene, sin reentrenar, sobre BTC, ETH y SOL. Solo se evalúan resultados posteriores al **2025-09-01** (Kronos se publicó en agosto de 2025, así que no pudo verlos). Período: 2025-08-27 → 2026-10-20.

## Conclusiones

- **Hay indicios, pero no alcanzan:** en 15m→1h (55.3% de aciertos, p=0.041), 15m→4h (56.6% de aciertos, p=0.026), 1h→1d (60.2% de aciertos, p=0.013) acertó más que una moneda al aire, pero al corregir por haber probado 5 combinaciones hace falta p<0.010, y la muestra es chica (el servidor sin placa de video llegó a hacer pocas predicciones).
- **Qué hace Kronos en el fondo:** sus predicciones se parecen mucho a la regla simple "lo que subió, baja" (correlación promedio 0.49). Gran parte de lo que acierta lo acierta también esa regla.
- **Con costos no sirve:** la mejor ganancia bruta por operación fue 0.145% (15m→4h), y entrar y salir cuesta 0.30%. Ninguna combinación le ganó a comprar y mantener después de costos de forma apreciable.

## ¿Acierta la dirección?

| Entrada → horizonte | Momentos independientes | Aciertos Kronos | p-valor | "Lo que subió, baja" | Seguir tendencia | "Siempre sube" | Parecido de Kronos a "lo que subió, baja" |
|---|---:|---:|---:|---:|---:|---:|---:|
| 15m → 1h | 161 | 55.3% | 0.041 | 54.9% | 45.1% | 52.2% | 0.36 |
| 15m → 4h | 129 | 56.6% | 0.026 | 54.3% | 45.5% | 48.6% | 0.45 |
| 1h → 4h | 94 | 47.9% | 0.910 | 48.6% | 51.4% | 49.3% | 0.57 |
| 1h → 1d | 88 | 60.2% | 0.013 | 55.3% | 44.7% | 46.2% | 0.62 |
| 1d → 1w | 41 | 52.0% | 0.106 | 53.7% | 46.3% | 51.2% | 0.45 |

## Operando con eso (retorno promedio por operación, con costos)

| Entrada → horizonte | Kronos | Kronos solo si espera más que los costos | % del tiempo operando | Seguir tendencia | Comprar y mantener | Kronos sin costos |
|---|---:|---:|---:|---:|---:|---:|
| 15m → 1h | -0.138% | -0.042% | 21% | -0.193% | -0.028% | 0.005% |
| 15m → 4h | -0.123% | -0.092% | 40% | -0.140% | -0.084% | 0.030% |
| 1h → 4h | -0.160% | -0.107% | 24% | -0.191% | -0.035% | -0.009% |
| 1h → 1d | -0.241% | -0.210% | 50% | -0.366% | -0.266% | -0.074% |
| 1d → 1w | -0.442% | -0.487% | 47% | -0.319% | -0.688% | -0.296% |

## Cómo leer esto

- **Aciertos**: % de veces que la dirección predicha (sube o baja) coincidió con la real. Una moneda al aire da 50%.
- **Momentos independientes**: BTC, ETH y SOL se mueven juntas, así que las tres predicciones de un mismo momento cuentan como una sola prueba.
- **p-valor**: probabilidad de acertar así de seguido por pura suerte. Como se probaron varias combinaciones, para ser significativo tiene que ser menor que 0.010.
- **Correlación**: qué tan bien ordena las subas grandes y chicas (0 = nada, 1 = perfecto). En finanzas, 0,02-0,05 ya se considera una señal.
- **Operando con eso**: comprar cuando Kronos predice suba y quedarse afuera cuando predice baja, pagando 0,15% al entrar y al salir.
- Configuración fija: NeoQuasar/Kronos-small, contexto 400 velas, promedio de 4 trayectorias, temperatura 1.0.

📊 Tablero: https://dcohenm.github.io/trading-arena/kronos/

*Generado el 2026-10-20 22:05 UTC (métricas recalculadas) en 216 minutos. Todo es simulado; no es asesoramiento financiero.*

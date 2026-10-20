# ¿Kronos predice las velas?

Kronos-small usado tal como viene, sin reentrenar, sobre BTC, ETH y SOL. Solo se evalúan resultados posteriores al **2025-09-01** (Kronos se publicó en agosto de 2025, así que no pudo verlos). Período: 2025-08-27 → 2026-10-20.

## Conclusiones

- **Predice algo:** en 15m→4h (56.8% de aciertos), 1h→1d (60.8% de aciertos) acertó la dirección más que una moneda al aire y más que las reglas simples, con significancia estadística aun corrigiendo por haber probado 5 combinaciones.
- **Con costos:** operar según Kronos no le ganó a comprar y mantener ni a seguir la tendencia en ninguna combinación.

## ¿Acierta la dirección?

| Entrada → horizonte | Predicciones | Aciertos Kronos | p-valor | Aciertos tendencia | Aciertos "siempre sube" | Correlación Kronos | Correlación tendencia |
|---|---:|---:|---:|---:|---:|---:|---:|
| 15m → 1h | 561 | 54.2% | 0.026 | 38.9% | 51.7% | 0.124 | -0.074 |
| 15m → 4h | 444 | 56.8% | 0.003 | 39.6% | 48.9% | 0.191 | -0.006 |
| 1h → 4h | 285 | 47.7% | 0.797 | 50.9% | 48.8% | 0.008 | -0.037 |
| 1h → 1d | 273 | 60.8% | 0.000 | 43.2% | 46.5% | 0.169 | -0.104 |
| 1d → 1w | 123 | 52.0% | 0.359 | 46.3% | 51.2% | -0.046 | -0.026 |

## Operando con eso (retorno promedio por operación, con costos)

| Entrada → horizonte | Kronos | Kronos solo si espera más que los costos | % del tiempo operando | Seguir tendencia | Comprar y mantener | Kronos sin costos |
|---|---:|---:|---:|---:|---:|---:|
| 15m → 1h | -0.142% | -0.041% | 19% | -0.166% | -0.028% | 0.000% |
| 15m → 4h | -0.116% | -0.072% | 36% | -0.122% | -0.101% | 0.036% |
| 1h → 4h | -0.161% | -0.105% | 24% | -0.189% | -0.036% | -0.009% |
| 1h → 1d | -0.222% | -0.191% | 50% | -0.354% | -0.256% | -0.055% |
| 1d → 1w | -0.442% | -0.487% | 47% | -0.319% | -0.688% | -0.296% |

## Cómo leer esto

- **Aciertos**: % de veces que la dirección predicha (sube o baja) coincidió con la real. Una moneda al aire da 50%.
- **p-valor**: probabilidad de acertar así de seguido por pura suerte. Como se probaron varias combinaciones, para ser significativo tiene que ser menor que 0.010.
- **Correlación**: qué tan bien ordena las subas grandes y chicas (0 = nada, 1 = perfecto). En finanzas, 0,02-0,05 ya se considera una señal.
- **Operando con eso**: comprar cuando Kronos predice suba y quedarse afuera cuando predice baja, pagando 0,15% al entrar y al salir.
- Configuración fija: NeoQuasar/Kronos-small, contexto 400 velas, promedio de 4 trayectorias, temperatura 1.0.

📊 Tablero: https://dcohenm.github.io/trading-arena/kronos/

*Generado el 2026-10-20 19:58 UTC en 216 minutos. Todo es simulado; no es asesoramiento financiero.*

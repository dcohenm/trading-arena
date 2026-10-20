# Estudio histórico

Simulación de la arena completa sobre **1097 días de precios reales** (2023-10-19 → 2026-10-20, velas de 15 min de coinbase, BTC/USDT, ETH/USDT, SOL/USDT). Mismos bots, mismo gestor de riesgo, mismos costos y la misma evolución semanal que corre en vivo, usando en cada momento solo los datos disponibles hasta ese momento.

## Conclusiones

- **Bots individuales:** 1 pasaron todos los filtros (`breakout`). Ojo: se probaron 70 bots, así que algunos pueden haber pasado por suerte; mirá cuánto vivieron y cuánto ganaron.
- **El proceso completo:** repartir la plata entre los bots activos rindió +20.2% (Sharpe 0.41, caída máxima 37.4%) contra +196.2% de comprar y mantener (Sharpe 0.89, caída máxima 67.8%). Pero su ventaja no es estadísticamente sólida (probabilidad 75.7%, hace falta 95%); no le ganó a comprar y mantener ajustado por riesgo.
- **¿Aprender sirve?** La evolución eligió 66 bots entre 1928 candidatos. Después de ser elegidos, 30.8% ganó plata y su percentil mediano contra los bots al azar fue 7.5 (por pura suerte sería 50). Eso indica que el examen no logró predecir qué bots iban a andar bien: lo que funcionó en el pasado reciente no siguió funcionando.
- La relación entre la nota del examen y el rendimiento posterior fue -0.14 (1 = la nota predice perfecto, 0 = no predice nada).

## Carteras

| | Retorno | Sharpe | Caída máx. | Prob. ventaja real |
|---|---:|---:|---:|---:|
| Comprar y mantener | +196.2% | 0.89 | 67.8% | 93.6% |
| Cartera del proceso (todos los bots activos) | +20.2% | 0.41 | 37.4% | 75.7% |
| Cartera evolutiva (solo los bots que creó la evolución) | -4.9% | 0.01 | 37.5% | 50.9% |
| Cartera al azar (los 20 bots aleatorios) | +4.8% | 0.20 | 19.7% | 63.1% |

## Por año (retorno %)

| | 2023 | 2024 | 2025 | 2026 |
|---|---:|---:|---:|---:|
| Comprar y mantener | +147.2 | +86.2 | -25.2 | -13.9 |
| momentum | +32.9 | +52.6 | -20.1 | — |
| mean_reversion | +0.9 | +9.2 | — | — |
| breakout | +36.0 | +36.9 | — | — |
| Cartera del proceso | +21.0 | +14.7 | -10.2 | -3.5 |
| Cartera evolutiva | +2.7 | +6.0 | -9.5 | -3.5 |
| Cartera al azar | +18.8 | -9.1 | -3.0 | +0.0 |

## Evolución

- Generaciones: 156 · candidatos probados: 1928 · promovidos: 66
- De los promovidos que vivieron al menos 14 días (65): 30.8% ganó plata, 21.5% le ganó a comprar y mantener en su mismo período, percentil mediano contra el azar: 7.5.

## Bots iniciales

| Bot | Retorno | Sharpe | Caída máx. | Trades | Veredicto |
|---|---:|---:|---:|---:|---|
| `buy_and_hold` | +196.2% | 0.89 | 67.8% | 3 | Referencia |
| `momentum` | +62.2% | 1.29 | 29.8% | 493 | Sin evidencia estadística (puede ser suerte) |
| `mean_reversion` | +10.2% | 2.12 | 4.2% | 195 | Sin evidencia estadística (puede ser suerte) |
| `breakout` | +86.1% | 3.58 | 10.5% | 206 | Candidato: pasar a la siguiente fase |

## Cómo leer esto

- **Cartera del proceso** es lo que hubieras obtenido repartiendo la plata en partes iguales entre los bots que la arena tenía activos en cada momento. Es la mejor medida de si *el sistema completo* sirve.
- **Cartera al azar** es lo mismo pero con los bots que operan al azar: es la vara contra la que hay que ganar.
- **Sharpe** mide retorno por unidad de riesgo. **Prob. ventaja real** es la probabilidad de que el Sharpe sea mayor que cero de verdad y no por ruido; hace falta 95% o más.
- Un backtest, aunque sea cuidadoso, es más optimista que la realidad: no simula caídas del exchange, órdenes que no se llenan ni cambios bruscos de liquidez.

📊 Tablero interactivo: https://dcohenm.github.io/trading-arena/estudio/

*Generado el 2026-10-20 12:56 UTC en 12 minutos. Todo es simulado; no es asesoramiento financiero.*

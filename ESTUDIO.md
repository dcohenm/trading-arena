# Estudio histórico

Simulación de la arena completa sobre **1097 días de precios reales** (2023-10-19 → 2026-10-20, velas de 15 min de coinbase, BTC/USDT, ETH/USDT, SOL/USDT). Mismos bots, mismo gestor de riesgo, mismos costos y la misma evolución semanal que corre en vivo, usando en cada momento solo los datos disponibles hasta ese momento.

## Conclusiones

- **Bots individuales:** ninguno de los 100 bots pasó todos los filtros (ventaja estadística, ganarle al 95% del azar y a comprar y mantener).
- **El proceso completo:** repartir la plata entre los bots activos rindió +60.7% (Sharpe 0.92, caída máxima 21.2%) contra +196.2% de comprar y mantener (Sharpe 0.89, caída máxima 67.8%). Pero su ventaja no es estadísticamente sólida (probabilidad 94.3%, hace falta 95%).
- **¿Aprender sirve?** La evolución eligió 97 bots entre 2808 candidatos. Después de ser elegidos, 49.5% ganó plata y su percentil mediano contra los bots al azar fue 10.0 (por pura suerte sería 50). Eso indica que el examen no logró predecir qué bots iban a andar bien: lo que funcionó en el pasado reciente no siguió funcionando.
- La relación entre la nota del examen y el rendimiento posterior fue +0.21 (1 = la nota predice perfecto, 0 = no predice nada).

## Carteras

| | Retorno | Sharpe | Caída máx. | Prob. ventaja real |
|---|---:|---:|---:|---:|
| Comprar y mantener | +196.2% | 0.89 | 67.8% | 93.6% |
| Cartera del proceso (todos los bots activos) | +60.7% | 0.92 | 21.2% | 94.3% |
| Cartera evolutiva (solo los bots que creó la evolución) | +34.6% | 0.60 | 21.2% | 84.7% |
| Cartera al azar (los 20 bots aleatorios) | +6.1% | 0.23 | 18.3% | 65.1% |

## Por año (retorno %)

| | 2023 | 2024 | 2025 | 2026 |
|---|---:|---:|---:|---:|
| Comprar y mantener | +147.2 | +86.2 | -25.2 | -13.9 |
| momentum | +33.3 | +26.1 | — | — |
| mean_reversion | +1.2 | +4.4 | — | — |
| breakout | +35.4 | +22.5 | — | — |
| Cartera del proceso | +23.5 | +20.6 | +8.0 | -0.1 |
| Cartera evolutiva | +6.4 | +17.2 | +8.0 | -0.1 |
| Cartera al azar | +18.8 | -7.2 | -2.9 | -0.9 |

## Evolución

- Generaciones: 156 · candidatos probados: 2808 · promovidos: 97
- De los promovidos que vivieron al menos 14 días (95): 49.5% ganó plata, 40.0% le ganó a comprar y mantener en su mismo período, percentil mediano contra el azar: 10.0.

## Bots iniciales

| Bot | Retorno | Sharpe | Caída máx. | Trades | Veredicto |
|---|---:|---:|---:|---:|---|
| `buy_and_hold` | +196.2% | 0.89 | 67.8% | 3 | Referencia |
| `momentum` | +68.0% | 4.01 | 12.3% | 132 | No supera claramente a los bots al azar |
| `mean_reversion` | +5.7% | 1.36 | 4.2% | 191 | Sin evidencia estadística (puede ser suerte) |
| `breakout` | +65.8% | 1.99 | 17.4% | 348 | No le gana a comprar y mantener (ajustado por riesgo) |

## Cómo leer esto

- **Cartera del proceso** es lo que hubieras obtenido repartiendo la plata en partes iguales entre los bots que la arena tenía activos en cada momento. Es la mejor medida de si *el sistema completo* sirve.
- **Cartera al azar** es lo mismo pero con los bots que operan al azar: es la vara contra la que hay que ganar.
- **Sharpe** mide retorno por unidad de riesgo. **Prob. ventaja real** es la probabilidad de que el Sharpe sea mayor que cero de verdad y no por ruido; hace falta 95% o más.
- Un backtest, aunque sea cuidadoso, es más optimista que la realidad: no simula caídas del exchange, órdenes que no se llenan ni cambios bruscos de liquidez.

📊 Tablero interactivo: https://dcohenm.github.io/trading-arena/estudio/

*Generado el 2026-10-20 12:39 UTC en 14 minutos. Todo es simulado; no es asesoramiento financiero.*

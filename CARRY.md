# Estudio de carry (tasa de financiamiento)

Período: **2023-09-21 → 2026-10-19** (1125 días). Datos de funding de **Phemex**; precios de contado de coinbase.

## Conclusiones

- **Le ganó a los bonos por muy poco:** la regla A (siempre) rindió +5.3% por año contra ~4.5% de los bonos del Tesoro: apenas 0.8 puntos más por año. Es una diferencia chica para el riesgo de tener la plata depositada en un exchange cripto.
- **Hoy:** en los últimos 6 meses el funding promedio fue BTC 3.7%, ETH 2.7%, SOL 3.0% anual, por debajo de los ~4.5% de los bonos. En este momento no paga el riesgo.
- **Riesgo que no aparece en el número:** si el exchange quiebra (como FTX en 2022) se puede perder todo lo depositado. No hubo días con subas de más de 40%, que hubieran puesto en riesgo la garantía.

## Resultados

| | Retorno | Retorno anual | Sharpe | Caída máx. | Peor mes | Meses negativos | Operaciones |
|---|---:|---:|---:|---:|---:|---:|---:|
| A · siempre | +17.3% | +5.3% | 11.37 | 0.3% | -0.2% | 14% | 254 |
| B · solo cuando paga | +14.8% | +4.6% | 9.67 | 0.2% | -0.1% | 14% | 179 |
| Bonos del Tesoro (~4.5% anual, aprox.) | +14.9% | +4.5% | — | 0% | — | 0% | — |

## Funding promedio por año (% anual)

| | BTC | ETH | SOL | Días con funding negativo |
|---|---:|---:|---:|---:|
| 2023 | 11.8 | 15.9 | 21.0 | 11% |
| 2024 | 12.6 | 15.8 | 16.1 | 5% |
| 2025 | 5.1 | 6.2 | 5.3 | 12% |
| 2026 | 2.8 | 2.1 | 1.6 | 27% |

## Retorno por año

| | 2023 | 2024 | 2025 | 2026 |
|---|---:|---:|---:|---:|
| A · siempre | +2.7% | +9.9% | +3.2% | +0.7% |
| B · solo cuando paga | +2.5% | +9.4% | +2.3% | +0.1% |

## ¿Pasa lo mismo en otros exchanges? (funding promedio, % anual, en el período que cada uno tiene)

| Exchange | Desde | Días | BTC | ETH | SOL | Phemex mismo período |
|---|---|---:|---:|---:|---:|---:|
| Bitget | 2026-07-22 | 90 | 5.8 | 6.4 | 4.6 | BTC 4.5, ETH 3.4, SOL 4.9 |
| KuCoin | 2026-09-17 | 33 | 4.5 | 5.1 | 3.4 | BTC 3.8, ETH 3.9, SOL 6.4 |
| MEXC | 2026-09-17 | 33 | 3.9 | 4.4 | 3.9 | BTC 3.8, ETH 3.9, SOL 6.4 |
| BingX | 2025-11-21 | 333 | 4.2 | 3.8 | 4.7 | BTC 2.9, ETH 2.4, SOL 1.8 |
| WOO X | 2025-06-07 | 500 | 3.4 | 3.2 | -3.2 | BTC 3.9, ETH 3.8, SOL 2.7 |
| Kraken Futures | 2025-10-15 | 370 | 3.3 | 3.5 | 0.5 | BTC 3.1, ETH 2.8, SOL 1.8 |
| OKX | 2026-07-20 | 92 | 5.3 | 4.3 | 3.2 | BTC 4.6, ETH 3.4, SOL 4.9 |

## Sensibilidad de la regla B (no es optimización: solo muestra si el resultado depende del umbral)

| Entrar si funding > | Retorno | Sharpe |
|---|---:|---:|
| 5% anual | +15.2% | 9.28 |
| 10% anual | +14.8% | 9.67 |
| 20% anual | +12.4% | 8.75 |

## Supuestos

- Capital = 1,5 veces lo invertido (50% extra como garantía de los futuros). Lo que no se invierte no rinde nada.
- Costos por entrar o salir de una moneda: 0.21% (comisión y deslizamiento en las dos patas). Rebalanceo cuando una posición se desvía más de 10%.
- Reglas fijadas antes de mirar los resultados. Nada se ajustó sobre estos datos.
- El Sharpe sale muy alto porque no se simulan las oscilaciones de la diferencia de precio entre contado y futuro; en la realidad la curva es más irregular.
- Solo Phemex dio 3 años completos de historia desde los servidores de GitHub (Binance y Bybit los bloquean). Los demás exchanges sirven para comparar el último tramo.
- No incluye: quiebra o congelamiento del exchange, cambios en las reglas del exchange, impuestos.

📊 Tablero: https://dcohenm.github.io/trading-arena/carry/

*Generado el 2026-10-20 15:52 UTC. Todo es simulado; no es asesoramiento financiero.*

# Comprar la caída en tendencia alcista (acciones de EE.UU.)

La idea del post de Reddit, con reglas fijas, sobre **2012-01-03 → 2026-10-20** (datos de Yahoo Finance). Costos 0,03% por lado (también se muestra 0,10%).

## Conclusiones

- **60 acciones conocidas:** la estrategia rindió 3.1% anual (Sharpe 0.31, caída máx. 25%, invertida en promedio el 41% del tiempo) contra 25.6% de comprar y mantener esos mismos activos (Sharpe 1.10) y 14.9% del S&P 500 (Sharpe 0.93). Por operación: 0.064% contra 0.077% de entrar en cualquier día al azar y 0.049% de entrar al azar en días de tendencia alcista (le ganó al 30% y al 71% de esas versiones). No se distingue de entrar al azar.
- **20 ETFs (sin sesgo):** la estrategia rindió 2.1% anual (Sharpe 0.37, caída máx. 18%, invertida en promedio el 13% del tiempo) contra 14.7% de comprar y mantener esos mismos activos (Sharpe 0.89) y 14.9% del S&P 500 (Sharpe 0.93). Por operación: 0.124% contra 0.037% de entrar en cualquier día al azar y 0.018% de entrar al azar en días de tendencia alcista (le ganó al 100% y al 100% de esas versiones). Le gana al azar, pero no a comprar y mantener ajustado por riesgo.
- **Antes y durante el período del autor (60 acciones):** 2012-2023, que el autor nunca vio: 3.6% anual (Sharpe 0.35); 2024-2026, el período con el que lo diseñó: 1.1% anual (Sharpe 0.15). Comprar y mantener esas acciones: 23.7% y 34.6%.

## 60 acciones conocidas

| | Retorno anual | Sharpe | Caída máx. | Prob. ventaja real |
|---|---:|---:|---:|---:|
| Estrategia (costo 0,03%) | 3.1% | 0.31 | 25% | 89% |
| Estrategia (costo 0,10%) | -5.2% | -0.37 | 58% | 7% |
| Comprar y mantener el mismo grupo | 25.6% | 1.10 | 42% | 100% |
| S&P 500 (SPY) | 14.9% | 0.93 | 34% | 100% |

Operaciones: 8862 · ganadoras 52% · promedio por operación 0.064% · invertida en promedio el 41% del tiempo.

| Año | 2012 | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Estrategia | 1.5 | 16.2 | 2.7 | -5.0 | 4.2 | 9.6 | -14.0 | 2.2 | 39.7 | 6.0 | -21.2 | 13.7 | 10.9 | -0.6 | -6.5 |
| Comprar y mantener | 19.0 | 49.2 | 17.9 | 15.0 | 12.7 | 35.2 | 4.3 | 33.3 | 71.2 | 39.6 | -37.3 | 66.9 | 65.6 | 25.7 | 8.5 |
| S&P 500 | 14.2 | 32.3 | 13.5 | 1.2 | 12.0 | 21.7 | -4.6 | 31.2 | 18.3 | 28.7 | -18.2 | 26.2 | 24.9 | 17.7 | 13.7 |

## 20 ETFs

| | Retorno anual | Sharpe | Caída máx. | Prob. ventaja real |
|---|---:|---:|---:|---:|
| Estrategia (costo 0,03%) | 2.1% | 0.37 | 18% | 92% |
| Estrategia (costo 0,10%) | -0.5% | -0.05 | 25% | 43% |
| Comprar y mantener el mismo grupo | 14.7% | 0.89 | 32% | 100% |
| S&P 500 (SPY) | 14.9% | 0.93 | 34% | 100% |

Operaciones: 2649 · ganadoras 55% · promedio por operación 0.124% · invertida en promedio el 13% del tiempo.

| Año | 2012 | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Estrategia | 2.8 | 6.6 | 0.8 | 1.3 | 4.5 | 7.3 | -9.6 | -0.6 | -3.6 | 7.5 | -6.6 | 2.0 | 5.3 | 5.3 | 9.4 |
| Comprar y mantener | 13.3 | 24.5 | 15.2 | 0.7 | 10.2 | 23.7 | -6.9 | 31.4 | 23.7 | 21.8 | -19.6 | 26.6 | 19.7 | 23.8 | 22.6 |
| S&P 500 | 14.2 | 32.3 | 13.5 | 1.2 | 12.0 | 21.7 | -4.6 | 31.2 | 18.3 | 28.7 | -18.2 | 26.2 | 24.9 | 17.7 | 13.7 |

## Cómo leer esto

- **Sharpe**: retorno por unidad de riesgo. Es la comparación justa, porque la estrategia pasa parte del tiempo en efectivo.
- **Entradas al azar**: las mismas reglas de salida (stop, objetivo, 3 días) pero comprando en días al azar. Si la señal de "comprar la caída" sirve, tiene que ganarle a casi todas esas versiones (97,5% o más).
- **Sesgo de supervivencia**: las 60 acciones son ganadoras conocidas de hoy. Por eso el grupo de ETFs es la prueba más honesta.
- Supuesto conservador: si un día toca stop y objetivo, se cuenta como stop. Los datos diarios no dicen cuál pasó primero.

📊 Tablero: https://dcohenm.github.io/trading-arena/acciones/

*Generado el 2026-10-20 23:36 UTC en 1 minutos. Todo es simulado; no es asesoramiento financiero.*

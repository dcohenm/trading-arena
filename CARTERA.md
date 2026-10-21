# Bot de cartera: estudio de 20 años

Período **2005-09-01 → 2026-10-19** (Yahoo Finance (precios ajustados por dividendos)). Incluye la crisis de 2008, el COVID en 2020 y 2022. Rebalanceo mensual, costos de 0.25% por operación.

**Cartera base:** Acciones EE.UU. (S&P 500) 45% · Acciones de países desarrollados 15% · Bonos del Tesoro cortos 25% · Oro 10% · Bitcoin 5%

## Conclusiones

- **Cartera con filtro de tendencia:** 7.7% anual, caída máxima 19%, peor año -15.4%, Sharpe 0.96.
- **Comparada con:** la misma cartera sin filtro 10.0% anual (caída máx. 35%); el S&P 500 solo 11.1% anual (caída máx. 55%); la 60/40 8.0% anual (caída máx. 35%).
- **En una frase:** el filtro recortó la peor caída en un 65% respecto del S&P 500, a cambio de 3.4 puntos menos de retorno por año. Su relación retorno/riesgo (Sharpe) fue mejor que la del S&P 500.
- **¿Cuánto aporta el 5% en bitcoin?** Con bitcoin: 7.7% anual; sin bitcoin: 5.8% anual (caída máx. 19% vs 17%). Bitcoin entra recién en 2015, cuando tiene 10 meses de historia; su efecto depende muchísimo de lo que hizo en esos años y no hay garantía de que se repita.
- **Aportes mensuales:** esperar una caída corta dentro del mes en vez de comprar el primer día cambió el resultado final en -0.18% en 254 meses. Una diferencia mínima: no vale la pena complicarse.

## Resultados

| | Retorno anual | Caída máx. | Peor año | Sharpe | Meses en caída (más largo) |
|---|---:|---:|---:|---:|---:|
| Cartera con filtro de tendencia | 7.7% | 19% | -15.4% | 0.96 | 30 |
| Misma cartera sin filtro | 10.0% | 35% | -21.7% | 0.84 | 36 |
| Con filtro, sin bitcoin | 5.8% | 17% | -15.4% | 0.78 | 32 |
| Sin filtro, sin bitcoin | 8.0% | 35% | -21.7% | 0.72 | 36 |
| S&P 500 solo | 11.1% | 55% | -36.8% | 0.65 | 58 |
| 60/40 clásica | 8.0% | 35% | -20.9% | 0.73 | 37 |
| Cartera con filtro de tendencia (costos 0.5%) | 7.1% | 21% | -16.4% | 0.88 | 36 |
| Misma cartera sin filtro (costos 0.5%) | 9.9% | 35% | -21.8% | 0.84 | 36 |

## Por año (%)

| | 2005 | 2006 | 2007 | 2008 | 2009 | 2010 | 2011 | 2012 | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Cartera con filtro de tendencia | 4 | 13 | 9 | 5 | 14 | 0 | -1 | 3 | 17 | 4 | -6 | 5 | 34 | -6 | 9 | 20 | 15 | -15 | 10 | 21 | 15 | 2 |
| Misma cartera sin filtro | 4 | 14 | 9 | -22 | 19 | 12 | 1 | 11 | 13 | 4 | 2 | 12 | 36 | -8 | 25 | 23 | 18 | -15 | 23 | 21 | 19 | 7 |
| S&P 500 solo | 3 | 16 | 5 | -37 | 26 | 15 | 2 | 16 | 32 | 13 | 1 | 12 | 22 | -5 | 31 | 18 | 29 | -18 | 26 | 25 | 18 | 13 |
| 60/40 clásica | 1 | 11 | 6 | -21 | 17 | 12 | 5 | 11 | 18 | 11 | 1 | 8 | 14 | -2 | 22 | 15 | 16 | -16 | 18 | 15 | 14 | 7 |

## El filtro en la práctica

Porcentaje del tiempo que cada activo estuvo dentro de la cartera: Acciones EE.UU. (S&P 500) 81%, Acciones de países desarrollados 70%, Oro 69%, Bitcoin 37%. Entradas y salidas en total: 118 en 22 años (unas 5.4 por año).

## Cómo leer esto

- **Caída máxima**: lo peor que habrías visto desde un máximo hasta un mínimo. Es lo que hace que la gente abandone.
- **Meses en caída**: el período más largo sin recuperar el máximo anterior.
- El filtro no busca ganar más: busca perder menos en las crisis para poder sostener la inversión.
- Supuestos: impuestos no incluidos; el bitcoin se modela con su precio en dólares; los CEDEARs pueden tener diferencias de precio con el original.

📊 Tablero: https://dcohenm.github.io/trading-arena/cartera/

*Generado el 2026-10-21 00:11 UTC. Todo es simulado; no es asesoramiento financiero.*

# Soportes, resistencias y números redondos

Velas de 1 hora de BTC, ETH y SOL (coinbase), **2023-10-13 → 2026-10-20**. Reglas fijadas antes de mirar los datos; costos de 0,15% por lado. Cada estrategia se compara con las mismas operaciones hechas en momentos al azar (300 veces).

## Conclusiones

- **Rebote en soporte:** 2613 operaciones, -0.299% promedio por operación con costos (las mismas operaciones en momentos al azar dan -0.253%). No se distingue del azar (le ganó al 10% de las versiones al azar; hace falta más de 98.3%).
- **Ruptura con volumen:** 992 operaciones, -0.306% promedio por operación con costos (las mismas operaciones en momentos al azar dan -0.194%). No se distingue del azar (le ganó al 10% de las versiones al azar; hace falta más de 98.3%).
- **Comprar al cruzar un número redondo:** 1471 operaciones, -0.258% promedio por operación con costos (las mismas operaciones en momentos al azar dan -0.194%). No se distingue del azar (le ganó al 19% de las versiones al azar; hace falta más de 98.3%).
- **¿El precio se frena en los números redondos?** Cerca de un número redondo lo cruzó el 78.0% de las veces; cerca de un nivel no redondo, el 78.2% (p=0.935). No se ve un efecto claro.
- **¿Después de cruzarlo sigue de largo?** Al cruzar hacia arriba, las 24 h siguientes promediaron 0.089% en números redondos contra 0.071% en los de control (p=0.877); al cruzar hacia abajo, 0.247% contra 0.252% (p=0.964).

## Estrategias

| | Operaciones | Promedio por operación (con costos) | % ganadoras | Al azar: promedio | Al azar: 95% mejor | Le ganó al % del azar |
|---|---:|---:|---:|---:|---:|---:|
| A · Rebote en soporte | 2613 | -0.299% | 42% | -0.253% | -0.194% | 10% |
| B · Ruptura con volumen | 992 | -0.306% | 35% | -0.194% | -0.040% | 10% |
| C · Comprar al cruzar un número redondo | 1471 | -0.258% | 29% | -0.194% | -0.073% | 19% |

## Por año (promedio por operación, con costos)

| | 2023 | 2024 | 2025 | 2026 |
|---|---:|---:|---:|---:|
| A · Rebote en soporte | -0.044% (n=97) | -0.356% (n=967) | -0.310% (n=964) | -0.229% (n=585) |
| B · Ruptura con volumen | 0.446% (n=85) | -0.461% (n=375) | -0.335% (n=299) | -0.292% (n=233) |
| C · Comprar al cruzar un número redondo | 0.232% (n=72) | -0.244% (n=561) | -0.319% (n=608) | -0.285% (n=230) |

## Por moneda

| | BTC | ETH | SOL |
|---|---:|---:|---:|
| A · Rebote en soporte | -0.283% (n=789) | -0.269% (n=882) | -0.342% (n=942) |
| B · Ruptura con volumen | -0.226% (n=304) | -0.342% (n=323) | -0.340% (n=365) |
| C · Comprar al cruzar un número redondo | -0.174% (n=348) | -0.317% (n=439) | -0.263% (n=684) |

## Números redondos en detalle

| Prueba | Números redondos | Niveles de control | p-valor |
|---|---:|---:|---:|
| Lo cruza en las 24 h siguientes al acercarse (desde abajo y arriba) | 78.0% (n=455) | 78.2% (n=478) | 0.935 |
| Retorno 24 h después de cruzar hacia arriba | 0.089% (n=2337) | 0.071% (n=2495) | 0.877 |
| Retorno 24 h después de cruzar hacia abajo | 0.247% (n=2314) | 0.252% (n=2468) | 0.964 |

## Cómo leer esto

- **Le ganó al % del azar**: de las 300 versiones con entradas al azar (mismos stops y objetivos), a qué porcentaje superó. Como se prueban 3 estrategias, hace falta más de 98,3% para descartar la suerte.
- **Niveles de control**: niveles justo a mitad de camino entre dos números redondos (BTC 2.500, 7.500…). Si los redondos fueran especiales, deberían comportarse distinto que estos.
- Supuesto conservador: si en una misma vela se tocan el stop y el objetivo, se cuenta como stop.

📊 Tablero: https://dcohenm.github.io/trading-arena/soportes/

*Generado el 2026-10-20 23:10 UTC en 1 minutos. Todo es simulado; no es asesoramiento financiero.*

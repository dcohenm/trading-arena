# Trading Arena (proyecto terminado)

Un experimento para responder una pregunta: **¿se puede armar un bot que opere solo y le gane al mercado?**
Se probó con rigor, con datos reales, costos incluidos, reglas fijadas antes de mirar los resultados y comparando siempre contra el azar y contra no hacer nada.

**Respuesta corta: no encontramos ninguno.** Lo que más rindió en todas las pruebas fue lo más simple: comprar el índice S&P 500 y no tocarlo.

Todo está apagado: no corre nada automático. Lo que queda es el registro de lo que se probó.

## Qué se probó y qué salió

| Prueba | Resultado | Detalle |
|---|---|---|
| Bots clásicos de cripto (tendencia, reversión, rupturas) compitiendo 24/7 contra bots al azar | Ninguno le ganó al azar ni a comprar y mantener | [ESTUDIO.md](ESTUDIO.md) |
| Bots que "aprenden solos" (evolución semanal con examen fuera de muestra) | Empeoró los resultados: los elegidos rindieron peor que el azar | [ESTUDIO.md](ESTUDIO.md) |
| Carry de futuros (cobrar la tasa de financiamiento sin apostar al precio) | Funcionó en 2023-24; hoy rinde menos que los bonos del Tesoro | [CARRY.md](CARRY.md) |
| Kronos, un modelo de IA entrenado con 12.000 millones de velas (versión chica y versión 4 veces más grande) | Ve algo muy chico (sobre todo "lo que subió, baja"); el modelo grande no mejora; no cubre los costos | [KRONOS.md](KRONOS.md), [KRONOS_MAC_SMALL.md](KRONOS_MAC_SMALL.md), [KRONOS_MAC_BASE.md](KRONOS_MAC_BASE.md) |
| Soportes, resistencias y números redondos | Peor que entrar al azar; los números redondos no tienen nada especial | [SOPORTES.md](SOPORTES.md) |
| Acciones de EE.UU.: comprar la caída en tendencia (idea de un post de Reddit) | En ETFs hay una ventaja real pero chica; no le gana a comprar el índice | [ACCIONES.md](ACCIONES.md) |
| Cartera diversificada con filtro de tendencia mensual | Menos caídas (−19% vs −55% del S&P 500) a cambio de menos retorno | [CARTERA.md](CARTERA.md) |

## Lecciones

1. **Los costos deciden casi todo.** Varias ideas ganaban un poquito antes de comisiones y perdían después.
2. **Pocos datos engañan.** Resultados que parecían prometedores con muestras chicas desaparecieron con la muestra completa.
3. **Optimizar sobre el pasado se paga en el futuro.** La evolución automática mejoraba el backtest y empeoraba lo que venía después.
4. **La comparación justa es contra el azar y contra no hacer nada.** Ganar plata en un mercado que sube no prueba nada.
5. **Errores de medición inflan resultados.** Dos veces se corrigió un error propio que hacía ver mejor un resultado; las versiones anteriores quedaron en [study/historial](study/historial/README.md).

## Qué hay en el repositorio

- `*.md`: los reportes de cada prueba.
- `study/`: datos y resultados de cada estudio.
- `docs/`: tableros visuales (https://dcohenm.github.io/trading-arena/).
- `arena/`, `*.py`: el código. Se puede volver a correr a mano; ver [GUIA.md](GUIA.md).

*Todo fue simulado: no se usó dinero real. Nada de esto es asesoramiento financiero.*

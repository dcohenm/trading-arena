# Historial del estudio

Cada vez que se corrige algo de la metodología, la corrida anterior queda guardada acá para que se vea qué cambió y por qué.

## v1 (2026-10-20)

**Problema encontrado:** para decidir qué bots retirar y cuáles usar como padres, se comparaba el Sharpe de cada bot sobre *toda su vida*. Un bot nacido en medio de una suba fuerte (que solo vivió la parte buena) quedaba arriba de otro que había atravesado subas y bajas. Así se retiró a `momentum` en marzo de 2024 (Sharpe 4,0, +68% en 140 días) por estar entre "los peores", y la evolución terminó persiguiendo a los ganadores recientes: 88 de los 97 bots promovidos fueron variantes de `breakout`.

**Corrección (v2):** cada bot se compara contra los bots al azar *en su misma ventana* (sus últimos 90 días de vida). El resto de la metodología no cambió: mismos datos, mismos bots iniciales, mismo examen.

Resultados de v1: ver [v1/ESTUDIO.md](v1/ESTUDIO.md).

## Kronos v1 (2026-10-20)

**Problemas encontrados:** (1) las predicciones de BTC, ETH y SOL de un mismo momento se contaban como tres pruebas independientes, pero las tres monedas se mueven juntas, así que la significancia salía exagerada; (2) en la regla "seguir la tendencia", los momentos sin dato previo se contaban como errores, lo que la hacía ver peor (39%) de lo que era (45%).

**Corrección:** una observación por momento para calcular la significancia, comparar solo donde hay datos, y sumar la regla "lo que subió, baja" como referencia. Las predicciones de Kronos son las mismas; solo cambió cómo se miden. La versión v1 del reporte decía "predice algo"; corregida dice "hay indicios, pero no alcanzan". Ver [kronos_v1.md](kronos_v1.md).

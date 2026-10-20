# Trading Arena — piloto automático

Bots de trading cripto compitiendo con plata **simulada** sobre precios reales. Corre solo cada hora en GitHub. La evolución automática está **apagada**: el [estudio histórico](ESTUDIO.md) mostró que empeoraba los resultados. Quedan los bots fijos compitiendo contra los bots al azar.

> Lleva 0.6 días. En las primeras semanas los números son ruido: todavía no se puede sacar ninguna conclusión.

**Última actualización:** 2026-10-20 13:30 UTC · **Desde:** 2026-10-19 23:30 UTC · **Datos:** bingx · **Evolución:** apagada

## Ranking (bots activos)

| Bot | Días | Retorno | Sharpe | Caída máx. | Trades | Veredicto |
|---|---:|---:|---:|---:|---:|---|
| `buy_and_hold` | 1 | -0.4% | -6.18 | 1.1% | 3 | Referencia |
| `breakout` | 1 | +0.0% | — | 0.0% | 0 | En observación (1 de 30 días mínimos) |
| `mean_reversion` | 1 | +0.0% | — | 0.0% | 0 | En observación (1 de 30 días mínimos) |
| `momentum` | 1 | +0.0% | — | 0.0% | 0 | En observación (1 de 30 días mínimos) |

Para correr backtests o pruebas a mano en tu computadora: [GUIA.md](GUIA.md).

## Cómo leer esto

- **Retorno**: cuánto ganó o perdió desde que entró a la arena (cada bot arranca con 10.000 USDT simulados).
- **Sharpe**: retorno por unidad de riesgo. Más alto es mejor; negativo es perder.
- **Veredicto**: un bot solo es *candidato* si después de al menos 30 días su ventaja es estadísticamente sólida, le gana al 95% de los bots que operan al azar y le gana a comprar y mantener. Lo normal es que durante mucho tiempo no haya ninguno.
- Si algún bot pasa todos los filtros, se abre un *Issue* en este repositorio y GitHub te avisa por mail.

## Cómo frenarlo

Pestaña **Actions** → workflow **Arena** → botón **⋯** → **Disable workflow**. Para reanudar, el mismo lugar → **Enable workflow**.

---
*Todo es simulado: no hay dinero real ni conexión a ninguna cuenta. No es asesoramiento financiero.*

# Trading Arena — piloto automático

Bots de trading cripto compitiendo con plata **simulada** sobre precios reales. Corre solo cada hora en GitHub y una vez por semana se mejora solo: prueba variantes nuevas de los mejores bots y retira a los peores.

> Recién arrancó. Todavía no hay datos suficientes para mostrar resultados.

**Última actualización:** — · **Desde:** — · **Datos:** — · **Generación:** 0 · **Próxima evolución:** —


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

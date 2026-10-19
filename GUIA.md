# Guía manual (backtests y pruebas en tu computadora)

Una arena donde varios bots de trading cripto compiten 24/7 con la misma plata simulada, los mismos datos y los mismos costos. Algunos bots usan a Grok (la IA de xAI) y otros son estrategias clásicas que sirven de vara para medir. Al final el sistema te dice, con estadística, si alguno tiene una ventaja real o si lo que ves es suerte.

**Todo es paper trading:** usa precios reales del exchange pero las órdenes son simuladas. No se arriesga plata. No es asesoramiento financiero.

---

## Cómo funciona

```
 Exchange (datos públicos, sin cuenta)
          │  velas de 15 min
          ▼
 ┌──────────────────────────────────────────────────────────┐
 │  MOTOR (el mismo para backtest y para vivo)              │
 │                                                          │
 │   Bots ──propuesta──▶ GESTOR DE RIESGO ──órdenes──▶ Broker│
 │   (no tocan el        (código duro: recorta,           simulado
 │    mercado)            frena, elimina, liquida)        (comisiones
 │                                                          + slippage)
 └──────────────────────────────────────────────────────────┘
          │
          ▼
   arena.db (SQLite) ──▶ tablero HTML con ranking y veredicto
```

Reglas de diseño que importan:

- **Los bots nunca hablan con el exchange.** Devuelven una propuesta ("quiero 30% en BTC"). El gestor de riesgo la recorta si hace falta y recién ahí se convierte en orden. Si Grok alucina "300% en SOL", queda en el máximo permitido.
- **Nadie ve el futuro.** El bot decide con datos hasta el cierre de la vela y la orden se ejecuta en la apertura de la siguiente. Hay un test que lo verifica.
- **Costos siempre incluidos.** 0,10% de comisión + 0,05% de deslizamiento por operación. Sin esto cualquier estrategia parece genial.
- **Si Grok falla** (timeout, respuesta rota, se acabó el presupuesto), el bot mantiene lo que tiene. Nunca opera a ciegas.

## Los competidores

| Bot | Qué hace | Para qué está |
|---|---|---|
| `buy_and_hold` | Compra al inicio en partes iguales y no toca nada | La vara mínima: si no le ganás a esto, no tiene sentido operar |
| `momentum` | Sigue la tendencia (medias móviles) con tamaño ajustado por volatilidad | Estrategia clásica sin IA |
| `mean_reversion` | Compra caídas fuertes (RSI bajo) y vende al normalizarse | Otra clásica, opuesta a la anterior |
| `grok_trader` | Grok recibe un resumen de indicadores cada 4 h y decide los pesos de cada activo | ¿Grok sabe operar solo? |
| `grok_overlay` | El momentum elige qué comprar; Grok decide cada 6 h cuánto arriesgar según el contexto | ¿Grok agrega valor como gestor de riesgo? |
| 30 × `_luck_XX` | Operan al azar con distintas frecuencias | Miden cuánto se puede "ganar" por pura suerte |

## El veredicto (lo más importante)

El tablero no premia al que más ganó. Para cada bot calcula:

- **Sharpe**: retorno por unidad de riesgo.
- **Probabilidad de Sharpe > 0** (Probabilistic Sharpe Ratio): qué tan probable es que la ventaja sea real y no ruido, corrigiendo por la cantidad de datos y por las colas gordas de cripto. Hace falta **≥ 95%**.
- **Percentil contra los bots al azar**: hace falta quedar por encima del **95%** de ellos.
- **Contra comprar y mantener**: tiene que tener mejor Sharpe.

Solo si pasa todo eso dice **"Candidato: pasar a la siguiente fase"**. Esperá que durante semanas la respuesta sea "Sin evidencia estadística". Eso es el sistema funcionando, no fallando.

---

## Instalación

Necesitás Python 3.10 o más nuevo.

```bash
cd grok_arena
python -m venv .venv
source .venv/bin/activate          # en Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest -q tests          # 18 tests deberían pasar
```

## Paso 1 — Probar que todo anda (sin internet, 15 segundos)

```bash
python main.py backtest --synthetic
```

Corre 180 días de precios inventados con Grok simulado y abre el tablero. Sirve solo para ver el sistema funcionando: con datos inventados ningún bot tiene ventaja, y el veredicto lo detecta.

## Paso 2 — Backtest con historia real

```bash
python main.py download --days 365     # baja 1 año de velas del exchange de config.yaml (datos públicos, sin cuenta)
python main.py backtest                # Grok simulado; las estrategias clásicas sí se evalúan de verdad
```

En el backtest, Grok va **simulado** a propósito. Grok ya "leyó" internet durante su entrenamiento, así que conoce gran parte de esta historia y un backtest con él estaría contaminado (y además costaría plata). Si igual querés probarlo: `python main.py backtest --llm real`.

## Paso 3 — Paper trading en vivo 24/7 con Grok real

1. Creá una API key en https://console.x.ai
2. Copiá `.env.example` como `.env` y pegá la key.
3. Verificá qué modelos tenés disponibles y, si hace falta, cambiá `llm.model` en `config.yaml`:
   ```bash
   python main.py models
   ```
4. Completá en `config.yaml` los precios por millón de tokens (`price_input_per_m`, `price_output_per_m`) que figuran en la consola de xAI. Así el sistema mide cuánto gasta y respeta el tope diario (`daily_budget_usd`, USD 5 por defecto).
5. Arrancá:
   ```bash
   python main.py paper
   ```

Muestra el capital de cada bot en cada vela y actualiza `reports/latest.html` cada hora. Con la configuración por defecto, Grok se consulta unas 10 veces por día en total.

**Para que corra 24/7** necesitás una máquina que quede prendida: un VPS barato o una PC que no se apague. En Linux o Mac:

```bash
nohup python main.py paper > arena.log 2>&1 &
```

**Si se corta** (luz, reinicio, internet), retomá donde estaba con el ID de la corrida (aparece al arrancar, tipo `live-20261019-2230`):

```bash
python main.py paper --resume live-20261019-2230
```

**Ver el tablero en cualquier momento:**

```bash
python main.py report                      # última corrida
python main.py report --run live-2026...   # una corrida específica
```

## Frenos de emergencia

- **Archivo `KILL`:** si creás un archivo llamado `KILL` en la carpeta del proyecto, todos los bots liquidan y la arena deja de operar.
- **Pérdida diaria:** un bot que pierde 5% en el día (UTC) solo puede reducir posiciones hasta el día siguiente.
- **Drawdown máximo:** un bot que cae 30% desde su máximo queda eliminado y liquidado.
- **Límites de tamaño:** máximo 50% del capital por activo, sin apalancamiento, mínimo 15 USDT por operación, máximo 24 operaciones por día por bot.

Todo se ajusta en la sección `risk` de `config.yaml`.

---

## Cómo agregar tu propio bot

Creá una clase que herede de `Bot` y devuelva una `Proposal` con pesos objetivo (0 a 1 por activo):

```python
# arena/bots/mi_bot.py
from ..core import Proposal
from .base import Bot

class Breakout(Bot):
    type = "breakout"

    def decide(self, ctx):
        targets = {}
        for s in ctx.market.symbols:
            c = ctx.market.series(s, n=200)          # cierres hasta ahora (nunca el futuro)
            if c[-1] >= c[:-1].max():
                targets[s] = 0.3                      # máximo de 200 velas: entrar
            elif c[-1] <= c[-50:].min():
                targets[s] = 0.0                      # mínimo de 50 velas: salir
        return Proposal(targets, stops={s: 0.08 for s in targets}, reason="ruptura de máximos")
```

Registralo en `arena/bots/__init__.py` (agregalo a `REGISTRY`) y sumalo en `config.yaml`:

```yaml
  - name: breakout
    type: breakout
    every: 1h
```

Lo que tenés disponible en `ctx`: `ctx.market.series(símbolo, campo, n)` con campo `open/high/low/close/volume`, `ctx.weights` (tus posiciones actuales), `ctx.equity`, `ctx.cash` y `ctx.ts` (hora en milisegundos).

Para pedirle ideas a Grok, la mejor forma es que te escriba bots así, como código fijo que se puede testear, en lugar de que opere él directamente.

## Archivos

```
config.yaml            toda la configuración
main.py                comandos: download, backtest, paper, report, models
arena/engine.py        el motor (mismo para backtest y vivo)
arena/risk.py          gestor de riesgo
arena/broker.py        broker simulado
arena/llm.py           cliente de Grok + Grok simulado
arena/bots/            los bots
arena/metrics.py       métricas y veredicto
arena/report.py        tablero HTML (funciona sin internet)
arena/live.py          bucle 24/7
tests/                 tests
arena.db               se crea solo: todo el historial
```

## Próximos pasos posibles

1. **Noticias y X en tiempo real para Grok.** Es su ventaja más clara frente a otros modelos. La API de xAI tiene herramientas de búsqueda; cuando quieras usarlas, se habilitan desde `llm.extra_body` en `config.yaml` siguiendo la documentación vigente de xAI (https://docs.x.ai), que cambia seguido.
2. **Más variantes de Grok compitiendo entre sí:** distintos prompts, frecuencias o modelos, cada uno como un bot más.
3. **Selección tipo evolución:** cada mes eliminar a los peores y crear variantes de los mejores, siempre probándolas en datos que no vieron.
4. **Ejecución en testnet del exchange:** recién cuando un bot pase el veredicto después de meses de paper trading. Después, plata real chica.

## Aviso

Esto es una herramienta de investigación. La mayoría de las estrategias de trading minorista pierden plata, y que un bot gane en papel no garantiza que gane con dinero real. Antes de operar con plata real, considerá las implicancias impositivas y legales en tu país y asesorate con un profesional.

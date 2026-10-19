"""Motor de la arena. El MISMO motor corre el backtest y el paper trading en vivo,
así lo que probás en el pasado es exactamente lo que corre en el presente.

Orden en cada vela cerrada k:
  1. se ejecutan las órdenes pendientes al precio de APERTURA de k (decididas al cierre de k-1)
  2. se chequean los stop-loss con el mínimo de la vela
  3. se valúa todo al cierre y el gestor de riesgo actualiza drawdown / pérdida diaria
  4. los bots a los que les toca decidir ven datos HASTA el cierre de k (nunca el futuro)
  5. sus propuestas pasan por el gestor de riesgo y quedan como órdenes pendientes
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .broker import PaperBroker
from .core import Order, parse_minutes
from .ledger import Ledger
from .risk import RiskManager


class Market:
    """Velas alineadas de todos los símbolos, guardadas como arrays para que sea rápido."""

    def __init__(self, frames: dict[str, pd.DataFrame]):
        self.symbols = list(frames)
        self._set(frames)

    def _set(self, frames):
        self.frames = frames
        self.ts = frames[self.symbols[0]]["ts"].to_numpy(np.int64)
        self.arr = {s: {c: df[c].to_numpy(float) for c in ("open", "high", "low", "close", "volume")}
                    for s, df in frames.items()}

    def __len__(self):
        return len(self.ts)

    def append(self, new_frames: dict[str, pd.DataFrame]) -> None:
        merged = {s: pd.concat([self.frames[s], new_frames[s]]).drop_duplicates("ts").reset_index(drop=True)
                  for s in self.symbols}
        self._set(merged)

    def prices(self, k: int, field: str = "close") -> dict[str, float]:
        return {s: float(self.arr[s][field][k]) for s in self.symbols}


class MarketView:
    """Lo que ve un bot: solo datos hasta la vela k inclusive. Imposible mirar el futuro."""

    def __init__(self, market: Market, k: int):
        self._m, self.k = market, k
        self.symbols = market.symbols

    def series(self, symbol: str, field: str = "close", n: int | None = None) -> np.ndarray:
        a = self._m.arr[symbol][field][: self.k + 1]
        return a if n is None else a[-n:]

    @property
    def ts(self) -> int:
        return int(self._m.ts[self.k])


class Context:
    def __init__(self, view: MarketView, broker: PaperBroker, prices: dict[str, float], timeframe: str):
        self.market = view
        self.ts = view.ts
        self.prices = prices
        self.equity = broker.equity(prices)
        self.cash = broker.cash
        self.weights = broker.weights(prices)
        self.timeframe = timeframe


class Arena:
    def __init__(self, cfg: dict, bots: list, market: Market, ledger: Ledger,
                 luck_bots: list | None = None, record_every_min: int = 60, persist_state: bool = False):
        self.cfg = cfg
        self.market = market
        self.ledger = ledger
        self.tf = cfg["market"]["timeframe"]
        self.tf_min = parse_minutes(self.tf)
        self.bots = list(bots)
        self.luck_names = {b.name for b in (luck_bots or [])}
        self.all_bots = self.bots + list(luck_bots or [])
        c = cfg["costs"]
        self.brokers = {b.name: PaperBroker(b.name, cfg["capital"]["starting_cash"], c["fee_rate"], c["slippage_bps"])
                        for b in self.all_bots}
        self.risk = RiskManager(cfg["risk"])
        self.pending: dict[str, list[Order]] = {b.name: [] for b in self.all_bots}
        self.last_decision: dict[str, int] = {}          # bot -> timestamp (ms) de su última decisión
        self.warmup = cfg["market"]["warmup_bars"]
        self.record_every_min = max(record_every_min, self.tf_min)
        self.persist_state = persist_state
        self.halted = False
        self.benchmarks = {b.name for b in self.all_bots if getattr(b, "benchmark", False)}

    # ---------- utilidades ----------
    def _exec(self, bot: str, orders: list[Order], prices: dict[str, float], ts: int) -> None:
        br = self.brokers[bot]
        for o in orders:
            f = br.execute(o, prices[o.symbol], ts)
            if f:
                self.risk.count_fill(bot)
                if bot not in self.luck_names:
                    self.ledger.trade(f)

    def _event(self, ts, ev):
        if ev["bot"] not in self.luck_names or ev["type"] == "GLOBAL_KILL":
            self.ledger.risk_event(ts, ev)

    # ---------- ciclo por vela ----------
    def on_bar(self, k: int, live_prices: dict[str, float] | None = None) -> None:
        m = self.market
        ts = int(m.ts[k])
        opens, lows, closes = m.prices(k, "open"), m.prices(k, "low"), m.prices(k, "close")

        # 1. pendientes a la apertura de esta vela (solo backtest; en vivo ya se ejecutaron)
        for bot, orders in self.pending.items():
            if orders:
                self._exec(bot, orders, opens, ts)
                self.pending[bot] = []

        # 2. stop-loss
        for bot, br in self.brokers.items():
            for s, stop in list(br.stop_price.items()):
                if lows[s] <= stop and br.qty.get(s, 0) > 0:
                    px = min(opens[s], stop)            # si abrió por debajo (gap), sale a la apertura
                    self._exec(bot, [Order(bot, s, "sell", br.qty[s] * px * 2, f"STOP {stop:.4g}")], {s: px}, ts)

        # 3. valuación y riesgo
        if self.risk.global_kill() and not self.halted:
            self.halted = True
            self._event(ts, {"bot": "*", "type": "GLOBAL_KILL", "detail": "archivo KILL detectado: todo liquidado"})
            for bot, br in self.brokers.items():
                self._exec(bot, self.risk.flatten(bot, br, closes, "GLOBAL_KILL"), closes, ts)

        for bot, br in self.brokers.items():
            if bot in self.benchmarks:
                continue
            was_killed = self.risk.is_killed(bot)
            for ev in self.risk.update(bot, br.equity(closes), ts):
                self._event(ts, ev)
            if self.risk.is_killed(bot) and not was_killed:
                self._exec(bot, self.risk.flatten(bot, br, closes, "KILLED"), closes, ts)

        # 4-5. decisiones
        if k >= self.warmup and not self.halted:
            view = MarketView(m, k)
            for bot in self.all_bots:
                name = bot.name
                if self.risk.is_killed(name):
                    continue
                last = self.last_decision.get(name)
                if last is not None and ts - last < parse_minutes(bot.every) * 60_000:
                    continue
                self.last_decision[name] = ts
                br = self.brokers[name]
                ctx = Context(view, br, closes, self.tf)
                try:
                    prop = bot.decide(ctx)
                except Exception as e:                        # un bot roto no tumba la arena
                    self._event(ts, {"bot": name, "type": "BOT_ERROR", "detail": repr(e)[:300]})
                    continue
                if prop is None:
                    continue
                orders, events = self.risk.filter(name, prop, br, closes)
                for ev in events:
                    self._event(ts, ev)
                if name not in self.luck_names:
                    self.ledger.decision(ts, name, prop.targets, prop.reason, prop.meta)
                if live_prices is not None:
                    self._exec(name, orders, live_prices, ts)
                else:
                    self.pending[name] = orders

        # registro
        if (ts // 60_000) % self.record_every_min == 0 or live_prices is not None:
            for bot, br in self.brokers.items():
                self.ledger.equity(ts, bot, br.equity(closes), br.cash, br.exposure(closes))
        if self.persist_state:
            self.save_state()

    def run_backtest(self, start: int = 0, end: int | None = None, progress: bool = True) -> None:
        end = len(self.market) if end is None else end
        for k in range(start, end):
            self.on_bar(k)
            if progress and k % 2000 == 0:
                print(f"  vela {k}/{end}", end="\r")
        if progress:
            print()
        self.ledger.commit()

    # ---------- agregar / retirar bots (lo usa la evolución automática) ----------
    def add_bot(self, bot, luck: bool = False) -> None:
        c = self.cfg["costs"]
        self.brokers[bot.name] = PaperBroker(bot.name, self.cfg["capital"]["starting_cash"],
                                             c["fee_rate"], c["slippage_bps"])
        self.pending[bot.name] = []
        if luck:
            self.luck_names.add(bot.name)
        else:
            self.bots.append(bot)
        self.all_bots.append(bot)
        if getattr(bot, "benchmark", False):
            self.benchmarks.add(bot.name)

    def remove_bot(self, name: str) -> None:
        self.bots = [b for b in self.bots if b.name != name]
        self.all_bots = [b for b in self.all_bots if b.name != name]
        for d in (self.brokers, self.pending, self.last_decision, self.risk.state):
            d.pop(name, None)

    # ---------- estado completo (para reanudar) ----------
    def export_state(self) -> dict:
        return {
            "halted": self.halted,
            "bots": {
                b.name: {
                    "broker": self.brokers[b.name].to_dict(),
                    "risk": self.risk.state.get(b.name, {}),
                    "last_ts": self.last_decision.get(b.name),
                    "pending": [o.__dict__ for o in self.pending.get(b.name, [])],
                    "bot": b.get_state(),
                } for b in self.all_bots
            },
        }

    def import_state(self, st: dict) -> None:
        self.halted = st.get("halted", False)
        for b in self.all_bots:
            d = st.get("bots", {}).get(b.name)
            if not d:
                continue
            self.brokers[b.name].load_dict(d["broker"])
            self.risk.state[b.name] = d.get("risk", {})
            if d.get("last_ts") is not None:
                self.last_decision[b.name] = int(d["last_ts"])
            self.pending[b.name] = [Order(**o) for o in d.get("pending", [])]
            b.set_state(d.get("bot", {}))

    def save_state(self) -> None:
        for name, data in self.export_state()["bots"].items():
            self.ledger.save_state(name, data)
        self.ledger.commit()

    def load_state(self) -> bool:
        st = self.ledger.load_state()
        if not st:
            return False
        self.import_state({"bots": st})
        return True

"""Gestor de riesgo: código determinístico entre los bots y el broker.

Ninguna propuesta llega al broker sin pasar por acá. Las reglas no dependen del LLM
y no se pueden "convencer": si Grok alucina un 300% en SOL, se recorta al máximo permitido.
"""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from .broker import PaperBroker
from .core import Order, Proposal


@lru_cache(maxsize=8192)
def _day_from_index(day_index: int) -> str:
    return datetime.fromtimestamp(day_index * 86400, tz=timezone.utc).strftime("%Y-%m-%d")


def utc_day(ts_ms: int) -> str:
    return _day_from_index(int(ts_ms // 86_400_000))


class RiskManager:
    def __init__(self, cfg: dict):
        self.max_w = cfg["max_weight_per_symbol"]
        self.max_gross = cfg["max_gross_exposure"]
        self.min_notional = cfg["min_trade_notional"]
        self.threshold = cfg["rebalance_threshold"]
        self.max_trades_day = cfg["max_trades_per_day"]
        self.default_stop = cfg["default_stop_loss"]
        self.daily_loss = cfg["daily_loss_limit"]
        self.max_dd = cfg["max_drawdown_kill"]
        self.kill_file = Path(cfg.get("kill_file", "KILL"))
        self.state: dict[str, dict] = {}

    DEFAULTS = {"day": None, "day_start_equity": None, "trades_today": 0,
                "halted_today": False, "killed": False, "peak_equity": 0.0}

    def _st(self, bot: str) -> dict:
        st = self.state.get(bot)
        if st is None or len(st) < len(self.DEFAULTS):       # completar estados viejos o nuevos
            st = {**self.DEFAULTS, **(st or {})}
            self.state[bot] = st
        return st

    # ---------- chequeos por vela ----------
    def global_kill(self) -> bool:
        return self.kill_file.exists()

    def update(self, bot: str, equity: float, ts: int) -> list[dict]:
        """Actualiza el estado del bot y devuelve eventos de riesgo nuevos."""
        st, events = self._st(bot), []
        day = utc_day(ts)
        if st["day"] != day:
            st.update(day=day, day_start_equity=equity, trades_today=0, halted_today=False)
        st["peak_equity"] = max(st["peak_equity"], equity)

        if not st["killed"] and st["peak_equity"] > 0:
            dd = 1 - equity / st["peak_equity"]
            if dd >= self.max_dd:
                st["killed"] = True
                events.append({"bot": bot, "type": "KILLED",
                               "detail": f"drawdown {dd:.1%} >= {self.max_dd:.0%}: bot eliminado y liquidado"})

        if not st["halted_today"] and st["day_start_equity"]:
            day_ret = equity / st["day_start_equity"] - 1
            if day_ret <= -self.daily_loss:
                st["halted_today"] = True
                events.append({"bot": bot, "type": "DAILY_HALT",
                               "detail": f"pérdida diaria {day_ret:.1%}: solo puede reducir hasta mañana (UTC)"})
        return events

    def is_killed(self, bot: str) -> bool:
        return self._st(bot)["killed"]

    # ---------- filtro de propuestas ----------
    def filter(self, bot: str, proposal: Proposal, broker: PaperBroker,
               prices: dict[str, float]) -> tuple[list[Order], list[dict]]:
        st, events = self._st(bot), []
        if st["killed"]:
            return [], events

        # 1) limpiar y recortar pesos
        targets = {}
        for s in prices:
            w = proposal.targets.get(s, None)
            if w is None:
                continue                                  # el bot no opina sobre este símbolo: no tocar
            try:
                w = float(w)
            except (TypeError, ValueError):
                events.append({"bot": bot, "type": "INVALID", "detail": f"peso inválido para {s}: {w!r}"})
                continue
            if w != w:                                    # NaN
                continue
            clipped = min(max(w, 0.0), self.max_w)
            if abs(clipped - w) > 1e-9:
                events.append({"bot": bot, "type": "CLIPPED", "detail": f"{s}: {w:.2f} -> {clipped:.2f}"})
            targets[s] = clipped

        current = broker.weights(prices)
        full = {s: targets.get(s, current.get(s, 0.0)) for s in prices}
        gross = sum(full.values())
        if gross > self.max_gross:
            k = self.max_gross / gross
            targets = {s: w * k for s, w in targets.items()}
            events.append({"bot": bot, "type": "SCALED", "detail": f"exposición {gross:.2f} -> {self.max_gross:.2f}"})

        # 2) si está frenado por pérdida diaria, solo puede reducir
        if st["halted_today"]:
            targets = {s: min(w, current.get(s, 0.0)) for s, w in targets.items()}

        # 3) convertir a órdenes (ventas primero para liberar efectivo)
        equity = broker.equity(prices)
        sells, buys = [], []
        for s, tgt in targets.items():
            cur = current.get(s, 0.0)
            delta = tgt - cur
            closing = tgt == 0 and cur > 0
            if not closing and abs(delta) < self.threshold:
                continue
            notional = abs(delta) * equity
            if not closing and notional < self.min_notional:
                continue
            if delta < 0:
                sells.append(Order(bot, s, "sell", notional, proposal.reason))
            elif delta > 0:
                stop = proposal.stops.get(s) or self.default_stop
                stop = min(max(float(stop), 0.005), 0.5)
                buys.append(Order(bot, s, "buy", notional, proposal.reason, stop))

        # 4) límite de operaciones diarias (las ventas/reducciones siempre se permiten)
        room = max(self.max_trades_day - st["trades_today"], 0)
        if len(buys) > room:
            events.append({"bot": bot, "type": "TRADE_LIMIT",
                           "detail": f"{len(buys) - room} compras descartadas por límite diario"})
            buys = buys[:room]
        return sells + buys, events

    def count_fill(self, bot: str) -> None:
        self._st(bot)["trades_today"] += 1

    @staticmethod
    def flatten(bot: str, broker: PaperBroker, prices: dict[str, float], reason: str) -> list[Order]:
        return [Order(bot, s, "sell", q * prices[s] * 2, reason)       # *2: asegura vender todo
                for s, q in list(broker.qty.items()) if q > 0]

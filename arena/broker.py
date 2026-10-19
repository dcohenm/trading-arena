"""Broker simulado (paper): una cuenta independiente por bot, con comisiones y slippage.

Solo spot, sin apalancamiento y sin cortos. El efectivo nunca puede quedar negativo.
"""
from __future__ import annotations

from .core import Fill, Order

DUST_USD = 1.0   # restos menores a 1 USDT se liquidan completos


class PaperBroker:
    def __init__(self, bot: str, cash: float, fee_rate: float, slippage_bps: float):
        self.bot = bot
        self.cash = float(cash)
        self.fee_rate = fee_rate
        self.slip = slippage_bps / 10_000
        self.qty: dict[str, float] = {}
        self.avg_cost: dict[str, float] = {}
        self.stop_price: dict[str, float] = {}
        self.fees_paid = 0.0
        self.traded_notional = 0.0
        self.n_trades = 0

    # ---------- valuación ----------
    def position_value(self, symbol: str, price: float) -> float:
        return self.qty.get(symbol, 0.0) * price

    def equity(self, prices: dict[str, float]) -> float:
        return self.cash + sum(q * prices[s] for s, q in self.qty.items() if q > 0)

    def weights(self, prices: dict[str, float]) -> dict[str, float]:
        eq = self.equity(prices)
        if eq <= 0:
            return {s: 0.0 for s in prices}
        return {s: self.position_value(s, p) / eq for s, p in prices.items()}

    def exposure(self, prices: dict[str, float]) -> float:
        return sum(self.weights(prices).values())

    # ---------- ejecución ----------
    def execute(self, order: Order, ref_price: float, ts: int) -> Fill | None:
        if order.side == "buy":
            return self._buy(order, ref_price, ts)
        return self._sell(order, ref_price, ts)

    def _buy(self, order: Order, ref: float, ts: int) -> Fill | None:
        price = ref * (1 + self.slip)
        notional = min(order.notional, self.cash / (1 + self.fee_rate))
        if notional < DUST_USD:
            return None
        qty = notional / price
        fee = notional * self.fee_rate
        held = self.qty.get(order.symbol, 0.0)
        self.avg_cost[order.symbol] = (held * self.avg_cost.get(order.symbol, 0.0) + qty * price) / (held + qty)
        self.qty[order.symbol] = held + qty
        self.cash -= notional + fee
        if order.stop:
            self.stop_price[order.symbol] = self.avg_cost[order.symbol] * (1 - order.stop)
        return self._record(order, ts, qty, price, fee)

    def _sell(self, order: Order, ref: float, ts: int) -> Fill | None:
        held = self.qty.get(order.symbol, 0.0)
        if held <= 0:
            return None
        price = ref * (1 - self.slip)
        qty = min(order.notional / price, held)
        if (held - qty) * price < DUST_USD:
            qty = held                          # cierre completo, sin restos
        if qty * price < DUST_USD and qty < held:
            return None
        proceeds = qty * price
        fee = proceeds * self.fee_rate
        self.cash += proceeds - fee
        remaining = held - qty
        if remaining <= 1e-12:
            self.qty.pop(order.symbol, None)
            self.avg_cost.pop(order.symbol, None)
            self.stop_price.pop(order.symbol, None)
        else:
            self.qty[order.symbol] = remaining
        return self._record(order, ts, qty, price, fee)

    def _record(self, order: Order, ts: int, qty: float, price: float, fee: float) -> Fill:
        self.fees_paid += fee
        self.traded_notional += qty * price
        self.n_trades += 1
        return Fill(self.bot, ts, order.symbol, order.side, qty, price, fee, order.reason)

    # ---------- persistencia (para reanudar tras un reinicio) ----------
    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in
                ("cash", "qty", "avg_cost", "stop_price", "fees_paid", "traded_notional", "n_trades")}

    def load_dict(self, d: dict) -> None:
        for k, v in d.items():
            setattr(self, k, v)

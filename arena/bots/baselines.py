"""Bots de referencia. Si un bot con IA no les gana después de costos, no aporta nada."""
from __future__ import annotations

import numpy as np

from ..core import Proposal, bars_per_year
from ..indicators import ema, realized_vol, rsi
from .base import Bot


class BuyHold(Bot):
    """Compra en partes iguales al principio y no toca nada más."""
    type = "buy_hold"
    benchmark = True          # referencia pasiva: el gestor de riesgo no la frena ni la elimina
    STATE_ATTRS = ("done",)

    def __init__(self, name, every="1d", params=None):
        super().__init__(name, every, params)
        self.done = False

    def decide(self, ctx):
        if self.done:
            return None
        self.done = True
        n = len(ctx.market.symbols)
        return Proposal({s: 1.0 / n for s in ctx.market.symbols}, stops={s: 0.5 for s in ctx.market.symbols},
                        reason="compra inicial y mantener")


class RandomBot(Bot):
    """Opera al azar. Muchos de estos forman la 'distribución de la suerte'."""
    type = "random"

    def __init__(self, name, every="4h", params=None):
        super().__init__(name, every, params)
        self.rng = np.random.default_rng(self.params.get("seed", 0))

    def get_state(self):
        return {"rng": self.rng.bit_generator.state}

    def set_state(self, d):
        if "rng" in d:
            self.rng.bit_generator.state = d["rng"]

    def decide(self, ctx):
        syms = ctx.market.symbols
        if self.rng.random() < 0.3:
            return Proposal({s: 0.0 for s in syms}, reason="azar: afuera")
        w = self.rng.dirichlet(np.ones(len(syms))) * self.rng.uniform(0.3, 1.0)
        return Proposal({s: float(x) for s, x in zip(syms, w)}, reason="azar")


class Momentum(Bot):
    """Sigue la tendencia: si la media rápida está sobre la lenta y el precio sobre la lenta, compra.
    El tamaño se ajusta por volatilidad (más volátil = posición más chica)."""
    type = "momentum"

    def signal_weights(self, ctx) -> dict[str, float]:
        p = self.params
        fast, slow, tv = p.get("fast", 20), p.get("slow", 100), p.get("target_vol", 0.6)
        per_year = bars_per_year(ctx.timeframe)
        week = int(per_year / 52)                     # volatilidad de la última semana (estable, menos rotación)
        out = {}
        n = len(ctx.market.symbols)
        for s in ctx.market.symbols:
            c = ctx.market.series(s, n=max(slow * 5, week + 2))
            if len(c) < slow + 2:
                out[s] = 0.0
                continue
            ef, es = ema(c, fast), ema(c, slow)
            band = p.get("band", 0.01)                # histéresis: evita entrar y salir por ruido
            held = ctx.weights.get(s, 0.0) > 0.01
            if held:
                on = ef > es * (1 - band) and c[-1] > es * (1 - 2 * band)
            else:
                on = ef > es * (1 + band) and c[-1] > es
            vol = realized_vol(c, week, per_year)
            size = min(tv / vol, 1.0) / n if vol and vol == vol and vol > 0 else 0.0
            out[s] = size if on else 0.0
        return out

    def decide(self, ctx):
        return Proposal(self.signal_weights(ctx), stops={s: 0.10 for s in ctx.market.symbols},
                        reason="momentum EMA + ajuste por volatilidad")


class MeanReversion(Bot):
    """Compra caídas fuertes (RSI bajo) y vende cuando el RSI se normaliza."""
    type = "mean_reversion"

    def decide(self, ctx):
        p = self.params
        n, entry, exit_, w = p.get("rsi_len", 14), p.get("entry", 28), p.get("exit", 55), p.get("weight", 0.25)
        targets = {}
        for s in ctx.market.symbols:
            r = rsi(ctx.market.series(s, n=n * 6), n)
            held = ctx.weights.get(s, 0.0) > 0.01
            if r < entry:
                targets[s] = w
            elif held and r > exit_:
                targets[s] = 0.0
        if not targets:
            return None
        return Proposal(targets, stops={s: 0.06 for s in targets}, reason="reversión a la media (RSI)")


class Breakout(Bot):
    """Ruptura de canal (Donchian): compra cuando el precio supera el máximo de N velas
    y sale cuando perfora el mínimo de M velas. Tamaño ajustado por volatilidad."""
    type = "breakout"

    def decide(self, ctx):
        p = self.params
        n_in, n_out, tv = int(p.get("entry", 192)), int(p.get("exit", 96)), p.get("target_vol", 0.6)
        per_year = bars_per_year(ctx.timeframe)
        week = int(per_year / 52)
        n = len(ctx.market.symbols)
        targets = {}
        for s in ctx.market.symbols:
            c = ctx.market.series(s, n=max(n_in, n_out, week) + 2)
            if len(c) < max(n_in, n_out) + 2:
                continue
            held = ctx.weights.get(s, 0.0) > 0.01
            if not held and c[-1] > c[-n_in - 1:-1].max():
                vol = realized_vol(c, week, per_year)
                targets[s] = min(tv / vol, 1.0) / n if vol and vol == vol and vol > 0 else 0.0
            elif held and c[-1] < c[-n_out - 1:-1].min():
                targets[s] = 0.0
        if not targets:
            return None
        return Proposal(targets, stops={s: p.get("stop", 0.10) for s in targets}, reason="ruptura de canal")

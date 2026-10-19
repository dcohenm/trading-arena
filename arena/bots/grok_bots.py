"""Bots que usan a Grok.

- GrokTrader: Grok decide directamente los pesos de cada activo (cada pocas horas).
- GrokOverlay: una estrategia de momentum fija decide QUÉ comprar; Grok solo decide CUÁNTO
  arriesgar según el contexto (régimen de mercado, noticias si se habilita la búsqueda).

A Grok no se le pasan miles de números crudos (los LLM los manejan mal): se le pasa un resumen
de indicadores por activo. Las respuestas son JSON con esquema fijo, y si algo falla el bot
simplemente mantiene lo que tiene. Todo pasa igual por el gestor de riesgo.
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from ..core import Proposal, bars_per_year, parse_minutes
from ..indicators import ema, pct_change, realized_vol, rsi, zscore_last
from ..llm import LLMError
from .base import Bot
from .baselines import Momentum


def features(ctx) -> dict:
    tf = parse_minutes(ctx.timeframe)
    b = lambda minutes: max(1, minutes // tf)              # noqa: E731  minutos -> velas
    per_year = bars_per_year(ctx.timeframe)
    out = {}
    for s in ctx.market.symbols:
        c = ctx.market.series(s, n=b(60 * 24 * 30))
        v = ctx.market.series(s, "volume", n=b(60 * 24 * 7))
        last7 = c[-b(60 * 24 * 7):]
        e1d, e7d = ema(c, b(1440)), ema(c, b(10080))
        step = b(240)
        shape = (c[::-1][::step][:12][::-1] / c[-1] - 1) * 100   # cierres cada 4h, en % vs. ahora
        out[s] = {
            "price": round(float(c[-1]), 6),
            "ret_1h_pct": round(pct_change(c, b(60)) * 100, 2),
            "ret_4h_pct": round(pct_change(c, b(240)) * 100, 2),
            "ret_24h_pct": round(pct_change(c, b(1440)) * 100, 2),
            "ret_7d_pct": round(pct_change(c, b(10080)) * 100, 2),
            "vol_24h_ann_pct": round(realized_vol(c, b(1440), per_year) * 100, 1),
            "vol_7d_ann_pct": round(realized_vol(c, b(10080), per_year) * 100, 1),
            "dist_ema_1d_pct": round((c[-1] / e1d - 1) * 100, 2),
            "dist_ema_7d_pct": round((c[-1] / e7d - 1) * 100, 2),
            "rsi14": round(rsi(c, 14), 1),
            "volume_z": round(zscore_last(v, len(v)), 2),
            "pos_in_7d_range": round(float((c[-1] - last7.min()) / (np.ptp(last7) or 1)), 2),
            "last_12x4h_closes_pct_vs_now": [round(float(x), 2) for x in shape],
        }
    return out


def _clean(d: dict) -> dict:
    """Reemplaza NaN por None para que el JSON sea válido."""
    if isinstance(d, dict):
        return {k: _clean(v) for k, v in d.items()}
    if isinstance(d, list):
        return [_clean(v) for v in d]
    if isinstance(d, float) and d != d:
        return None
    return d


class GrokBase(Bot):
    STATE_ATTRS = ("start_equity", "peak")
    def __init__(self, name, every="4h", params=None, llm=None, risk_cfg=None, costs=None):
        super().__init__(name, every, params)
        self.llm = llm
        self.risk_cfg = risk_cfg or {}
        self.costs = costs or {}
        self.start_equity = None
        self.peak = 0.0

    def portfolio(self, ctx) -> dict:
        self.start_equity = self.start_equity or ctx.equity
        self.peak = max(self.peak, ctx.equity)
        return {
            "equity_usdt": round(ctx.equity, 2),
            "pnl_since_start_pct": round((ctx.equity / self.start_equity - 1) * 100, 2),
            "drawdown_from_peak_pct": round((1 - ctx.equity / self.peak) * 100, 2),
            "current_weights": {s: round(w, 3) for s, w in ctx.weights.items()},
            "cash_weight": round(ctx.cash / ctx.equity, 3) if ctx.equity else 1.0,
        }

    def utc(self, ctx) -> str:
        return datetime.fromtimestamp(ctx.ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


TRADER_SYSTEM = """Sos un trader cuantitativo disciplinado que gestiona una cartera spot de cripto (solo compras, sin apalancamiento ni cortos).
Cada {every} recibís un resumen de indicadores y tu cartera actual, y devolvés los pesos objetivo por activo.

Reglas:
- target_weight es la fracción del capital en ese activo (0 = sin posición). Máximo {max_w} por activo; la suma no puede superar {max_gross}. Lo que sobra queda en USDT.
- Cada operación cuesta aprox. {cost_pct}% ida (comisión + deslizamiento). Cambiar de opinión seguido destruye rentabilidad: solo cambiá pesos si tenés una razón concreta. No hacer nada es una decisión válida.
- Pensá en riesgo antes que en retorno: tamaño chico cuando hay incertidumbre o volatilidad alta.
- stop_loss_pct es la caída desde el precio promedio de compra que cierra la posición (ej. 0.06 = 6%).
- Si tenés acceso a noticias o publicaciones recientes, usalas solo si son relevantes y verificables; mencionalo en reason.
- Respondé únicamente con el JSON del esquema, con un elemento en positions por cada activo."""

OVERLAY_SYSTEM = """Sos el gestor de riesgo de una estrategia de momentum en cripto spot. La estrategia ya decide qué activos comprar; vos decidís CUÁNTO riesgo tomar en las próximas horas.
risk_multiplier: 0 = todo a USDT, 0.5 = la mitad del tamaño normal, 1 = tamaño normal. No puede superar 1.
Bajá el riesgo ante caídas bruscas, volatilidad extrema, eventos macro o noticias negativas importantes; subilo cuando el contexto acompaña.
avoid_symbols: activos a evitar por un motivo concreto (ej. hackeo, deslistado). Lista vacía si no hay.
Respondé únicamente con el JSON del esquema."""


class GrokTrader(GrokBase):
    type = "grok_trader"

    def schema(self, symbols):
        return {
            "type": "object",
            "properties": {
                "market_view": {"type": "string"},
                "positions": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "enum": symbols},
                        "target_weight": {"type": "number"},
                        "stop_loss_pct": {"type": "number"},
                        "confidence": {"type": "number"},
                        "reason": {"type": "string"},
                    },
                    "required": ["symbol", "target_weight", "stop_loss_pct", "confidence", "reason"],
                    "additionalProperties": False}},
                "risk_notes": {"type": "string"},
            },
            "required": ["market_view", "positions", "risk_notes"],
            "additionalProperties": False,
        }

    def decide(self, ctx):
        syms = ctx.market.symbols
        cost_pct = round((self.costs.get("fee_rate", 0.001) + self.costs.get("slippage_bps", 5) / 1e4) * 100, 2)
        system = TRADER_SYSTEM.format(every=self.every, max_w=self.risk_cfg.get("max_weight_per_symbol", 0.5),
                                      max_gross=self.risk_cfg.get("max_gross_exposure", 1.0), cost_pct=cost_pct)
        payload = _clean({"time": self.utc(ctx), "market": features(ctx), "portfolio": self.portfolio(ctx)})
        try:
            plan, meta = self.llm.chat_json(system, payload, self.schema(syms), "trade_plan")
        except LLMError as e:
            return Proposal({}, reason=f"sin cambios: {e}", meta={"error": str(e)})
        targets, stops, reasons = {}, {}, []
        for p in plan.get("positions", []):
            s = p.get("symbol")
            if s in syms:
                targets[s] = p.get("target_weight", 0.0)
                stops[s] = p.get("stop_loss_pct")
                reasons.append(f"{s}: {p.get('reason', '')}")
        reason = plan.get("market_view", "") + " | " + " | ".join(reasons)
        return Proposal(targets, stops={k: v for k, v in stops.items() if v}, reason=reason,
                        meta={"llm": meta, "plan": plan})


class GrokOverlay(GrokBase):
    type = "grok_overlay"
    STATE_ATTRS = ("start_equity", "peak", "last_llm_ts", "mult", "avoid", "regime", "why")

    def __init__(self, name, every="1h", params=None, llm=None, risk_cfg=None, costs=None):
        super().__init__(name, every, params, llm, risk_cfg, costs)
        self.momentum = Momentum(name + "_mom", every, params)
        self.llm_every_min = parse_minutes(self.params.get("llm_every", "6h"))
        self.last_llm_ts = None
        self.mult, self.avoid, self.regime, self.why = 0.5, [], "unknown", "sin consulta todavía"

    def schema(self, symbols):
        return {
            "type": "object",
            "properties": {
                "regime": {"type": "string", "enum": ["risk_on", "neutral", "risk_off", "crisis"]},
                "risk_multiplier": {"type": "number"},
                "avoid_symbols": {"type": "array", "items": {"type": "string", "enum": symbols}},
                "reason": {"type": "string"},
            },
            "required": ["regime", "risk_multiplier", "avoid_symbols", "reason"],
            "additionalProperties": False,
        }

    def decide(self, ctx):
        meta = {}
        due = self.last_llm_ts is None or (ctx.ts - self.last_llm_ts) >= self.llm_every_min * 60_000
        if due:
            payload = _clean({"time": self.utc(ctx), "market": features(ctx), "portfolio": self.portfolio(ctx)})
            try:
                ans, meta = self.llm.chat_json(OVERLAY_SYSTEM, payload, self.schema(ctx.market.symbols), "risk_overlay")
                self.mult = float(min(max(ans.get("risk_multiplier", 0.5), 0.0), 1.0))
                self.avoid = [s for s in ans.get("avoid_symbols", []) if s in ctx.market.symbols]
                self.regime, self.why = ans.get("regime", "unknown"), ans.get("reason", "")
                meta = {"llm": meta, "answer": ans}
            except LLMError as e:
                self.mult = min(self.mult, 0.5)          # sin información, ser conservador
                meta = {"error": str(e)}
            self.last_llm_ts = ctx.ts
        base = self.momentum.signal_weights(ctx)
        targets = {s: (0.0 if s in self.avoid else w * self.mult) for s, w in base.items()}
        return Proposal(targets, stops={s: 0.10 for s in targets},
                        reason=f"momentum x {self.mult:.2f} ({self.regime}): {self.why}", meta=meta)

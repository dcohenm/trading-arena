"""Evolución automática: cada semana el sistema crea variantes de sus mejores bots y algunos
bots nuevos al azar, los prueba sobre datos reales recientes y solo deja entrar a la arena a los
que pasan un examen sobre datos que NO se usaron para elegirlos.

Por qué así: si probás 30 variantes y te quedás con la mejor en los mismos datos, siempre vas a
encontrar una que "funciona" por casualidad. Separar los datos en dos partes (elegir en la primera,
examinar en la segunda) es la forma de no engañarse.
"""
from __future__ import annotations

import copy
import random

import pandas as pd

from .bots import bot_from_spec
from .engine import Arena, Market
from .metrics import stats_from_equity

EVERY = ["30m", "1h", "2h", "4h"]

SPACE = {   # rango de cada parámetro: (mínimo, máximo, es_entero)
    "momentum": {"fast": (12, 96, True), "slow": (96, 480, True), "band": (0.0, 0.03, False),
                 "target_vol": (0.3, 0.9, False)},
    "mean_reversion": {"rsi_len": (7, 28, True), "entry": (15, 35, True), "exit": (45, 65, True),
                       "weight": (0.1, 0.4, False)},
    "breakout": {"entry": (48, 480, True), "exit": (24, 240, True), "target_vol": (0.3, 0.9, False),
                 "stop": (0.05, 0.2, False)},
}
SHORT = {"momentum": "mom", "mean_reversion": "rev", "breakout": "brk"}


def _fix(family: str, p: dict) -> dict:
    """Respeta las restricciones lógicas entre parámetros."""
    sp = SPACE[family]
    for k, (lo, hi, is_int) in sp.items():
        v = min(max(p.get(k, (lo + hi) / 2), lo), hi)
        p[k] = int(round(v)) if is_int else round(float(v), 4)
    if family == "momentum" and p["slow"] < 2 * p["fast"]:
        p["slow"] = min(max(2 * p["fast"], sp["slow"][0]), sp["slow"][1])
        p["fast"] = min(p["fast"], p["slow"] // 2)
    if family == "breakout" and p["exit"] >= p["entry"]:
        p["exit"] = max(sp["exit"][0], p["entry"] // 2)
    if family == "mean_reversion" and p["exit"] <= p["entry"] + 10:
        p["exit"] = p["entry"] + 10
    return p


def random_spec(family: str, rng: random.Random) -> dict:
    p = {}
    for k, (lo, hi, is_int) in SPACE[family].items():
        p[k] = rng.randint(lo, hi) if is_int else rng.uniform(lo, hi)
    return {"type": family, "every": rng.choice(EVERY), "params": _fix(family, p)}


def mutate(spec: dict, rng: random.Random, strength: float = 0.25) -> dict:
    fam = spec["type"]
    p = copy.deepcopy(spec.get("params") or {})
    for k, (lo, hi, _) in SPACE[fam].items():
        if rng.random() < 0.7:
            base = p.get(k, (lo + hi) / 2)
            p[k] = base * (1 + rng.uniform(-strength, strength)) if base else rng.uniform(lo, hi) * strength
    every = spec.get("every", "1h")
    if rng.random() < 0.25:
        every = rng.choice(EVERY)
    return {"type": fam, "every": every, "params": _fix(fam, p), "parent": spec.get("name")}


class _MemLedger:
    """Registro en memoria, solo de capital (para evaluar candidatos rápido)."""

    def __init__(self):
        self.eq = []
        self.trades = 0

    def equity(self, ts, bot, equity, cash, exposure):
        self.eq.append((ts, bot, equity))

    def trade(self, f):
        self.trades += 1

    def decision(self, *a, **k): pass
    def risk_event(self, *a, **k): pass
    def commit(self): pass
    def save_state(self, *a, **k): pass


def evaluate(specs: list[dict], cfg: dict, frames: dict[str, pd.DataFrame], split_frac: float) -> pd.DataFrame:
    """Corre cada candidato sobre todo el período y mide su desempeño por separado en la parte
    de selección (antes del corte) y en la de examen (después del corte)."""
    market = Market(frames)
    split_ts = int(market.ts[int(len(market) * split_frac)])
    ppy = 365 * 24
    rows = []
    for sp in specs:
        bot = bot_from_spec({**sp, "name": sp.get("name", "cand")}, cfg)
        if bot is None:
            continue
        led = _MemLedger()
        arena = Arena(cfg, [bot], market, led, record_every_min=60)
        arena.run_backtest(progress=False)
        eq = pd.Series({ts: e for ts, _, e in led.eq}).sort_index()
        ins, oos = eq[eq.index < split_ts], eq[eq.index >= split_ts]
        a, b = stats_from_equity(ins, ppy), stats_from_equity(oos, ppy)
        rows.append({"spec": sp, "trades": led.trades,
                     "is_sharpe": a.get("sharpe", float("nan")), "is_return": a.get("return_pct", float("nan")),
                     "oos_sharpe": b.get("sharpe", float("nan")), "oos_return": b.get("return_pct", float("nan")),
                     "oos_dd": b.get("max_dd_pct", float("nan"))})
    return pd.DataFrame(rows)


def run_generation(cfg: dict, frames: dict[str, pd.DataFrame], parents: list[dict], incumbents: list[dict],
                   gen: int, seed: int, n_mutations: int = 4, n_random: int = 6, max_promote: int = 2,
                   split_frac: float = 2 / 3, log=print) -> tuple[list[dict], pd.DataFrame]:
    """Devuelve (bots que entran a la arena, tabla con todos los candidatos evaluados)."""
    rng = random.Random(seed)
    cands = []
    for par in parents:
        for _ in range(n_mutations):
            cands.append(mutate(par, rng))
    fams = list(SPACE)
    for i in range(n_random):
        cands.append(random_spec(fams[i % len(fams)], rng))
    for i, c in enumerate(cands):
        c["name"] = f"{SHORT[c['type']]}_g{gen}_{chr(97 + i)}" if i < 26 else f"{SHORT[c['type']]}_g{gen}_{i}"

    bh = {"name": "buy_and_hold", "type": "buy_hold", "every": "1d", "params": {}}
    log(f"  evaluando {len(cands)} candidatos + {len(incumbents)} bots actuales…")
    res = evaluate(cands + incumbents + [bh], cfg, frames, split_frac)
    res["name"] = [r["name"] for r in res["spec"]]
    res["role"] = ["candidato"] * len(cands) + ["actual"] * len(incumbents) + ["referencia"]
    bh_oos = res.loc[res.name == "buy_and_hold", "oos_sharpe"].iloc[0]
    floor = max(0.0, bh_oos) if bh_oos == bh_oos else 0.0

    pool = res[(res.role == "candidato") & (res.trades >= 10) & (res.is_sharpe > 0)]
    finalists = pool.sort_values("is_sharpe", ascending=False).head(6)          # elegidos SOLO con la 1ª parte
    passed = finalists[(finalists.oos_sharpe > floor) & (finalists.oos_return > 0)]  # examen en la 2ª parte
    promoted = passed.sort_values("oos_sharpe", ascending=False).head(max_promote)

    res["decision"] = "descartado"
    res.loc[res.role != "candidato", "decision"] = res.loc[res.role != "candidato", "role"]
    res.loc[res.name.isin(finalists.name), "decision"] = "finalista: no aprobó el examen"
    res.loc[res.name.isin(promoted.name), "decision"] = "promovido"
    return [r for r in promoted["spec"]], res

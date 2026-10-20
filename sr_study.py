#!/usr/bin/env python3
"""¿Funcionan los soportes, las resistencias y los números redondos?

Reglas FIJAS, escritas antes de mirar los datos (velas de 1 hora, BTC/ETH/SOL, ~3 años, costos 0,15% por lado):

Niveles: un "máximo/mínimo importante" (pivote) es una vela cuyo máximo (o mínimo) es el más alto (o bajo)
de las 24 horas anteriores y las 24 posteriores. Solo se conoce 24 horas después (no se mira el futuro).
Se usan los pivotes de los últimos 30 días.

A) REBOTE EN SOPORTE: si una vela toca el soporte más cercano (mínimo a menos de 0,3% de él) y cierra arriba,
   se compra en la apertura siguiente. Stop 1% debajo del soporte. Objetivo: la resistencia más cercana
   (o +3% si no hay). Máximo 3 días.
B) RUPTURA CON VOLUMEN: si una vela cierra arriba de la resistencia más cercana con volumen mayor a 1,5 veces
   la mediana de la última semana, se compra en la apertura siguiente. Stop 1,5% debajo de la resistencia.
   Objetivo: el doble de lo que se arriesga. Máximo 3 días.
C) NÚMEROS REDONDOS (BTC cada 5.000, ETH cada 250, SOL cada 10), comparados con niveles "de control" justo
   en el medio (BTC 2.500, 7.500…), que no son redondos:
   C1) ¿El precio se frena más al acercarse a un número redondo? (lo cruza menos en las 24 h siguientes)
   C2) ¿Después de cruzarlo hacia arriba sigue subiendo más? ¿Y al cruzarlo hacia abajo sigue bajando más?
   C3) Estrategia: comprar al cruzar hacia arriba un número redondo, stop 1% debajo, salir a las 24 h.

Control de suerte para A, B y C3: las mismas operaciones (mismos stops, objetivos y plazos) pero entrando en
momentos al azar, 300 veces. Una estrategia sirve solo si le gana a casi todas esas versiones al azar.

Uso:  python sr_study.py            (lo corre GitHub Actions)
      python sr_study.py --synthetic
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from arena.data import fetch_recent, synthetic  # noqa: E402

OUT = ROOT / "study" / "soportes"
DOCS = ROOT / "docs" / "soportes"
COINS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
ROUND_STEP = {"BTC": 5000.0, "ETH": 250.0, "SOL": 10.0}
COST = 0.0015
K = 24                  # ventana del pivote (horas de cada lado)
LOOKBACK = 24 * 30      # pivotes de los últimos 30 días
MAX_HOLD = 72
N_RANDOM = 300
LOG: list[str] = []


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG.append(line)
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "log.txt", "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


# ------------------------------------------------------------------ niveles
def pivots(x: np.ndarray, kind: str) -> np.ndarray:
    from numpy.lib.stride_tricks import sliding_window_view
    w = sliding_window_view(x, 2 * K + 1)
    ext = w.max(axis=1) if kind == "high" else w.min(axis=1)
    idx = np.where(x[K:-K] == ext)[0] + K
    return idx


def active_levels(piv_idx: np.ndarray, values: np.ndarray, t: int) -> np.ndarray:
    """Pivotes ya confirmados en la vela t (i + K <= t) y de los últimos 30 días."""
    lo = np.searchsorted(piv_idx, t - LOOKBACK)
    hi = np.searchsorted(piv_idx, t - K, side="right")
    return values[piv_idx[lo:hi]]


# ------------------------------------------------------------------ operaciones
def run_trade(o, h, l, c, e: int, stop: float, target: float | None, max_hold: int) -> tuple[float, int]:
    """Entra en la apertura de la vela e. Si en una vela se tocan stop y objetivo, se asume el stop (conservador)."""
    entry = o[e]
    end = min(e + max_hold, len(c) - 1)
    for j in range(e, end + 1):
        if l[j] <= stop:
            px = min(o[j], stop) if j > e else min(entry, stop)
            return px / entry - 1 - 2 * COST, j
        if target is not None and h[j] >= target:
            px = max(o[j], target) if j > e else target
            return px / entry - 1 - 2 * COST, j
    return c[end] / entry - 1 - 2 * COST, end


def strategy_A(o, h, l, c, v):
    ph, pl = pivots(h, "high"), pivots(l, "low")
    trades, t, n = [], LOOKBACK + K, len(c)
    while t < n - 2:
        sup = active_levels(pl, l, t)
        sup = sup[sup <= c[t]]
        if len(sup):
            S = sup.max()
            if l[t] <= S * 1.003 and c[t] > S:
                e = t + 1
                stop = S * 0.99
                res = active_levels(ph, h, t)
                res = res[res > o[e] * 1.002]
                target = res.min() if len(res) else o[e] * 1.03
                if stop < o[e] < target:
                    r, j = run_trade(o, h, l, c, e, stop, target, MAX_HOLD)
                    trades.append({"t": t, "ret": r, "stop_pct": 1 - stop / o[e], "target_pct": target / o[e] - 1, "hold": j - e + 1})
                    t = j + 1
                    continue
        t += 1
    return trades


def strategy_B(o, h, l, c, v):
    ph = pivots(h, "high")
    trades, t, n = [], LOOKBACK + K, len(c)
    vol_med = pd.Series(v).rolling(168, min_periods=100).median().to_numpy()
    while t < n - 2:
        res = active_levels(ph, h, t)
        res = res[res >= c[t - 1]]
        if len(res):
            R = res.min()
            if c[t - 1] <= R < c[t] and v[t] > 1.5 * vol_med[t]:
                e = t + 1
                stop = R * 0.985
                if o[e] > stop:
                    risk = o[e] - stop
                    target = o[e] + 2 * risk
                    r, j = run_trade(o, h, l, c, e, stop, target, MAX_HOLD)
                    trades.append({"t": t, "ret": r, "stop_pct": risk / o[e], "target_pct": 2 * risk / o[e], "hold": j - e + 1})
                    t = j + 1
                    continue
        t += 1
    return trades


def round_levels(coin: str, lo: float, hi: float, control: bool) -> np.ndarray:
    s = ROUND_STEP[coin]
    off = s / 2 if control else 0.0
    k0, k1 = math.floor((lo - off) / s), math.ceil((hi - off) / s)
    return np.array([k * s + off for k in range(k0, k1 + 1) if k * s + off > 0])


def round_events(coin, o, h, l, c, control: bool):
    """C1: acercamientos (desde abajo y desde arriba) y si se cruza en 24 h.
    C2: cruces de cierre y el retorno de las 24 h siguientes. C3: operación tras cruce hacia arriba."""
    levels = round_levels(coin, l.min(), h.max(), control)
    appr, cross, trades = [], [], []
    n = len(c)
    busy_until = -1
    for t in range(K + 1, n - 25):
        for L in levels:
            # C1 desde abajo: se acerca a menos de 0,3% sin tocarlo y venía lejos en las últimas 24 h
            if L * 0.997 <= h[t] < L and h[t - 24:t].max() < L * 0.997:
                appr.append({"side": "abajo", "crossed": bool(h[t + 1:t + 25].max() >= L)})
            if L < l[t] <= L * 1.003 and l[t - 24:t].min() > L * 1.003:
                appr.append({"side": "arriba", "crossed": bool(l[t + 1:t + 25].min() <= L)})
            # C2 cruces de cierre
            if c[t - 1] < L <= c[t]:
                cross.append({"dir": "sube", "ret24": c[t + 24] / c[t] - 1})
                if t > busy_until and o[t + 1] > L * 0.99:
                    r, j = run_trade(o, h, l, c, t + 1, L * 0.99, None, 24)
                    trades.append({"t": t, "ret": r, "stop_pct": 1 - L * 0.99 / o[t + 1], "target_pct": float("nan"), "hold": j - t})
                    busy_until = j
            elif c[t - 1] > L >= c[t]:
                cross.append({"dir": "baja", "ret24": c[t + 24] / c[t] - 1})
    return appr, cross, trades


def random_control(o, h, l, c, trades: list[dict], rng, max_hold: int, start: int) -> np.ndarray:
    """Las mismas operaciones (stops, objetivos, plazos) pero entrando en momentos al azar."""
    if not trades:
        return np.array([])
    n = len(c)
    sp = np.array([tr["stop_pct"] for tr in trades])
    tp = np.array([tr["target_pct"] for tr in trades])
    means = np.empty(N_RANDOM)
    for k in range(N_RANDOM):
        es = rng.integers(start, n - max_hold - 2, size=len(trades))
        rets = []
        for e, s_, t_ in zip(es, sp, tp):
            stop = o[e] * (1 - s_)
            target = None if t_ != t_ else o[e] * (1 + t_)
            rets.append(run_trade(o, h, l, c, e, stop, target, max_hold)[0])
        means[k] = np.mean(rets)
    return means


# ------------------------------------------------------------------ estadística
def two_prop_p(k1, n1, k2, n2):
    if min(n1, n2) == 0:
        return float("nan")
    p = (k1 + k2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2)) or 1e-12
    z = (k1 / n1 - k2 / n2) / se
    return math.erfc(abs(z) / math.sqrt(2))


def welch_p(a, b):
    a, b = np.asarray(a), np.asarray(b)
    if len(a) < 3 or len(b) < 3:
        return float("nan")
    se = math.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b)) or 1e-12
    z = (a.mean() - b.mean()) / se
    return math.erfc(abs(z) / math.sqrt(2))


def strat_summary(name, trades_by_coin, rand_by_coin, frames):
    allt = [tr for v in trades_by_coin.values() for tr in v]
    if not allt:
        return {"name": name, "n": 0}
    rets = np.array([tr["ret"] for tr in allt])
    # control al azar combinado: promedio ponderado por cantidad de operaciones de cada moneda
    w = {c: len(v) for c, v in trades_by_coin.items()}
    tot = sum(w.values())
    comb = sum(rand_by_coin[c] * w[c] / tot for c in rand_by_coin if len(rand_by_coin[c]))
    years = {}
    for coin, v in trades_by_coin.items():
        ts = frames[coin]["ts"].to_numpy()
        for tr in v:
            y = datetime.fromtimestamp(int(ts[tr["t"]]) / 1000, tz=timezone.utc).year
            years.setdefault(str(y), []).append(tr["ret"])
    return {
        "name": name, "n": int(len(rets)), "mean_net_pct": float(rets.mean() * 100),
        "win_pct": float((rets > 0).mean() * 100), "total_compound_pct": float((np.prod(1 + rets / 3) - 1) * 100),
        "random_mean_pct": float(np.mean(comb) * 100), "random_p95_pct": float(np.percentile(comb, 95) * 100),
        "pctl_vs_random": float((comb < rets.mean()).mean() * 100),
        "p_vs_random": float((comb >= rets.mean()).mean()),
        "per_coin": {c.split("/")[0]: {"n": len(v), "mean_net_pct": float(np.mean([t["ret"] for t in v]) * 100) if v else float("nan")}
                     for c, v in trades_by_coin.items()},
        "per_year": {y: {"n": len(r), "mean_net_pct": float(np.mean(r) * 100)} for y, r in sorted(years.items())},
        "avg_hold_h": float(np.mean([tr["hold"] for tr in allt])),
    }


# ------------------------------------------------------------------ reporte
def f(v, d=2, suf=""):
    return "—" if v is None or (isinstance(v, float) and not math.isfinite(v)) else f"{v:.{d}f}{suf}"


def conclusions(S: dict, R: dict) -> list[str]:
    out, thr = [], 0.05 / 3
    labels = {"A": "Rebote en soporte", "B": "Ruptura con volumen", "C3": "Comprar al cruzar un número redondo"}
    for k in ("A", "B", "C3"):
        s = S[k]
        if not s.get("n"):
            out.append(f"**{labels[k]}:** no hubo operaciones.")
            continue
        good = s["p_vs_random"] < thr and s["mean_net_pct"] > 0
        out.append(f"**{labels[k]}:** {s['n']} operaciones, {f(s['mean_net_pct'], 3)}% promedio por operación con costos "
                   f"(las mismas operaciones en momentos al azar dan {f(s['random_mean_pct'], 3)}%). "
                   + ("**Le gana claramente al azar y gana plata.** Vale la pena seguirla en vivo." if good else
                      ("Le gana al azar pero pierde plata con costos." if s["p_vs_random"] < thr else
                       f"No se distingue del azar (le ganó al {f(s['pctl_vs_random'], 0)}% de las versiones al azar; hace falta más de {100 - thr * 100:.1f}%).")))
    c1 = R["c1"]
    out.append(f"**¿El precio se frena en los números redondos?** Cerca de un número redondo lo cruzó el {f(c1['round_cross_pct'], 1)}% "
               f"de las veces; cerca de un nivel no redondo, el {f(c1['ctrl_cross_pct'], 1)}% (p={f(c1['p'], 3)}). "
               + ("Sí: hay un efecto de freno medible." if c1["p"] < 0.05 and c1["round_cross_pct"] < c1["ctrl_cross_pct"]
                  else "No se ve un efecto claro."))
    c2u, c2d = R["c2_up"], R["c2_down"]
    out.append(f"**¿Después de cruzarlo sigue de largo?** Al cruzar hacia arriba, las 24 h siguientes promediaron {f(c2u['round_pct'], 3)}% "
               f"en números redondos contra {f(c2u['ctrl_pct'], 3)}% en los de control (p={f(c2u['p'], 3)}); al cruzar hacia abajo, "
               f"{f(c2d['round_pct'], 3)}% contra {f(c2d['ctrl_pct'], 3)}% (p={f(c2d['p'], 3)}).")
    return out


def write_reports(S, R, meta):
    OUT.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    concl = conclusions(S, R)
    (OUT / "resumen.json").write_text(json.dumps({"meta": meta, "strategies": S, "round": R}, indent=1, default=float, ensure_ascii=False))
    labels = {"A": "A · Rebote en soporte", "B": "B · Ruptura con volumen", "C3": "C · Comprar al cruzar un número redondo"}
    md = ["# Soportes, resistencias y números redondos", "",
          f"Velas de 1 hora de BTC, ETH y SOL ({meta['source']}), **{meta['start']} → {meta['end']}**. Reglas fijadas antes de mirar los datos; "
          "costos de 0,15% por lado. Cada estrategia se compara con las mismas operaciones hechas en momentos al azar (300 veces).",
          "", "## Conclusiones", ""] + [f"- {c}" for c in concl] + [
          "", "## Estrategias", "",
          "| | Operaciones | Promedio por operación (con costos) | % ganadoras | Al azar: promedio | Al azar: 95% mejor | Le ganó al % del azar |",
          "|---|---:|---:|---:|---:|---:|---:|"]
    for k in ("A", "B", "C3"):
        s = S[k]
        if s.get("n"):
            md.append(f"| {labels[k]} | {s['n']} | {f(s['mean_net_pct'], 3)}% | {f(s['win_pct'], 0)}% | {f(s['random_mean_pct'], 3)}% | "
                      f"{f(s['random_p95_pct'], 3)}% | {f(s['pctl_vs_random'], 0)}% |")
    years = sorted({y for k in ("A", "B", "C3") for y in S[k].get("per_year", {})})
    md += ["", "## Por año (promedio por operación, con costos)", "", "| | " + " | ".join(years) + " |", "|---|" + "---:|" * len(years)]
    for k in ("A", "B", "C3"):
        py = S[k].get("per_year", {})
        md.append(f"| {labels[k]} | " + " | ".join(f"{f(py[y]['mean_net_pct'], 3)}% (n={py[y]['n']})" if y in py else "—" for y in years) + " |")
    md += ["", "## Por moneda", "", "| | " + " | ".join(c.split('/')[0] for c in COINS) + " |", "|---|" + "---:|" * len(COINS)]
    for k in ("A", "B", "C3"):
        pc = S[k].get("per_coin", {})
        md.append(f"| {labels[k]} | " + " | ".join(f"{f(pc[c.split('/')[0]]['mean_net_pct'], 3)}% (n={pc[c.split('/')[0]]['n']})"
                                                     if c.split('/')[0] in pc else "—" for c in COINS) + " |")
    c1 = R["c1"]
    md += ["", "## Números redondos en detalle", "",
           "| Prueba | Números redondos | Niveles de control | p-valor |", "|---|---:|---:|---:|",
           f"| Lo cruza en las 24 h siguientes al acercarse (desde abajo y arriba) | {f(c1['round_cross_pct'], 1)}% (n={c1['round_n']}) | "
           f"{f(c1['ctrl_cross_pct'], 1)}% (n={c1['ctrl_n']}) | {f(c1['p'], 3)} |",
           f"| Retorno 24 h después de cruzar hacia arriba | {f(R['c2_up']['round_pct'], 3)}% (n={R['c2_up']['round_n']}) | "
           f"{f(R['c2_up']['ctrl_pct'], 3)}% (n={R['c2_up']['ctrl_n']}) | {f(R['c2_up']['p'], 3)} |",
           f"| Retorno 24 h después de cruzar hacia abajo | {f(R['c2_down']['round_pct'], 3)}% (n={R['c2_down']['round_n']}) | "
           f"{f(R['c2_down']['ctrl_pct'], 3)}% (n={R['c2_down']['ctrl_n']}) | {f(R['c2_down']['p'], 3)} |",
           "", "## Cómo leer esto", "",
           "- **Le ganó al % del azar**: de las 300 versiones con entradas al azar (mismos stops y objetivos), a qué porcentaje superó. "
           "Como se prueban 3 estrategias, hace falta más de 98,3% para descartar la suerte.",
           "- **Niveles de control**: niveles justo a mitad de camino entre dos números redondos (BTC 2.500, 7.500…). Si los redondos fueran especiales, "
           "deberían comportarse distinto que estos.",
           "- Supuesto conservador: si en una misma vela se tocan el stop y el objetivo, se cuenta como stop.",
           "", "📊 Tablero: https://dcohenm.github.io/trading-arena/soportes/", "",
           f"*Generado el {meta['generated']} en {meta['minutes']:.0f} minutos. Todo es simulado; no es asesoramiento financiero.*"]
    (ROOT / "SOPORTES.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    import html as H
    import re
    mdh = lambda s: re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", H.escape(s))   # noqa: E731
    rows = "".join(f"<tr><td class='bot'>{labels[k]}</td><td class='num'>{S[k]['n']}</td><td class='num'><b>{f(S[k]['mean_net_pct'], 3)}%</b></td>"
                   f"<td class='num'>{f(S[k]['random_mean_pct'], 3)}%</td><td class='num'>{f(S[k]['pctl_vs_random'], 0)}%</td></tr>"
                   for k in ("A", "B", "C3") if S[k].get("n"))
    page = f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Soportes y resistencias</title><style>
:root{{--surface:#fcfcfb;--page:#f9f9f7;--ink:#0b0b0b;--ink2:#52514e;--grid:#e1e0d9;--axis:#c3c2b7;--ring:rgba(11,11,11,.10);color-scheme:light}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--surface:#1a1a19;--page:#0d0d0d;--ink:#f0efec;--ink2:#c3c2b7;--grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10);color-scheme:dark}}}}
:root[data-theme="dark"]{{--surface:#1a1a19;--page:#0d0d0d;--ink:#f0efec;--ink2:#c3c2b7;--grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10);color-scheme:dark}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--page);color:var(--ink);font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1000px;margin:0 auto;padding:28px 16px 60px}}h1{{font-size:22px;margin:0 0 4px}}h2{{font-size:15px;margin:0 0 12px}}
.sub{{color:var(--ink2);margin:0 0 20px}}.card{{background:var(--surface);border-radius:12px;box-shadow:0 0 0 1px var(--ring);padding:18px;margin-bottom:16px}}
.scroll{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;font-size:13px}}th{{color:var(--ink2);font-weight:500;text-align:left;padding:8px;border-bottom:1px solid var(--axis)}}
td{{padding:8px;border-bottom:1px solid var(--grid)}}.num{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}th.num{{text-align:right}}
.bot{{font-weight:500}}ul{{margin:0;padding-left:18px}}li{{margin-bottom:6px}}
</style></head><body><main><h1>Soportes, resistencias y números redondos</h1>
<p class="sub">BTC, ETH, SOL · velas de 1 hora · {meta['start']} → {meta['end']} · todo simulado</p>
<div class="card"><h2>Conclusiones</h2><ul>{''.join(f'<li>{mdh(c)}</li>' for c in concl)}</ul></div>
<div class="card"><h2>Estrategias contra el azar</h2><div class="scroll"><table><thead><tr><th></th><th class="num">Operaciones</th>
<th class="num">Promedio con costos</th><th class="num">Mismas operaciones al azar</th><th class="num">Le ganó al % del azar</th></tr></thead>
<tbody>{rows}</tbody></table></div></div></main></body></html>"""
    (DOCS / "index.html").write_text(page, encoding="utf-8")
    log("Reportes escritos: SOPORTES.md, study/soportes/, docs/soportes/index.html")


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", action="store_true")
    a = ap.parse_args()
    import shutil
    shutil.rmtree(OUT, ignore_errors=True)
    t0 = time.time()
    days = 3 * 365 + 40
    if a.synthetic:
        frames = synthetic(COINS, days * 24, "1h", seed=21)
        frames = {c: df.assign(close=df.close * m, open=df.open * m, high=df.high * m, low=df.low * m)
                  for (c, df), m in zip(frames.items(), (1.5, 1.0, 1.0))}
        source = "datos SINTÉTICOS"
    else:
        frames, source = fetch_recent(["coinbase", "okx", "bingx"], COINS, "1h", days, min_coverage=0.9, log=log)
    log(f"{len(frames[COINS[0]])} velas de 1 h por moneda ({source})")
    rng = np.random.default_rng(7)
    S = {"A": {}, "B": {}, "C3": {}}
    tr = {k: {} for k in S}
    rnd = {k: {} for k in S}
    appr_r, appr_c, cross_r, cross_c = [], [], [], []
    for coin in COINS:
        df = frames[coin]
        o, h, l, c, v = (df[x].to_numpy(float) for x in ("open", "high", "low", "close", "volume"))
        base = coin.split("/")[0]
        tr["A"][coin] = strategy_A(o, h, l, c, v)
        tr["B"][coin] = strategy_B(o, h, l, c, v)
        ar, cr, t3 = round_events(base, o, h, l, c, control=False)
        ac, cc, _ = round_events(base, o, h, l, c, control=True)
        tr["C3"][coin] = t3
        appr_r += ar; appr_c += ac; cross_r += cr; cross_c += cc
        for k, mh in (("A", MAX_HOLD), ("B", MAX_HOLD), ("C3", 24)):
            rnd[k][coin] = random_control(o, h, l, c, tr[k][coin], rng, mh, LOOKBACK + K)
        log(f"  {base}: A {len(tr['A'][coin])} · B {len(tr['B'][coin])} · C {len(t3)} operaciones; "
            f"{len(ar)} acercamientos y {len(cr)} cruces de números redondos")
        pd.DataFrame([{**x, "coin": base, "strategy": k, "ts": int(df.ts.iloc[x["t"]])} for k in S for x in tr[k][coin]]) \
            .to_csv(OUT / f"operaciones_{base}.csv", index=False)
    for k in S:
        S[k] = strat_summary(k, tr[k], rnd[k], frames)
    kr = sum(x["crossed"] for x in appr_r); kc = sum(x["crossed"] for x in appr_c)
    up_r = [x["ret24"] for x in cross_r if x["dir"] == "sube"]; up_c = [x["ret24"] for x in cross_c if x["dir"] == "sube"]
    dn_r = [x["ret24"] for x in cross_r if x["dir"] == "baja"]; dn_c = [x["ret24"] for x in cross_c if x["dir"] == "baja"]
    R = {"c1": {"round_n": len(appr_r), "ctrl_n": len(appr_c),
                "round_cross_pct": kr / max(len(appr_r), 1) * 100, "ctrl_cross_pct": kc / max(len(appr_c), 1) * 100,
                "p": two_prop_p(kr, len(appr_r), kc, len(appr_c))},
         "c2_up": {"round_n": len(up_r), "ctrl_n": len(up_c), "round_pct": float(np.mean(up_r) * 100) if up_r else float("nan"),
                   "ctrl_pct": float(np.mean(up_c) * 100) if up_c else float("nan"), "p": welch_p(up_r, up_c)},
         "c2_down": {"round_n": len(dn_r), "ctrl_n": len(dn_c), "round_pct": float(np.mean(dn_r) * 100) if dn_r else float("nan"),
                     "ctrl_pct": float(np.mean(dn_c) * 100) if dn_c else float("nan"), "p": welch_p(dn_r, dn_c)}}
    day = lambda t: datetime.fromtimestamp(int(t) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")   # noqa: E731
    ts = frames[COINS[0]]["ts"]
    meta = {"start": day(ts.iloc[LOOKBACK + K]), "end": day(ts.iloc[-1]), "source": source, "minutes": (time.time() - t0) / 60,
            "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    write_reports(S, R, meta)
    for line in conclusions(S, R):
        log(line)


if __name__ == "__main__":
    try:
        main()
    except BaseException as e:
        import traceback
        log(f"✗ {e.__class__.__name__}: {e}")
        with open(OUT / "log.txt", "a", encoding="utf-8") as fh:
            fh.write(traceback.format_exc())
        raise

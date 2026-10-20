#!/usr/bin/env python3
"""Estudio del "carry" de futuros perpetuos (cobrar la tasa de financiamiento sin apostar al precio).

La estrategia: por cada moneda, comprar al contado y vender la misma cantidad en futuros perpetuos.
Si el precio sube o baja, una pata compensa a la otra. Lo que queda es la tasa de financiamiento
("funding"): cuando el mercado está optimista, los que compran futuros con apalancamiento les pagan
a los que venden. Esa es la ganancia que se busca.

Reglas FIJAS, decididas antes de ver los resultados (nada se optimiza sobre estos datos):
  A) "Siempre": carry permanente en BTC, ETH y SOL, un tercio cada una.
  B) "Solo cuando paga": se entra en una moneda cuando su funding promedio de los últimos 7 días
     supera 10% anual y se sale cuando baja de 0%. Decisión diaria con datos del día anterior.

Supuestos (conservadores):
  - capital = 1,5 veces lo invertido (el 0,5 extra queda como garantía de los futuros)
  - costos por entrar o salir: comisión + deslizamiento en las DOS patas
  - el capital que no se usa no rinde nada (en la realidad podría estar en bonos del Tesoro)
  - se ignora la diferencia de precio entre contado y futuro al entrar y salir (en promedio juega
    a favor de la regla B, así que ignorarla es conservador)

Uso:  python carry.py              datos reales (lo corre GitHub Actions)
      python carry.py --synthetic  prueba con datos inventados
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from arena.data import fetch_recent                          # noqa: E402
from arena.metrics import probabilistic_sharpe, stats_from_equity  # noqa: E402

OUT = ROOT / "study" / "carry"
DOCS = ROOT / "docs" / "carry"
DAY = 86_400_000
COINS = ["BTC", "ETH", "SOL"]
SOURCES = [  # (exchange en ccxt, símbolo del perpetuo, nombre para mostrar)
    ("binanceusdm", "{c}/USDT:USDT", "Binance"),
    ("bybit", "{c}/USDT:USDT", "Bybit"),
    ("hyperliquid", "{c}/USDC:USDC", "Hyperliquid"),
    ("krakenfutures", "{c}/USD:USD", "Kraken Futures"),
    ("okx", "{c}/USDT:USDT", "OKX"),
]
CFG = {
    "days": 3 * 365 + 30,
    "margin": 0.5,                 # garantía extra para los futuros, como fracción de lo invertido
    "spot_fee": 0.0010,            # 0,10% comisión contado
    "perp_fee": 0.0005,            # 0,05% comisión futuros
    "slippage": 0.0003,            # 0,03% por pata
    "rebalance_band": 0.10,        # rebalancear si una posición se desvía más de 10% de su objetivo
    "enter_apr": 0.10,             # regla B: entrar si el funding de 7 días supera 10% anual
    "exit_apr": 0.0,               # regla B: salir si baja de 0%
    "lookback": 7,
    "risk_free": 0.045,            # referencia aproximada: letras del Tesoro de EE.UU. (~4,5% anual)
    "liq_move": 0.40,              # suba diaria que pondría en riesgo la garantía del 50%
    "min_coverage": 0.85,
}
LOG: list[str] = []


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG.append(line)


# ------------------------------------------------------------------ datos
def fetch_funding(ex_id: str, symbol: str, since: int) -> pd.Series:
    """Historia de funding (tasa por período) paginando hacia adelante."""
    import ccxt
    ex = getattr(ccxt, ex_id)({"enableRateLimit": True})
    ex.load_markets()
    if symbol not in ex.markets:
        raise ValueError(f"{symbol} no existe")
    rows, cur, now = {}, since, ex.milliseconds()
    for _ in range(2000):
        batch = ex.fetch_funding_rate_history(symbol, since=cur, limit=None if ex_id == "krakenfutures" else
                                              {"binanceusdm": 1000, "bybit": 200, "hyperliquid": 500, "okx": 100}.get(ex_id))
        new = [(b["timestamp"], b["fundingRate"]) for b in batch
               if b.get("timestamp") and b["timestamp"] >= cur and b.get("fundingRate") is not None]
        if not new:
            break
        for t, r in new:
            rows[int(t)] = float(r)
        nxt = max(t for t, _ in new) + 1
        if nxt <= cur or nxt > now:
            break
        cur = nxt
    if not rows:
        raise ValueError("sin datos")
    return pd.Series(rows).sort_index()


def to_daily(s: pd.Series) -> pd.Series:
    """Suma de las tasas de cada día (UTC): el funding cobrado ese día por cada dólar invertido."""
    idx = pd.to_datetime(s.index, unit="ms", utc=True).floor("D")
    return pd.Series(s.values, index=idx).groupby(level=0).sum()


def load_sources(since: int, start_day: pd.Timestamp, end_day: pd.Timestamp) -> dict:
    out = {}
    expected = (end_day - start_day).days
    for ex_id, tpl, label in SOURCES:
        try:
            cols, cov = {}, {}
            for c in COINS:
                d = to_daily(fetch_funding(ex_id, tpl.format(c=c), since))
                d = d[(d.index >= start_day) & (d.index < end_day)]
                cols[c], cov[c] = d, len(d) / expected
            df = pd.DataFrame(cols)
            apr = (df.mean() * 365).abs().max()
            if apr > 1.0:
                raise ValueError(f"funding anualizado de {apr:.0%}: no parece una tasa, se descarta")
            ok = min(cov.values()) >= CFG["min_coverage"]
            log(f"  {label}: cobertura " + ", ".join(f"{c} {v:.0%}" for c, v in cov.items())
                + ("" if ok else "  → insuficiente, solo como referencia"))
            out[label] = {"funding": df, "coverage": cov, "full": ok, "id": ex_id}
        except Exception as e:
            log(f"  {label}: no disponible ({e.__class__.__name__}: {str(e)[:120]})")
    return out


# ------------------------------------------------------------------ simulación
def simulate(funding: pd.DataFrame, prices: pd.DataFrame, rule: str, enter: float = None,
             exit_: float = None) -> tuple[pd.Series, dict]:
    """Simulación diaria. El funding del día d se cobra sobre la posición decidida al cierre de d-1."""
    enter = CFG["enter_apr"] if enter is None else enter
    exit_ = CFG["exit_apr"] if exit_ is None else exit_
    leg_cost = CFG["spot_fee"] + CFG["perp_fee"] + 2 * CFG["slippage"]
    days = funding.index
    coins = list(funding.columns)
    w = 1 / len(coins)
    cap = 10_000.0
    notional = dict.fromkeys(coins, 0.0)
    active = dict.fromkeys(coins, False)
    eq, costs_paid, funding_earned, trades = [], 0.0, 0.0, 0
    days_active = dict.fromkeys(coins, 0)
    roll = funding.rolling(CFG["lookback"], min_periods=CFG["lookback"]).mean() * 365
    px = prices.reindex(days).ffill()
    for i, d in enumerate(days):
        # 1) cobrar (o pagar) el funding del día sobre la posición que se tenía
        f = funding.loc[d].fillna(0.0)
        pnl = sum(notional[c] * f[c] for c in coins)
        cap += pnl
        funding_earned += pnl
        # 2) las cantidades quedan fijas: el valor de la posición se mueve con el precio
        if i > 0:
            for c in coins:
                p0, p1 = px[c].iloc[i - 1], px[c].iloc[i]
                if notional[c] and p0 == p0 and p1 == p1 and p0 > 0:
                    notional[c] *= p1 / p0
        # 3) decidir la posición de mañana con datos hasta hoy
        for c in coins:
            has_data = funding[c].iloc[: i + 1].notna().sum() >= CFG["lookback"]
            if rule == "siempre":
                active[c] = bool(has_data)
            else:
                r = roll[c].iloc[i]
                if r == r:
                    if not active[c] and r > enter:
                        active[c] = True
                    elif active[c] and r < exit_:
                        active[c] = False
                else:
                    active[c] = False
            days_active[c] += active[c]
        for c in coins:
            target = (w * cap / (1 + CFG["margin"])) if active[c] else 0.0
            cur = notional[c]
            if target == 0 and cur == 0:
                continue
            if target > 0 and cur > 0 and abs(target - cur) <= CFG["rebalance_band"] * target:
                continue
            delta = abs(target - cur)
            cost = delta * leg_cost
            cap -= cost
            costs_paid += cost
            trades += 1
            notional[c] = target
        eq.append(cap)
    # al final se cierra todo
    close_cost = sum(notional.values()) * leg_cost
    eq[-1] -= close_cost
    costs_paid += close_cost
    return pd.Series(eq, index=days), {"costs": costs_paid, "funding": funding_earned, "trades": trades,
                                       "pct_days_active": {c: days_active[c] / len(days) * 100 for c in coins}}


def metrics(eq: pd.Series) -> dict:
    st = stats_from_equity(eq, 365)
    r = eq.pct_change().dropna()
    st["psr"] = probabilistic_sharpe(r.to_numpy())
    ex = r - CFG["risk_free"] / 365
    st["sharpe_excess"] = float(ex.mean() / ex.std(ddof=1) * math.sqrt(365)) if ex.std(ddof=1) > 0 else float("nan")
    st["psr_excess"] = probabilistic_sharpe(ex.to_numpy())
    m = eq.resample("ME").last().pct_change().dropna()
    st["worst_month_pct"] = float(m.min() * 100) if len(m) else float("nan")
    st["pct_months_negative"] = float((m < 0).mean() * 100) if len(m) else float("nan")
    return st


def yearly(eq: pd.Series) -> dict:
    out = {}
    for y, g in eq.groupby(eq.index.year):
        prev = eq[eq.index < g.index[0]]
        base = prev.iloc[-1] if len(prev) else 10_000.0
        out[str(y)] = (g.iloc[-1] / base - 1) * 100
    return out


def rf_curve(index) -> pd.Series:
    return pd.Series(10_000 * (1 + CFG["risk_free"] / 365) ** np.arange(1, len(index) + 1), index=index)


# ------------------------------------------------------------------ reporte
def pct(v, signed=True, d=1):
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    return f"{v:+.{d}f}%" if signed else f"{v:.{d}f}%"


def num(v):
    return "—" if v is None or (isinstance(v, float) and not math.isfinite(v)) else f"{v:.2f}"


def verdict(A: dict, B: dict, rf_total: float) -> list[str]:
    out = []
    best_name, best = max((("A (siempre)", A), ("B (solo cuando paga)", B)), key=lambda kv: kv[1]["sharpe_excess"])
    beats_rf = best["return_pct"] > rf_total
    solid = best["psr_excess"] >= 0.95
    if beats_rf and solid:
        out.append(f"**Sí hay algo:** la regla {best_name} rindió {pct(best['return_pct'])} contra {pct(rf_total)} de los "
                   f"bonos del Tesoro, con una caída máxima de {pct(best['max_dd_pct'], False)} y una ventaja sobre los bonos "
                   f"estadísticamente sólida ({best['psr_excess'] * 100:.0f}%). Vale la pena seguir mirándolo, sabiendo los riesgos de abajo.")
    elif beats_rf:
        out.append(f"**Le ganó a los bonos, pero sin evidencia sólida:** la regla {best_name} rindió {pct(best['return_pct'])} "
                   f"contra {pct(rf_total)} de los bonos del Tesoro, pero la ventaja no es estadísticamente firme "
                   f"({best['psr_excess'] * 100:.0f}%, hace falta 95%).")
    else:
        out.append(f"**No conviene:** ni siempre ni eligiendo cuándo, el carry le ganó a dejar la plata en bonos del Tesoro "
                   f"({pct(best['return_pct'])} contra {pct(rf_total)}), y con bastante más riesgo.")
    return out


def write_report(src: dict, primary: str, res: dict, prices: pd.DataFrame, meta: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    P = res[primary]
    A, B = P["A"]["m"], P["B"]["m"]
    rf = rf_curve(P["A"]["eq"].index)
    rf_total = (rf.iloc[-1] / 10_000 - 1) * 100
    concl = verdict(A, B, rf_total)

    fund = src[primary]["funding"]
    fy = (fund.groupby(fund.index.year).mean() * 365 * 100).round(1)
    neg = (fund < 0).groupby(fund.index.year).mean() * 100
    recent = fund[fund.index >= fund.index[-1] - pd.Timedelta(days=180)]
    recent_apr = (recent.mean() * 365 * 100).round(1)
    if (recent_apr < CFG["risk_free"] * 100).all():
        concl.append(f"**Hoy:** en los últimos 6 meses el funding promedio fue " +
                     ", ".join(f"{c} {v:.1f}%" for c, v in recent_apr.items()) +
                     f" anual, por debajo de los ~{CFG['risk_free'] * 100:.1f}% de los bonos. En este momento no paga el riesgo.")
    else:
        concl.append(f"**Hoy:** en los últimos 6 meses el funding promedio fue " +
                     ", ".join(f"{c} {v:.1f}%" for c, v in recent_apr.items()) + " anual.")
    big = (prices.pct_change() > CFG["liq_move"]).sum()
    liq = {c: int(v) for c, v in big.items()}
    concl.append("**Riesgo que no aparece en el número:** si el exchange quiebra (como FTX en 2022) se puede perder todo lo depositado. "
                 + (f"Además hubo {sum(liq.values())} días con subas de más de {CFG['liq_move'] * 100:.0f}% en un día "
                    f"({', '.join(f'{c}: {v}' for c, v in liq.items() if v)}), que con esta garantía hubieran forzado a cerrar la posición."
                    if sum(liq.values()) else f"No hubo días con subas de más de {CFG['liq_move'] * 100:.0f}%, que hubieran puesto en riesgo la garantía."))

    others = {k: v for k, v in res.items() if k != primary}
    md = ["# Estudio de carry (tasa de financiamiento)", "",
          f"Período: **{meta['start']} → {meta['end']}** ({meta['days']} días). Datos de funding de **{primary}**; precios de contado de {meta['price_source']}.",
          "", "## Conclusiones", ""] + [f"- {c}" for c in concl] + [
          "", "## Resultados", "",
          "| | Retorno | Retorno anual | Sharpe | Caída máx. | Peor mes | Meses negativos | Operaciones |",
          "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name, k in (("A · siempre", "A"), ("B · solo cuando paga", "B")):
        m, x = P[k]["m"], P[k]["x"]
        md.append(f"| {name} | {pct(m['return_pct'])} | {pct(m['cagr_pct'])} | {num(m['sharpe'])} | {pct(m['max_dd_pct'], False)} | "
                  f"{pct(m['worst_month_pct'])} | {pct(m['pct_months_negative'], False, 0)} | {x['trades']} |")
    md.append(f"| Bonos del Tesoro (~{CFG['risk_free'] * 100:.1f}% anual, aprox.) | {pct(rf_total)} | {pct(CFG['risk_free'] * 100)} | — | 0% | — | 0% | — |")
    md += ["", "## Funding promedio por año (% anual)", "", "| | " + " | ".join(COINS) + " | Días con funding negativo |",
           "|---|" + "---:|" * (len(COINS) + 1)]
    for y in fy.index:
        md.append(f"| {y} | " + " | ".join(f"{fy.loc[y, c]:.1f}" for c in COINS) + f" | {neg.loc[y].mean():.0f}% |")
    ya, yb = P["A"]["y"], P["B"]["y"]
    md += ["", "## Retorno por año", "", "| | " + " | ".join(ya) + " |", "|---|" + "---:|" * len(ya),
           "| A · siempre | " + " | ".join(pct(v) for v in ya.values()) + " |",
           "| B · solo cuando paga | " + " | ".join(pct(yb.get(k)) for k in ya) + " |"]
    if others:
        md += ["", "## Otros exchanges (para ver si el resultado se repite)", "",
               "| Exchange | Cobertura | A · siempre | B · solo cuando paga |", "|---|---:|---:|---:|"]
        for k, v in others.items():
            cov = min(src[k]["coverage"].values()) * 100
            md.append(f"| {k} | {cov:.0f}% | {pct(v['A']['m']['return_pct'])} | {pct(v['B']['m']['return_pct'])} |")
    sens = P.get("sens", {})
    if sens:
        md += ["", "## Sensibilidad de la regla B (no es optimización: solo muestra si el resultado depende del umbral)", "",
               "| Entrar si funding > | Retorno | Sharpe |", "|---|---:|---:|"]
        for th, m in sens.items():
            md.append(f"| {th:.0f}% anual | {pct(m['return_pct'])} | {num(m['sharpe'])} |")
    md += ["", "## Supuestos", "",
           f"- Capital = 1,5 veces lo invertido (50% extra como garantía de los futuros). Lo que no se invierte no rinde nada.",
           f"- Costos por entrar o salir de una moneda: {(CFG['spot_fee'] + CFG['perp_fee'] + 2 * CFG['slippage']) * 100:.2f}% (comisión y deslizamiento en las dos patas). Rebalanceo cuando una posición se desvía más de 10%.",
           "- Reglas fijadas antes de mirar los resultados. Nada se ajustó sobre estos datos.",
           "- No incluye: quiebra o congelamiento del exchange, cambios en las reglas del exchange, impuestos.",
           "", "📊 Tablero: https://dcohenm.github.io/trading-arena/carry/", "",
           f"*Generado el {meta['generated']}. Todo es simulado; no es asesoramiento financiero.*"]
    (ROOT / "CARRY.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    for k, v in src.items():
        v["funding"].round(8).to_csv(OUT / f"funding_diario_{v['id']}.csv")
    summary = {"meta": meta, "primary": primary, "config": CFG,
               "results": {k: {s: {"metrics": v[s]["m"], "extra": v[s]["x"], "yearly": v[s]["y"]} for s in ("A", "B")}
                           for k, v in res.items()},
               "funding_apr_by_year": fy.to_dict(), "recent_apr": recent_apr.to_dict(), "big_up_days": liq}
    (OUT / "resumen.json").write_text(json.dumps(summary, indent=1, default=float, ensure_ascii=False))
    (OUT / "log.txt").write_text("\n".join(LOG) + "\n", encoding="utf-8")
    write_html(P, rf, concl, meta, primary, fy)
    log("Reportes escritos: CARRY.md, study/carry/, docs/carry/index.html")


def write_html(P, rf, concl, meta, primary, fy):
    import html as H
    import re
    shutil.copyfile(ROOT / "arena" / "assets" / "chart.umd.js", DOCS / "chart.umd.js")
    ea, eb = P["A"]["eq"], P["B"]["eq"]
    step = max(1, len(ea) // 1000)
    data = {"labels": [d.strftime("%Y-%m-%d") for d in ea.index[::step]],
            "series": [{"name": "A · siempre", "light": "#2a78d6", "dark": "#3987e5", "data": ea.iloc[::step].round(2).tolist()},
                       {"name": "B · solo cuando paga", "light": "#eb6834", "dark": "#d95926", "data": eb.iloc[::step].round(2).tolist()},
                       {"name": "Bonos del Tesoro (aprox.)", "light": "#898781", "dark": "#898781", "dash": True,
                        "data": rf.iloc[::step].round(2).tolist()}]}
    md = lambda s: re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", H.escape(s))   # noqa: E731
    rows = ""
    for name, k in (("A · siempre", "A"), ("B · solo cuando paga", "B")):
        m = P[k]["m"]
        rows += (f"<tr><td class='bot'>{name}</td><td class='num'>{pct(m['return_pct'])}</td><td class='num'>{pct(m['cagr_pct'])}</td>"
                 f"<td class='num'>{num(m['sharpe'])}</td><td class='num'>{pct(m['max_dd_pct'], False)}</td>"
                 f"<td class='num'>{pct(m['worst_month_pct'])}</td></tr>")
    rf_total = (rf.iloc[-1] / 10_000 - 1) * 100
    rows += (f"<tr><td class='bot'>Bonos del Tesoro (aprox.)</td><td class='num'>{pct(rf_total)}</td>"
             f"<td class='num'>{pct(CFG['risk_free'] * 100)}</td><td class='num'>—</td><td class='num'>0.0%</td><td class='num'>—</td></tr>")
    frows = "".join(f"<tr><td class='bot'>{y}</td>" + "".join(f"<td class='num'>{fy.loc[y, c]:.1f}%</td>" for c in COINS) + "</tr>"
                    for y in fy.index)
    page = f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Estudio de carry</title><script src="chart.umd.js"></script>
<style>
:root{{--surface:#fcfcfb;--page:#f9f9f7;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;--ring:rgba(11,11,11,.10);color-scheme:light}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--surface:#1a1a19;--page:#0d0d0d;--ink:#f0efec;--ink2:#c3c2b7;--grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10);color-scheme:dark}}}}
:root[data-theme="dark"]{{--surface:#1a1a19;--page:#0d0d0d;--ink:#f0efec;--ink2:#c3c2b7;--grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10);color-scheme:dark}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--page);color:var(--ink);font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1000px;margin:0 auto;padding:28px 16px 60px}}h1{{font-size:22px;margin:0 0 4px}}h2{{font-size:15px;margin:0 0 12px}}
.sub{{color:var(--ink2);margin:0 0 20px}}.card{{background:var(--surface);border-radius:12px;box-shadow:0 0 0 1px var(--ring);padding:18px;margin-bottom:16px}}
.chart{{position:relative;height:340px}}.scroll{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{color:var(--ink2);font-weight:500;text-align:left;padding:8px;border-bottom:1px solid var(--axis)}}td{{padding:8px;border-bottom:1px solid var(--grid)}}
.num{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}th.num{{text-align:right}}.bot{{font-weight:500;white-space:nowrap}}
ul{{margin:0;padding-left:18px}}li{{margin-bottom:6px}}
</style></head><body><main>
<h1>Estudio de carry</h1><p class="sub">Funding de {H.escape(primary)} · {meta['start']} → {meta['end']} · todo simulado</p>
<div class="card"><h2>Conclusiones</h2><ul>{''.join(f'<li>{md(c)}</li>' for c in concl)}</ul></div>
<div class="card"><h2>Capital (USDT, arrancando con 10.000)</h2><div class="chart"><canvas id="eq"></canvas></div></div>
<div class="card"><h2>Resultados</h2><div class="scroll"><table><thead><tr><th></th><th class="num">Retorno</th><th class="num">Anual</th>
<th class="num">Sharpe</th><th class="num">Caída máx.</th><th class="num">Peor mes</th></tr></thead><tbody>{rows}</tbody></table></div></div>
<div class="card"><h2>Funding promedio por año (% anual)</h2><div class="scroll"><table><thead><tr><th></th>
{''.join(f"<th class='num'>{c}</th>" for c in COINS)}</tr></thead><tbody>{frows}</tbody></table></div></div>
</main><script>
const D={json.dumps(data)};
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const dark=()=>css('--surface')==='#1a1a19';let ch;
function draw(){{if(ch)ch.destroy();
ch=new Chart(document.getElementById('eq'),{{type:'line',data:{{labels:D.labels,datasets:D.series.map(s=>({{label:s.name,data:s.data,
borderColor:dark()?s.dark:s.light,backgroundColor:dark()?s.dark:s.light,borderWidth:2,borderDash:s.dash?[4,4]:[],pointRadius:0,pointHoverRadius:4}}))}},
options:{{responsive:true,maintainAspectRatio:false,animation:false,interaction:{{mode:'index',intersect:false}},
plugins:{{legend:{{position:'bottom',labels:{{color:css('--ink2'),boxWidth:10,boxHeight:10,usePointStyle:true,pointStyle:'rectRounded'}}}},
tooltip:{{backgroundColor:css('--surface'),titleColor:css('--ink'),bodyColor:css('--ink2'),borderColor:css('--axis'),borderWidth:1,
callbacks:{{label:c=>' '+c.dataset.label+': '+Math.round(c.raw).toLocaleString('es-AR')}}}}}},
scales:{{x:{{ticks:{{color:css('--muted'),maxTicksLimit:7,maxRotation:0}},grid:{{display:false}},border:{{color:css('--axis')}}}},
y:{{ticks:{{color:css('--muted'),callback:v=>Math.round(v).toLocaleString('es-AR')}},grid:{{color:css('--grid')}},border:{{display:false}}}}}}}}}});}}
draw();matchMedia('(prefers-color-scheme: dark)').addEventListener('change',draw);
new MutationObserver(draw).observe(document.documentElement,{{attributes:true,attributeFilter:['data-theme']}});
</script></body></html>"""
    (DOCS / "index.html").write_text(page, encoding="utf-8")


# ------------------------------------------------------------------ main
def run_all(src: dict, prices: pd.DataFrame) -> dict:
    res = {}
    for k, v in src.items():
        f = v["funding"]
        out = {}
        for rule, key in (("siempre", "A"), ("cuando_paga", "B")):
            eq, x = simulate(f, prices, rule)
            out[key] = {"eq": eq, "x": x, "m": metrics(eq), "y": yearly(eq)}
        out["sens"] = {th * 100: metrics(simulate(f, prices, "cuando_paga", enter=th)[0]) for th in (0.05, 0.10, 0.20)}
        res[k] = out
    return res


def synthetic_inputs(days: int):
    rng = np.random.default_rng(3)
    idx = pd.date_range("2023-10-19", periods=days, freq="D", tz="UTC")
    regime = np.repeat(rng.choice([0.25, 0.08, -0.02], size=days // 60 + 1), 60)[:days]
    f = pd.DataFrame({c: regime / 365 * m + rng.normal(0, 0.0004, days)
                      for c, m in zip(COINS, (1.0, 1.1, 1.3))}, index=idx)
    p = pd.DataFrame({c: 100 * np.exp(np.cumsum(rng.normal(0, 0.03, days))) for c in COINS}, index=idx)
    return {"Sintético": {"funding": f, "coverage": dict.fromkeys(COINS, 1.0), "full": True, "id": "sintetico"}}, p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", action="store_true")
    a = ap.parse_args()
    now = pd.Timestamp.now(tz="UTC").floor("D")
    start = now - pd.Timedelta(days=CFG["days"])
    if a.synthetic:
        src, prices = synthetic_inputs(CFG["days"])
        price_source = "datos sintéticos"
        log("⚠ Datos sintéticos: solo prueba que el estudio funciona.")
    else:
        log("Bajando historia de funding…")
        src = load_sources(int(start.value // 1_000_000), start, now)
        log("Bajando precios diarios de contado…")
        frames, price_source = fetch_recent(["coinbase", "okx", "bingx"], [f"{c}/USDT" for c in COINS], "1d",
                                            CFG["days"], min_coverage=0.9, log=log)
        prices = pd.DataFrame({c: frames[f"{c}/USDT"].set_index(pd.to_datetime(frames[f"{c}/USDT"].ts, unit="ms", utc=True)).close
                               for c in COINS})
    full = [k for k, v in src.items() if v["full"]]
    if not full:
        raise SystemExit("Ningún exchange dio historia suficiente de funding. Ver log.")
    primary = full[0]
    res = run_all({k: src[k] for k in full}, prices)
    f = src[primary]["funding"]
    meta = {"start": f.index[0].strftime("%Y-%m-%d"), "end": f.index[-1].strftime("%Y-%m-%d"), "days": len(f),
            "price_source": price_source, "sources_ok": full,
            "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    write_report(src, primary, res, prices, meta)
    for line in (ROOT / "CARRY.md").read_text().split("## Resultados")[0].splitlines()[4:]:
        if line.strip():
            log(line)


if __name__ == "__main__":
    try:
        main()
    except BaseException as e:                     # dejar registro aunque falle (se sube al repositorio)
        import traceback
        log(f"✗ {e.__class__.__name__}: {e}")
        LOG.append(traceback.format_exc())
        raise
    finally:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "log.txt").write_text("\n".join(LOG) + "\n", encoding="utf-8")

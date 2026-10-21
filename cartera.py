#!/usr/bin/env python3
"""Bot de cartera: diversificar, filtrar por tendencia una vez por mes y rebalancear.

Reglas FIJAS (decididas antes de mirar los datos):
  Cartera base:  45% S&P 500 (SPY) · 15% acciones de países desarrollados (EFA) · 25% bonos del Tesoro
                 cortos (SHY) · 10% oro (GLD) · 5% bitcoin (BTC).
  Filtro de tendencia: el último día hábil de cada mes, cada activo de riesgo (SPY, EFA, GLD, BTC) se mantiene
                 solo si su cierre está por encima del promedio de sus últimos 10 cierres de fin de mes.
                 Si está por debajo, esa parte pasa a bonos cortos (SHY) hasta el mes siguiente.
  Ejecución:     al cierre del primer día hábil del mes siguiente (nunca con el mismo precio que generó la señal).
  Costos:        0,25% por operación sobre lo que se compra o vende (también se muestra 0,50%).

Se compara contra: la misma cartera sin filtro, comprar y mantener el S&P 500, y la clásica 60/40
(60% S&P 500, 40% bonos AGG), todas rebalanceadas una vez por mes con los mismos costos.

Además, una prueba aparte para quien aporta todos los meses: ¿conviene comprar el primer día del mes o esperar
a una caída corta del S&P 500 (3% a 10% debajo del máximo de 10 días) dentro del mes?

Uso:  python cartera.py study            estudio histórico (GitHub Actions)
      python cartera.py signal           señal del mes (GitHub Actions, una vez por mes)
      python cartera.py study --synthetic
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from arena.metrics import probabilistic_sharpe, stats_from_equity  # noqa: E402

OUT = ROOT / "study" / "cartera"
DOCS = ROOT / "docs" / "cartera"
WEIGHTS = {"SPY": 0.45, "EFA": 0.15, "SHY": 0.25, "GLD": 0.10, "BTC-USD": 0.05}
RISKY = ["SPY", "EFA", "GLD", "BTC-USD"]
SAFE = "SHY"
NAMES = {"SPY": "Acciones EE.UU. (S&P 500)", "EFA": "Acciones de países desarrollados", "SHY": "Bonos del Tesoro cortos",
         "GLD": "Oro", "BTC-USD": "Bitcoin", "AGG": "Bonos (para la 60/40)"}
CEDEAR = {"SPY": "SPY", "EFA": "EFA", "SHY": "SHY", "GLD": "GLD", "BTC-USD": "BTC (exchange) o un ETF de bitcoin"}
SMA_MONTHS = 10
COSTS = [0.0025, 0.0050]
LOG: list[str] = []


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG.append(line)
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "log.txt", "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


# ------------------------------------------------------------------ datos
def load_closes(tickers: list[str], start="2003-01-01") -> pd.DataFrame:
    import yfinance as yf
    raw = yf.download(tickers, start=start, auto_adjust=True, progress=False, threads=True)["Close"]
    raw.index = pd.to_datetime(raw.index).tz_localize(None)
    return raw


def synthetic_closes(tickers, start="2003-01-01") -> pd.DataFrame:
    rng = np.random.default_rng(3)
    idx = pd.bdate_range(start, "2026-10-19")
    params = {"SPY": (0.0004, 0.012), "EFA": (0.0002, 0.013), "SHY": (0.0001, 0.001), "GLD": (0.0003, 0.011),
              "BTC-USD": (0.002, 0.04), "AGG": (0.00015, 0.003)}
    df = pd.DataFrame({t: 100 * np.exp(np.cumsum(rng.normal(*params[t], len(idx)))) for t in tickers}, index=idx)
    df.loc[df.index < "2014-09-17", "BTC-USD"] = np.nan
    df.loc[df.index < "2004-11-18", "GLD"] = np.nan
    return df


def prepare(closes: pd.DataFrame) -> pd.DataFrame:
    """Calendario del S&P 500; bitcoin (que opera los fines de semana) toma su último precio disponible."""
    cal = closes["SPY"].dropna().index
    return closes.reindex(closes.index.union(cal)).ffill(limit=5).reindex(cal)


def month_end_signals(px: pd.DataFrame) -> pd.DataFrame:
    """Para cada fin de mes: True si el activo está arriba de su promedio de 10 fines de mes (NaN si no hay datos)."""
    me = px.groupby(px.index.to_period("M")).tail(1)
    sma = me.rolling(SMA_MONTHS, min_periods=SMA_MONTHS).mean()
    sig = (me > sma).astype(float).where(sma.notna())
    sig.index.name = "date"
    return sig


def targets(sig_row: pd.Series, avail: pd.Series, mode: str, base: dict[str, float]) -> dict[str, float]:
    w = {}
    for a, x in base.items():
        if a == SAFE or (mode == "fija" and a not in RISKY):
            w[a] = w.get(a, 0) + x
            continue
        if not avail.get(a, False):                       # sin historia todavía: esa parte va a bonos cortos
            w[SAFE] = w.get(SAFE, 0) + x
            continue
        if mode == "tendencia" and not (sig_row.get(a, 0) == 1):
            w[SAFE] = w.get(SAFE, 0) + x
        else:
            w[a] = w.get(a, 0) + x
    return w


# ------------------------------------------------------------------ simulación
def simulate(px: pd.DataFrame, base: dict[str, float], mode: str, cost: float, start) -> tuple[pd.Series, pd.DataFrame]:
    rets = px.pct_change().fillna(0.0)
    sig = month_end_signals(px)
    me_dates = list(sig.index)
    days = px.index
    exec_dates = {}                                        # fecha de ejecución -> fecha de señal
    for d in me_dates:
        nxt = days[days > d]
        if len(nxt):
            exec_dates[nxt[0]] = d
    vals = None
    eq, hist = [], []
    for day in days[days >= start]:
        if vals is not None:
            vals = {a: v * (1 + rets.at[day, a]) for a, v in vals.items()}
        if day in exec_dates:
            sd = exec_dates[day]
            if mode == "tendencia":                        # hace falta el promedio de 10 meses para decidir
                avail = sig.loc[sd].notna()
            else:                                          # sin filtro: alcanza con que el activo ya exista
                avail = pd.Series({a: bool(px.loc[:sd, a].notna().any()) for a in base})
            tgt = targets(sig.loc[sd], avail, mode, base)
            equity = sum(vals.values()) if vals else 100_000.0
            cur = vals or {}
            turnover = sum(abs(tgt.get(a, 0) * equity - cur.get(a, 0)) for a in set(tgt) | set(cur))
            equity -= turnover * cost
            vals = {a: tgt[a] * equity for a in tgt if tgt[a] > 0}
            hist.append({"date": day, **{a: round(tgt.get(a, 0), 4) for a in base}})
        if vals is not None:
            eq.append((day, sum(vals.values())))
    return pd.Series(dict(eq)), pd.DataFrame(hist)


def dca_test(spy: pd.Series, start) -> dict:
    """Aporte mensual de 1.000: el primer día hábil del mes vs. esperar una caída corta dentro del mes."""
    s = spy[spy.index >= start].dropna()
    hi10 = spy.rolling(10).max().reindex(s.index)
    units_a = units_b = 0.0
    n = 0
    for _, g in s.groupby(s.index.to_period("M")):
        units_a += 1000 / g.iloc[0]
        depth = 1 - g / hi10.loc[g.index]
        hit = g[(depth >= 0.03) & (depth <= 0.10)]
        units_b += 1000 / (hit.iloc[0] if len(hit) else g.iloc[-1])
        n += 1
    last = s.iloc[-1]
    return {"months": n, "invested": n * 1000, "final_first_day": units_a * last, "final_wait_dip": units_b * last,
            "diff_pct": (units_b / units_a - 1) * 100}


def stats(eq: pd.Series) -> dict:
    s = stats_from_equity(eq.dropna(), 252)
    s["psr"] = probabilistic_sharpe(eq.pct_change().dropna().to_numpy())
    dd = eq / eq.cummax() - 1
    under = dd < 0
    longest, run = 0, 0
    for u in under:
        run = run + 1 if u else 0
        longest = max(longest, run)
    s["longest_dd_months"] = longest / 21
    yr = yearly(eq)
    s["worst_year_pct"] = min(yr.values()) if yr else float("nan")
    return s


def yearly(eq: pd.Series) -> dict:
    out = {}
    for y, g in eq.groupby(eq.index.year):
        prev = eq[eq.index < g.index[0]]
        base = prev.iloc[-1] if len(prev) else g.iloc[0]
        out[str(y)] = (g.iloc[-1] / base - 1) * 100
    return out


# ------------------------------------------------------------------ reporte del estudio
def f(v, d=1, suf=""):
    return "—" if v is None or (isinstance(v, float) and not math.isfinite(v)) else f"{v:.{d}f}{suf}"


def study(synthetic: bool):
    shutil.rmtree(OUT, ignore_errors=True)
    t0 = time.time()
    tickers = list(WEIGHTS) + ["AGG"]
    raw = synthetic_closes(tickers) if synthetic else load_closes(tickers)
    src = "datos SINTÉTICOS" if synthetic else "Yahoo Finance (precios ajustados por dividendos)"
    px = prepare(raw)
    log("Primer dato por activo: " + ", ".join(f"{t} {px[t].first_valid_index().date()}" for t in tickers))
    # arranca cuando todos los activos centrales (salvo bitcoin) tienen 10 meses de historia
    core = [t for t in tickers if t != "BTC-USD"]
    sig = month_end_signals(px)
    ok = sig[core].notna().all(axis=1)
    start = px.index[px.index > ok[ok].index[0]][0]
    log(f"La simulación arranca el {start.date()} (cuando todos tienen 10 meses de historia)")
    no_btc = {k: v for k, v in WEIGHTS.items() if k != "BTC-USD"}
    no_btc[SAFE] += WEIGHTS["BTC-USD"]
    variants = {
        "tendencia": (WEIGHTS, "tendencia"), "fija": (WEIGHTS, "fija"),
        "tendencia_sin_btc": (no_btc, "tendencia"), "fija_sin_btc": (no_btc, "fija"),
        "spy": ({"SPY": 1.0}, "fija"), "6040": ({"SPY": 0.6, "AGG": 0.4}, "fija"),
    }
    curves, R, hists = {}, {}, {}
    for name, (base, mode) in variants.items():
        eq, h = simulate(px, base, mode, COSTS[0], start)
        curves[name], hists[name] = eq, h
        R[name] = {"all": stats(eq), "yearly": yearly(eq)}
        if name in ("tendencia", "fija"):
            eq2, _ = simulate(px, base, mode, COSTS[1], start)
            R[name]["all_hicost"] = stats(eq2)
        log(f"  {name}: {R[name]['all']['cagr_pct']:.1f}% anual, caída máx. {R[name]['all']['max_dd_pct']:.0f}%")
    # tiempo fuera del mercado y operaciones del filtro
    h = hists["tendencia"]
    time_on = {a: float((h[a] > 0).mean() * 100) for a in RISKY if a in h}
    switches = int(((h[RISKY] > 0).astype(int).diff().abs().sum()).sum())
    D = dca_test(px["SPY"], start)
    R["dca"] = D
    R["trend_time_on_pct"] = time_on
    R["trend_switches"] = switches
    for k, v in hists.items():
        v.to_csv(OUT / f"pesos_{k}.csv", index=False)
    meta = {"start": start.strftime("%Y-%m-%d"), "end": px.index[-1].strftime("%Y-%m-%d"), "source": src,
            "minutes": (time.time() - t0) / 60, "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    (OUT / "resumen.json").write_text(json.dumps({"meta": meta, "weights": WEIGHTS, "results": R}, indent=1,
                                                 default=float, ensure_ascii=False))
    write_study_report(R, curves, meta)
    return R


def study_conclusions(R) -> list[str]:
    t, fx, spy, b6 = R["tendencia"]["all"], R["fija"]["all"], R["spy"]["all"], R["6040"]["all"]
    out = [f"**Cartera con filtro de tendencia:** {f(t['cagr_pct'])}% anual, caída máxima {f(t['max_dd_pct'], 0)}%, peor año "
           f"{f(t['worst_year_pct'])}%, Sharpe {f(t['sharpe'], 2)}.",
           f"**Comparada con:** la misma cartera sin filtro {f(fx['cagr_pct'])}% anual (caída máx. {f(fx['max_dd_pct'], 0)}%); "
           f"el S&P 500 solo {f(spy['cagr_pct'])}% anual (caída máx. {f(spy['max_dd_pct'], 0)}%); la 60/40 {f(b6['cagr_pct'])}% anual "
           f"(caída máx. {f(b6['max_dd_pct'], 0)}%)."]
    dd_cut = 1 - t["max_dd_pct"] / spy["max_dd_pct"] if spy["max_dd_pct"] else float("nan")
    ret_gap = t["cagr_pct"] - spy["cagr_pct"]
    out.append(f"**En una frase:** el filtro {'recortó' if dd_cut > 0 else 'no recortó'} la peor caída en un {f(dd_cut * 100, 0)}% respecto del "
               f"S&P 500, a cambio de {f(abs(ret_gap))} puntos {'menos' if ret_gap < 0 else 'más'} de retorno por año. "
               + ("Su relación retorno/riesgo (Sharpe) fue mejor que la del S&P 500." if t["sharpe"] > spy["sharpe"] else
                  "Su relación retorno/riesgo (Sharpe) no fue mejor que la del S&P 500."))
    tb, fb = R["tendencia_sin_btc"]["all"], R["fija_sin_btc"]["all"]
    out.append(f"**¿Cuánto aporta el 5% en bitcoin?** Con bitcoin: {f(t['cagr_pct'])}% anual; sin bitcoin: {f(tb['cagr_pct'])}% anual "
               f"(caída máx. {f(t['max_dd_pct'], 0)}% vs {f(tb['max_dd_pct'], 0)}%). Bitcoin entra recién en 2015, cuando tiene 10 meses de historia; "
               "su efecto depende muchísimo de lo que hizo en esos años y no hay garantía de que se repita.")
    D = R["dca"]
    out.append(f"**Aportes mensuales:** esperar una caída corta dentro del mes en vez de comprar el primer día cambió el resultado final en "
               f"{f(D['diff_pct'], 2)}% en {D['months']} meses. " + ("Una diferencia mínima: no vale la pena complicarse." if abs(D["diff_pct"]) < 1
                                                                       else "Una diferencia apreciable."))
    return out


def write_study_report(R, curves, meta):
    DOCS.mkdir(parents=True, exist_ok=True)
    concl = study_conclusions(R)
    labels = {"tendencia": "Cartera con filtro de tendencia", "fija": "Misma cartera sin filtro",
              "tendencia_sin_btc": "Con filtro, sin bitcoin", "fija_sin_btc": "Sin filtro, sin bitcoin",
              "spy": "S&P 500 solo", "6040": "60/40 clásica"}
    md = ["# Bot de cartera: estudio de 20 años", "",
          f"Período **{meta['start']} → {meta['end']}** ({meta['source']}). Incluye la crisis de 2008, el COVID en 2020 y 2022. "
          f"Rebalanceo mensual, costos de {COSTS[0] * 100:.2f}% por operación.", "",
          "**Cartera base:** " + " · ".join(f"{NAMES[a]} {w * 100:.0f}%" for a, w in WEIGHTS.items()), "",
          "## Conclusiones", ""] + [f"- {c}" for c in concl] + [
          "", "## Resultados", "", "| | Retorno anual | Caída máx. | Peor año | Sharpe | Meses en caída (más largo) |", "|---|---:|---:|---:|---:|---:|"]
    for k in labels:
        s = R[k]["all"]
        md.append(f"| {labels[k]} | {f(s['cagr_pct'])}% | {f(s['max_dd_pct'], 0)}% | {f(s['worst_year_pct'])}% | {f(s['sharpe'], 2)} | {f(s['longest_dd_months'], 0)} |")
    for k in ("tendencia", "fija"):
        s = R[k]["all_hicost"]
        md.append(f"| {labels[k]} (costos {COSTS[1] * 100:.1f}%) | {f(s['cagr_pct'])}% | {f(s['max_dd_pct'], 0)}% | {f(s['worst_year_pct'])}% | {f(s['sharpe'], 2)} | {f(s['longest_dd_months'], 0)} |")
    yrs = list(R["tendencia"]["yearly"])
    md += ["", "## Por año (%)", "", "| | " + " | ".join(yrs) + " |", "|---|" + "---:|" * len(yrs)]
    for k in ("tendencia", "fija", "spy", "6040"):
        md.append(f"| {labels[k]} | " + " | ".join(f(R[k]['yearly'].get(y), 0) for y in yrs) + " |")
    md += ["", "## El filtro en la práctica", "",
           "Porcentaje del tiempo que cada activo estuvo dentro de la cartera: " +
           ", ".join(f"{NAMES[a]} {f(v, 0)}%" for a, v in R["trend_time_on_pct"].items()) +
           f". Entradas y salidas en total: {R['trend_switches']} en {len(yrs)} años (unas {R['trend_switches'] / max(len(yrs), 1):.1f} por año).",
           "", "## Cómo leer esto", "",
           "- **Caída máxima**: lo peor que habrías visto desde un máximo hasta un mínimo. Es lo que hace que la gente abandone.",
           "- **Meses en caída**: el período más largo sin recuperar el máximo anterior.",
           "- El filtro no busca ganar más: busca perder menos en las crisis para poder sostener la inversión.",
           "- Supuestos: impuestos no incluidos; el bitcoin se modela con su precio en dólares; los CEDEARs pueden tener diferencias de precio con el original.",
           "", "📊 Tablero: https://dcohenm.github.io/trading-arena/cartera/", "",
           f"*Generado el {meta['generated']}. Todo es simulado; no es asesoramiento financiero.*"]
    (ROOT / "CARTERA.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    write_study_html(R, curves, concl, meta, labels)
    log("Reportes escritos: CARTERA.md, study/cartera/, docs/cartera/index.html")


def write_study_html(R, curves, concl, meta, labels):
    import html as H
    import re
    shutil.copyfile(ROOT / "arena" / "assets" / "chart.umd.js", DOCS / "chart.umd.js")
    mdh = lambda s: re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", H.escape(s))   # noqa: E731
    pal = {"tendencia": ("#2a78d6", "#3987e5"), "fija": ("#eb6834", "#d95926"), "6040": ("#1baf7a", "#199e70"), "spy": ("#898781", "#898781")}
    wk = {k: curves[k].resample("W").last() for k in pal}
    idx = wk["tendencia"].index
    data = {"labels": [d.strftime("%Y-%m-%d") for d in idx],
            "series": [{"name": labels[k], "light": pal[k][0], "dark": pal[k][1], "dash": k == "spy",
                        "data": [None if x != x else round(float(x)) for x in wk[k].reindex(idx).values]} for k in pal],
            "dd": [{"name": labels[k], "light": pal[k][0], "dark": pal[k][1], "dash": k == "spy",
                    "data": [None if x != x else round(float(x), 1) for x in ((wk[k] / wk[k].cummax() - 1) * 100).reindex(idx).values]} for k in pal]}
    rows = "".join(f"<tr><td class='bot'>{labels[k]}</td><td class='num'>{f(R[k]['all']['cagr_pct'])}%</td><td class='num'>{f(R[k]['all']['max_dd_pct'], 0)}%</td>"
                   f"<td class='num'>{f(R[k]['all']['worst_year_pct'])}%</td><td class='num'>{f(R[k]['all']['sharpe'], 2)}</td></tr>" for k in labels)
    signal_card = ""
    sj = DOCS / "senal.json"
    if sj.exists():
        s = json.loads(sj.read_text())
        trs = "".join(f"<tr><td class='bot'>{NAMES[a]}</td><td>{'✓ en tendencia' if s['trend'].get(a) == 1 else ('— sin datos' if s['trend'].get(a) is None else '✗ debajo del promedio')}</td>"
                      f"<td class='num'><b>{s['targets'].get(a, 0) * 100:.0f}%</b></td></tr>" for a in WEIGHTS)
        signal_card = (f"<div class='card'><h2>Señal de {H.escape(s['month_label'])}</h2><p class='sub' style='margin:0 0 10px'>Con precios al {s['signal_date']}. "
                       f"Ejecutar el primer día hábil del mes.</p><div class='scroll'><table><thead><tr><th>Activo</th><th>Filtro</th><th class='num'>Peso objetivo</th></tr></thead>"
                       f"<tbody>{trs}</tbody></table></div></div>")
    page = f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bot de cartera</title><script src="chart.umd.js"></script><style>
:root{{--surface:#fcfcfb;--page:#f9f9f7;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;--ring:rgba(11,11,11,.10);color-scheme:light}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--surface:#1a1a19;--page:#0d0d0d;--ink:#f0efec;--ink2:#c3c2b7;--grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10);color-scheme:dark}}}}
:root[data-theme="dark"]{{--surface:#1a1a19;--page:#0d0d0d;--ink:#f0efec;--ink2:#c3c2b7;--grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10);color-scheme:dark}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--page);color:var(--ink);font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1000px;margin:0 auto;padding:28px 16px 60px}}h1{{font-size:22px;margin:0 0 4px}}h2{{font-size:15px;margin:0 0 12px}}
.sub{{color:var(--ink2);margin:0 0 20px}}.card{{background:var(--surface);border-radius:12px;box-shadow:0 0 0 1px var(--ring);padding:18px;margin-bottom:16px}}
.chart{{position:relative;height:320px}}.chart.s{{height:220px}}.scroll{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{color:var(--ink2);font-weight:500;text-align:left;padding:8px;border-bottom:1px solid var(--axis)}}td{{padding:8px;border-bottom:1px solid var(--grid)}}
.num{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}th.num{{text-align:right}}.bot{{font-weight:500}}ul{{margin:0;padding-left:18px}}li{{margin-bottom:8px}}
</style></head><body><main><h1>Bot de cartera</h1><p class="sub">Diversificación + filtro de tendencia mensual · {meta['start']} → {meta['end']} · simulado</p>
{signal_card}
<div class="card"><h2>Conclusiones del estudio</h2><ul>{''.join(f'<li>{mdh(c)}</li>' for c in concl)}</ul></div>
<div class="card"><h2>Capital (USD, desde 100.000)</h2><div class="chart"><canvas id="eq"></canvas></div></div>
<div class="card"><h2>Caída desde el máximo (%)</h2><div class="chart s"><canvas id="dd"></canvas></div></div>
<div class="card"><h2>Resultados</h2><div class="scroll"><table><thead><tr><th></th><th class="num">Anual</th><th class="num">Caída máx.</th><th class="num">Peor año</th><th class="num">Sharpe</th></tr></thead>
<tbody>{rows}</tbody></table></div></div></main><script>
const D={json.dumps(data)};const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const dark=()=>css('--surface')==='#1a1a19';const C=[];
function mk(id,series,fmt){{return new Chart(document.getElementById(id),{{type:'line',data:{{labels:D.labels,datasets:series.map(s=>({{label:s.name,data:s.data,
borderColor:dark()?s.dark:s.light,backgroundColor:dark()?s.dark:s.light,borderWidth:2,borderDash:s.dash?[4,4]:[],pointRadius:0,pointHoverRadius:4,spanGaps:true}}))}},
options:{{responsive:true,maintainAspectRatio:false,animation:false,interaction:{{mode:'index',intersect:false}},
plugins:{{legend:{{position:'bottom',labels:{{color:css('--ink2'),boxWidth:10,boxHeight:10,usePointStyle:true,pointStyle:'rectRounded'}}}},
tooltip:{{backgroundColor:css('--surface'),titleColor:css('--ink'),bodyColor:css('--ink2'),borderColor:css('--axis'),borderWidth:1,callbacks:{{label:c=>' '+c.dataset.label+': '+fmt(c.raw)}}}}}},
scales:{{x:{{ticks:{{color:css('--muted'),maxTicksLimit:8,maxRotation:0}},grid:{{display:false}},border:{{color:css('--axis')}}}},
y:{{ticks:{{color:css('--muted'),maxTicksLimit:6,callback:fmt}},grid:{{color:css('--grid')}},border:{{display:false}}}}}}}}}});}}
function draw(){{C.forEach(c=>c.destroy());C.length=0;C.push(mk('eq',D.series,v=>Math.round(v).toLocaleString('es-AR')));C.push(mk('dd',D.dd,v=>v.toFixed(0)+'%'));}}
draw();matchMedia('(prefers-color-scheme: dark)').addEventListener('change',draw);
new MutationObserver(draw).observe(document.documentElement,{{attributes:true,attributeFilter:['data-theme']}});
</script></body></html>"""
    (DOCS / "index.html").write_text(page, encoding="utf-8")


# ------------------------------------------------------------------ señal mensual
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def signal(synthetic: bool, create_issue: bool):
    raw = synthetic_closes(list(WEIGHTS)) if synthetic else load_closes(list(WEIGHTS), start="2023-01-01")
    px = prepare(raw)
    today = px.index[-1]
    sig = month_end_signals(px)
    # usar el último fin de mes YA CERRADO (si hoy es fin de mes todavía abierto, el anterior)
    closed = sig[sig.index.to_period("M") < pd.Timestamp(datetime.now(timezone.utc).date()).to_period("M")]
    sd = closed.index[-1]
    row = closed.loc[sd]
    avail = row.notna()
    tgt = targets(row, avail, "tendencia", WEIGHTS)
    me = px.groupby(px.index.to_period("M")).tail(1)
    sma = me.rolling(SMA_MONTHS).mean()
    dist = {a: float(me.loc[sd, a] / sma.loc[sd, a] - 1) * 100 if pd.notna(sma.loc[sd, a]) else None for a in WEIGHTS}
    nxt = (sd + pd.offsets.MonthBegin(1))
    label = f"{MESES[nxt.month - 1]} {nxt.year}"
    prev_path = DOCS / "senal.json"
    prev = json.loads(prev_path.read_text()) if prev_path.exists() else None
    out = {"signal_date": sd.strftime("%Y-%m-%d"), "month_label": label,
           "trend": {a: (None if pd.isna(row.get(a)) else int(row.get(a))) for a in WEIGHTS},
           "targets": {a: round(tgt.get(a, 0), 4) for a in WEIGHTS}, "distance_pct": dist,
           "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    DOCS.mkdir(parents=True, exist_ok=True)
    if prev and prev.get("signal_date") == out["signal_date"]:
        log(f"La señal de {label} ya estaba generada; no se repite el aviso.")
        create_issue = False
    changes = []
    if prev:
        for a in WEIGHTS:
            o, n = prev["targets"].get(a, 0), out["targets"][a]
            if abs(o - n) > 1e-6:
                changes.append(f"{NAMES[a]}: {o * 100:.0f}% → {n * 100:.0f}%")
    prev_path.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    hist = DOCS / "senales.csv"
    pd.DataFrame([{"signal_date": out["signal_date"], **{a: out["targets"][a] for a in WEIGHTS}}]) \
        .to_csv(hist, mode="a", header=not hist.exists(), index=False)
    lines = [f"# Señal de cartera: {label}", "", f"Con precios de cierre al **{out['signal_date']}**. "
             "Ejecutar el primer día hábil del mes (no hace falta que sea exacto).", "",
             "| Activo | Instrumento (ETF de EE.UU.) | Filtro de tendencia | Distancia al promedio de 10 meses | Peso objetivo |",
             "|---|---|---|---:|---:|"]
    for a in WEIGHTS:
        tr = out["trend"][a]
        st = "— sin datos" if tr is None else ("✓ arriba del promedio" if tr == 1 else "✗ debajo: va a bonos cortos")
        if a == SAFE:
            st = "siempre"
        d = dist[a]
        lines.append(f"| {NAMES[a]} | {CEDEAR[a]} | {st} | {'' if d is None else f'{d:+.1f}%'} | **{out['targets'][a] * 100:.0f}%** |")
    lines += ["", "**Cambios respecto del mes anterior:** " + ("; ".join(changes) if changes else ("ninguno" if prev else "primera señal")), "",
              "**Qué hacer:** llevar la cartera a esos porcentajes. Si los cambios son menores a 2-3 puntos, se pueden ignorar para ahorrar costos. "
              "Si hacés un aporte este mes, usalo para acercarte a los porcentajes en vez de vender.", "",
              "*Desde Argentina: fijate en tu broker si hay CEDEAR de cada ETF; si alguno no está, se puede usar uno equivalente "
              "(por ejemplo, para bonos cortos, un fondo o instrumento en dólares de corto plazo).*", "",
              "*Generado automáticamente. Es una regla mecánica para uso propio, no asesoramiento financiero.*"]
    body = "\n".join(lines)
    (ROOT / "SENAL.md").write_text(body + "\n", encoding="utf-8")
    log(f"Señal de {label}: " + ", ".join(f"{a} {out['targets'][a] * 100:.0f}%" for a in WEIGHTS))
    if create_issue and os.environ.get("GITHUB_ACTIONS"):
        try:
            subprocess.run(["gh", "issue", "create", "--title", f"📅 Cartera: señal de {label}", "--body", body], check=True, timeout=60)
            log("Aviso creado (llega por mail).")
        except Exception as e:
            log(f"⚠ no se pudo crear el aviso: {e}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["study", "signal"])
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--no-issue", action="store_true")
    a = ap.parse_args()
    if a.cmd == "study":
        study(a.synthetic)
    else:
        signal(a.synthetic, create_issue=not a.no_issue)


if __name__ == "__main__":
    try:
        main()
    except BaseException as e:
        import traceback
        log(f"✗ {e.__class__.__name__}: {e}")
        with open(OUT / "log.txt", "a", encoding="utf-8") as fh:
            fh.write(traceback.format_exc())
        raise

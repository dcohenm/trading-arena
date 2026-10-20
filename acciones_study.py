#!/usr/bin/env python3
"""¿Funciona "comprar acciones en tendencia alcista que acaban de caer un poco"? (idea de un post de Reddit)

Reglas FIJAS, decididas antes de mirar los datos (datos diarios ajustados por splits y dividendos):
  - Tendencia alcista: cierre arriba de la media de 200 días y media de 50 días arriba de la de 200.
  - "Cayó un poco": el cierre está entre 3% y 10% debajo del cierre más alto de los últimos 10 días,
    y cerró en baja ese día.
  - Se compra en la apertura del día siguiente. Stop 4% abajo, objetivo 4% arriba, máximo 3 días
    (sale al cierre del tercero). Si un mismo día toca stop y objetivo, se cuenta como stop.
  - Cartera de hasta 10 posiciones de 10% cada una; si hay más señales que lugares, se eligen las
    caídas más profundas.
  - Costo: 0,03% por lado (sin comisión, diferencia entre compra y venta + deslizamiento). También 0,10%.

Dos grupos:
  - "estrellas": 60 acciones conocidas de hoy (como el post). Tiene sesgo: son las que sabemos que
    sobrevivieron y crecieron. Por eso se compara contra comprar y mantener ESAS MISMAS acciones.
  - "etfs": 20 fondos de índices y sectores (SPY, QQQ, XLF…). Sin sesgo de elegir ganadoras.

Comparaciones: comprar y mantener el mismo grupo, el S&P 500 (SPY), y las mismas operaciones con
entradas al azar (300 veces), tanto en cualquier día como solo en días de tendencia alcista.
El autor diseñó su bot con datos de 2024-2026: el período 2012-2023 es una prueba que él nunca vio.

Uso:  python acciones_study.py            (lo corre GitHub Actions; baja datos de Yahoo/Stooq)
      python acciones_study.py --synthetic
"""
from __future__ import annotations

import argparse
import io
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
from arena.metrics import probabilistic_sharpe, stats_from_equity  # noqa: E402

OUT = ROOT / "study" / "acciones"
DOCS = ROOT / "docs" / "acciones"
START = "2011-01-01"           # 2011 se usa para calcular las medias; la simulación arranca en 2012
SIM_START = pd.Timestamp("2012-01-01")
AUTHOR_START = pd.Timestamp("2024-01-01")
UNIVERSES = {
    "estrellas": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "JPM", "BAC", "WFC", "GS", "MS", "C",
                  "V", "MA", "UNH", "JNJ", "PFE", "MRK", "ABBV", "LLY", "TMO", "ABT", "XOM", "CVX", "KO", "PEP", "PG",
                  "WMT", "COST", "HD", "MCD", "NKE", "DIS", "NFLX", "ADBE", "CRM", "ORCL", "INTC", "AMD", "CSCO",
                  "QCOM", "TXN", "IBM", "CAT", "BA", "GE", "HON", "UPS", "MMM", "T", "VZ", "CMCSA", "BRK-B", "AMGN",
                  "GILD", "BMY", "CVS", "LOW"],
    "etfs": ["SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLV", "XLE", "XLI", "XLP", "XLY", "XLU", "XLB", "EFA", "EEM",
             "TLT", "GLD", "VNQ", "SMH", "XBI"],
}
RULES = {"sma_fast": 50, "sma_slow": 200, "hi_window": 10, "dip_min": 0.03, "dip_max": 0.10,
         "stop": 0.04, "target": 0.04, "max_days": 3, "slots": 10}
COSTS = [0.0003, 0.0010]
N_RANDOM = 300
LOG: list[str] = []


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG.append(line)
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "log.txt", "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


# ------------------------------------------------------------------ datos
def load_yahoo(tickers: list[str]) -> dict[str, pd.DataFrame]:
    import yfinance as yf
    raw = yf.download(tickers, start=START, auto_adjust=True, group_by="ticker", progress=False, threads=True)
    out = {}
    for t in tickers:
        try:
            d = raw[t].dropna(subset=["Close"])
            d = d.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
            d.index = pd.to_datetime(d.index).tz_localize(None)
            if len(d) > 300:
                out[t] = d
        except Exception:
            pass
    return out


def load_stooq(t: str) -> pd.DataFrame | None:
    import requests
    sym = t.lower().replace("-", ".") + ".us"
    r = requests.get(f"https://stooq.com/q/d/l/?s={sym}&i=d", timeout=30)
    if r.status_code != 200 or "Date" not in r.text[:50]:
        return None
    d = pd.read_csv(io.StringIO(r.text), parse_dates=["Date"]).set_index("Date").rename(columns=str.lower)
    d = d[d.index >= START][["open", "high", "low", "close", "volume"]]
    return d if len(d) > 300 else None


def load_prices(tickers: list[str]) -> tuple[dict[str, pd.DataFrame], str]:
    data, src = {}, "Yahoo Finance"
    try:
        data = load_yahoo(tickers)
    except Exception as e:
        log(f"  Yahoo falló ({e.__class__.__name__}: {str(e)[:100]})")
    missing = [t for t in tickers if t not in data]
    if missing:
        log(f"  {len(missing)} sin datos de Yahoo, probando Stooq: {', '.join(missing[:10])}…")
        for t in missing:
            try:
                d = load_stooq(t)
                if d is not None:
                    data[t] = d
                    src = "Yahoo Finance + Stooq"
            except Exception:
                pass
    return data, src


def synthetic_prices(tickers: list[str], seed: int) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(START, "2026-10-19")
    out = {}
    for t in tickers:
        r = rng.normal(0.0004, 0.018, len(idx))
        c = 50 * np.exp(np.cumsum(r))
        o = c * np.exp(rng.normal(0, 0.005, len(idx)))
        h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.008, len(idx))))
        lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.008, len(idx))))
        out[t] = pd.DataFrame({"open": o, "high": h, "low": lo, "close": c, "volume": 1e6}, index=idx)
    return out


# ------------------------------------------------------------------ señales y operaciones
def add_signals(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    c = d.close
    d["sma_f"] = c.rolling(RULES["sma_fast"]).mean()
    d["sma_s"] = c.rolling(RULES["sma_slow"]).mean()
    d["hi"] = c.rolling(RULES["hi_window"]).max()
    d["trend"] = (c > d.sma_s) & (d.sma_f > d.sma_s)
    depth = 1 - c / d.hi
    d["depth"] = depth
    d["signal"] = d.trend & (depth >= RULES["dip_min"]) & (depth <= RULES["dip_max"]) & (c < c.shift(1))
    return d


def exit_trade(d: pd.DataFrame, i: int, cost: float) -> tuple[float, int]:
    """Entra en la apertura de la fila i. Devuelve (retorno neto, fila de salida)."""
    o, h, l, c = d.open.values, d.high.values, d.low.values, d.close.values
    entry = o[i]
    stop, target = entry * (1 - RULES["stop"]), entry * (1 + RULES["target"])
    last = min(i + RULES["max_days"] - 1, len(d) - 1)
    for j in range(i, last + 1):
        oj = o[j] if j > i else entry
        if l[j] <= stop:
            px = min(oj, stop)
            return px / entry * (1 - cost) / (1 + cost) - 1, j
        if h[j] >= target:
            px = max(oj, target)
            return px / entry * (1 - cost) / (1 + cost) - 1, j
    return c[last] / entry * (1 - cost) / (1 + cost) - 1, last


def simulate(data: dict[str, pd.DataFrame], cost: float) -> tuple[pd.Series, pd.DataFrame, pd.Series]:
    """Cartera diaria. Señal al cierre del día d → compra en la apertura de d+1."""
    dates = sorted(set().union(*[set(d.index) for d in data.values()]))
    dates = [x for x in dates if x >= SIM_START]
    pos = {}                      # ticker -> dict(shares, entry, row, entry_date, stop, target, days)
    cash, eq_hist, trades, expo = 100_000.0, [], [], []
    idx = {t: {dt: k for k, dt in enumerate(d.index)} for t, d in data.items()}
    pending: list[tuple[str, float]] = []
    equity_prev = cash
    for dt in dates:
        # 1) compras pendientes en la apertura
        free = RULES["slots"] - len(pos)
        for t, _ in pending[:max(free, 0)]:
            if t in pos or dt not in idx[t]:
                continue
            k = idx[t][dt]
            d = data[t]
            entry = d.open.iat[k]
            alloc = min(equity_prev / RULES["slots"], cash / (1 + cost))
            if alloc < 100 or not entry > 0:
                continue
            sh = alloc / entry
            cash -= alloc * (1 + cost)
            pos[t] = {"shares": sh, "entry": entry, "row": k, "date": dt, "stop": entry * (1 - RULES["stop"]),
                      "target": entry * (1 + RULES["target"]), "days": 0}
        pending = []
        # 2) gestionar posiciones con la vela del día
        for t in list(pos):
            if dt not in idx[t]:
                continue
            p, d, k = pos[t], data[t], idx[t][dt]
            p["days"] += 1
            o = d.open.iat[k] if k > p["row"] else p["entry"]
            px = None
            if d.low.iat[k] <= p["stop"]:
                px = min(o, p["stop"])
            elif d.high.iat[k] >= p["target"]:
                px = max(o, p["target"])
            elif p["days"] >= RULES["max_days"]:
                px = d.close.iat[k]
            if px is not None:
                cash += p["shares"] * px * (1 - cost)
                trades.append({"ticker": t, "entry_date": p["date"], "exit_date": dt,
                               "ret": px / p["entry"] * (1 - cost) / (1 + cost) - 1})
                del pos[t]
        # 3) valuación y señales para mañana
        inv = sum(p["shares"] * data[t].close.iat[idx[t][dt]] if dt in idx[t] else p["shares"] * p["entry"]
                  for t, p in pos.items())
        equity_prev = cash + inv
        eq_hist.append((dt, equity_prev))
        expo.append((dt, inv / equity_prev if equity_prev > 0 else 0))
        sig = []
        for t, d in data.items():
            if dt in idx[t] and t not in pos:
                k = idx[t][dt]
                if bool(d.signal.iat[k]):
                    sig.append((t, float(d.depth.iat[k])))
        pending = sorted(sig, key=lambda x: -x[1])
    eq = pd.Series(dict(eq_hist))
    return eq, pd.DataFrame(trades), pd.Series(dict(expo))


def buy_hold(data: dict[str, pd.DataFrame]) -> pd.Series:
    """Mismo monto en cada activo desde el primer día y no tocar nada (los que empiezan después, entran al empezar)."""
    closes = pd.DataFrame({t: d.close for t, d in data.items()})
    closes = closes[closes.index >= SIM_START].ffill()
    first = closes.apply(lambda s: s.first_valid_index())
    growth = pd.DataFrame({t: closes[t] / closes[t].loc[first[t]] for t in closes.columns})
    return growth.mean(axis=1) * 100_000


def random_controls(data, trades: pd.DataFrame, cost: float, rng, trend_only: bool) -> np.ndarray:
    """Las mismas reglas de salida, entrando en días al azar (vectorizado: todas las series concatenadas)."""
    O, H, L, C, pool, off = [], [], [], [], [], 0
    for t, d in data.items():
        ok = (d.index >= SIM_START) & d.sma_s.notna().values
        if trend_only:
            ok &= d.trend.values
        rows = np.where(ok)[0] + 1                                     # entrar al día siguiente de la condición
        rows = rows[rows < len(d) - RULES["max_days"]]
        O.append(d.open.values); H.append(d.high.values); L.append(d.low.values); C.append(d.close.values)
        pool.append(rows + off)
        off += len(d)
    O, H, L, C = (np.concatenate(x) for x in (O, H, L, C))
    sizes = np.array([len(p) for p in pool], float)
    probs = (sizes > 0) / max((sizes > 0).sum(), 1)                   # primero un activo al azar, después un día al azar
    n = len(trades)
    means = np.empty(N_RANDOM)
    for r in range(N_RANDOM):
        which = rng.choice(len(pool), size=n, p=probs)
        e = np.array([pool[w][rng.integers(len(pool[w]))] for w in which])
        means[r] = exit_vec(O, H, L, C, e, cost).mean()
    return means


def exit_vec(O, H, L, C, e, cost):
    entry = O[e]
    stop, target = entry * (1 - RULES["stop"]), entry * (1 + RULES["target"])
    ret = np.full(len(e), np.nan)
    done = np.zeros(len(e), bool)
    k = (1 - cost) / (1 + cost)
    for j in range(RULES["max_days"]):
        r = e + j
        oj = entry if j == 0 else O[r]
        hs = ~done & (L[r] <= stop)
        ret[hs] = (np.minimum(oj, stop) / entry * k - 1)[hs]
        done |= hs
        ht = ~done & (H[r] >= target)
        ret[ht] = (np.maximum(oj, target) / entry * k - 1)[ht]
        done |= ht
    last = e + RULES["max_days"] - 1
    ret[~done] = (C[last] / entry * k - 1)[~done]
    return ret


def stats(eq: pd.Series) -> dict:
    eq = eq.dropna()
    s = stats_from_equity(eq, 252)
    s["psr"] = probabilistic_sharpe(eq.pct_change().dropna().to_numpy())
    return s


def yearly(eq: pd.Series) -> dict:
    out = {}
    for y, g in eq.groupby(eq.index.year):
        prev = eq[eq.index < g.index[0]]
        base = prev.iloc[-1] if len(prev) else g.iloc[0]
        out[str(y)] = (g.iloc[-1] / base - 1) * 100
    return out


def period_stats(eq: pd.Series, a, b) -> dict:
    return stats(eq[(eq.index >= a) & (eq.index < b)])


# ------------------------------------------------------------------ reporte
def f(v, d=1, suf=""):
    return "—" if v is None or (isinstance(v, float) and not math.isfinite(v)) else f"{v:.{d}f}{suf}"


def conclusions(R: dict) -> list[str]:
    out = []
    for u, r in R.items():
        s, bh, spy = r["strategy"]["all"], r["buyhold"]["all"], r["spy"]["all"]
        rc = r["random"]
        beat_rand = rc["pctl_any"] >= 97.5 and rc["pctl_trend"] >= 97.5
        better_sharpe = s["sharpe"] > max(bh["sharpe"], spy["sharpe"])
        lbl = "60 acciones conocidas" if u == "estrellas" else "20 ETFs (sin sesgo)"
        out.append(f"**{lbl}:** la estrategia rindió {f(s['cagr_pct'], 1)}% anual (Sharpe {f(s['sharpe'], 2)}, caída máx. {f(s['max_dd_pct'], 0)}%, "
                   f"invertida en promedio el {f(r['exposure_pct'], 0)}% del tiempo) contra {f(bh['cagr_pct'], 1)}% de comprar y mantener esos mismos "
                   f"activos (Sharpe {f(bh['sharpe'], 2)}) y {f(spy['cagr_pct'], 1)}% del S&P 500 (Sharpe {f(spy['sharpe'], 2)}). "
                   f"Por operación: {f(r['trade_mean_pct'], 3)}% contra {f(rc['mean_any_pct'], 3)}% de entrar en cualquier día al azar y "
                   f"{f(rc['mean_trend_pct'], 3)}% de entrar al azar en días de tendencia alcista "
                   f"(le ganó al {f(rc['pctl_any'], 0)}% y al {f(rc['pctl_trend'], 0)}% de esas versiones). "
                   + ("**Le gana al azar y tiene mejor relación retorno/riesgo que comprar y mantener.**" if beat_rand and better_sharpe else
                      ("Le gana al azar, pero no a comprar y mantener ajustado por riesgo." if beat_rand else
                       "No se distingue de entrar al azar.")))
    st = R.get("estrellas")
    if st:
        a, b = st["strategy"]["before_author"], st["strategy"]["author_period"]
        out.append(f"**Antes y durante el período del autor (60 acciones):** 2012-2023, que el autor nunca vio: {f(a['cagr_pct'], 1)}% anual "
                   f"(Sharpe {f(a['sharpe'], 2)}); 2024-2026, el período con el que lo diseñó: {f(b['cagr_pct'], 1)}% anual (Sharpe {f(b['sharpe'], 2)}). "
                   f"Comprar y mantener esas acciones: {f(st['buyhold']['before_author']['cagr_pct'], 1)}% y {f(st['buyhold']['author_period']['cagr_pct'], 1)}%.")
    return out


def write_reports(R: dict, curves: dict, meta: dict):
    DOCS.mkdir(parents=True, exist_ok=True)
    concl = conclusions(R)
    (OUT / "resumen.json").write_text(json.dumps({"meta": meta, "rules": RULES, "results": R}, indent=1, default=float, ensure_ascii=False))
    md = ["# Comprar la caída en tendencia alcista (acciones de EE.UU.)", "",
          f"La idea del post de Reddit, con reglas fijas, sobre **{meta['start']} → {meta['end']}** (datos de {meta['source']}). "
          "Costos 0,03% por lado (también se muestra 0,10%).", "", "## Conclusiones", ""] + [f"- {c}" for c in concl]
    for u, r in R.items():
        lbl = "60 acciones conocidas" if u == "estrellas" else "20 ETFs"
        md += ["", f"## {lbl}", "",
               "| | Retorno anual | Sharpe | Caída máx. | Prob. ventaja real |", "|---|---:|---:|---:|---:|"]
        for name, key in (("Estrategia (costo 0,03%)", "strategy"), ("Estrategia (costo 0,10%)", "strategy_hicost"),
                          ("Comprar y mantener el mismo grupo", "buyhold"), ("S&P 500 (SPY)", "spy")):
            s = r[key]["all"]
            md.append(f"| {name} | {f(s['cagr_pct'], 1)}% | {f(s['sharpe'], 2)} | {f(s['max_dd_pct'], 0)}% | {f(s['psr'] * 100, 0)}% |")
        md += ["", f"Operaciones: {r['n_trades']} · ganadoras {f(r['win_pct'], 0)}% · promedio por operación {f(r['trade_mean_pct'], 3)}% · "
                   f"invertida en promedio el {f(r['exposure_pct'], 0)}% del tiempo.", "",
               "| Año | " + " | ".join(r["yearly"]["strategy"]) + " |", "|---|" + "---:|" * len(r["yearly"]["strategy"])]
        for name, key in (("Estrategia", "strategy"), ("Comprar y mantener", "buyhold"), ("S&P 500", "spy")):
            md.append(f"| {name} | " + " | ".join(f(r["yearly"][key].get(y), 1) for y in r["yearly"]["strategy"]) + " |")
    md += ["", "## Cómo leer esto", "",
           "- **Sharpe**: retorno por unidad de riesgo. Es la comparación justa, porque la estrategia pasa parte del tiempo en efectivo.",
           "- **Entradas al azar**: las mismas reglas de salida (stop, objetivo, 3 días) pero comprando en días al azar. Si la señal de \"comprar la caída\" "
           "sirve, tiene que ganarle a casi todas esas versiones (97,5% o más).",
           "- **Sesgo de supervivencia**: las 60 acciones son ganadoras conocidas de hoy. Por eso el grupo de ETFs es la prueba más honesta.",
           "- Supuesto conservador: si un día toca stop y objetivo, se cuenta como stop. Los datos diarios no dicen cuál pasó primero.",
           "", "📊 Tablero: https://dcohenm.github.io/trading-arena/acciones/", "",
           f"*Generado el {meta['generated']} en {meta['minutes']:.0f} minutos. Todo es simulado; no es asesoramiento financiero.*"]
    (ROOT / "ACCIONES.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    write_html(R, curves, concl, meta)
    log("Reportes escritos: ACCIONES.md, study/acciones/, docs/acciones/index.html")


def write_html(R, curves, concl, meta):
    import html as H
    import re
    shutil.copyfile(ROOT / "arena" / "assets" / "chart.umd.js", DOCS / "chart.umd.js")
    md = lambda s: re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", H.escape(s))   # noqa: E731
    pal = [("#2a78d6", "#3987e5"), ("#eb6834", "#d95926"), ("#898781", "#898781")]
    charts = ""
    data = {}
    for u, cv in curves.items():
        wk = {k: v.resample("W").last() for k, v in cv.items()}
        labels = [d.strftime("%Y-%m-%d") for d in wk["strategy"].index]
        names = {"strategy": "Estrategia", "buyhold": "Comprar y mantener", "spy": "S&P 500"}
        data[u] = {"labels": labels, "series": [{"name": names[k], "light": pal[i][0], "dark": pal[i][1], "dash": k == "spy",
                                                 "data": [None if x != x else round(float(x), 0) for x in wk[k].reindex(wk["strategy"].index).values]}
                                                for i, k in enumerate(("strategy", "buyhold", "spy"))]}
        lbl = "60 acciones conocidas" if u == "estrellas" else "20 ETFs (sin sesgo)"
        charts += f"<div class='card'><h2>{lbl}: capital (USD, desde 100.000)</h2><div class='chart'><canvas id='c_{u}'></canvas></div></div>"
    page = f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Acciones: comprar la caída</title><script src="chart.umd.js"></script><style>
:root{{--surface:#fcfcfb;--page:#f9f9f7;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;--ring:rgba(11,11,11,.10);color-scheme:light}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--surface:#1a1a19;--page:#0d0d0d;--ink:#f0efec;--ink2:#c3c2b7;--grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10);color-scheme:dark}}}}
:root[data-theme="dark"]{{--surface:#1a1a19;--page:#0d0d0d;--ink:#f0efec;--ink2:#c3c2b7;--grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10);color-scheme:dark}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--page);color:var(--ink);font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1000px;margin:0 auto;padding:28px 16px 60px}}h1{{font-size:22px;margin:0 0 4px}}h2{{font-size:15px;margin:0 0 12px}}
.sub{{color:var(--ink2);margin:0 0 20px}}.card{{background:var(--surface);border-radius:12px;box-shadow:0 0 0 1px var(--ring);padding:18px;margin-bottom:16px}}
.chart{{position:relative;height:320px}}ul{{margin:0;padding-left:18px}}li{{margin-bottom:8px}}
</style></head><body><main><h1>Comprar la caída en tendencia alcista</h1>
<p class="sub">Acciones y ETFs de EE.UU. · {meta['start']} → {meta['end']} · todo simulado</p>
<div class="card"><h2>Conclusiones</h2><ul>{''.join(f'<li>{md(c)}</li>' for c in concl)}</ul></div>{charts}
</main><script>
const D={json.dumps(data)};const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const dark=()=>css('--surface')==='#1a1a19';const C=[];
function draw(){{C.forEach(c=>c.destroy());C.length=0;for(const u in D){{const d=D[u];
C.push(new Chart(document.getElementById('c_'+u),{{type:'line',data:{{labels:d.labels,datasets:d.series.map(s=>({{label:s.name,data:s.data,
borderColor:dark()?s.dark:s.light,backgroundColor:dark()?s.dark:s.light,borderWidth:2,borderDash:s.dash?[4,4]:[],pointRadius:0,pointHoverRadius:4,spanGaps:true}}))}},
options:{{responsive:true,maintainAspectRatio:false,animation:false,interaction:{{mode:'index',intersect:false}},
plugins:{{legend:{{position:'bottom',labels:{{color:css('--ink2'),boxWidth:10,boxHeight:10,usePointStyle:true,pointStyle:'rectRounded'}}}},
tooltip:{{backgroundColor:css('--surface'),titleColor:css('--ink'),bodyColor:css('--ink2'),borderColor:css('--axis'),borderWidth:1,
callbacks:{{label:c=>' '+c.dataset.label+': '+Math.round(c.raw).toLocaleString('es-AR')}}}}}},
scales:{{x:{{ticks:{{color:css('--muted'),maxTicksLimit:8,maxRotation:0}},grid:{{display:false}},border:{{color:css('--axis')}}}},
y:{{ticks:{{color:css('--muted'),maxTicksLimit:6,callback:v=>Math.round(v).toLocaleString('es-AR')}},grid:{{color:css('--grid')}},border:{{display:false}}}}}}}}}}));}}}}
draw();matchMedia('(prefers-color-scheme: dark)').addEventListener('change',draw);
new MutationObserver(draw).observe(document.documentElement,{{attributes:true,attributeFilter:['data-theme']}});
</script></body></html>"""
    (DOCS / "index.html").write_text(page, encoding="utf-8")


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", action="store_true")
    a = ap.parse_args()
    shutil.rmtree(OUT, ignore_errors=True)
    t0 = time.time()
    rng = np.random.default_rng(11)
    R, curves, src = {}, {}, ""
    if a.synthetic:
        spy = synthetic_prices(["SPY"], 99)["SPY"]
    for u, tickers in UNIVERSES.items():
        log(f"Grupo {u}: bajando {len(tickers)} activos…")
        if a.synthetic:
            data, src = synthetic_prices(tickers, 1 if u == "estrellas" else 2), "datos SINTÉTICOS"
        else:
            data, src = load_prices(tickers + (["SPY"] if "SPY" not in tickers else []))
            spy = data.get("SPY")
            if u == "estrellas":
                data.pop("SPY", None)
        log(f"  {len(data)} activos con datos ({src})")
        data = {t: add_signals(d) for t, d in data.items()}
        res = {}
        eq, trades, expo = simulate(data, COSTS[0])
        eq_hi, _, _ = simulate(data, COSTS[1])
        bh = buy_hold(data)
        spy_eq = (spy.close[spy.index >= SIM_START] / spy.close[spy.index >= SIM_START].iloc[0] * 100_000)
        log(f"  {len(trades)} operaciones simuladas; probando contra entradas al azar…")
        r_any = random_controls(data, trades, COSTS[0], rng, trend_only=False)
        r_tr = random_controls(data, trades, COSTS[0], rng, trend_only=True)
        tm = float(trades.ret.mean()) if len(trades) else float("nan")
        end = pd.Timestamp.max
        for name, curve in (("strategy", eq), ("strategy_hicost", eq_hi), ("buyhold", bh), ("spy", spy_eq)):
            res[name] = {"all": stats(curve), "before_author": period_stats(curve, SIM_START, AUTHOR_START),
                         "author_period": period_stats(curve, AUTHOR_START, end)}
        res["yearly"] = {"strategy": yearly(eq), "buyhold": yearly(bh), "spy": yearly(spy_eq)}
        res["n_trades"] = int(len(trades))
        res["win_pct"] = float((trades.ret > 0).mean() * 100) if len(trades) else float("nan")
        res["trade_mean_pct"] = tm * 100
        res["exposure_pct"] = float(expo.mean() * 100)
        res["random"] = {"mean_any_pct": float(r_any.mean() * 100), "mean_trend_pct": float(r_tr.mean() * 100),
                         "pctl_any": float((r_any < tm).mean() * 100), "pctl_trend": float((r_tr < tm).mean() * 100)}
        R[u] = res
        curves[u] = {"strategy": eq, "buyhold": bh.reindex(eq.index).ffill(), "spy": spy_eq.reindex(eq.index).ffill()}
        trades.to_csv(OUT / f"operaciones_{u}.csv", index=False)
        log(f"  {u}: estrategia {res['strategy']['all']['cagr_pct']:.1f}% anual vs comprar y mantener {res['buyhold']['all']['cagr_pct']:.1f}%")
    any_eq = next(iter(curves.values()))["strategy"]
    meta = {"start": any_eq.index[0].strftime("%Y-%m-%d"), "end": any_eq.index[-1].strftime("%Y-%m-%d"), "source": src,
            "minutes": (time.time() - t0) / 60, "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    write_reports(R, curves, meta)
    for c in conclusions(R):
        log(c)


if __name__ == "__main__":
    try:
        main()
    except BaseException as e:
        import traceback
        log(f"✗ {e.__class__.__name__}: {e}")
        with open(OUT / "log.txt", "a", encoding="utf-8") as fh:
            fh.write(traceback.format_exc())
        raise

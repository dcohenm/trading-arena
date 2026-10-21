#!/usr/bin/env python3
"""¿Kronos predice las próximas velas de cripto mejor que reglas simples?

Kronos es un modelo tipo GPT entrenado con más de 12.000 millones de velas (OHLCV) de 45 exchanges
(Tsinghua, AAAI 2026). Acá se lo usa tal como viene (sin reentrenar) para predecir:

    velas de 15 min  →  1 hora y 4 horas adelante
    velas de 1 hora  →  4 horas y 1 día adelante
    velas diarias    →  1 semana adelante

Reglas fijas, decididas antes de ver resultados:
  - Solo se evalúan predicciones cuyo resultado ocurre DESPUÉS del 1/9/2025. Kronos se publicó en
    agosto de 2025, así que no pudo haber "visto" esas velas durante su entrenamiento.
  - Modelo Kronos-small, contexto de 400 velas, temperatura 1.0, top_p 0.9, promedio de 4 trayectorias.
  - Para medir si acierta se usan predicciones que no se superponen en el tiempo.
  - Se compara contra: "siempre sube", "sigue la tendencia" (el signo del último tramo igual de largo)
    y comprar y mantener. Con costos de 0,15% por operación (ida) en la prueba de trading.

Uso:  python kronos_eval.py            (lo corre GitHub Actions; necesita torch y el repo de Kronos)
      python kronos_eval.py --stub     prueba local con un predictor falso (sin torch)
"""
from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from arena.data import fetch_recent  # noqa: E402

OUT = ROOT / "study" / "kronos"
DOCS = ROOT / "docs" / "kronos"
COINS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
EVAL_START = pd.Timestamp("2025-09-01", tz="UTC")
COST = 0.0015            # por operación (ida): comisión 0,10% + deslizamiento 0,05%
CFG = {"model": "NeoQuasar/Kronos-small", "tokenizer": "NeoQuasar/Kronos-Tokenizer-base", "lookback": 400,
       "T": 1.0, "top_p": 0.9, "samples": 4, "batch": 24, "seed": 0}
GROUPS = [  # marco de entrada, minutos por vela, horizontes (en velas), separación entre predicciones, tiempo máximo
    {"tf": "15m", "minutes": 15, "horizons": {"1h": 4, "4h": 16}, "spacing": 16, "budget_min": 110},
    {"tf": "1h", "minutes": 60, "horizons": {"4h": 4, "1d": 24}, "spacing": 24, "budget_min": 70},
    {"tf": "1d", "minutes": 1440, "horizons": {"1w": 7}, "spacing": 1, "budget_min": 25},
]
LOG: list[str] = []
REPORT_MD = ROOT / "KRONOS.md"
TAG = ""


def set_output(tag: str) -> None:
    """Con un sufijo (p. ej. mac_small) los resultados van a archivos aparte y no pisan los de GitHub."""
    global OUT, DOCS, REPORT_MD, TAG
    TAG = tag
    if tag:
        OUT = ROOT / "study" / f"kronos_{tag}"
        DOCS = ROOT / "docs" / f"kronos_{tag}"
        REPORT_MD = ROOT / f"KRONOS_{tag.upper()}.md"


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG.append(line)
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "log.txt", "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


# ------------------------------------------------------------------ predictor
class StubPredictor:
    """Predictor falso para probar el circuito sin torch: predice ruido alrededor del último precio."""

    def predict_batch(self, df_list, x_timestamp_list, y_timestamp_list, pred_len, **kw):
        rng = np.random.default_rng(len(df_list))
        out = []
        for df, yts in zip(df_list, y_timestamp_list):
            last = df["close"].iloc[-1]
            path = last * np.exp(np.cumsum(rng.normal(0, 0.003, pred_len)))
            out.append(pd.DataFrame({"open": path, "high": path, "low": path, "close": path,
                                     "volume": 0.0, "amount": 0.0}, index=yts))
        return out


def load_predictor(stub: bool, device: str = "cpu"):
    if stub:
        return StubPredictor()
    import torch
    sys.path.insert(0, str(ROOT / "vendor" / "Kronos"))
    from model import Kronos, KronosPredictor, KronosTokenizer
    torch.manual_seed(CFG["seed"])
    torch.set_num_threads(max(1, torch.get_num_threads()))
    tok = KronosTokenizer.from_pretrained(CFG["tokenizer"])
    model = Kronos.from_pretrained(CFG["model"])
    model.eval()
    if device == "auto":
        device = "mps" if torch.backends.mps.is_available() else ("cuda:0" if torch.cuda.is_available() else "cpu")
    log(f"Dispositivo: {device}")
    return KronosPredictor(model, tok, device=device, max_context=512)


# ------------------------------------------------------------------ predicciones
def run_group(pred, g: dict, frames: dict, deadline: float) -> pd.DataFrame:
    """Predice en orígenes al azar (orden mezclado: si se acaba el tiempo, la muestra sigue cubriendo
    todo el período de manera pareja)."""
    L, H = CFG["lookback"], max(g["horizons"].values())
    step = pd.Timedelta(minutes=g["minutes"])
    ts = frames[COINS[0]]["ts"]
    when = pd.to_datetime(ts, unit="ms", utc=True)
    first_ok = EVAL_START - step * H               # el resultado (t + horizonte) cae después del corte
    idx = [i for i in range(L - 1, len(ts) - H) if when.iloc[i] >= first_ok]
    idx = idx[::g["spacing"]]
    random.Random(CFG["seed"]).shuffle(idx)
    log(f"  {g['tf']}: {len(idx)} momentos × {len(COINS)} monedas para predecir")
    rows, t0, done = [], time.time(), 0
    jobs = [(i, c) for i in idx for c in COINS]
    for k in range(0, len(jobs), CFG["batch"]):
        if time.time() > deadline:
            log(f"  {g['tf']}: se acabó el tiempo asignado; se evalúa con {done} predicciones")
            break
        chunk = jobs[k:k + CFG["batch"]]
        dfs, xts, yts = [], [], []
        for i, c in chunk:
            d = frames[c].iloc[i - L + 1: i + 1]
            dfs.append(d[["open", "high", "low", "close", "volume"]].reset_index(drop=True))
            xt = pd.Series(pd.to_datetime(d["ts"].values, unit="ms", utc=True).tz_localize(None))
            xts.append(xt)
            yts.append(pd.Series([xt.iloc[-1] + step * (j + 1) for j in range(H)]))
        preds = pred.predict_batch(dfs, xts, yts, pred_len=H, T=CFG["T"], top_p=CFG["top_p"],
                                   sample_count=CFG["samples"], verbose=False)
        for (i, c), p in zip(chunk, preds):
            base = float(frames[c]["close"].iloc[i])
            row = {"tf": g["tf"], "coin": c.split("/")[0], "t": int(ts.iloc[i]), "close": base}
            tsc = frames[c]["ts"]
            for name, h in g["horizons"].items():
                hms = h * g["minutes"] * 60_000
                ok_f = int(tsc.iloc[i + h]) - int(tsc.iloc[i]) == hms          # sin huecos en los datos
                ok_p = i - h >= 0 and int(tsc.iloc[i]) - int(tsc.iloc[i - h]) == hms
                fut = float(frames[c]["close"].iloc[i + h]) if ok_f else float("nan")
                past = float(frames[c]["close"].iloc[i - h]) if ok_p else float("nan")
                row[f"pred_{name}"] = float(p["close"].iloc[h - 1]) / base - 1
                row[f"real_{name}"] = fut / base - 1
                row[f"past_{name}"] = base / past - 1
            rows.append(row)
        done += len(chunk)
        if (k // CFG["batch"]) % 10 == 0:
            el = time.time() - t0
            log(f"    {done}/{len(jobs)} · {el / 60:.1f} min · {done / max(el, 1e-9):.1f} pred/s")
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ evaluación
def binom_p(k: int, n: int) -> float:
    """p-valor de una cola de acertar k de n o más si fuera una moneda (aprox. normal)."""
    if n == 0:
        return float("nan")
    z = (k - 0.5 * n - 0.5) / math.sqrt(0.25 * n)
    return 0.5 * math.erfc(z / math.sqrt(2))


def spearman(a, b) -> float:
    s = pd.DataFrame({"a": a, "b": b}).dropna()
    return float(s.a.rank().corr(s.b.rank())) if len(s) > 5 else float("nan")


def evaluate(df: pd.DataFrame, g: dict) -> list[dict]:
    """Métricas por combinación. Dos cuidados importantes:
    - BTC, ETH y SOL se mueven juntas: las tres predicciones de un mismo momento NO son tres pruebas
      independientes. La significancia se calcula con UNA observación por momento (mayoría de aciertos).
    - Las reglas de comparación solo se evalúan donde tienen datos (sin contar huecos como errores)."""
    out = []
    step_ms = g["minutes"] * 60_000
    for name, h in g["horizons"].items():
        d = df.dropna(subset=[f"pred_{name}", f"real_{name}", f"past_{name}"]).copy()
        d = d[pd.to_datetime(d.t + h * step_ms, unit="ms", utc=True) >= EVAL_START]
        keep, last = [], -10**18                         # momentos separados al menos por el horizonte
        for t in sorted(d.t.unique()):
            if t - last >= h * step_ms:
                keep.append(t)
                last = t
        d = d[d.t.isin(keep)]
        p, r, m = d[f"pred_{name}"], d[f"real_{name}"], d[f"past_{name}"]
        d["hk"] = (np.sign(p) == np.sign(r)).astype(float)
        d["hm"] = (np.sign(m) == np.sign(r)).astype(float)
        d["hr"] = (np.sign(-m) == np.sign(r)).astype(float)
        d["lsk"], d["lsr"] = np.sign(p) * r, np.sign(-m) * r
        per = d[["t", "hk", "hm", "hr", "lsk", "lsr"]].groupby("t").mean()
        nm = len(per)
        wins = lambda col: int(round((per[col] > 0.5).sum() + 0.5 * (per[col] == 0.5).sum()))   # noqa: E731
        n = int(len(d))
        long_flat = np.where(p > 0, r, 0.0) - np.where(p > 0, 2 * COST, 0.0)
        long_flat_f = np.where(p > 2 * COST, r, 0.0) - np.where(p > 2 * COST, 2 * COST, 0.0)
        mom = np.where(m > 0, r, 0.0) - np.where(m > 0, 2 * COST, 0.0)
        hours = sorted(pd.to_datetime(d.t, unit="ms", utc=True).dt.hour.unique().tolist())
        out.append({
            "input": g["tf"], "horizon": name, "n": n, "moments": nm, "origin_hours": hours,
            "hit_kronos": float(d.hk.mean() * 100), "p_kronos": binom_p(wins("hk"), nm),
            "hit_momentum": float(d.hm.mean() * 100), "hit_reversal": float(d.hr.mean() * 100),
            "p_reversal": binom_p(wins("hr"), nm),
            "hit_always_up": float((r > 0).mean() * 100),
            "corr_with_reversal": float(np.corrcoef(p, -m)[0, 1]) if n > 2 else float("nan"),
            "ic_kronos": spearman(p, r), "ic_momentum": spearman(m, r),
            "ls_gross_kronos": float(per.lsk.mean() * 100), "ls_gross_reversal": float(per.lsr.mean() * 100),
            "ret_kronos_net": float(long_flat.mean() * 100), "ret_kronos_filtered_net": float(long_flat_f.mean() * 100),
            "trades_filtered_pct": float((p > 2 * COST).mean() * 100) if n else float("nan"),
            "ret_momentum_net": float(mom.mean() * 100), "ret_buyhold": float(r.mean() * 100),
            "ret_kronos_gross": float(np.where(p > 0, r, 0.0).mean() * 100),
        })
    return out


# ------------------------------------------------------------------ reporte
def f(v, d=1, suf=""):
    return "—" if v is None or (isinstance(v, float) and not math.isfinite(v)) else f"{v:.{d}f}{suf}"


def conclusions(res: list[dict]) -> list[str]:
    out = []
    thr = 0.05 / max(len(res), 1)
    sig = [r for r in res if r["moments"] >= 50 and r["p_kronos"] < thr
           and r["hit_kronos"] > max(r["hit_momentum"], r["hit_reversal"], r["hit_always_up"])]
    hint = [r for r in res if r["p_kronos"] < 0.05 and r not in sig]
    if sig:
        out.append("**Predice algo:** en " + ", ".join(f"{r['input']}→{r['horizon']} ({f(r['hit_kronos'])}% de aciertos)" for r in sig)
                   + f" acertó la dirección más que el azar y que las reglas simples, con significancia aun corrigiendo por las {len(res)} pruebas.")
    elif hint:
        out.append("**Hay indicios, pero no alcanzan:** en " + ", ".join(
            f"{r['input']}→{r['horizon']} ({f(r['hit_kronos'])}% de aciertos, p={f(r['p_kronos'], 3)})" for r in hint)
            + f" acertó más que una moneda al aire, pero al corregir por haber probado {len(res)} combinaciones hace falta p<{thr:.3f}"
            + (", y la muestra es chica." if min(r["moments"] for r in hint) < 200 else "."))
    else:
        out.append(f"**No predice mejor que el azar** en ninguna de las {len(res)} combinaciones.")
    avg_corr = np.nanmean([r["corr_with_reversal"] for r in res])
    out.append(f"**Qué hace Kronos en el fondo:** sus predicciones se parecen mucho a la regla simple \"lo que subió, baja\" "
               f"(correlación promedio {avg_corr:.2f}). Gran parte de lo que acierta lo acierta también esa regla.")
    one_hour = [r for r in res if r["input"] != "1d" and len(r.get("origin_hours", [])) == 1]
    if one_hour:
        h = one_hour[0]["origin_hours"][0]
        out.append("**Ojo:** en " + ", ".join(f"{r['input']}→{r['horizon']}" for r in one_hour)
                   + f" todas las predicciones arrancan a la misma hora ({h:02d}:00 UTC), así que el resultado vale para esa franja "
                   "del día y no necesariamente para cualquier momento.")
    big = [r for r in res if r["moments"] >= 200] or res       # las muestras chicas son puro ruido
    best = max(big, key=lambda r: r["ls_gross_kronos"])
    out.append(f"**Con costos no sirve:** la mejor ganancia bruta por operación fue {f(best['ls_gross_kronos'], 3)}% "
               f"({best['input']}→{best['horizon']}{', entre las combinaciones con suficientes datos' if big is not res else ''}), "
               f"y entrar y salir cuesta {2 * COST * 100:.2f}%. Ninguna combinación le ganó "
               "a comprar y mantener después de costos de forma apreciable." if not any(r["ret_kronos_net"] > max(r["ret_buyhold"], 0.05) for r in res)
               else "**Con costos:** " + ", ".join(f"{r['input']}→{r['horizon']} ({f(r['ret_kronos_net'], 3)}% por operación)"
                                                   for r in res if r["ret_kronos_net"] > max(r["ret_buyhold"], 0.05))
               + " ganó plata después de costos; hay que confirmarlo con más datos antes de creerlo.")
    return out


def write_reports(res: list[dict], meta: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    concl = conclusions(res)
    (OUT / "resumen.json").write_text(json.dumps({"meta": meta, "config": CFG, "results": res}, indent=1,
                                                 default=float, ensure_ascii=False))
    hdr = ("| Entrada → horizonte | Momentos independientes | Aciertos Kronos | p-valor | \"Lo que subió, baja\" | Seguir tendencia | "
           "\"Siempre sube\" | Parecido de Kronos a \"lo que subió, baja\" |")
    md = ["# ¿Kronos predice las velas?", "",
          f"{CFG['model'].split('/')[-1]} usado tal como viene, sin reentrenar, sobre BTC, ETH y SOL"
          f"{' (corrido en ' + meta.get('device', '') + ', datos de ' + meta.get('source', '') + ')' if TAG else ''}. Solo se evalúan resultados posteriores al "
          f"**{EVAL_START.date()}** (Kronos se publicó en agosto de 2025, así que no pudo verlos). Período: {meta['start']} → {meta['end']}.",
          "", "## Conclusiones", ""] + [f"- {c}" for c in concl] + [
          "", "## ¿Acierta la dirección?", "", hdr, "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in res:
        md.append(f"| {r['input']} → {r['horizon']} | {r['moments']} | {f(r['hit_kronos'])}% | {f(r['p_kronos'], 3)} | "
                  f"{f(r['hit_reversal'])}% | {f(r['hit_momentum'])}% | {f(r['hit_always_up'])}% | {f(r['corr_with_reversal'], 2)} |")
    md += ["", "## Operando con eso (retorno promedio por operación, con costos)", "",
           "| Entrada → horizonte | Kronos | Kronos solo si espera más que los costos | % del tiempo operando | Seguir tendencia | Comprar y mantener | Kronos sin costos |",
           "|---|---:|---:|---:|---:|---:|---:|"]
    for r in res:
        md.append(f"| {r['input']} → {r['horizon']} | {f(r['ret_kronos_net'], 3)}% | {f(r['ret_kronos_filtered_net'], 3)}% | "
                  f"{f(r['trades_filtered_pct'], 0)}% | {f(r['ret_momentum_net'], 3)}% | {f(r['ret_buyhold'], 3)}% | {f(r['ret_kronos_gross'], 3)}% |")
    md += ["", "## Cómo leer esto", "",
           "- **Aciertos**: % de veces que la dirección predicha (sube o baja) coincidió con la real. Una moneda al aire da 50%.",
           "- **Momentos independientes**: BTC, ETH y SOL se mueven juntas, así que las tres predicciones de un mismo momento cuentan como una sola prueba.",
           "- **p-valor**: probabilidad de acertar así de seguido por pura suerte. Como se probaron varias combinaciones, para ser "
           f"significativo tiene que ser menor que {0.05 / max(len(res), 1):.3f}.",
           "- **Correlación**: qué tan bien ordena las subas grandes y chicas (0 = nada, 1 = perfecto). En finanzas, 0,02-0,05 ya se considera una señal.",
           "- **Operando con eso**: comprar cuando Kronos predice suba y quedarse afuera cuando predice baja, pagando 0,15% al entrar y al salir.",
           f"- Configuración fija: {CFG['model']}, contexto {CFG['lookback']} velas, promedio de {CFG['samples']} trayectorias, temperatura {CFG['T']}.",
           "", f"📊 Tablero: https://dcohenm.github.io/trading-arena/{DOCS.name}/", "",
           f"*Generado el {meta['generated']} en {meta['minutes']:.0f} minutos. Todo es simulado; no es asesoramiento financiero.*"]
    REPORT_MD.write_text("\n".join(md) + "\n", encoding="utf-8")
    write_html(res, concl, meta)
    log(f"Reportes escritos: {REPORT_MD.name}, {OUT.relative_to(ROOT)}/, {DOCS.relative_to(ROOT)}/index.html")


def write_html(res, concl, meta):
    import html as H
    import re
    md = lambda s: re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", H.escape(s))   # noqa: E731
    rows = "".join(
        f"<tr><td class='bot'>{r['input']} → {r['horizon']}</td><td class='num'>{r['moments']}</td>"
        f"<td class='num'><b>{f(r['hit_kronos'])}%</b></td><td class='num'>{f(r['p_kronos'], 3)}</td>"
        f"<td class='num'>{f(r['hit_reversal'])}%</td><td class='num'>{f(r['hit_momentum'])}%</td>"
        f"<td class='num'>{f(r['hit_always_up'])}%</td></tr>" for r in res)
    rows2 = "".join(
        f"<tr><td class='bot'>{r['input']} → {r['horizon']}</td><td class='num'><b>{f(r['ret_kronos_net'], 3)}%</b></td>"
        f"<td class='num'>{f(r['ret_kronos_filtered_net'], 3)}%</td><td class='num'>{f(r['ret_momentum_net'], 3)}%</td>"
        f"<td class='num'>{f(r['ret_buyhold'], 3)}%</td></tr>" for r in res)
    page = f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kronos vs. azar</title><style>
:root{{--surface:#fcfcfb;--page:#f9f9f7;--ink:#0b0b0b;--ink2:#52514e;--grid:#e1e0d9;--axis:#c3c2b7;--ring:rgba(11,11,11,.10);color-scheme:light}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--surface:#1a1a19;--page:#0d0d0d;--ink:#f0efec;--ink2:#c3c2b7;--grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10);color-scheme:dark}}}}
:root[data-theme="dark"]{{--surface:#1a1a19;--page:#0d0d0d;--ink:#f0efec;--ink2:#c3c2b7;--grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10);color-scheme:dark}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--page);color:var(--ink);font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1000px;margin:0 auto;padding:28px 16px 60px}}h1{{font-size:22px;margin:0 0 4px}}h2{{font-size:15px;margin:0 0 12px}}
.sub{{color:var(--ink2);margin:0 0 20px}}.card{{background:var(--surface);border-radius:12px;box-shadow:0 0 0 1px var(--ring);padding:18px;margin-bottom:16px}}
.scroll{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;font-size:13px}}th{{color:var(--ink2);font-weight:500;text-align:left;padding:8px;border-bottom:1px solid var(--axis)}}
td{{padding:8px;border-bottom:1px solid var(--grid)}}.num{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}th.num{{text-align:right}}
.bot{{font-weight:500;white-space:nowrap}}ul{{margin:0;padding-left:18px}}li{{margin-bottom:6px}}.help{{color:var(--ink2);font-size:12.5px;margin:10px 0 0}}
</style></head><body><main>
<h1>¿Kronos predice las velas?</h1><p class="sub">Kronos-small sin reentrenar · BTC, ETH, SOL · resultados posteriores al {EVAL_START.date()} · {meta['start']} → {meta['end']}</p>
<div class="card"><h2>Conclusiones</h2><ul>{''.join(f'<li>{md(c)}</li>' for c in concl)}</ul></div>
<div class="card"><h2>¿Acierta la dirección?</h2><div class="scroll"><table><thead><tr><th>Entrada → horizonte</th><th class="num">Momentos</th>
<th class="num">Kronos</th><th class="num">p-valor</th><th class="num">Lo que subió, baja</th><th class="num">Seguir tendencia</th><th class="num">Siempre sube</th></tr></thead>
<tbody>{rows}</tbody></table></div><p class="help">Una moneda al aire acierta 50%. Para ser significativo, el p-valor tiene que ser menor que {0.05 / max(len(res), 1):.3f} (se probaron {len(res)} combinaciones).</p></div>
<div class="card"><h2>Retorno promedio por operación, con costos</h2><div class="scroll"><table><thead><tr><th>Entrada → horizonte</th><th class="num">Kronos</th>
<th class="num">Kronos filtrado</th><th class="num">Seguir tendencia</th><th class="num">Comprar y mantener</th></tr></thead><tbody>{rows2}</tbody></table></div>
<p class="help">Kronos filtrado: solo opera cuando la suba predicha supera lo que cuesta entrar y salir.</p></div>
</main></body></html>"""
    (DOCS / "index.html").write_text(page, encoding="utf-8")


# ------------------------------------------------------------------ main
def reevaluate():
    res, span = [], []
    for g in GROUPS:
        p = OUT / f"predicciones_{g['tf']}.csv"
        if p.exists():
            df = pd.read_csv(p)
            res += evaluate(df, g)
            span += [df.t.min(), df.t.max()]
    old = json.loads((OUT / "resumen.json").read_text())["meta"] if (OUT / "resumen.json").exists() else {}
    day = lambda t: datetime.fromtimestamp(int(t) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")   # noqa: E731
    meta = {**old, "start": day(min(span)), "end": day(max(span)),
            "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") + " (métricas recalculadas)"}
    meta.setdefault("minutes", 0)
    write_reports(res, meta)
    for c in conclusions(res):
        log(c)



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stub", action="store_true", help="predictor falso, para probar sin torch")
    ap.add_argument("--quick", action="store_true", help="pocas predicciones, para chequear que todo anda")
    ap.add_argument("--from-csv", action="store_true", help="recalcular métricas con las predicciones ya guardadas")
    ap.add_argument("--full", action="store_true", help="todas las predicciones, sin tiempo máximo (para la Mac)")
    ap.add_argument("--device", default="cpu", help="cpu, mps, cuda o auto")
    ap.add_argument("--model", default="small", choices=["small", "base"])
    ap.add_argument("--tag", default="", help="sufijo para los archivos de salida (p. ej. mac_small)")
    ap.add_argument("--exchanges", default="coinbase,okx,bingx")
    ap.add_argument("--batch", type=int, default=None)
    a = ap.parse_args()
    set_output(a.tag)
    CFG["model"] = f"NeoQuasar/Kronos-{a.model}"
    if a.batch:
        CFG["batch"] = a.batch
    elif a.device in ("mps", "auto") or a.device.startswith("cuda"):
        CFG["batch"] = 64
    if a.from_csv:
        return reevaluate()
    shutil.rmtree(OUT, ignore_errors=True)
    t0 = time.time()
    log(f"Cargando modelo {'(falso, prueba)' if a.stub else CFG['model']}…")
    pred = load_predictor(a.stub, a.device)
    now = pd.Timestamp.now(tz="UTC")
    results, all_preds, span = [], [], []
    for g in GROUPS:
        days = (now - EVAL_START).days + CFG["lookback"] * g["minutes"] / 1440 + 10
        frames, src = fetch_recent(a.exchanges.split(","), COINS, g["tf"], days, min_coverage=0.85, log=log)
        log(f"{g['tf']}: {len(frames[COINS[0]])} velas de {src}")
        budget = (2 if a.quick else (100_000 if a.full else g["budget_min"])) * 60
        df = run_group(pred, g, frames, time.time() + budget)
        if len(df):
            df.round(6).to_csv(OUT / f"predicciones_{g['tf']}.csv", index=False)
            results += evaluate(df, g)
            all_preds.append(df)
            span += [df.t.min(), df.t.max()]
    if not results:
        raise SystemExit("No se generó ninguna predicción.")
    day = lambda t: datetime.fromtimestamp(int(t) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")   # noqa: E731
    meta = {"start": day(min(span)), "end": day(max(span)), "stub": a.stub, "quick": a.quick, "tag": a.tag,
            "model": CFG["model"], "device": a.device, "source": src,
            "minutes": (time.time() - t0) / 60, "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    write_reports(results, meta)
    for c in conclusions(results):
        log(c)


if __name__ == "__main__":
    try:
        main()
    except BaseException as e:
        import traceback
        log(f"✗ {e.__class__.__name__}: {e}")
        LOG.append(traceback.format_exc())
        with open(OUT / "log.txt", "a", encoding="utf-8") as fh:
            fh.write(traceback.format_exc())
        raise

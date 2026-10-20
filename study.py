#!/usr/bin/env python3
"""Estudio histórico (walk-forward): ¿la arena y su evolución hubieran funcionado en los últimos años?

Simula exactamente lo que hace el piloto automático, pero sobre años de precios reales:
  - los mismos bots iniciales, el mismo gestor de riesgo, los mismos costos
  - cada semana, la misma evolución: crea variantes, las examina con datos que no usó para elegirlas,
    suma las que aprueban y retira a las peores
  - todo con datos estrictamente PASADOS en cada momento (nunca mira el futuro)

Después responde tres preguntas:
  1. ¿Algún bot le ganó a comprar y mantener y a los bots al azar, con evidencia estadística?
  2. ¿Los bots que la evolución eligió rindieron bien DESPUÉS de ser elegidos? (¿aprender sirve?)
  3. ¿Cómo le fue en cada año (alcista, bajista, lateral)?

Uso:  python study.py                       datos reales (lo corre GitHub Actions)
      python study.py --synthetic --years 1 prueba rápida con datos inventados
"""
from __future__ import annotations

import argparse
import copy
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

from arena.bots import RandomBot, bot_from_spec            # noqa: E402
from arena.core import load_config                          # noqa: E402
from arena.csvledger import CsvLedger                       # noqa: E402
from arena.data import fetch_recent, synthetic              # noqa: E402
from arena.engine import Arena, Market                      # noqa: E402
from arena.evolve import SPACE, run_generation              # noqa: E402
from arena.metrics import leaderboard, load_run, probabilistic_sharpe, recent_scores, stats_from_equity  # noqa: E402

OUT = ROOT / "study"
RUN_DIR = OUT / "run"          # registros crudos (no se suben al repositorio: son grandes)
RES = OUT / "results"          # resultados que sí se suben
DOCS = ROOT / "docs" / "estudio"
DAY = 86_400_000
LOG: list[str] = []


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG.append(line)


def day(ts) -> str:
    return datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


class StudyLedger(CsvLedger):
    """Registro en CSV que además guarda el capital en memoria (para elegir padres en la evolución)."""

    def __init__(self, folder):
        super().__init__(folder, run_id="estudio")
        self.mem: dict[str, list] = {}
        self.trade_count: dict[str, int] = {}

    def equity(self, ts, bot, equity, cash, exposure):
        super().equity(ts, bot, equity, cash, exposure)
        self.mem.setdefault(bot, []).append((ts, equity))

    def trade(self, f):
        super().trade(f)
        self.trade_count[f.bot] = self.trade_count.get(f.bot, 0) + 1

    def scores(self, names: list[str], now: int, window_days: float, ppy: float) -> dict[str, float]:
        """Puntaje de cada bot contra los bots al azar en su misma ventana reciente."""
        lo = now - window_days * DAY
        cols = {}
        for n in set(names) | {b for b in self.mem if b.startswith("_luck_")}:
            pts = [(t, e) for t, e in self.mem.get(n, []) if t >= lo]
            if pts:
                cols[n] = pd.Series(dict(pts))
        wide = pd.DataFrame(cols).sort_index()
        return recent_scores(wide, [n for n in names if n in wide], window_days, ppy)


# ---------------------------------------------------------------- simulación
def simulate(cfg: dict, frames: dict[str, pd.DataFrame], sc: dict) -> dict:
    ap, ev = cfg["autopilot"], cfg["autopilot"]["evolution"]
    every_days = sc.get("every_days", ev["every_days"])
    data_days = sc.get("data_days", ev["data_days"])
    record_min = sc.get("record_every_min", 240)
    ppy = 365 * 24 * 60 / record_min

    market = Market(frames)
    ts = market.ts
    start_ts = int(ts[0]) + data_days * DAY                 # la primera evolución ya tiene su historia
    start_k = int(np.searchsorted(ts, start_ts))
    log(f"Simulación: {day(ts[start_k])} → {day(ts[-1])} ({(ts[-1] - ts[start_k]) / DAY:.0f} días, "
        f"{len(market) - start_k} velas). Evolución cada {every_days} días con {data_days} días de historia.")

    shutil.rmtree(RUN_DIR, ignore_errors=True)
    ledger = StudyLedger(RUN_DIR)
    ledger.start_run("estudio histórico", {})
    pop = [{**copy.deepcopy(s), "born_ts": int(ts[start_k]), "status": "active", "origin": "inicial"}
           for s in ap["initial_population"]]
    bots = [bot_from_spec(p, cfg) for p in pop]
    freqs = ["4h", "12h", "1d", "3d"]
    luck = [RandomBot(f"_luck_{i:02d}", every=freqs[i % 4], params={"seed": 1000 + i})
            for i in range(ap["luck_bots"])]
    arena = Arena(cfg, bots, market, ledger, luck_bots=luck, record_every_min=record_min)
    arena.warmup = 0

    gen, evo_rows, gen_summary = 0, [], []
    next_evo = start_ts + every_days * DAY
    t0 = time.time()
    for k in range(start_k, len(market)):
        arena.on_bar(k)
        t = int(ts[k])
        if t < next_evo:
            continue
        next_evo += every_days * DAY
        gen += 1
        ledger.commit()
        lo = t - data_days * DAY
        hist = {s: df[(df.ts >= lo) & (df.ts <= t)].reset_index(drop=True) for s, df in frames.items()}
        active = [p for p in pop if p["status"] == "active" and p["type"] in SPACE]
        score = ledger.scores([p["name"] for p in active], t, ev.get("rank_window_days", 90), ppy)
        sc_of = lambda p: score.get(p["name"], float("nan"))                                   # noqa: E731
        parents = sorted([p for p in active if sc_of(p) == sc_of(p)], key=sc_of, reverse=True)[:3]
        promoted, res = run_generation(cfg, hist, parents, active, gen, seed=gen * 7919 + t % 10007,
                                       n_mutations=ev["n_mutations"], n_random=ev["n_random"],
                                       max_promote=ev["max_promote"], log=lambda *_: None)
        for spec in promoted:
            p = {**spec, "born_ts": t, "status": "active", "origin": f"generación {gen}"}
            pop.append(p)
            arena.add_bot(bot_from_spec(p, cfg))
        retired = [(p, "eliminado por el gestor de riesgo") for p in active if arena.risk.is_killed(p["name"])]
        gone = {p["name"] for p, _ in retired}
        alive = [p for p in pop if p["status"] == "active" and p["type"] in SPACE and p["name"] not in gone]
        excess = len(alive) - ev["max_active"]
        old = [p for p in alive if t - p["born_ts"] >= ev["min_days_before_retire"] * DAY]
        old = [p for p in old if sc_of(p) == sc_of(p)]                 # sin datos suficientes: no se juzga
        for p in sorted(old, key=sc_of)[:max(excess, 0)]:
            retired.append((p, "de los peores en vivo"))
        for p, why in retired:
            p.update(status="retired", retired_ts=t, retired_why=why)
            arena.remove_bot(p["name"])
        r = res.assign(generation=gen, date=day(t))
        evo_rows.append(r.drop(columns=["spec"]).assign(params=[json.dumps(s.get("params", {})) for s in res["spec"]],
                                                        every=[s.get("every") for s in res["spec"]],
                                                        type=[s["type"] for s in res["spec"]]))
        gen_summary.append({"generation": gen, "date": day(t), "tested": int((res.role == "candidato").sum()),
                            "promoted": [s["name"] for s in promoted], "retired": [p["name"] for p, _ in retired],
                            "active": sum(1 for p in pop if p["status"] == "active")})
        el = time.time() - t0
        frac = (k - start_k) / max(len(market) - start_k, 1)
        log(f"  gen {gen:3d} {day(t)}: +{len(promoted)} -{len(retired)} · activos "
            f"{gen_summary[-1]['active']} · {frac:.0%} · {el / 60:.1f} min (faltan ~{el / max(frac, 1e-9) * (1 - frac) / 60:.0f})")
    ledger.commit()
    log(f"Simulación terminada en {(time.time() - t0) / 60:.1f} min: {gen} generaciones, "
        f"{sum(1 for p in pop if p['origin'].startswith('gener'))} bots promovidos en total.")
    evo = pd.concat(evo_rows, ignore_index=True) if evo_rows else pd.DataFrame()
    return {"pop": pop, "evo": evo, "gens": gen_summary, "ledger": ledger, "ppy": ppy,
            "start_ts": int(ts[start_k]), "end_ts": int(ts[-1])}


# ---------------------------------------------------------------- análisis
def portfolio_index(wide: pd.DataFrame, cols: list[str]) -> pd.Series:
    """Repartir la plata en partes iguales entre los bots activos en cada momento.
    Si no hay ninguno activo, la cartera queda en efectivo (retorno 0)."""
    if not cols:
        return pd.Series(1.0, index=wide.index)
    sub = wide[cols]
    r = sub.pct_change()
    valid = sub.notna() & sub.shift(1).notna()
    avg = r.where(valid).mean(axis=1).fillna(0.0)
    return (1 + avg).cumprod() * 10_000


def yearly_returns(series: dict[str, pd.Series]) -> pd.DataFrame:
    rows = {}
    for name, s in series.items():
        s = s.dropna()
        if s.empty:
            continue
        idx = pd.to_datetime(s.index, unit="ms", utc=True)
        y = pd.Series(s.values, index=idx)
        out = {}
        for year, g in y.groupby(y.index.year):
            prev = y[y.index < g.index[0]]
            base = prev.iloc[-1] if len(prev) else g.iloc[0]
            out[str(year)] = (g.iloc[-1] / base - 1) * 100
        rows[name] = out
    return pd.DataFrame(rows).T


def analyze(cfg: dict, sim: dict) -> dict:
    cash = cfg["capital"]["starting_cash"]
    ledger: StudyLedger = sim["ledger"]
    db = RUN_DIR / "estudio.db"
    run = ledger.to_sqlite(db, mode="estudio histórico")
    data = load_run(str(db), run)
    table, wide = leaderboard(data, cash, min_days=cfg["autopilot"]["min_days_for_verdict"])
    ppy = sim["ppy"]
    pop = {p["name"]: p for p in sim["pop"]}

    initial = [n for n, p in pop.items() if p["origin"] == "inicial" and n != "buy_and_hold" and n in wide]
    promoted = [n for n, p in pop.items() if p["origin"].startswith("gener") and n in wide]
    luck_cols = [c for c in wide.columns if c.startswith("_luck_")]
    port = {
        "cartera_proceso": portfolio_index(wide, initial + promoted),
        "cartera_evolutiva": portfolio_index(wide, promoted),
        "cartera_azar": portfolio_index(wide, luck_cols),
    }
    bh = wide["buy_and_hold"].dropna()
    pstats = {}
    for name, s in {**port, "buy_and_hold": bh}.items():
        st = stats_from_equity(s, ppy)
        st["psr"] = probabilistic_sharpe(s.pct_change().dropna().to_numpy())
        pstats[name] = st

    # bots promovidos: cómo rindieron DESPUÉS de ser elegidos
    pr = table[table.index.isin(promoted)].copy()
    lived = pr[pr["days"] >= 14]
    evo = sim["evo"]
    exam = evo[evo.decision == "promovido"].set_index("name")["oos_sharpe"] if len(evo) else pd.Series(dtype=float)
    lived = lived.assign(exam_sharpe=exam.reindex(lived.index))
    corr = float("nan")
    if lived["exam_sharpe"].notna().sum() >= 8:
        corr = float(lived[["exam_sharpe", "sharpe"]].dropna().corr(method="spearman").iloc[0, 1])
    promo = {
        "n_promoted": len(promoted),
        "n_evaluated": int(len(lived)),
        "pct_positive": float((lived["return_pct"] > 0).mean() * 100) if len(lived) else float("nan"),
        "median_luck_pctl": float(lived["luck_pctl_sharpe"].median()) if len(lived) else float("nan"),
        "pct_beat_bh": float((lived["sharpe"] > lived["bh_sharpe_same_window"]).mean() * 100) if len(lived) else float("nan"),
        "exam_vs_live_corr": corr,
        "n_candidates_tested": int((evo.role == "candidato").sum()) if len(evo) else 0,
    }

    yearly = yearly_returns({"Comprar y mantener": bh,
                             **{n: wide[n] for n in initial},
                             "Cartera del proceso": port["cartera_proceso"],
                             "Cartera evolutiva": port["cartera_evolutiva"],
                             "Cartera al azar": port["cartera_azar"]})
    return {"table": table, "wide": wide, "port": port, "pstats": pstats, "promo": promo, "yearly": yearly,
            "initial": initial, "promoted": promoted, "db": db, "run": run}


# ---------------------------------------------------------------- conclusiones
def f1(v, suf="", signed=False):
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    return f"{v:+.1f}{suf}" if signed else f"{v:.1f}{suf}"


def f2(v):
    return "—" if v is None or (isinstance(v, float) and not math.isfinite(v)) else f"{v:.2f}"


def conclusions(a: dict) -> list[str]:
    ps, pm, t = a["pstats"], a["promo"], a["table"]
    out = []
    bh, pro, evo, az = ps["buy_and_hold"], ps["cartera_proceso"], ps["cartera_evolutiva"], ps["cartera_azar"]

    cands = t[t.verdict.str.startswith("Candidato")]
    if len(cands):
        names = ", ".join(f"`{n}`" for n in cands.index[:5])
        out.append(f"**Bots individuales:** {len(cands)} pasaron todos los filtros ({names}). Ojo: se probaron "
                   f"{len(t)} bots, así que algunos pueden haber pasado por suerte; mirá cuánto vivieron y cuánto ganaron.")
    else:
        out.append(f"**Bots individuales:** ninguno de los {len(t) - 1} bots pasó todos los filtros "
                   "(ventaja estadística, ganarle al 95% del azar y a comprar y mantener).")

    beats_bh = pro.get("sharpe", -9) > bh.get("sharpe", 9)
    beats_az = pro.get("sharpe", -9) > az.get("sharpe", 9)
    sig = pro.get("psr", 0) >= 0.95
    if sig and beats_bh and beats_az:
        out.append(f"**El proceso completo:** repartir la plata entre los bots que la arena tenía activos rindió "
                   f"{f1(pro.get('return_pct'), '%', True)} con Sharpe {f2(pro.get('sharpe'))}, mejor que comprar y "
                   f"mantener ({f1(bh.get('return_pct'), '%', True)}, Sharpe {f2(bh.get('sharpe'))}) y que una cartera "
                   "al azar, con evidencia estadística. Es un resultado prometedor que vale la pena verificar en vivo.")
    else:
        why = []
        if not sig:
            why.append(f"su ventaja no es estadísticamente sólida (probabilidad {f1(pro.get('psr', float('nan')) * 100, '%')}, hace falta 95%)")
        if not beats_bh:
            why.append("no le ganó a comprar y mantener ajustado por riesgo")
        if not beats_az:
            why.append("no le ganó a una cartera de bots al azar")
        out.append(f"**El proceso completo:** repartir la plata entre los bots activos rindió "
                   f"{f1(pro.get('return_pct'), '%', True)} (Sharpe {f2(pro.get('sharpe'))}, caída máxima "
                   f"{f1(pro.get('max_dd_pct'), '%')}) contra {f1(bh.get('return_pct'), '%', True)} de comprar y mantener "
                   f"(Sharpe {f2(bh.get('sharpe'))}, caída máxima {f1(bh.get('max_dd_pct'), '%')}). Pero " + "; ".join(why) + ".")

    if pm["n_evaluated"] >= 5:
        p = pm["median_luck_pctl"]
        skill = p >= 60
        out.append(f"**¿Aprender sirve?** La evolución eligió {pm['n_promoted']} bots entre {pm['n_candidates_tested']} candidatos. "
                   f"Después de ser elegidos, {f1(pm['pct_positive'], '%')} ganó plata y su percentil mediano contra los bots "
                   f"al azar fue {f1(p)} (por pura suerte sería 50). "
                   + ("Eso sugiere que el examen sí detecta algo." if skill else
                      "Eso indica que el examen no logró predecir qué bots iban a andar bien: lo que funcionó en el pasado reciente no siguió funcionando."))
        if math.isfinite(pm["exam_vs_live_corr"]):
            c = pm["exam_vs_live_corr"]
            out.append(f"La relación entre la nota del examen y el rendimiento posterior fue {c:+.2f} "
                       f"(1 = la nota predice perfecto, 0 = no predice nada).")
    else:
        out.append("**¿Aprender sirve?** Muy pocos bots promovidos vivieron lo suficiente para evaluarlos.")
    return out


def write_reports(cfg: dict, sim: dict, a: dict, meta: dict) -> None:
    RES.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    t = a["table"]
    cols = ["days", "return_pct", "sharpe", "max_dd_pct", "psr", "luck_pctl_sharpe", "trades", "fees_usdt", "verdict"]
    t[cols].round(3).to_csv(RES / "ranking.csv")
    a["yearly"].round(2).to_csv(RES / "por_anio.csv")
    if len(sim["evo"]):
        sim["evo"].round(3).to_csv(RES / "evolucion.csv", index=False)
    pd.DataFrame(sim["pop"]).to_csv(RES / "poblacion.csv", index=False)
    summary = {"meta": meta, "portfolios": a["pstats"], "promoted": a["promo"], "generations": sim["gens"]}
    (RES / "resumen.json").write_text(json.dumps(summary, indent=1, default=float, ensure_ascii=False))
    (RES / "log.txt").write_text("\n".join(LOG) + "\n", encoding="utf-8")

    concl = conclusions(a)
    ps = a["pstats"]
    names = {"buy_and_hold": "Comprar y mantener", "cartera_proceso": "Cartera del proceso (todos los bots activos)",
             "cartera_evolutiva": "Cartera evolutiva (solo los bots que creó la evolución)",
             "cartera_azar": "Cartera al azar (los 20 bots aleatorios)"}

    md = ["# Estudio histórico", "",
          f"Simulación de la arena completa sobre **{meta['days']:.0f} días de "
          f"{'precios inventados (prueba)' if meta.get('synthetic') else 'precios reales'}** "
          f"({meta['start']} → {meta['end']}, velas de 15 min de {meta['source']}, {', '.join(meta['symbols'])}). "
          "Mismos bots, mismo gestor de riesgo, mismos costos y la misma evolución semanal que corre en vivo, "
          "usando en cada momento solo los datos disponibles hasta ese momento.", "",
          "## Conclusiones", ""] + [f"- {c}" for c in concl] + [
          "", "## Carteras", "",
          "| | Retorno | Sharpe | Caída máx. | Prob. ventaja real |", "|---|---:|---:|---:|---:|"]
    for k in ("buy_and_hold", "cartera_proceso", "cartera_evolutiva", "cartera_azar"):
        s = ps[k]
        md.append(f"| {names[k]} | {f1(s.get('return_pct'), '%', True)} | {f2(s.get('sharpe'))} | "
                  f"{f1(s.get('max_dd_pct'), '%')} | {f1(s.get('psr', float('nan')) * 100, '%')} |")
    y = a["yearly"]
    md += ["", "## Por año (retorno %)", "", "| | " + " | ".join(y.columns) + " |", "|---|" + "---:|" * len(y.columns)]
    for n, r in y.iterrows():
        md.append(f"| {n} | " + " | ".join(f1(v, '', True) for v in r.values) + " |")
    pm = a["promo"]
    md += ["", "## Evolución", "",
           f"- Generaciones: {len(sim['gens'])} · candidatos probados: {pm['n_candidates_tested']} · promovidos: {pm['n_promoted']}",
           f"- De los promovidos que vivieron al menos 14 días ({pm['n_evaluated']}): {f1(pm['pct_positive'], '%')} ganó plata, "
           f"{f1(pm['pct_beat_bh'], '%')} le ganó a comprar y mantener en su mismo período, percentil mediano contra el azar: {f1(pm['median_luck_pctl'])}.",
           "", "## Bots iniciales", "", "| Bot | Retorno | Sharpe | Caída máx. | Trades | Veredicto |", "|---|---:|---:|---:|---:|---|"]
    for n in ["buy_and_hold"] + a["initial"]:
        if n in t.index:
            r = t.loc[n]
            md.append(f"| `{n}` | {f1(r['return_pct'], '%', True)} | {f2(r['sharpe'])} | {f1(r['max_dd_pct'], '%')} | "
                      f"{int(r['trades'])} | {r['verdict']} |")
    md += ["", "## Cómo leer esto", "",
           "- **Cartera del proceso** es lo que hubieras obtenido repartiendo la plata en partes iguales entre los bots que la arena tenía activos en cada momento. Es la mejor medida de si *el sistema completo* sirve.",
           "- **Cartera al azar** es lo mismo pero con los bots que operan al azar: es la vara contra la que hay que ganar.",
           "- **Sharpe** mide retorno por unidad de riesgo. **Prob. ventaja real** es la probabilidad de que el Sharpe sea mayor que cero de verdad y no por ruido; hace falta 95% o más.",
           "- Un backtest, aunque sea cuidadoso, es más optimista que la realidad: no simula caídas del exchange, órdenes que no se llenan ni cambios bruscos de liquidez.",
           "", f"📊 Tablero interactivo: https://dcohenm.github.io/trading-arena/estudio/",
           "", f"*Generado el {meta['generated']} en {meta['minutes']:.0f} minutos. Todo es simulado; no es asesoramiento financiero.*"]
    (ROOT / "ESTUDIO.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    # tablero: carteras + bots iniciales + bots al azar (para la franja de suerte)
    import sqlite3
    from arena.report import build_report
    keep = set(["buy_and_hold"] + a["initial"] + [c for c in a["wide"].columns if c.startswith("_luck_")])
    con = sqlite3.connect(str(a["db"]))
    con.execute(f"DELETE FROM equity WHERE bot NOT IN ({','.join('?' * len(keep))})", list(keep))
    rows = []
    for name, s in a["port"].items():
        if name == "cartera_azar":
            continue
        rows += [(a["run"], int(ts), name, float(v), 0.0, 0.0) for ts, v in s.items() if v == v]
    con.executemany("INSERT INTO equity VALUES (?,?,?,?,?,?)", rows)
    con.execute("DELETE FROM decisions")
    con.commit()
    con.close()
    tr = a["table"]
    override = {k: {"trades": int(tr.loc[tr.index.isin(a["initial"] + a["promoted"] if k == "cartera_proceso" else a["promoted"]), "trades"].sum()),
                    "fees_usdt": float("nan"), "avg_exposure_pct": float("nan")}
                for k in ("cartera_proceso", "cartera_evolutiva")}
    html_concl = "".join(f"<li>{_md(c)}</li>" for c in concl)
    yhtml = "<table><thead><tr><th></th>" + "".join(f"<th class='num'>{c}</th>" for c in y.columns) + "</tr></thead><tbody>"
    for n, r in y.iterrows():
        yhtml += f"<tr><td class='bot'>{n}</td>" + "".join(
            f"<td class='num {'pos' if v > 0 else 'neg' if v < 0 else ''}'>{f1(v, '%', True)}</td>" for v in r.values) + "</tr>"
    yhtml += "</tbody></table>"
    extra = (f"<div class='card'><h2>Conclusiones</h2><ul style='margin:0;padding-left:18px'>{html_concl}</ul></div>"
             f"<div class='card'><h2>Retorno por año</h2><div class='scroll'>{yhtml}</div></div>")
    build_report(str(a["db"]), str(DOCS / "index.html"), cfg["capital"]["starting_cash"], a["run"],
                 note=(f"Estudio histórico sobre {'datos inventados (prueba)' if meta.get('synthetic') else 'precios reales'} "
                       f"({meta['start']} → {meta['end']}). Todo simulado."),
                 min_days=cfg["autopilot"]["min_days_for_verdict"], extra_html=extra, inline_chartjs=False,
                 trade_override=override,
                 labels_map={"cartera_proceso": "Cartera del proceso", "cartera_evolutiva": "Cartera evolutiva"})
    log("Reportes escritos: ESTUDIO.md, study/results/, docs/estudio/index.html")


def _md(s: str) -> str:
    import html
    import re
    s = html.escape(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", s)


# ---------------------------------------------------------------- main
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--synthetic", action="store_true")
    p.add_argument("--years", type=float, default=None)
    p.add_argument("--every-days", type=int, default=None)
    a = p.parse_args()
    cfg = load_config(ROOT / "config.yaml")
    sc = dict(cfg.get("study", {}))
    years = a.years or sc.get("years", 3.5)
    if a.every_days:
        sc["every_days"] = a.every_days
    syms, tf = cfg["market"]["symbols"], cfg["market"]["timeframe"]
    t0 = time.time()
    if a.synthetic:
        frames = synthetic(syms, int(years * 365 * 96), tf, seed=11)
        source = "datos SINTÉTICOS (prueba)"
        log("⚠ Datos sintéticos: esto solo prueba que el estudio funciona.")
    else:
        log(f"Bajando {years} años de velas de {tf} para {', '.join(syms)}…")
        frames, source = fetch_recent(sc.get("exchanges", ["coinbase", "okx", "bingx"]), syms, tf,
                                      years * 365, min_coverage=0.85, log=log)
        log(f"Datos de {source}: {len(next(iter(frames.values())))} velas alineadas")
    sim = simulate(cfg, frames, sc)
    res = analyze(cfg, sim)
    meta = {"start": day(sim["start_ts"]), "end": day(sim["end_ts"]), "days": (sim["end_ts"] - sim["start_ts"]) / DAY,
            "source": source, "symbols": syms, "synthetic": a.synthetic, "minutes": (time.time() - t0) / 60,
            "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    write_reports(cfg, sim, res, meta)
    for c in conclusions(res):
        log(c)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Piloto automático: lo ejecuta GitHub Actions cada hora, sin intervención.

En cada corrida:
  1. baja precios reales recientes (si un exchange falla, prueba otro)
  2. procesa las velas nuevas desde la última corrida: los bots deciden, el gestor de riesgo
     filtra y el broker simulado ejecuta (exactamente el mismo motor que el backtest)
  3. una vez por semana corre la evolución: crea variantes de los mejores bots, las examina
     con datos que no se usaron para elegirlas, suma las que aprueban y retira a las peores
  4. guarda todo en state/ y actualiza el README (resumen) y docs/index.html (tablero)

Uso:  python autopilot.py tick        (lo que corre cada hora)
      python autopilot.py evolve      (forzar una evolución ahora)
      python autopilot.py report      (solo regenerar resumen y tablero)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from arena.bots import RandomBot, bot_from_spec           # noqa: E402
from arena.core import load_config                         # noqa: E402
from arena.csvledger import CsvLedger                      # noqa: E402
from arena.data import fetch_recent                        # noqa: E402
from arena.engine import Arena, Market                     # noqa: E402
from arena.evolve import SPACE, run_generation             # noqa: E402

STATE_DIR = ROOT / "state"
STATE = STATE_DIR / "state.json"
EVOLOG = STATE_DIR / "evolution.csv"
DOCS = ROOT / "docs"
DAY = 86_400_000


def now_ms() -> int:
    return int(time.time() * 1000)


def fmt_ts(ms) -> str:
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


RUN_LOG: list[str] = []


def log(msg: str) -> None:
    print(msg, flush=True)
    RUN_LOG.append(msg)


def save_run_log() -> None:
    """Deja el registro de la última corrida en state/last_run.log (para ver qué pasó sin entrar a Actions)."""
    STATE_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    (STATE_DIR / "last_run.log").write_text(f"Corrida: {stamp}\n" + "\n".join(RUN_LOG) + "\n", encoding="utf-8")


# ---------------- estado ----------------
def load_state(cfg: dict) -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text())
    pop = [{**s, "born_ts": None, "status": "active", "origin": "inicial"} for s in cfg["autopilot"]["initial_population"]]
    return {"created_ts": None, "last_ts": None, "exchange": None, "generation": 0, "last_evolution_ts": None,
            "population": pop, "arena": {}, "failures": 0, "alerts": [], "llm_spent": {}}


def save_state(st: dict) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1, default=float))
    tmp.replace(STATE)


def make_llm(cfg: dict, st: dict):
    if not os.environ.get(cfg["llm"].get("api_key_env", "XAI_API_KEY")):
        return None
    from arena.llm import GrokClient
    llm = GrokClient(cfg["llm"])
    llm.spent = dict(st.get("llm_spent", {}))
    return llm


def ensure_grok_population(cfg: dict, st: dict, llm) -> None:
    if llm is None:
        return
    names = {p["name"] for p in st["population"]}
    for s in cfg["autopilot"].get("grok_population", []):
        if s["name"] not in names:
            st["population"].append({**s, "born_ts": st.get("last_ts"), "status": "active", "origin": "grok"})
            log(f"  + {s['name']} activado (hay API key de xAI)")


def build_arena(cfg: dict, st: dict, market: Market, ledger, llm) -> Arena:
    bots = []
    for spec in st["population"]:
        if spec["status"] != "active":
            continue
        b = bot_from_spec(spec, cfg, llm)
        if b is not None:
            bots.append(b)
    n_luck = cfg["autopilot"]["luck_bots"]
    freqs = ["4h", "12h", "1d", "3d"]
    luck = [RandomBot(f"_luck_{i:02d}", every=freqs[i % 4], params={"seed": 1000 + i}) for i in range(n_luck)]
    arena = Arena(cfg, bots, market, ledger, luck_bots=luck, record_every_min=60)
    arena.warmup = 0                                   # la historia bajada ya alcanza como contexto
    if st.get("arena"):
        arena.import_state(st["arena"])
    return arena


# ---------------- alertas (issues de GitHub = te llega un mail) ----------------
def open_issue(st: dict, key: str, title: str, body: str) -> None:
    if key in st["alerts"]:
        return
    st["alerts"].append(key)
    if not os.environ.get("GITHUB_ACTIONS"):
        log(f"  [alerta] {title}")
        return
    try:
        subprocess.run(["gh", "issue", "create", "--title", title, "--body", body], check=True, timeout=60)
        log(f"  alerta creada: {title}")
    except Exception as e:                             # una alerta fallida no frena la arena
        log(f"  ⚠ no se pudo crear la alerta: {e}")


# ---------------- corrida horaria ----------------
def tick(cfg: dict, force_evolve: bool = False) -> None:
    ap = cfg["autopilot"]
    st = load_state(cfg)
    llm = make_llm(cfg, st)
    ensure_grok_population(cfg, st, llm)

    order = [st["exchange"]] + [e for e in ap["exchanges"] if e != st["exchange"]] if st["exchange"] else ap["exchanges"]
    try:
        frames, ex_used = fetch_recent(order, cfg["market"]["symbols"], cfg["market"]["timeframe"], ap["history_days"], log=log)
    except Exception as e:
        st["failures"] = st.get("failures", 0) + 1
        log(f"✗ sin datos ({st['failures']} corridas seguidas): {e}")
        if st["failures"] >= ap["alert_after_failures"]:
            open_issue(st, f"nodata-{st['failures'] // 24}", "La arena no puede bajar precios",
                       f"Hace {st['failures']} corridas que ningún exchange responde.\n\nÚltimo error:\n```\n{e}\n```\n"
                       "Si se resuelve solo, podés cerrar este aviso.")
        save_state(st)
        write_outputs(cfg, st)
        return
    if st.get("failures"):
        log(f"  datos recuperados después de {st['failures']} corridas fallidas")
    st["failures"] = 0
    if st["exchange"] != ex_used:
        log(f"  usando datos de {ex_used}")
        st["exchange"] = ex_used

    market = Market(frames)
    ledger = CsvLedger(STATE_DIR)
    ledger.start_run("piloto automático", {})
    arena = build_arena(cfg, st, market, ledger, llm)

    ts = market.ts
    if st["last_ts"] is None:
        todo = [len(market) - 1]                       # primera corrida: arranca en la última vela
        st["created_ts"] = int(ts[-1])
        for p in st["population"]:
            p["born_ts"] = p["born_ts"] or int(ts[-1])
    else:
        todo = [k for k in range(len(market)) if int(ts[k]) > st["last_ts"]]
    for k in todo:
        arena.on_bar(k)
    if todo:
        st["last_ts"] = int(ts[todo[-1]])
    ledger.commit()
    log(f"✓ {len(todo)} velas nuevas procesadas (hasta {fmt_ts(st['last_ts'])}) con datos de {ex_used}")

    # evolución semanal
    ev = ap["evolution"]
    due = st["last_evolution_ts"] is None and st["created_ts"] and st["last_ts"] - st["created_ts"] >= ev["every_days"] * DAY
    due = due or (st["last_evolution_ts"] and st["last_ts"] - st["last_evolution_ts"] >= ev["every_days"] * DAY)
    if force_evolve or due:
        try:
            evolve(cfg, st, arena, order)
        except Exception as e:
            log(f"⚠ la evolución falló (se reintenta la semana que viene): {e}")
            st["last_evolution_ts"] = st["last_ts"]

    st["arena"] = arena.export_state()
    if llm is not None:
        st["llm_spent"] = {d: v for d, v in llm.spent.items()}
    save_state(st)
    write_outputs(cfg, st)


# ---------------- evolución ----------------
def live_table(cfg: dict, with_wide: bool = False):
    from arena.metrics import leaderboard, load_run
    ledger = CsvLedger(STATE_DIR)
    if not (STATE_DIR / "equity.csv").exists():
        return None
    db = STATE_DIR / "_tmp.db"
    run = ledger.to_sqlite(db)
    try:
        table, wide = leaderboard(load_run(str(db), run), cfg["capital"]["starting_cash"],
                                  min_days=cfg["autopilot"]["min_days_for_verdict"])
    except SystemExit:
        table, wide = None, None
    db.unlink(missing_ok=True)
    return (table, wide) if with_wide else table


def evolve(cfg: dict, st: dict, arena: Arena, exchanges: list[str]) -> None:
    ev = cfg["autopilot"]["evolution"]
    st["generation"] += 1
    gen = st["generation"]
    log(f"⟳ Evolución, generación {gen}")
    frames, _ = fetch_recent(exchanges, cfg["market"]["symbols"], cfg["market"]["timeframe"], ev["data_days"], log=log)

    from arena.metrics import recent_scores
    table, wide = live_table(cfg, with_wide=True)
    active = [p for p in st["population"] if p["status"] == "active" and p["type"] in SPACE]
    score = (recent_scores(wide, [p["name"] for p in active], ev.get("rank_window_days", 90), 365 * 24)
             if wide is not None else {})
    sc_of = lambda p: score.get(p["name"], float("nan"))                                       # noqa: E731
    parents = sorted([p for p in active if sc_of(p) == sc_of(p)], key=sc_of, reverse=True)[:3]
    promoted, res = run_generation(cfg, frames, parents, active, gen, seed=gen * 7919 + st["last_ts"] % 10007,
                                   n_mutations=ev["n_mutations"], n_random=ev["n_random"],
                                   max_promote=ev["max_promote"], log=log)

    for spec in promoted:
        p = {**spec, "born_ts": st["last_ts"], "status": "active", "origin": f"generación {gen}"}
        st["population"].append(p)
        arena.add_bot(bot_from_spec(p, cfg))
        log(f"  + entra {p['name']} ({p['type']}, padre: {spec.get('parent') or 'nuevo al azar'})")

    # retiros: eliminados por el gestor de riesgo, y los peores si hay demasiados
    retired = []
    for p in active:
        if arena.risk.is_killed(p["name"]):
            retired.append((p, "eliminado por el gestor de riesgo"))
    alive = [p for p in st["population"] if p["status"] == "active" and p["type"] in SPACE
             and p not in [r[0] for r in retired]]
    excess = len(alive) - ev["max_active"]
    old = [p for p in alive if p.get("born_ts") and st["last_ts"] - p["born_ts"] >= ev["min_days_before_retire"] * DAY]
    old = [p for p in old if sc_of(p) == sc_of(p)]
    for p in sorted(old, key=sc_of)[:max(excess, 0)]:
        retired.append((p, "de los peores en vivo"))
    for p, why in retired:
        p["status"], p["retired_ts"], p["retired_why"] = "retired", st["last_ts"], why
        arena.remove_bot(p["name"])
        log(f"  - se retira {p['name']} ({why})")

    # registro de la generación
    import pandas as pd
    out = res.assign(generation=gen, ts=st["last_ts"], type=[s["type"] for s in res["spec"]],
                     every=[s.get("every") for s in res["spec"]],
                     params=[json.dumps(s.get("params", {})) for s in res["spec"]])
    out = out[["generation", "ts", "name", "type", "every", "params", "role", "trades",
               "is_sharpe", "oos_sharpe", "oos_return", "oos_dd", "decision"]].round(3)
    retired_rows = pd.DataFrame([{"generation": gen, "ts": st["last_ts"], "name": p["name"], "type": p["type"],
                                  "every": p.get("every"), "params": json.dumps(p.get("params", {})),
                                  "role": "actual", "decision": f"retirado: {why}"} for p, why in retired])
    out = pd.concat([out, retired_rows], ignore_index=True)
    out.to_csv(EVOLOG, mode="a", header=not EVOLOG.exists(), index=False)
    st["last_evolution_ts"] = st["last_ts"]
    st.setdefault("evolution_summary", []).append({
        "generation": gen, "ts": st["last_ts"], "tested": int((res.role == "candidato").sum()),
        "promoted": [s["name"] for s in promoted], "retired": [p["name"] for p, _ in retired]})


# ---------------- resumen (README) y tablero (docs/index.html) ----------------
def _pct(v, d=1):
    return "—" if v is None or v != v else f"{v:+.{d}f}%"


def _num(v, d=2):
    return "—" if v is None or v != v else f"{v:.{d}f}"


def headline(table, st, min_days) -> str:
    if table is None or not len(table):
        return "Recién arrancó. Todavía no hay datos suficientes para mostrar resultados."
    days = (st["last_ts"] - st["created_ts"]) / DAY if st.get("created_ts") else 0
    active = [p["name"] for p in st["population"] if p["status"] == "active"]
    t = table[table.index.isin(active)]
    cands = t[t.verdict.str.startswith("Candidato")]
    others = t[(t.index != "buy_and_hold") & t["sharpe"].notna()]
    bh = t.loc["buy_and_hold", "return_pct"] if "buy_and_hold" in t.index else float("nan")
    if len(cands):
        names = ", ".join(f"**{n}**" for n in cands.index)
        return (f"🔎 {names} muestra una ventaja que pasa todos los filtros estadísticos después de "
                f"{cands['days'].max():.0f} días. Sigue siendo simulado: vale la pena mirarlo con atención, "
                "no salir corriendo a poner plata.")
    if days < 7:
        return (f"Lleva {days:.1f} días. En las primeras semanas los números son ruido: "
                "todavía no se puede sacar ninguna conclusión.")
    if not len(others):
        return f"Lleva {days:.0f} días. Todavía no hay bots con datos suficientes para comparar."
    best = others.sort_values("sharpe", ascending=False).index[0]
    r = others.loc[best, "return_pct"]
    cmp = f" Comprar y mantener va {_pct(bh)}." if bh == bh else ""
    return (f"Lleva {days:.0f} días. Ningún bot muestra todavía una ventaja real. "
            f"El que mejor va (ajustado por riesgo) es **{best}** con {_pct(r)}, pero puede ser suerte.{cmp}")


def write_outputs(cfg: dict, st: dict) -> None:
    from arena.metrics import load_run
    from arena.report import build_report
    min_days = cfg["autopilot"]["min_days_for_verdict"]
    table = live_table(cfg)
    status = {p["name"]: p["status"] for p in st["population"]}

    # alerta si aparece un candidato
    if table is not None:
        for name in table.index[table.verdict.str.startswith("Candidato")]:
            open_issue(st, f"cand-{name}", f"🔎 {name} pasó todos los filtros",
                       f"Después de {table.loc[name, 'days']:.0f} días en paper trading, **{name}** muestra una ventaja "
                       f"estadísticamente significativa (Sharpe {table.loc[name, 'sharpe']:.2f}, retorno "
                       f"{table.loc[name, 'return_pct']:+.1f}%).\n\nTodo es simulado. Revisá el tablero antes de decidir nada.")
        save_state(st)

    # README
    head = headline(table, st, min_days)
    lines = ["# Trading Arena — piloto automático", "",
             "Bots de trading cripto compitiendo con plata **simulada** sobre precios reales. "
             "Corre solo cada hora en GitHub y una vez por semana se mejora solo: prueba variantes "
             "nuevas de los mejores bots y retira a los peores.", "",
             f"> {head}", ""]
    upd = fmt_ts(st["last_ts"]) if st.get("last_ts") else "—"
    since = fmt_ts(st["created_ts"]) if st.get("created_ts") else "—"
    nxt = (fmt_ts((st["last_evolution_ts"] or st["created_ts"]) + cfg["autopilot"]["evolution"]["every_days"] * DAY)
           if st.get("created_ts") else "—")
    lines += [f"**Última actualización:** {upd} · **Desde:** {since} · **Datos:** {st.get('exchange') or '—'} · "
              f"**Generación:** {st.get('generation', 0)} · **Próxima evolución:** {nxt}", ""]
    if table is not None:
        lines += ["## Ranking (bots activos)", "",
                  "| Bot | Días | Retorno | Sharpe | Caída máx. | Trades | Veredicto |",
                  "|---|---:|---:|---:|---:|---:|---|"]
        act = table[table.index.map(lambda n: status.get(n) == "active")]
        for n, r in act.iterrows():
            lines.append(f"| `{n}` | {r['days']:.0f} | {_pct(r['return_pct'])} | {_num(r['sharpe'])} | "
                         f"{abs(r['max_dd_pct']):.1f}% | {int(r['trades'])} | {r['verdict']} |")
        ret = table[table.index.map(lambda n: status.get(n) == "retired")]
        if len(ret):
            lines += ["", "<details><summary>Bots retirados</summary>", "",
                      "| Bot | Días | Retorno | Sharpe |", "|---|---:|---:|---:|"]
            lines += [f"| `{n}` | {r['days']:.0f} | {_pct(r['return_pct'])} | {_num(r['sharpe'])} |" for n, r in ret.iterrows()]
            lines += ["", "</details>"]
    evs = st.get("evolution_summary", [])[-6:]
    if evs:
        lines += ["", "## Evolución", ""]
        for e in reversed(evs):
            pro = ", ".join(f"`{x}`" for x in e["promoted"]) or "ninguno aprobó el examen"
            rt = ", ".join(f"`{x}`" for x in e["retired"]) or "ninguno"
            lines.append(f"- **Generación {e['generation']}** ({fmt_ts(e['ts'])[:10]}): se probaron {e['tested']} "
                         f"variantes. Entraron: {pro}. Se retiraron: {rt}.")
    user_repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in user_repo:
        u, r = user_repo.split("/")
        lines += ["", f"📊 **Tablero completo:** https://{u}.github.io/{r}/"]
    lines += ["", "Para correr backtests o pruebas a mano en tu computadora: [GUIA.md](GUIA.md)."]
    lines += ["", "## Cómo leer esto", "",
              "- **Retorno**: cuánto ganó o perdió desde que entró a la arena (cada bot arranca con 10.000 USDT simulados).",
              "- **Sharpe**: retorno por unidad de riesgo. Más alto es mejor; negativo es perder.",
              "- **Veredicto**: un bot solo es *candidato* si después de al menos "
              f"{min_days} días su ventaja es estadísticamente sólida, le gana al 95% de los bots que operan al azar "
              "y le gana a comprar y mantener. Lo normal es que durante mucho tiempo no haya ninguno.",
              "- Si algún bot pasa todos los filtros, se abre un *Issue* en este repositorio y GitHub te avisa por mail.",
              "", "## Cómo frenarlo", "",
              "Pestaña **Actions** → workflow **Arena** → botón **⋯** → **Disable workflow**. "
              "Para reanudar, el mismo lugar → **Enable workflow**.", "",
              "---", "*Todo es simulado: no hay dinero real ni conexión a ninguna cuenta. No es asesoramiento financiero.*"]
    (ROOT / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # tablero HTML
    if table is not None:
        DOCS.mkdir(exist_ok=True)
        db = STATE_DIR / "_tmp.db"
        run = CsvLedger(STATE_DIR).to_sqlite(db, note="")
        extra = f"<div class='card'><h2>Resumen</h2><p>{_md_to_html(head)}</p></div>"
        build_report(str(db), str(DOCS / "index.html"), cfg["capital"]["starting_cash"], run,
                     note="Todo es simulado: precios reales, dinero ficticio.", min_days=min_days,
                     status=status, extra_html=extra, inline_chartjs=False)
        db.unlink(missing_ok=True)
        (DOCS / ".nojekyll").touch()


def _md_to_html(s: str) -> str:
    import html
    import re
    s = html.escape(s)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)


def main():
    cfg = load_config(ROOT / "config.yaml")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "tick"
    try:
        if cmd == "tick":
            tick(cfg)
        elif cmd == "evolve":
            tick(cfg, force_evolve=True)
        elif cmd == "report":
            write_outputs(cfg, load_state(cfg))
        else:
            raise SystemExit(__doc__)
    except Exception as e:
        log(f"✗ error inesperado: {e.__class__.__name__}: {e}")
        raise
    finally:
        if cmd in ("tick", "evolve"):
            save_run_log()


if __name__ == "__main__":
    main()

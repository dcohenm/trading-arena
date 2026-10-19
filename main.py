#!/usr/bin/env python3
"""Grok Arena — línea de comandos.

  python main.py download --days 365          baja historia real del exchange (datos públicos)
  python main.py backtest                     corre la competencia sobre la historia bajada
  python main.py backtest --synthetic         prueba rápida con datos inventados (sin internet)
  python main.py paper                        paper trading en vivo 24/7
  python main.py paper --resume RUN_ID        retoma una corrida en vivo después de un corte
  python main.py report [--run RUN_ID]        regenera el tablero HTML
  python main.py models                       lista los modelos de Grok disponibles en tu cuenta
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from arena.bots import build_bots, build_luck_bots          # noqa: E402
from arena.core import load_config, parse_minutes            # noqa: E402
from arena.data import download_ohlcv, load_cached, synthetic  # noqa: E402
from arena.engine import Arena, Market                       # noqa: E402
from arena.ledger import Ledger                              # noqa: E402
from arena.llm import GrokClient, LLMError, MockLLM          # noqa: E402
from arena.report import build_report                        # noqa: E402

DB = ROOT / "arena.db"
REPORTS = ROOT / "reports"


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def make_llm(cfg, mode: str):
    if mode == "off":
        return None
    if mode == "mock":
        print("  ℹ Grok SIMULADO (reglas fijas): sirve para probar el sistema, no para evaluar a Grok.")
        return MockLLM()
    try:
        return GrokClient(cfg["llm"])
    except LLMError as e:
        print(f"  ⚠ {e}\n  Los bots de Grok quedan desactivados (o usá --llm mock).")
        return None


def report(cfg, run_id=None, note="", open_it=True):
    REPORTS.mkdir(exist_ok=True)
    out = build_report(str(DB), str(REPORTS / "latest.html"), cfg["capital"]["starting_cash"], run_id, note)
    print(f"Tablero: {out}")
    if open_it:
        try:
            webbrowser.open(Path(out).resolve().as_uri())
        except Exception:
            pass
    return out


def print_table(cfg, run_id):
    from arena.metrics import leaderboard, load_run
    table, _ = leaderboard(load_run(str(DB), run_id), cfg["capital"]["starting_cash"])
    cols = ["return_pct", "sharpe", "max_dd_pct", "psr", "luck_pctl_sharpe", "trades", "fees_usdt", "verdict"]
    with __import__("pandas").option_context("display.width", 200, "display.max_columns", 20,
                                             "display.float_format", "{:,.2f}".format):
        print(table[cols].rename(columns={
            "return_pct": "retorno%", "sharpe": "sharpe", "max_dd_pct": "caida_max%", "psr": "prob_SR>0",
            "luck_pctl_sharpe": "pctl_vs_azar", "trades": "trades", "fees_usdt": "comisiones", "verdict": "veredicto"}))


def cmd_download(cfg, a):
    m = cfg["market"]
    for s in m["symbols"]:
        df = download_ohlcv(m["exchange"], s, m["timeframe"], a.days)
        print(f"{s}: {len(df)} velas guardadas")


def cmd_backtest(cfg, a):
    m = cfg["market"]
    if a.synthetic:
        bars = int(a.days * 24 * 60 / parse_minutes(m["timeframe"]))
        frames = synthetic(m["symbols"], bars, m["timeframe"], seed=a.seed)
        note = "DATOS SINTÉTICOS y Grok simulado: esto solo prueba que el sistema funciona. No dice nada del mercado real."
        llm_mode = "mock" if a.llm == "auto" else a.llm
    else:
        frames = load_cached(m["exchange"], m["symbols"], m["timeframe"])
        note = ""
        llm_mode = "mock" if a.llm == "auto" else a.llm
        if llm_mode == "real":
            print("  ⚠ Backtest con Grok real: Grok ya 'vio' gran parte de esta historia en su entrenamiento,\n"
                  "    así que el resultado está contaminado y además cuesta plata. Lo válido es el paper trading en vivo.")
            note = "Backtest con Grok real: resultado contaminado por lo que el modelo ya conoce del pasado."
    market = Market(frames)
    llm = make_llm(cfg, llm_mode)
    bots, luck = build_bots(cfg, llm), build_luck_bots(cfg)
    run_id = time.strftime("bt-%Y%m%d-%H%M%S")
    ledger = Ledger(DB, run_id)
    ledger.start_run("backtest" + (" sintético" if a.synthetic else ""), cfg, note)
    print(f"Backtest {run_id}: {len(market)} velas · {len(bots)} bots + {len(luck)} al azar")
    arena = Arena(cfg, bots, market, ledger, luck_bots=luck)
    arena.run_backtest()
    ledger.close()
    print_table(cfg, run_id)
    report(cfg, run_id, note, open_it=not a.no_open)


def cmd_paper(cfg, a):
    from arena.live import run_live
    llm = make_llm(cfg, "real" if a.llm == "auto" else a.llm)
    bots, luck = build_bots(cfg, llm), build_luck_bots(cfg)
    run_id = a.resume or time.strftime("live-%Y%m%d-%H%M%S")
    ledger = Ledger(DB, run_id)
    ledger.start_run("paper en vivo", cfg)
    print(f"Corrida {run_id}")
    last = {"t": 0.0}

    def refresh(_arena):
        if time.time() - last["t"] > 3600:          # tablero actualizado cada hora
            last["t"] = time.time()
            try:
                report(cfg, run_id, open_it=False)
            except SystemExit:
                pass

    run_live(cfg, bots, luck, ledger, resume=bool(a.resume), on_new_bar=refresh)


def cmd_report(cfg, a):
    report(cfg, a.run, open_it=not a.no_open)
    print_table(cfg, a.run)


def cmd_models(cfg, a):
    print("\n".join(GrokClient(cfg["llm"]).list_models()))


def main():
    load_env()
    p = argparse.ArgumentParser(description="Grok Arena: competencia de bots de trading cripto (paper)")
    p.add_argument("--config", default=str(ROOT / "config.yaml"))
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("download"); d.add_argument("--days", type=int, default=365)
    b = sub.add_parser("backtest")
    b.add_argument("--synthetic", action="store_true", help="datos inventados para probar sin internet")
    b.add_argument("--days", type=int, default=180, help="días de datos sintéticos")
    b.add_argument("--seed", type=int, default=7)
    b.add_argument("--llm", choices=["auto", "mock", "real", "off"], default="auto",
                   help="auto = simulado en backtest (Grok real contamina el backtest)")
    b.add_argument("--no-open", action="store_true")
    pp = sub.add_parser("paper")
    pp.add_argument("--resume", metavar="RUN_ID")
    pp.add_argument("--llm", choices=["auto", "mock", "real", "off"], default="auto")
    r = sub.add_parser("report"); r.add_argument("--run"); r.add_argument("--no-open", action="store_true")
    sub.add_parser("models")
    a = p.parse_args()
    cfg = load_config(a.config)
    {"download": cmd_download, "backtest": cmd_backtest, "paper": cmd_paper,
     "report": cmd_report, "models": cmd_models}[a.cmd](cfg, a)


if __name__ == "__main__":
    main()

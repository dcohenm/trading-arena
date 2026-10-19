"""Paper trading en vivo, 24/7: datos reales del exchange, órdenes simuladas.

Cada vez que cierra una vela en todos los símbolos, se corre el mismo motor del backtest.
Las órdenes se ejecutan (en papel) al último precio del mercado. El estado se guarda en cada
vela, así que si se corta la luz o reiniciás, con --resume sigue donde estaba.
"""
from __future__ import annotations

import time
import traceback

import pandas as pd

from .core import parse_minutes
from .data import COLS, download_ohlcv, load_cached, make_exchange
from .engine import Arena, Market


def fetch_closed(ex, symbol: str, timeframe: str, since_ts: int) -> pd.DataFrame:
    tf_ms = parse_minutes(timeframe) * 60_000
    rows = ex.fetch_ohlcv(symbol, timeframe, since=since_ts + 1, limit=50)
    df = pd.DataFrame(rows, columns=COLS)
    now = ex.milliseconds()
    return df[(df.ts > since_ts) & (df.ts + tf_ms <= now)]       # solo velas cerradas


def run_live(cfg: dict, bots: list, luck_bots: list, ledger, resume: bool,
             poll_s: int = 20, on_new_bar=None) -> None:
    m = cfg["market"]
    syms, tf = m["symbols"], m["timeframe"]
    print("Bajando historia reciente para que los bots tengan contexto…")
    for s in syms:
        download_ohlcv(m["exchange"], s, tf, days=35)
    frames = load_cached(m["exchange"], syms, tf)
    market = Market(frames)
    arena = Arena(cfg, bots, market, ledger, luck_bots=luck_bots, persist_state=True)
    arena.warmup = 0                                     # la historia ya alcanza como calentamiento
    if resume and arena.load_state():
        print("Estado anterior recuperado: los bots siguen con sus posiciones.")
    ex = make_exchange(m["exchange"])
    tf_ms = parse_minutes(tf) * 60_000
    print(f"Arena en vivo: {len(bots)} bots + {len(luck_bots)} al azar · {', '.join(syms)} · velas {tf}")
    print("Ctrl+C para detener (el estado queda guardado). Creá un archivo KILL para liquidar todo.\n")

    errors = 0
    try:
        while True:
            try:
                last = int(market.ts[-1])
                new = {s: fetch_closed(ex, s, tf, last) for s in syms}
                common = set.intersection(*(set(df.ts) for df in new.values())) if new else set()
                if common:
                    new = {s: df[df.ts.isin(common)] for s, df in new.items()}
                    tickers = ex.fetch_tickers(syms)
                    live_px = {s: float(tickers[s]["last"]) for s in syms}
                    n_before = len(market)
                    market.append(new)
                    for k in range(n_before, len(market)):
                        is_last = k == len(market) - 1
                        arena.on_bar(k, live_prices=live_px if is_last else market.prices(k + 1, "open"))
                    ledger.commit()
                    eqs = {b.name: arena.brokers[b.name].equity(live_px) for b in bots}
                    stamp = pd.to_datetime(int(market.ts[-1]), unit="ms", utc=True).strftime("%Y-%m-%d %H:%M")
                    print(f"[{stamp} UTC] " + " · ".join(f"{k}: {v:,.0f}" for k, v in eqs.items()))
                    if on_new_bar:
                        on_new_bar(arena)
                errors = 0
                next_close = int(market.ts[-1]) + 2 * tf_ms
                wait = max(poll_s, (next_close - ex.milliseconds()) / 1000 + 3)
                time.sleep(min(wait, 300))
            except KeyboardInterrupt:
                raise
            except Exception as e:                       # red caída, exchange en mantenimiento, etc.
                errors += 1
                backoff = min(30 * errors, 600)
                print(f"⚠ error ({e.__class__.__name__}): {e}. Reintento en {backoff}s")
                if errors == 1:
                    traceback.print_exc()
                time.sleep(backoff)
    except KeyboardInterrupt:
        print("\nDeteniendo… guardando estado.")
    finally:
        arena.save_state()
        ledger.close()

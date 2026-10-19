"""Datos de mercado: descarga histórica (ccxt), caché en CSV y datos sintéticos para pruebas."""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd

from .core import parse_minutes

COLS = ["ts", "open", "high", "low", "close", "volume"]


def _cache_path(data_dir: Path, exchange: str, symbol: str, timeframe: str) -> Path:
    return data_dir / f"{exchange}_{symbol.replace('/', '-')}_{timeframe}.csv"


def make_exchange(exchange_id: str):
    import ccxt  # import diferido: no hace falta para los tests

    ex = getattr(ccxt, exchange_id)({"enableRateLimit": True})
    return ex


def download_ohlcv(exchange_id: str, symbol: str, timeframe: str, days: int,
                   data_dir: str | Path = "data") -> pd.DataFrame:
    """Baja velas históricas paginando y las guarda en CSV (incremental si ya existe)."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(data_dir, exchange_id, symbol, timeframe)
    ex = make_exchange(exchange_id)
    tf_ms = parse_minutes(timeframe) * 60_000
    now_ms = ex.milliseconds()
    since = now_ms - days * 86_400_000

    old = pd.read_csv(path) if path.exists() else pd.DataFrame(columns=COLS)
    if len(old):
        since = max(since, int(old["ts"].max()) + tf_ms)

    rows: list[list] = []
    while since < now_ms - tf_ms:
        batch = ex.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
        if not batch:
            break
        rows.extend(batch)
        since = batch[-1][0] + tf_ms
        print(f"  {symbol}: {len(rows)} velas nuevas…", end="\r")
        time.sleep(ex.rateLimit / 1000)
    print()
    new = pd.DataFrame(rows, columns=COLS)
    df = pd.concat([old, new]).drop_duplicates("ts").sort_values("ts")
    df = df[df["ts"] < now_ms - tf_ms]          # descarta la vela en curso (sin cerrar)
    df.to_csv(path, index=False)
    return df.reset_index(drop=True)


def load_cached(exchange_id: str, symbols: list[str], timeframe: str,
                data_dir: str | Path = "data") -> dict[str, pd.DataFrame]:
    out = {}
    for s in symbols:
        p = _cache_path(Path(data_dir), exchange_id, s, timeframe)
        if not p.exists():
            raise FileNotFoundError(f"No hay datos para {s}. Corré: python main.py download")
        out[s] = pd.read_csv(p)
    return align(out)


def align(frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Deja solo los timestamps presentes en TODOS los símbolos (velas alineadas)."""
    common = None
    for df in frames.values():
        ts = set(df["ts"].astype("int64"))
        common = ts if common is None else common & ts
    out = {}
    for s, df in frames.items():
        d = df[df["ts"].isin(common)].sort_values("ts").reset_index(drop=True)
        out[s] = d[COLS].astype({"ts": "int64"})
    return out


def synthetic(symbols: list[str], bars: int, timeframe: str = "15m", seed: int = 7) -> dict[str, pd.DataFrame]:
    """Precios sintéticos con regímenes (tendencia alcista, bajista, lateral) y activos correlacionados.

    SOLO para probar que el sistema funciona. No dicen nada sobre el mercado real.
    """
    rng = np.random.default_rng(seed)
    dt_min = parse_minutes(timeframe)
    per_year = 365 * 24 * 60 / dt_min
    n = len(symbols)
    corr = np.full((n, n), 0.7) + np.eye(n) * 0.3
    chol = np.linalg.cholesky(corr)
    vols = np.array([0.55, 0.70, 0.95, 0.8, 0.8][:n]) / np.sqrt(per_year)
    starts = np.array([60000.0, 3000.0, 150.0, 1.0, 1.0][:n])

    regimes = [0.9, -0.8, 0.0]          # drift anual por régimen
    drift = np.zeros(bars)
    i = 0
    while i < bars:
        length = int(rng.integers(200, 1200))
        drift[i:i + length] = rng.choice(regimes) / per_year
        i += length

    shocks = rng.standard_normal((bars, n)) @ chol.T
    rets = drift[:, None] + shocks * vols
    closes = starts * np.exp(np.cumsum(rets, axis=0))
    t0 = 1_700_000_000_000 - (1_700_000_000_000 % (dt_min * 60_000))
    ts = t0 + np.arange(bars) * dt_min * 60_000

    out = {}
    for j, s in enumerate(symbols):
        c = closes[:, j]
        o = np.concatenate([[starts[j]], c[:-1]])
        wig = np.abs(rng.standard_normal(bars)) * vols[j] * c
        h = np.maximum(o, c) + wig
        lo = np.minimum(o, c) - wig
        v = rng.lognormal(10, 0.5, bars)
        out[s] = pd.DataFrame({"ts": ts, "open": o, "high": h, "low": lo, "close": c, "volume": v})
    return out


# ---------------- descarga robusta con exchanges de respaldo ----------------
PAGE_LIMIT = {"coinbase": 300, "okx": 100, "kraken": 720}


def _map_symbol(markets: dict, sym: str) -> str | None:
    """BTC/USDT en un exchange puede llamarse BTC/USD o BTC/USDC en otro."""
    base, quote = sym.split("/")
    for q in (quote, "USDT", "USD", "USDC"):
        if f"{base}/{q}" in markets:
            return f"{base}/{q}"
    return None


def fetch_recent(exchange_ids: list[str], symbols: list[str], timeframe: str, days: float,
                 min_coverage: float = 0.9, log=print) -> tuple[dict[str, pd.DataFrame], str]:
    """Baja las últimas `days` de velas cerradas probando exchanges en orden hasta que uno ande.
    Devuelve (velas alineadas por símbolo, exchange usado)."""
    tf_ms = parse_minutes(timeframe) * 60_000
    expected = days * 86_400_000 / tf_ms
    errors = []
    for ex_id in exchange_ids:
        try:
            ex = make_exchange(ex_id)
            markets = ex.load_markets()
            frames = {}
            for s in symbols:
                xs = _map_symbol(markets, s)
                if xs is None:
                    raise ValueError(f"{s} no existe en {ex_id}")
                now = ex.milliseconds()
                since = now - int(days * 86_400_000)
                rows, limit = [], PAGE_LIMIT.get(ex_id, 1000)
                while since < now - tf_ms:
                    batch = ex.fetch_ohlcv(xs, timeframe, since=since, limit=limit)
                    batch = [r for r in batch if r[0] >= since]
                    if not batch:
                        break
                    rows.extend(batch)
                    since = batch[-1][0] + tf_ms
                df = pd.DataFrame(rows, columns=COLS).drop_duplicates("ts")
                df = df[df.ts + tf_ms <= ex.milliseconds()]            # solo velas cerradas
                if len(df) < expected * min_coverage:
                    raise ValueError(f"{s}: solo {len(df)} de ~{int(expected)} velas")
                frames[s] = df
            return align(frames), ex_id
        except Exception as e:                                         # probamos el siguiente
            errors.append(f"{ex_id}: {e.__class__.__name__}: {str(e)[:160]}")
            log(f"  ⚠ {errors[-1]}")
    raise RuntimeError("Ningún exchange respondió: " + " | ".join(errors))

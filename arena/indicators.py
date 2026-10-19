"""Indicadores técnicos simples, sobre arrays de numpy."""
from __future__ import annotations

import numpy as np


def ema(x: np.ndarray, n: int) -> float:
    if len(x) == 0:
        return float("nan")
    a = 2 / (n + 1)
    x = x[-(n * 5):]                    # suficiente para converger, mucho más rápido
    e = x[0]
    for v in x[1:]:
        e = a * v + (1 - a) * e
    return float(e)


def realized_vol(close: np.ndarray, n: int, per_year: float) -> float:
    r = np.diff(np.log(close[-(n + 1):]))
    if len(r) < 2:
        return float("nan")
    return float(np.std(r, ddof=1) * np.sqrt(per_year))


def rsi(close: np.ndarray, n: int = 14) -> float:
    d = np.diff(close[-(n * 4 + 1):])
    if len(d) < n:
        return 50.0
    up, dn = np.clip(d, 0, None), np.clip(-d, 0, None)
    a = 1 / n
    au, ad = up[:n].mean(), dn[:n].mean()
    for u, w in zip(up[n:], dn[n:]):
        au = a * u + (1 - a) * au
        ad = a * w + (1 - a) * ad
    if ad == 0:
        return 100.0
    return float(100 - 100 / (1 + au / ad))


def pct_change(close: np.ndarray, bars: int) -> float:
    if len(close) <= bars:
        return float("nan")
    return float(close[-1] / close[-1 - bars] - 1)


def zscore_last(x: np.ndarray, n: int) -> float:
    w = x[-n:]
    if len(w) < 3 or np.std(w) == 0:
        return 0.0
    return float((w[-1] - w.mean()) / w.std())

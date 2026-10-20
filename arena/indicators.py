"""Indicadores técnicos simples, sobre arrays de numpy."""
from __future__ import annotations

from functools import lru_cache

import numpy as np


@lru_cache(maxsize=4096)
def _decay_weights(m: int, a: float) -> np.ndarray:
    """Pesos de un suavizado exponencial: el último dato pesa a, el anterior a(1-a), etc."""
    w = a * (1 - a) ** np.arange(m - 1, -1, -1)
    w.flags.writeable = False
    return w


def ema(x: np.ndarray, n: int) -> float:
    """Media móvil exponencial del último dato. Equivale al bucle clásico
    e = a*x + (1-a)*e arrancando en x[0], pero calculada de una vez (mucho más rápido)."""
    if len(x) == 0:
        return float("nan")
    a = 2 / (n + 1)
    x = np.asarray(x[-(n * 5):], dtype=float)
    m = len(x)
    if m == 1:
        return float(x[0])
    return float((1 - a) ** (m - 1) * x[0] + _decay_weights(m - 1, a) @ x[1:])


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
    rest = len(up) - n
    if rest > 0:
        w = _decay_weights(rest, a)
        k = (1 - a) ** rest
        au = k * au + w @ up[n:]
        ad = k * ad + w @ dn[n:]
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

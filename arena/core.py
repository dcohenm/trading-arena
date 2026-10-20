"""Tipos y utilidades compartidas."""
from __future__ import annotations

import re
from functools import lru_cache
from dataclasses import dataclass, field
from pathlib import Path

import yaml

TF_MINUTES = {"m": 1, "h": 60, "d": 1440}


@lru_cache(maxsize=256)
def parse_minutes(spec: str) -> int:
    """'15m' -> 15, '4h' -> 240, '1d' -> 1440."""
    m = re.fullmatch(r"\s*(\d+)\s*([mhd])\s*", str(spec))
    if not m:
        raise ValueError(f"Intervalo inválido: {spec!r} (usá 15m, 4h, 1d)")
    return int(m.group(1)) * TF_MINUTES[m.group(2)]


def bars_per_year(timeframe: str) -> float:
    """Cripto opera 24/7/365."""
    return 365 * 24 * 60 / parse_minutes(timeframe)


def load_config(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


@dataclass
class Proposal:
    """Lo que un bot QUIERE hacer. Nunca va directo al mercado: pasa por el gestor de riesgo.

    targets: peso objetivo por símbolo como fracción del capital (0 = sin posición, 0.3 = 30%).
    Solo spot y sin cortos: los pesos van de 0 a 1.
    """
    targets: dict[str, float]
    stops: dict[str, float] = field(default_factory=dict)   # stop-loss como % (0.05 = 5%)
    reason: str = ""
    meta: dict = field(default_factory=dict)                 # datos extra (respuesta del LLM, etc.)


@dataclass
class Order:
    bot: str
    symbol: str
    side: str            # "buy" | "sell"
    notional: float      # en USDT
    reason: str = ""
    stop: float | None = None


@dataclass
class Fill:
    bot: str
    ts: int
    symbol: str
    side: str
    qty: float
    price: float
    fee: float
    reason: str = ""

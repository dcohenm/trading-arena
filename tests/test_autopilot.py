"""Simula varias corridas horarias del piloto automático con un exchange falso."""
import importlib
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ap(tmp_path, monkeypatch):
    for item in ("arena", "autopilot.py", "config.yaml"):
        src = ROOT / item
        (shutil.copytree if src.is_dir() else shutil.copy)(src, tmp_path / item)
    monkeypatch.syspath_prepend(str(tmp_path))
    for m in [m for m in sys.modules if m == "autopilot" or m.startswith("arena")]:
        del sys.modules[m]
    mod = importlib.import_module("autopilot")
    from arena.data import synthetic
    cfg = mod.load_config(tmp_path / "config.yaml")
    cfg["autopilot"]["evolution"].update(enabled=True, data_days=20, n_mutations=1, n_random=2, every_days=1)
    syms = cfg["market"]["symbols"]
    full = synthetic(syms, 96 * 60, "15m", seed=3)
    clock = {"now": int(full[syms[0]].ts.iloc[96 * 45])}

    def fake_fetch(exchanges, symbols, tf, days, min_coverage=0.9, log=print):
        lo = clock["now"] - int(days * 86_400_000)
        return {s: d[(d.ts >= lo) & (d.ts + 900_000 <= clock["now"])].reset_index(drop=True)
                for s, d in full.items()}, exchanges[0]
    monkeypatch.setattr(mod, "fetch_recent", fake_fetch)
    return mod, cfg, clock


def test_ticks_resume_and_evolve(ap):
    mod, cfg, clock = ap
    mod.tick(cfg)
    st = json.loads(mod.STATE.read_text())
    assert st["last_ts"] and st["generation"] == 0
    for _ in range(10):                                    # 30 horas, de a 3
        clock["now"] += 3 * 3_600_000
        mod.tick(cfg)
    st = json.loads(mod.STATE.read_text())
    assert st["generation"] >= 1                           # evolucionó (cada 1 día en el test)
    assert (mod.STATE_DIR / "evolution.csv").exists()
    assert "Trading Arena" in (mod.ROOT / "README.md").read_text()
    assert (mod.ROOT / "docs" / "index.html").exists()
    # no se procesa dos veces la misma vela
    import pandas as pd
    eq = pd.read_csv(mod.STATE_DIR / "equity.csv")
    assert not eq.duplicated(["ts", "bot"]).any()


def test_no_data_does_not_break(ap, monkeypatch):
    mod, cfg, clock = ap
    mod.tick(cfg)

    def broken(*a, **k):
        raise RuntimeError("caído")
    monkeypatch.setattr(mod, "fetch_recent", broken)
    mod.tick(cfg)
    st = json.loads(mod.STATE.read_text())
    assert st["failures"] == 1


def test_evolution_off_by_config(ap):
    mod, cfg, clock = ap
    cfg["autopilot"]["evolution"]["enabled"] = False
    for _ in range(11):
        mod.tick(cfg)
        clock["now"] += 3 * 3_600_000
    st = json.loads(mod.STATE.read_text())
    assert st["generation"] == 0
    assert "apagada" in (mod.ROOT / "README.md").read_text()

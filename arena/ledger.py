"""Registro en SQLite: cada vela, operación, decisión del LLM y evento de riesgo queda guardado."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, mode TEXT, started REAL, config TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS equity (
  run_id TEXT, ts INTEGER, bot TEXT, equity REAL, cash REAL, exposure REAL);
CREATE TABLE IF NOT EXISTS trades (
  run_id TEXT, ts INTEGER, bot TEXT, symbol TEXT, side TEXT, qty REAL, price REAL, fee REAL, reason TEXT);
CREATE TABLE IF NOT EXISTS decisions (
  run_id TEXT, ts INTEGER, bot TEXT, targets TEXT, reason TEXT, meta TEXT);
CREATE TABLE IF NOT EXISTS risk_events (
  run_id TEXT, ts INTEGER, bot TEXT, type TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS state (
  run_id TEXT, bot TEXT, data TEXT, PRIMARY KEY (run_id, bot));
CREATE INDEX IF NOT EXISTS ix_eq ON equity(run_id, bot, ts);
"""


class Ledger:
    def __init__(self, path: str | Path, run_id: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.executescript(SCHEMA)
        self.run_id = run_id
        self._pending = 0

    def start_run(self, mode: str, config: dict, note: str = "") -> None:
        self.db.execute("INSERT OR IGNORE INTO runs VALUES (?,?,?,?,?)",
                        (self.run_id, mode, time.time(), json.dumps(config), note))
        self.db.commit()

    def equity(self, ts, bot, equity, cash, exposure):
        self.db.execute("INSERT INTO equity VALUES (?,?,?,?,?,?)",
                        (self.run_id, ts, bot, equity, cash, exposure))
        self._tick()

    def trade(self, f):
        self.db.execute("INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?)",
                        (self.run_id, f.ts, f.bot, f.symbol, f.side, f.qty, f.price, f.fee, f.reason[:500]))
        self._tick()

    def decision(self, ts, bot, targets, reason, meta):
        self.db.execute("INSERT INTO decisions VALUES (?,?,?,?,?,?)",
                        (self.run_id, ts, bot, json.dumps(targets), reason[:4000],
                         json.dumps(meta, default=str)[:20000]))
        self._tick()

    def risk_event(self, ts, ev):
        self.db.execute("INSERT INTO risk_events VALUES (?,?,?,?,?)",
                        (self.run_id, ts, ev["bot"], ev["type"], ev["detail"]))
        self._tick()

    def save_state(self, bot: str, data: dict):
        self.db.execute("INSERT OR REPLACE INTO state VALUES (?,?,?)",
                        (self.run_id, bot, json.dumps(data, default=str)))

    def load_state(self) -> dict[str, dict]:
        rows = self.db.execute("SELECT bot, data FROM state WHERE run_id=?", (self.run_id,)).fetchall()
        return {b: json.loads(d) for b, d in rows}

    def _tick(self):
        self._pending += 1
        if self._pending >= 500:
            self.commit()

    def commit(self):
        self.db.commit()
        self._pending = 0

    def close(self):
        self.commit()
        self.db.close()

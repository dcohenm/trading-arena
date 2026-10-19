"""Registro en archivos CSV de solo-agregar. Lo usa el piloto automático en GitHub:
los CSV de texto se versionan bien en git (cada hora se agregan unas pocas líneas)."""
from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

import pandas as pd

from .ledger import SCHEMA

FILES = {
    "equity": ["ts", "bot", "equity", "cash", "exposure"],
    "trades": ["ts", "bot", "symbol", "side", "qty", "price", "fee", "reason"],
    "decisions": ["ts", "bot", "targets", "reason", "meta"],
    "risk_events": ["ts", "bot", "type", "detail"],
}


class CsvLedger:
    def __init__(self, folder: str | Path, run_id: str = "autopilot"):
        self.dir = Path(folder)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.buf: dict[str, list] = {k: [] for k in FILES}

    def start_run(self, mode, config, note=""):
        p = self.dir / "run.json"
        if not p.exists():
            p.write_text(json.dumps({"run_id": self.run_id, "mode": mode, "note": note}, ensure_ascii=False))

    def equity(self, ts, bot, equity, cash, exposure):
        self.buf["equity"].append([ts, bot, round(equity, 2), round(cash, 2), round(exposure, 4)])

    def trade(self, f):
        self.buf["trades"].append([f.ts, f.bot, f.symbol, f.side, f"{f.qty:.8g}", f"{f.price:.8g}",
                                   round(f.fee, 4), f.reason[:300]])

    def decision(self, ts, bot, targets, reason, meta):
        self.buf["decisions"].append([ts, bot, json.dumps({k: round(float(v), 4) for k, v in targets.items()
                                                           if v is not None and v == v}),
                                      reason[:1500], json.dumps(meta, default=str, ensure_ascii=False)[:4000]])

    def risk_event(self, ts, ev):
        self.buf["risk_events"].append([ts, ev["bot"], ev["type"], ev["detail"][:300]])

    def save_state(self, bot, data):      # el estado lo maneja el piloto automático (state.json)
        pass

    def load_state(self):
        return {}

    def commit(self):
        for name, rows in self.buf.items():
            if not rows:
                continue
            p = self.dir / f"{name}.csv"
            new = not p.exists()
            with open(p, "a", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                if new:
                    w.writerow(FILES[name])
                w.writerows(rows)
            self.buf[name] = []

    def close(self):
        self.commit()

    # ---------- para las métricas y el tablero ----------
    def to_sqlite(self, db_path: str | Path, mode: str = "piloto automático", note: str = "") -> str:
        self.commit()
        db = Path(db_path)
        db.unlink(missing_ok=True)
        con = sqlite3.connect(str(db))
        con.executescript(SCHEMA)
        con.execute("INSERT INTO runs VALUES (?,?,?,?,?)", (self.run_id, mode, 0, "{}", note))
        for name, cols in FILES.items():
            p = self.dir / f"{name}.csv"
            if p.exists():
                df = pd.read_csv(p)
                df.insert(0, "run_id", self.run_id)
                df.to_sql(name, con, if_exists="append", index=False)
        con.commit()
        con.close()
        return self.run_id

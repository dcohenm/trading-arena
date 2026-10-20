"""Métricas de desempeño y la pregunta clave: ¿esto es habilidad o suerte?"""
from __future__ import annotations

import math
import sqlite3

import numpy as np
import pandas as pd


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def probabilistic_sharpe(rets: np.ndarray, sr_benchmark: float = 0.0) -> float:
    """Probabilidad de que el Sharpe verdadero supere al de referencia (Bailey & López de Prado).
    Corrige por la cantidad de datos, la asimetría y las colas gordas de los retornos."""
    r = rets[np.isfinite(rets)]
    n = len(r)
    if n < 10 or r.std(ddof=1) == 0:
        return float("nan")
    sr = r.mean() / r.std(ddof=1)
    z = (r - r.mean()) / r.std(ddof=0)
    skew, kurt = float(np.mean(z ** 3)), float(np.mean(z ** 4))
    denom = math.sqrt(max(1 - skew * sr + (kurt - 1) / 4 * sr ** 2, 1e-12))
    return _norm_cdf((sr - sr_benchmark) * math.sqrt(n - 1) / denom)


def stats_from_equity(eq: pd.Series, periods_per_year: float) -> dict:
    eq = eq.dropna()
    if len(eq) < 3:
        return {}
    rets = eq.pct_change().dropna().to_numpy()
    total = eq.iloc[-1] / eq.iloc[0] - 1
    years = len(rets) / periods_per_year
    cagr = (1 + total) ** (1 / years) - 1 if years > 0 and total > -1 else float("nan")
    sd = rets.std(ddof=1)
    downside = rets[rets < 0]
    sharpe = rets.mean() / sd * math.sqrt(periods_per_year) if sd > 0 else float("nan")
    sortino = (rets.mean() / downside.std(ddof=1) * math.sqrt(periods_per_year)
               if len(downside) > 1 and downside.std(ddof=1) > 0 else float("nan"))
    peak = eq.cummax()
    dd = (eq / peak - 1)
    mdd = float(-dd.min())
    return {
        "return_pct": total * 100,
        "cagr_pct": cagr * 100,
        "vol_ann_pct": sd * math.sqrt(periods_per_year) * 100,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_dd_pct": mdd * 100,
        "calmar": (cagr / mdd) if mdd > 0 and cagr == cagr else float("nan"),
        "psr": probabilistic_sharpe(rets),
        "n_obs": len(rets),
    }


def load_run(db_path: str, run_id: str | None = None):
    con = sqlite3.connect(db_path)
    if run_id is None:
        row = con.execute("SELECT run_id FROM runs ORDER BY started DESC LIMIT 1").fetchone()
        if not row:
            raise SystemExit("No hay corridas en la base de datos.")
        run_id = row[0]
    q = lambda sql: pd.read_sql_query(sql, con, params=(run_id,))   # noqa: E731
    data = {
        "run_id": run_id,
        "run": q("SELECT * FROM runs WHERE run_id=?"),
        "equity": q("SELECT ts, bot, equity, cash, exposure FROM equity WHERE run_id=? ORDER BY ts"),
        "trades": q("SELECT * FROM trades WHERE run_id=? ORDER BY ts"),
        "decisions": q("SELECT * FROM decisions WHERE run_id=? AND (meta LIKE '%\"llm\"%' OR meta LIKE '%\"error\"%') "
                       "ORDER BY ts DESC LIMIT 300"),
        "risk": q("SELECT * FROM risk_events WHERE run_id=? ORDER BY ts DESC LIMIT 300"),
    }
    con.close()
    return data


def leaderboard(data: dict, starting_cash: float, min_days: float = 0,
                trade_override: dict | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Ranking. Cada bot se compara contra los bots al azar EN SU MISMA VENTANA de tiempo
    (importa cuando hay bots que entraron después, como los que crea la evolución)."""
    eq = data["equity"]
    raw = eq.pivot_table(index="ts", columns="bot", values="equity").sort_index()
    if len(raw) < 3:
        raise SystemExit("Todavía hay muy pocos datos para calcular métricas.")
    dt_ms = float(np.median(np.diff(raw.index.to_numpy())))
    ppy = 365 * 24 * 3600 * 1000 / dt_ms

    def window(bot):
        col = raw[bot]
        first, last = col.first_valid_index(), col.last_valid_index()
        return col.loc[first:last].ffill()

    series = {b: window(b) for b in raw.columns}
    wide = pd.DataFrame(series)                       # sin rellenar más allá de la vida de cada bot
    luck_names = [b for b in raw.columns if b.startswith("_luck_")]

    rows = {}
    for bot, ser in series.items():
        st = stats_from_equity(ser, ppy)
        st["avg_exposure_pct"] = eq[eq.bot == bot]["exposure"].mean() * 100
        st["days"] = (ser.index[-1] - ser.index[0]) / 86_400_000 if len(ser) else 0.0
        st["first_ts"], st["last_ts"] = (ser.index[0], ser.index[-1]) if len(ser) else (0, 0)
        rows[bot] = st
    table = pd.DataFrame(rows).T

    tr = data["trades"]
    if len(tr):
        g = tr.assign(notional=tr.qty * tr.price).groupby("bot")
        table["trades"] = g.size()
        table["fees_usdt"] = g["fee"].sum()
        table["turnover_x"] = g["notional"].sum() / starting_cash
    for c in ("trades", "fees_usdt", "turnover_x"):
        if c not in table:
            table[c] = 0.0
        table[c] = table[c].fillna(0.0)
    for bot, vals in (trade_override or {}).items():    # p. ej. carteras que agregan varios bots
        if bot in table.index:
            for c, v in vals.items():
                table.loc[bot, c] = v

    # con muy poca historia el Sharpe es puro ruido (y engaña): no se muestra
    few = (table["days"] < 7) | (table["trades"] < 5)
    few &= ~table.index.isin(["buy_and_hold"]) & ~table.index.str.startswith("_luck_")
    table.loc[few, ["sharpe", "sortino", "psr", "calmar"]] = float("nan")

    main = table[~table.index.str.startswith("_luck_")].copy()
    bh_full = series.get("buy_and_hold")

    def same_window(bot):
        """Sharpe y retorno de los bots al azar y de comprar-y-mantener en la ventana del bot."""
        a, b = main.loc[bot, "first_ts"], main.loc[bot, "last_ts"]
        luck = [stats_from_equity(series[l].loc[a:b], ppy) for l in luck_names]
        luck = [x for x in luck if x]
        bh = stats_from_equity(bh_full.loc[a:b], ppy) if bh_full is not None else {}
        return luck, bh

    pr, ps, bhs = [], [], []
    for bot in main.index:
        luck, bh = same_window(bot)
        r, sh = main.loc[bot, "return_pct"], main.loc[bot, "sharpe"]
        pr.append(float(np.mean([x["return_pct"] < r for x in luck]) * 100) if luck and r == r else float("nan"))
        ps.append(float(np.mean([x["sharpe"] < sh for x in luck]) * 100) if luck and sh == sh else float("nan"))
        bhs.append(bh.get("sharpe", float("nan")))
    main["luck_pctl_return"], main["luck_pctl_sharpe"], main["bh_sharpe_same_window"] = pr, ps, bhs
    n_luck = len(luck_names)

    def verdict(r):
        if r.name == "buy_and_hold":
            return "Referencia"
        if r["days"] < min_days:
            return f"En observación ({r['days']:.0f} de {min_days:.0f} días mínimos)"
        if r["trades"] < 30:
            return "Pocas operaciones para concluir"
        if not (r["psr"] >= 0.95):
            return "Sin evidencia estadística (puede ser suerte)"
        if n_luck and not (r["luck_pctl_sharpe"] >= 95):
            return "No supera claramente a los bots al azar"
        if r["bh_sharpe_same_window"] == r["bh_sharpe_same_window"] and not (r["sharpe"] > r["bh_sharpe_same_window"]):
            return "No le gana a comprar y mantener (ajustado por riesgo)"
        return "Candidato: pasar a la siguiente fase"

    main["verdict"] = main.apply(verdict, axis=1)
    main = main.sort_values(["sharpe", "return_pct"], ascending=False, na_position="last")
    return main, wide


def recent_scores(wide: pd.DataFrame, bots: list[str], window_days: float, ppy: float,
                  min_points: int = 30) -> dict[str, float]:
    """Puntaje para elegir padres y decidir retiros, comparando a cada bot en la MISMA ventana.

    Puntaje = % de bots al azar a los que les ganó (en Sharpe) durante los últimos `window_days`
    días de vida del bot. Así un bot que vivió solo la parte buena de una suba no queda por
    encima de otro que atravesó subas y bajas: los dos se miden contra el azar en su propio período.
    Bots sin datos suficientes reciben NaN (no se retiran ni se eligen como padres).
    """
    luck = [c for c in wide.columns if c.startswith("_luck_")]
    if wide.empty:
        return {b: float("nan") for b in bots}
    end = wide.index[-1]
    out = {}
    for b in bots:
        s = wide[b].dropna() if b in wide else pd.Series(dtype=float)
        if len(s) < min_points:
            out[b] = float("nan")
            continue
        lo = max(s.index[0], end - window_days * 86_400_000)
        sb = stats_from_equity(s.loc[lo:], ppy).get("sharpe", float("nan"))
        ls = [stats_from_equity(wide[l].loc[lo:].dropna(), ppy).get("sharpe", float("nan")) for l in luck]
        ls = [x for x in ls if x == x]
        if sb != sb or not ls:
            out[b] = float("nan")
            continue
        out[b] = float(np.mean([x < sb for x in ls]) * 100) + 1e-3 * float(np.tanh(sb))   # desempate por Sharpe
    return out

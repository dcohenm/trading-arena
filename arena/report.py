"""Genera el tablero HTML (un solo archivo) a partir de la base de datos."""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .metrics import leaderboard, load_run

SERIES = [("#2a78d6", "#3987e5"), ("#eb6834", "#d95926"), ("#1baf7a", "#199e70"), ("#eda100", "#c98500"),
          ("#e87ba4", "#d55181"), ("#008300", "#008300"), ("#6250d6", "#9085e9"), ("#e34948", "#e66767")]


def _fmt(v, digits=2, suffix=""):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "—"
    return f"{v:,.{digits}f}{suffix}"


def _ts(ms: int) -> str:
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


VERDICT_CLASS = {
    "Candidato: pasar a la siguiente fase": ("good", "✓"),
    "Referencia": ("ref", "◆"),
}


def _nn(values) -> list:
    """NaN -> null para el gráfico (huecos donde el bot todavía no existía o ya se retiró)."""
    return [None if (v is None or v != v) else round(float(v), 2) for v in values]


def build_report(db_path: str, out_path: str, starting_cash: float, run_id: str | None = None,
                 note: str = "", min_days: float = 0, status: dict | None = None,
                 extra_html: str = "", inline_chartjs: bool = True,
                 trade_override: dict | None = None, labels_map: dict | None = None) -> str:
    status = status or {}
    data = load_run(db_path, run_id)
    if not note and len(data["run"]):
        note = data["run"]["note"].iloc[0] or ""
    table, wide = leaderboard(data, starting_cash, min_days=min_days, trade_override=trade_override)
    bots = list(table.index)
    labels_map = labels_map or {}

    step = max(1, len(wide) // 1500)
    w = wide.iloc[::step]
    labels = [_ts(t) for t in w.index]
    luck_cols = [c for c in w.columns if c.startswith("_luck_")]
    luck = {}
    if luck_cols:
        L = w[luck_cols].to_numpy()
        luck = {"p5": _nn(np.nanpercentile(L, 5, axis=1)),
                "p50": _nn(np.nanpercentile(L, 50, axis=1)),
                "p95": _nn(np.nanpercentile(L, 95, axis=1))}
    series, dds = [], []
    for i, b in enumerate(bots):
        col = SERIES[i % len(SERIES)]
        e = w[b]
        series.append({"name": labels_map.get(b, b), "light": col[0], "dark": col[1], "data": _nn(e)})
        dds.append({"name": labels_map.get(b, b), "light": col[0], "dark": col[1], "data": _nn((e / e.cummax() - 1) * 100)})

    # tabla
    rows = []
    for i, (b, r) in enumerate(table.iterrows()):
        cls, icon = VERDICT_CLASS.get(r["verdict"], ("warn", "!"))
        sw = SERIES[i % len(SERIES)][0]
        rows.append(f"""<tr>
<td class="bot"><span class="sw" style="--c:{sw}"></span>{html.escape(labels_map.get(b, b))}{' <span class="muted">(retirado)</span>' if status.get(b) == 'retired' else ''}</td>
<td class="num">{_fmt(r['days'], 0)}</td>
<td class="num {'pos' if r['return_pct'] > 0 else 'neg'}">{_fmt(r['return_pct'], 1, '%')}</td>
<td class="num">{_fmt(r['sharpe'])}</td><td class="num">{_fmt(r['sortino'])}</td>
<td class="num">{_fmt(r['max_dd_pct'], 1, '%')}</td><td class="num">{_fmt(r['psr'] * 100 if r['psr'] == r['psr'] else None, 0, '%')}</td>
<td class="num">{_fmt(r['luck_pctl_sharpe'], 0)}</td>
<td class="num">{int(r['trades'])}</td><td class="num">{_fmt(r['fees_usdt'], 0)}</td>
<td class="num">{_fmt(r['avg_exposure_pct'], 0, '%')}</td>
<td><span class="verdict {cls}"><b>{icon}</b> {html.escape(r['verdict'])}</span></td></tr>""")

    dec = data["decisions"]
    dec_rows = []
    for _, d in dec[dec.bot.str.startswith("grok")].iterrows():
        if len(dec_rows) >= 40:
            break
        meta = json.loads(d["meta"] or "{}")
        if not (isinstance(meta, dict) and ("llm" in meta or "error" in meta)):
            continue                                   # solo las veces que realmente se consultó a Grok
        llm = meta.get("llm", {}) if isinstance(meta, dict) else {}
        cost = llm.get("cost_usd")
        targets = json.loads(d["targets"] or "{}")
        tg = ", ".join(f"{k.split('/')[0]} {float(v):.0%}" for k, v in targets.items() if v is not None) or "sin cambios"
        dec_rows.append(f"<tr><td class='mono'>{_ts(d['ts'])}</td><td>{html.escape(d['bot'])}</td>"
                        f"<td class='mono'>{html.escape(tg)}</td><td class='reason'>{html.escape(d['reason'][:600])}</td>"
                        f"<td class='num'>{'' if cost is None else f'${cost:.4f}'}</td></tr>")
    risk_rows = "".join(
        f"<tr><td class='mono'>{_ts(r['ts'])}</td><td>{html.escape(r['bot'])}</td><td><b>{html.escape(r['type'])}</b></td>"
        f"<td>{html.escape(r['detail'])}</td></tr>" for _, r in data["risk"].head(60).iterrows())

    period = f"{_ts(wide.index[0])} → {_ts(wide.index[-1])} UTC"
    mode = data["run"]["mode"].iloc[0] if len(data["run"]) else "?"
    payload = json.dumps({"labels": labels, "series": series, "dd": dds, "luck": luck, "cash": starting_cash})
    best = table[table.index != "buy_and_hold"]
    best_name = best.index[0] if len(best) else "—"
    candidates = int((table["verdict"] == "Candidato: pasar a la siguiente fase").sum())

    asset = Path(__file__).parent / "assets" / "chart.umd.js"
    if inline_chartjs:
        chartjs = asset.read_text(encoding="utf-8")
    else:                                   # archivo aparte (no se re-sube en cada actualización)
        import shutil
        shutil.copyfile(asset, Path(out_path).parent / "chart.umd.js")
        chartjs = ""
    page = TEMPLATE.replace("__PAYLOAD__", payload).replace("__ROWS__", "\n".join(rows)) \
        .replace("__DECCARD__", DEC_CARD.replace("__DEC__", "\n".join(dec_rows)) if dec_rows else "") \
        .replace("__RISK__", risk_rows or "<tr><td colspan=4 class='muted'>Sin eventos de riesgo.</td></tr>") \
        .replace("__PERIOD__", period).replace("__MODE__", html.escape(mode)).replace("__RUN__", html.escape(data["run_id"])) \
        .replace("__NOTE__", f"<p class='note'>{html.escape(note)}</p>" if note else "") \
        .replace("__BEST__", html.escape(best_name)).replace("__CAND__", str(candidates)) \
        .replace("__NLUCK__", str(len(luck_cols))).replace("__NBOTS__", str(len(bots))) \
        .replace("__EXTRA__", extra_html) \
        .replace("<script>__CHARTJS__</script>", f"<script>{chartjs}</script>" if inline_chartjs
                 else '<script src="chart.umd.js"></script>')            # al final: el tablero funciona sin internet
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(page)
    return out_path


DEC_CARD = """<div class="card"><h2>Últimas decisiones de Grok</h2><div class="scroll"><table>
<thead><tr><th>Hora (UTC)</th><th>Bot</th><th>Pesos objetivo</th><th>Razonamiento</th><th class="num">Costo</th></tr></thead>
<tbody>__DEC__</tbody></table></div></div>"""

TEMPLATE = r"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Trading Arena</title>
<script>__CHARTJS__</script>
<style>
:root{--surface:#fcfcfb;--page:#f9f9f7;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;
--ring:rgba(11,11,11,.10);--good:#006300;--goodbg:rgba(12,163,12,.10);--warn:#8a5a00;--warnbg:rgba(250,178,25,.16);--neg:#b42d2d;--band:rgba(137,135,129,.18);color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--surface:#1a1a19;--page:#0d0d0d;--ink:#f0efec;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;
--ring:rgba(255,255,255,.10);--good:#0ca30c;--goodbg:rgba(12,163,12,.16);--warn:#fab219;--warnbg:rgba(250,178,25,.12);--neg:#e66767;--band:rgba(195,194,183,.14);color-scheme:dark}}
:root[data-theme="dark"]{--surface:#1a1a19;--page:#0d0d0d;--ink:#f0efec;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;
--ring:rgba(255,255,255,.10);--good:#0ca30c;--goodbg:rgba(12,163,12,.16);--warn:#fab219;--warnbg:rgba(250,178,25,.12);--neg:#e66767;--band:rgba(195,194,183,.14);color-scheme:dark}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--ink);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:28px 16px 60px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:15px;margin:0 0 12px}.sub{color:var(--ink2);margin:0 0 20px}
.note{background:var(--warnbg);border-radius:8px;padding:10px 14px;color:var(--ink);margin:0 0 20px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:16px}
.tile,.card{background:var(--surface);border-radius:12px;box-shadow:0 0 0 1px var(--ring)}
.tile{padding:14px 16px}.tile .k{color:var(--ink2);font-size:12px}.tile .v{font-size:22px;font-weight:600;margin-top:2px;overflow-wrap:anywhere}
.card{padding:18px;margin-bottom:16px}.chart{position:relative;height:340px}.chart.small{height:220px}
.legend-note{color:var(--muted);font-size:12px;margin-top:8px}
.scroll{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:13px}
th{color:var(--ink2);font-weight:500;text-align:left;padding:8px;border-bottom:1px solid var(--axis);white-space:nowrap}
td{padding:8px;border-bottom:1px solid var(--grid);vertical-align:top}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}th.num{text-align:right}
.pos{color:var(--good)}.neg{color:var(--neg)}.mono{font-variant-numeric:tabular-nums;white-space:nowrap;color:var(--ink2)}
.bot{white-space:nowrap;font-weight:500}.sw{display:inline-block;width:10px;height:10px;border-radius:3px;background:var(--c);margin-right:8px}
.verdict{display:inline-block;padding:2px 8px;border-radius:6px;font-size:12px;min-width:190px}
.verdict.good{background:var(--goodbg);color:var(--good)}.verdict.warn{background:var(--warnbg);color:var(--warn)}.verdict.ref{color:var(--ink2)}
.reason{color:var(--ink2);min-width:320px}.muted{color:var(--muted)}
details summary{cursor:pointer;color:var(--ink2);margin-bottom:8px}
.help{color:var(--ink2);font-size:12.5px;margin:10px 0 0}.help b{color:var(--ink)}
</style></head><body><main>
<h1>Trading Arena</h1>
<p class="sub">Corrida <b>__RUN__</b> · modo <b>__MODE__</b> · __PERIOD__</p>
__NOTE__
<div class="tiles">
<div class="tile"><div class="k">Mejor bot (Sharpe)</div><div class="v">__BEST__</div></div>
<div class="tile"><div class="k">Candidatos a la siguiente fase</div><div class="v">__CAND__ de __NBOTS__</div></div>
<div class="tile"><div class="k">Bots al azar (medida de suerte)</div><div class="v">__NLUCK__</div></div>
</div>

<div class="card"><h2>Ranking</h2><div class="scroll"><table>
<thead><tr><th>Bot</th><th class="num">Días</th><th class="num">Retorno</th><th class="num">Sharpe</th><th class="num">Sortino</th><th class="num">Caída máx.</th>
<th class="num">Prob. Sharpe&gt;0</th><th class="num">Percentil vs. azar</th><th class="num">Trades</th><th class="num">Comisiones</th><th class="num">Exposición</th><th>Veredicto</th></tr></thead>
<tbody>__ROWS__</tbody></table></div>
<p class="help"><b>Sharpe</b>: retorno por unidad de riesgo (anualizado). <b>Prob. Sharpe&gt;0</b>: probabilidad de que la ventaja sea real y no ruido; hace falta ≥95%. <b>Percentil vs. azar</b>: qué porcentaje de los bots que operan al azar quedó por debajo; hace falta ≥95.</p></div>

__EXTRA__
<div class="card"><h2>Capital por bot (USDT)</h2><div class="chart"><canvas id="eq"></canvas></div>
<p class="legend-note">La franja gris es el rango donde terminó el 90% de los bots al azar. Lo que está adentro de la franja se explica por suerte.</p></div>

<div class="card"><h2>Caída desde el máximo (%)</h2><div class="chart small"><canvas id="dd"></canvas></div></div>

__DECCARD__

<div class="card"><details><summary><h2 style="display:inline">Eventos de riesgo</h2></summary><div class="scroll"><table>
<thead><tr><th>Hora (UTC)</th><th>Bot</th><th>Tipo</th><th>Detalle</th></tr></thead><tbody>__RISK__</tbody></table></div></details></div>
</main>
<script>
const D = __PAYLOAD__;
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const dark = () => css('--surface') === '#1a1a19';
function base(yfmt){
  return {responsive:true,maintainAspectRatio:false,animation:false,
    interaction:{mode:'index',intersect:false},
    plugins:{legend:{position:'bottom',labels:{color:css('--ink2'),boxWidth:10,boxHeight:10,usePointStyle:true,pointStyle:'rectRounded',
      filter:i=>!i.text.startsWith('_')}},
      tooltip:{filter:i=>!i.dataset.label.startsWith('_'),backgroundColor:css('--surface'),titleColor:css('--ink'),bodyColor:css('--ink2'),
        borderColor:css('--axis'),borderWidth:1,padding:10,itemSort:(a,b)=>b.raw-a.raw,
        callbacks:{label:c=>' '+c.dataset.label+': '+yfmt(c.raw)}}},
    scales:{x:{ticks:{color:css('--muted'),maxTicksLimit:7,maxRotation:0,callback:function(v){return this.getLabelForValue(v).slice(0,10)}},grid:{display:false},border:{color:css('--axis')}},
      y:{ticks:{color:css('--muted'),callback:yfmt},grid:{color:css('--grid')},border:{display:false}}}};
}
const usd = v => Math.round(v).toLocaleString('es-AR');
const pct = v => v.toFixed(1)+'%';
function line(s){return {label:s.name,data:s.data,borderColor:dark()?s.dark:s.light,backgroundColor:dark()?s.dark:s.light,borderWidth:2,pointRadius:0,pointHoverRadius:4,tension:0}}
let charts=[];
function draw(){
  charts.forEach(c=>c.destroy());charts=[];
  const ds=D.series.map(line);
  if(D.luck.p5){
    ds.push({label:'_p95',data:D.luck.p95,borderWidth:0,pointRadius:0,fill:'+1',backgroundColor:css('--band')});
    ds.push({label:'_p5',data:D.luck.p5,borderWidth:0,pointRadius:0,fill:false});
  }
  charts.push(new Chart(document.getElementById('eq'),{type:'line',data:{labels:D.labels,datasets:ds},options:base(usd)}));
  charts.push(new Chart(document.getElementById('dd'),{type:'line',data:{labels:D.labels,datasets:D.dd.map(line)},options:base(pct)}));
}
draw();
matchMedia('(prefers-color-scheme: dark)').addEventListener('change',draw);
new MutationObserver(draw).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
</script></body></html>
"""

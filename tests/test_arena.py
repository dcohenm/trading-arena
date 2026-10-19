"""Tests de las piezas críticas: contabilidad, riesgo, sin mirar el futuro, y el cliente de Grok."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.broker import PaperBroker
from arena.core import Order, Proposal, load_config
from arena.data import synthetic
from arena.engine import Arena, Market
from arena.ledger import Ledger
from arena.risk import RiskManager
from arena.bots import build_bots, build_luck_bots
from arena.bots.base import Bot
from arena.llm import GrokClient, LLMError, MockLLM, BudgetExceeded

CFG = load_config(Path(__file__).resolve().parents[1] / "config.yaml")
PX = {"BTC/USDT": 100.0, "ETH/USDT": 10.0}


# ---------------- broker ----------------
def test_buy_sell_roundtrip_costs():
    b = PaperBroker("x", 1000, fee_rate=0.001, slippage_bps=10)
    b.execute(Order("x", "BTC/USDT", "buy", 500), 100.0, 0)
    assert b.cash == pytest.approx(1000 - 500 - 0.5)
    b.execute(Order("x", "BTC/USDT", "sell", 10_000), 100.0, 1)
    assert "BTC/USDT" not in b.qty
    assert b.cash < 1000                       # ida y vuelta al mismo precio pierde por costos
    assert b.cash == pytest.approx(1000 - 0.5 - 500 * (1 - 0.001) / 1.001 * 0.001 - 500 * (1 - (0.999 / 1.001)), rel=1e-3)


def test_cannot_overspend():
    b = PaperBroker("x", 100, 0.001, 0)
    b.execute(Order("x", "BTC/USDT", "buy", 1_000_000), 100.0, 0)
    assert b.cash >= -1e-9


def test_sell_without_position_is_noop():
    b = PaperBroker("x", 100, 0.001, 0)
    assert b.execute(Order("x", "BTC/USDT", "sell", 50), 100.0, 0) is None


# ---------------- riesgo ----------------
def rm(**over):
    cfg = dict(CFG["risk"]); cfg.update(over); cfg["kill_file"] = "__no_kill_file__"
    return RiskManager(cfg)


def test_risk_clips_crazy_llm_weights():
    r, b = rm(), PaperBroker("g", 10_000, 0.001, 0)
    orders, ev = r.filter("g", Proposal({"BTC/USDT": 3.0, "ETH/USDT": -1}), b, PX)
    buys = [o for o in orders if o.side == "buy"]
    assert len(buys) == 1 and buys[0].notional == pytest.approx(10_000 * CFG["risk"]["max_weight_per_symbol"])
    assert any(e["type"] == "CLIPPED" for e in ev)


def test_risk_scales_gross_exposure():
    r, b = rm(max_weight_per_symbol=0.9, max_gross_exposure=1.0), PaperBroker("g", 10_000, 0.001, 0)
    orders, _ = r.filter("g", Proposal({"BTC/USDT": 0.9, "ETH/USDT": 0.9}), b, PX)
    assert sum(o.notional for o in orders) == pytest.approx(10_000, rel=1e-6)


def test_risk_ignores_tiny_rebalances():
    r, b = rm(), PaperBroker("g", 10_000, 0.0, 0)
    b.execute(Order("g", "BTC/USDT", "buy", 3000), 100.0, 0)
    orders, _ = r.filter("g", Proposal({"BTC/USDT": 0.31}), b, PX)
    assert orders == []


def test_garbage_weights_dont_crash():
    r, b = rm(), PaperBroker("g", 10_000, 0.0, 0)
    orders, ev = r.filter("g", Proposal({"BTC/USDT": "mucho", "ETH/USDT": float("nan")}), b, PX)
    assert orders == [] and any(e["type"] == "INVALID" for e in ev)


def test_daily_halt_only_allows_reductions():
    r, b = rm(daily_loss_limit=0.05), PaperBroker("g", 10_000, 0.0, 0)
    r.update("g", 10_000, 0)
    r.update("g", 9_000, 1000)                 # -10% en el mismo día
    orders, _ = r.filter("g", Proposal({"BTC/USDT": 0.5}), b, PX)
    assert orders == []


def test_drawdown_kill():
    r = rm(max_drawdown_kill=0.3)
    r.update("g", 10_000, 0)
    ev = r.update("g", 6_900, 1000)
    assert r.is_killed("g") and any(e["type"] == "KILLED" for e in ev)


# ---------------- motor ----------------
class Peeker(Bot):
    """Bot que registra cuántos datos ve, para comprobar que nunca ve el futuro."""
    type = "peek"

    def __init__(self):
        super().__init__("peek", "15m")
        self.seen = []

    def decide(self, ctx):
        self.seen.append((ctx.market.k, len(ctx.market.series("BTC/USDT"))))
        return None


def make_arena(tmp_path, bots, bars=800, luck=0):
    cfg = json.loads(json.dumps(CFG))
    cfg["market"]["symbols"] = ["BTC/USDT", "ETH/USDT"]
    cfg["market"]["warmup_bars"] = 100
    cfg["risk"]["kill_file"] = str(tmp_path / "KILL")
    m = Market(synthetic(cfg["market"]["symbols"], bars, "15m", seed=1))
    led = Ledger(tmp_path / "t.db", "t")
    led.start_run("test", cfg)
    lb = build_luck_bots({"luck": {"random_bots": luck}})
    return Arena(cfg, bots, m, led, luck_bots=lb), cfg


def test_no_lookahead(tmp_path):
    p = Peeker()
    a, _ = make_arena(tmp_path, [p], bars=300)
    a.run_backtest(progress=False)
    assert p.seen and all(n == k + 1 for k, n in p.seen)


def test_full_backtest_with_mock_grok(tmp_path):
    cfg = json.loads(json.dumps(CFG))
    bots = build_bots(cfg, MockLLM())
    a, cfg = make_arena(tmp_path, bots, bars=3000, luck=4)
    a.run_backtest(progress=False)
    for name, br in a.brokers.items():
        eq = br.equity(a.market.prices(len(a.market) - 1))
        assert eq > 0 and br.cash >= -1e-6, name
        assert all(q >= 0 for q in br.qty.values())


def test_global_kill_file_flattens_everything(tmp_path):
    cfg = json.loads(json.dumps(CFG))
    a, cfg = make_arena(tmp_path, build_bots(cfg, MockLLM()), bars=1500)
    a.run_backtest(0, 1000, progress=False)
    (tmp_path / "KILL").write_text("stop")
    a.run_backtest(1000, 1002, progress=False)
    assert a.halted and all(not br.qty for br in a.brokers.values())


def test_state_roundtrip(tmp_path):
    cfg = json.loads(json.dumps(CFG))
    a, _ = make_arena(tmp_path, build_bots(cfg, MockLLM()), bars=1200)
    a.run_backtest(progress=False)
    a.save_state()
    b, _ = make_arena(tmp_path, build_bots(cfg, MockLLM()), bars=1200)
    assert b.load_state()
    for n in a.brokers:
        assert b.brokers[n].cash == pytest.approx(a.brokers[n].cash)


# ---------------- cliente de Grok (HTTP simulado) ----------------
class FakeResp:
    def __init__(self, code, body):
        self.status_code, self._b, self.text = code, body, json.dumps(body)

    def json(self):
        return self._b

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(str(self.status_code))


def grok(monkeypatch, responses, **cfg_over):
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    calls = []

    def fake_post(url, headers, data, timeout):
        calls.append(json.loads(data))
        return responses.pop(0)
    monkeypatch.setattr("arena.llm.requests.post", fake_post)
    monkeypatch.setattr("arena.llm.time.sleep", lambda s: None)
    cfg = dict(CFG["llm"]); cfg.update(cfg_over)
    return GrokClient(cfg), calls


def ok(content, tin=1000, tout=200):
    return FakeResp(200, {"model": "grok-x", "choices": [{"message": {"content": content}}],
                          "usage": {"prompt_tokens": tin, "completion_tokens": tout}})


def test_grok_client_parses_and_costs(monkeypatch):
    c, calls = grok(monkeypatch, [ok('{"a": 1}')], price_input_per_m=2.0, price_output_per_m=10.0)
    out, meta = c.chat_json("sys", {"x": 1}, {"type": "object"}, "t")
    assert out == {"a": 1}
    assert meta["cost_usd"] == pytest.approx(1000 / 1e6 * 2 + 200 / 1e6 * 10)
    assert calls[0]["response_format"]["type"] == "json_schema"
    assert calls[0]["model"] == CFG["llm"]["model"]


def test_grok_client_falls_back_when_schema_unsupported(monkeypatch):
    c, calls = grok(monkeypatch, [FakeResp(400, {"error": "bad"}), ok('texto antes {"a": 2} después')])
    out, _ = c.chat_json("sys", {}, {"type": "object"}, "t")
    assert out == {"a": 2} and calls[1]["response_format"]["type"] == "json_object"


def test_grok_client_retries_then_fails(monkeypatch):
    c, _ = grok(monkeypatch, [FakeResp(503, {}), FakeResp(503, {}), FakeResp(503, {})])
    with pytest.raises(LLMError):
        c.chat_json("sys", {}, {"type": "object"}, "t")


def test_budget_cap(monkeypatch):
    c, _ = grok(monkeypatch, [ok('{"a": 1}', tin=1_000_000)], price_input_per_m=10.0, daily_budget_usd=5.0)
    c.chat_json("sys", {}, {"type": "object"}, "t")
    with pytest.raises(BudgetExceeded):
        c.chat_json("sys", {}, {"type": "object"}, "t")


def test_grok_trader_holds_on_llm_failure(tmp_path, monkeypatch):
    from arena.bots.grok_bots import GrokTrader

    class Broken:
        def chat_json(self, *a, **k):
            raise LLMError("caído")
    bot = GrokTrader("grok_trader", "4h", llm=Broken(), risk_cfg=CFG["risk"], costs=CFG["costs"])
    a, _ = make_arena(tmp_path, [bot], bars=3000)
    a.run_backtest(progress=False)
    assert not a.brokers["grok_trader"].qty and a.brokers["grok_trader"].n_trades == 0

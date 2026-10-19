from .base import Bot
from .baselines import Breakout, BuyHold, MeanReversion, Momentum, RandomBot
from .grok_bots import GrokOverlay, GrokTrader

REGISTRY = {c.type: c for c in (BuyHold, Momentum, MeanReversion, Breakout, RandomBot, GrokTrader, GrokOverlay)}


def bot_from_spec(spec: dict, cfg: dict, llm=None):
    cls = REGISTRY[spec["type"]]
    kw = dict(name=spec["name"], every=spec.get("every", "1h"), params=spec.get("params"))
    if spec["type"].startswith("grok"):
        if llm is None:
            return None
        kw.update(llm=llm, risk_cfg=cfg["risk"], costs=cfg["costs"])
    return cls(**kw)


def build_bots(cfg: dict, llm=None) -> list[Bot]:
    bots = []
    for spec in cfg["bots"]:
        bot = bot_from_spec(spec, cfg, llm)
        if bot is None:
            print(f"  ⚠ {spec['name']} desactivado: no hay LLM configurado")
            continue
        bots.append(bot)
    return bots


def build_luck_bots(cfg: dict) -> list[Bot]:
    n = cfg.get("luck", {}).get("random_bots", 0)
    # frecuencias variadas: así la "suerte" incluye bots que operan poco (y pagan pocas comisiones)
    freqs = ["4h", "12h", "1d", "3d"]
    return [RandomBot(f"_luck_{i:02d}", every=freqs[i % len(freqs)], params={"seed": 1000 + i}) for i in range(n)]

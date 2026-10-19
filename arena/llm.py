"""Cliente de Grok (API de xAI, compatible con el formato de OpenAI) con salida JSON estructurada,
reintentos, medición de costo y tope de gasto diario. Incluye un LLM simulado para pruebas."""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone

import requests


class LLMError(Exception):
    pass


class BudgetExceeded(LLMError):
    pass


class GrokClient:
    def __init__(self, cfg: dict):
        self.base_url = cfg["base_url"].rstrip("/")
        self.model = cfg["model"]
        self.api_key = os.environ.get(cfg.get("api_key_env", "XAI_API_KEY"), "")
        self.temperature = cfg.get("temperature", 0.2)
        self.timeout = cfg.get("timeout_s", 90)
        self.retries = cfg.get("max_retries", 2)
        self.p_in = cfg.get("price_input_per_m", 0.0)
        self.p_out = cfg.get("price_output_per_m", 0.0)
        self.budget = cfg.get("daily_budget_usd", 5.0)
        self.extra = cfg.get("extra_body", {}) or {}
        self.spent: dict[str, float] = {}
        self.tokens = {"input": 0, "output": 0, "calls": 0}
        if not self.api_key:
            raise LLMError(f"Falta la API key: exportá {cfg.get('api_key_env', 'XAI_API_KEY')}=xai-...")

    def _today(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def list_models(self) -> list[str]:
        r = requests.get(f"{self.base_url}/models", headers={"Authorization": f"Bearer {self.api_key}"},
                         timeout=self.timeout)
        r.raise_for_status()
        return [m["id"] for m in r.json().get("data", [])]

    def chat_json(self, system: str, payload: dict, schema: dict, name: str) -> tuple[dict, dict]:
        if self.budget and self.spent.get(self._today(), 0.0) >= self.budget:
            raise BudgetExceeded(f"tope diario de USD {self.budget} alcanzado")
        body = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": name, "schema": schema, "strict": True}},
            **self.extra,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        last_err = None
        for attempt in range(self.retries + 1):
            t0 = time.time()
            try:
                r = requests.post(f"{self.base_url}/chat/completions", headers=headers,
                                  data=json.dumps(body), timeout=self.timeout)
                if r.status_code == 400 and body["response_format"]["type"] == "json_schema":
                    # algunos modelos no aceptan json_schema estricto: caemos a JSON libre
                    body["response_format"] = {"type": "json_object"}
                    body["messages"][0]["content"] += "\n\nDevolvé SOLO un JSON con este esquema:\n" + json.dumps(schema)
                    continue
                if r.status_code in (429, 500, 502, 503, 504):
                    raise LLMError(f"HTTP {r.status_code}: {r.text[:200]}")
                r.raise_for_status()
                data = r.json()
                content = data["choices"][0]["message"]["content"]
                parsed = _parse_json(content)
                usage = data.get("usage", {}) or {}
                tin, tout = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
                cost = tin / 1e6 * self.p_in + tout / 1e6 * self.p_out
                self.spent[self._today()] = self.spent.get(self._today(), 0.0) + cost
                self.tokens["input"] += tin
                self.tokens["output"] += tout
                self.tokens["calls"] += 1
                meta = {"model": data.get("model", self.model), "latency_s": round(time.time() - t0, 2),
                        "tokens_in": tin, "tokens_out": tout, "cost_usd": round(cost, 5)}
                return parsed, meta
            except (requests.RequestException, LLMError, ValueError, KeyError) as e:
                last_err = e
                time.sleep(2 ** attempt)
        raise LLMError(f"Grok no respondió bien tras {self.retries + 1} intentos: {last_err}")


def _parse_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise ValueError("la respuesta no contiene JSON")
        return json.loads(m.group(0))


class MockLLM:
    """Imita a Grok con reglas fijas. Sirve para probar el sistema sin gastar ni conectarse.
    NO representa cómo decidiría Grok."""

    model = "mock"

    def __init__(self, *_, **__):
        self.tokens = {"input": 0, "output": 0, "calls": 0}

    def chat_json(self, system: str, payload: dict, schema: dict, name: str) -> tuple[dict, dict]:
        self.tokens["calls"] += 1
        feats = payload["market"]
        if name == "trade_plan":
            pos = []
            for s, f in feats.items():
                bull = f["ret_24h_pct"] > 0 and f["dist_ema_7d_pct"] > 0 and f["rsi14"] < 70
                pos.append({"symbol": s, "target_weight": 0.3 if bull else 0.0, "stop_loss_pct": 0.07,
                            "confidence": 0.6 if bull else 0.5, "reason": "mock: tendencia" if bull else "mock: afuera"})
            return {"market_view": "mock", "positions": pos, "risk_notes": "mock"}, {"model": "mock"}
        avg = sum(f["dist_ema_7d_pct"] for f in feats.values()) / len(feats)
        vol = sum(f["vol_24h_ann_pct"] for f in feats.values()) / len(feats)
        if avg < -5 and vol > 90:
            reg, mult = "crisis", 0.0
        elif avg < 0:
            reg, mult = "risk_off", 0.4
        elif vol > 100:
            reg, mult = "neutral", 0.7
        else:
            reg, mult = "risk_on", 1.0
        return {"regime": reg, "risk_multiplier": mult, "avoid_symbols": [], "reason": "mock"}, {"model": "mock"}

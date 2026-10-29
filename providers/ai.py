from __future__ import annotations

import json

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from config.providers import ProviderSettings
from core.state import Market
from providers.common import ProviderUnavailable, request


class StrategyParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    short_window: int = Field(ge=2, le=99, strict=True)
    long_window: int = Field(ge=3, le=100, strict=True)

    @model_validator(mode="after")
    def ordered(self):
        if self.short_window >= self.long_window:
            raise ValueError("Short window must be smaller than long window")
        return self


class StrategyPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidates: list[StrategyParameters] = Field(min_length=1, max_length=3)


class AIProvider:
    """Providers return bounded parameters; generated Python never gains tools or credentials."""

    def __init__(self, settings: ProviderSettings) -> None:
        self.settings = settings
        self.backend = settings.ai_backend()
        self.status = "deterministic fallback" if self.backend == "none" else "configured"

    async def propose(self, market: Market, volatility: float) -> tuple[tuple[int, int], ...]:
        s = self.settings
        prompt = json.dumps({"market": str(market), "observed_return_volatility": volatility,
                             "task": "Return only JSON with 1 to 3 MA parameter candidates. Integers 2 <= short_window < long_window <= 100.",
                             "schema": StrategyPlan.model_json_schema()})
        if self.backend == "openai":
            if not s.openai_api_key:
                raise ProviderUnavailable("OpenAI key missing")
            from openai import AsyncOpenAI
            async with AsyncOpenAI(api_key=s.secret("openai_api_key"), timeout=s.request_timeout_seconds, max_retries=1) as client:
                response = await client.responses.create(model=s.openai_model, input=prompt, max_output_tokens=500)
                output = response.output_text
        elif self.backend == "anthropic":
            if not s.anthropic_api_key or not s.anthropic_model:
                raise ProviderUnavailable("Anthropic key/model missing")
            from anthropic import AsyncAnthropic
            async with AsyncAnthropic(api_key=s.secret("anthropic_api_key"), timeout=s.request_timeout_seconds, max_retries=1) as client:
                response = await client.messages.create(model=s.anthropic_model, max_tokens=500, messages=[{"role": "user", "content": prompt}])
                output = "".join(block.text for block in response.content if block.type == "text")
        elif self.backend == "ollama":
            if not s.ollama_model:
                raise ProviderUnavailable("Ollama model missing")
            async with httpx.AsyncClient(timeout=s.request_timeout_seconds) as client:
                response = await request(client, "POST", s.ollama_base_url + "/api/chat", json={
                    "model": s.ollama_model, "messages": [{"role": "user", "content": prompt}],
                    "stream": False, "format": StrategyPlan.model_json_schema()})
                output = response["message"]["content"]
        else:
            raise ProviderUnavailable("No AI provider configured")
        if len(output) > 4096:
            raise ValueError("AI response too large")
        plan = StrategyPlan.model_validate_json(output)
        self.status = "validated parameter plan received"
        return tuple((item.short_window, item.long_window) for item in plan.candidates)

"""Budget-aware OpenAI-compatible model client with deterministic fallback."""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from campaign_automaton.config import Settings
from campaign_automaton.store import SQLiteStore

log = logging.getLogger(__name__)

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "campaign_agent_result",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "assumptions": {"type": "array", "items": {"type": "string"}},
                "sources_needed": {"type": "array", "items": {"type": "string"}},
                "deliverables": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string"},
                            "channel": {"type": "string"},
                            "title": {"type": "string"},
                            "content": {"type": "string"},
                            "data_json": {"type": "string"},
                        },
                        "required": ["kind", "channel", "title", "content", "data_json"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": [
                "summary",
                "confidence",
                "assumptions",
                "sources_needed",
                "deliverables",
            ],
            "additionalProperties": False,
        },
    },
}


@dataclass(slots=True)
class ModelResult:
    data: dict[str, Any]
    model: str
    prompt_tokens: int
    completion_tokens: int
    deterministic: bool


class ModelBudgetExceeded(RuntimeError):
    pass


class LLMClient:
    def __init__(self, settings: Settings, store: SQLiteStore) -> None:
        self.settings = settings
        self.store = store
        self._run_counts: dict[str, int] = {}
        self._lock = threading.RLock()
        base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE")
        self.client = (
            OpenAI(
                api_key=os.getenv("OPENAI_API_KEY"),
                base_url=base_url,
                timeout=settings.llm_timeout_seconds,
                max_retries=2,
            )
            if settings.llm_available
            else None
        )

    @property
    def mode(self) -> str:
        return "openai-compatible" if self.client is not None else "deterministic"

    def _check_budget(self, run_id: str) -> None:
        with self._lock:
            run_count = self._run_counts.get(run_id, 0)
            usage = self.store.usage_counts()
            if run_count >= self.settings.llm_max_requests_per_run:
                raise ModelBudgetExceeded("per-run model request budget exhausted")
            if usage["hourly"] >= self.settings.llm_max_requests_per_hour:
                raise ModelBudgetExceeded("hourly model request budget exhausted")
            if usage["daily"] >= self.settings.llm_max_requests_per_day:
                raise ModelBudgetExceeded("daily model request budget exhausted")
            self._run_counts[run_id] = run_count + 1

    def generate(
        self,
        *,
        campaign_id: str,
        run_id: str,
        agent: str,
        system_prompt: str,
        user_prompt: str,
        deterministic_result: dict[str, Any],
    ) -> ModelResult:
        if self.client is None:
            return ModelResult(deterministic_result, "deterministic", 0, 0, True)
        self._check_budget(run_id)
        models = [self.settings.llm_model]
        if self.settings.llm_fallback_model not in models:
            models.append(self.settings.llm_fallback_model)
        last_error: Exception | None = None
        for model in models:
            try:
                parameters: dict[str, Any] = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "response_format": OUTPUT_SCHEMA,
                }
                if model.startswith("gpt-"):
                    parameters["max_completion_tokens"] = self.settings.llm_max_output_tokens
                else:
                    parameters["max_tokens"] = self.settings.llm_max_output_tokens
                response = self.client.chat.completions.create(**parameters)
                content = response.choices[0].message.content
                if not content:
                    raise ValueError("model returned empty content")
                data = json.loads(content)
                usage = response.usage
                prompt_tokens = int(usage.prompt_tokens if usage else 0)
                completion_tokens = int(usage.completion_tokens if usage else 0)
                self.store.record_inference_usage(
                    campaign_id,
                    run_id,
                    agent,
                    model,
                    prompt_tokens,
                    completion_tokens,
                    0.0,
                )
                return ModelResult(data, model, prompt_tokens, completion_tokens, False)
            except Exception as exc:  # provider or schema failure; retry on fallback model
                last_error = exc
                log.warning("Model %s failed for %s: %s", model, agent, exc)
        log.error("All models failed for %s; using deterministic result: %s", agent, last_error)
        self.store.audit(
            campaign_id,
            "system",
            "inference.fallback",
            "run",
            run_id,
            {"agent": agent, "error": str(last_error)},
        )
        return ModelResult(deterministic_result, "deterministic-fallback", 0, 0, True)

    def clear_run_budget(self, run_id: str) -> None:
        with self._lock:
            self._run_counts.pop(run_id, None)

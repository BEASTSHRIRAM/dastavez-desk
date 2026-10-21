"""Language-model provider abstraction. The rest of the app depends only on LLMProvider.complete_json.
'demo' means no model: extraction uses the deterministic rule engine."""
import json
import re
from typing import Protocol

import httpx

from app.config import Settings, get_settings


class LLMError(RuntimeError):
    pass


class LLMProvider(Protocol):
    name: str

    def complete_json(self, system: str, user: str) -> dict: ...


class DemoProvider:
    name = "demo"

    def complete_json(self, system: str, user: str) -> dict:
        raise LLMError("Demo mode has no language model. Rule-based extraction is used instead.")


def _parse_json_object(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start:end + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError("The model did not return valid JSON.") from exc
    if not isinstance(data, dict):
        raise LLMError("The model returned an unexpected structure.")
    return data


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, settings: Settings):
        if not settings.llm_api_key:
            raise LLMError("LLM_API_KEY is not set.")
        self.key = settings.llm_api_key
        self.model = settings.llm_model or "claude-sonnet-5-5"

    def complete_json(self, system: str, user: str) -> dict:
        try:
            r = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": self.key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": self.model, "max_tokens": 2000, "system": system,
                      "messages": [{"role": "user", "content": user}]},
                timeout=60,
            )
            r.raise_for_status()
            return _parse_json_object("".join(b.get("text", "") for b in r.json()["content"]))
        except httpx.HTTPError as exc:
            raise LLMError(f"Language model request failed: {exc.__class__.__name__}") from exc


class OpenAIProvider:
    """Any OpenAI-compatible chat-completions endpoint (OpenAI itself, or Groq)."""
    name = "openai"

    def __init__(self, key: str, model: str, base_url: str = "https://api.openai.com/v1", name: str = "openai"):
        if not key or not model:
            raise LLMError(f"An API key and model are required for the {name} provider.")
        self.key, self.model, self.base_url, self.name = key, model, base_url.rstrip("/"), name

    def complete_json(self, system: str, user: str) -> dict:
        try:
            r = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={"authorization": f"Bearer {self.key}"},
                json={"model": self.model, "response_format": {"type": "json_object"}, "temperature": 0,
                      "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
                timeout=60,
            )
            r.raise_for_status()
            return _parse_json_object(r.json()["choices"][0]["message"]["content"])
        except httpx.HTTPError as exc:
            raise LLMError(f"Language model request failed: {exc.__class__.__name__}") from exc


GROQ_BASE_URL = "https://api.groq.com/openai/v1"


def get_llm_provider(settings: Settings | None = None) -> LLMProvider:
    settings = settings or get_settings()
    match settings.llm_provider:
        case "anthropic":
            return AnthropicProvider(settings)
        case "openai":
            return OpenAIProvider(settings.llm_api_key, settings.llm_model)
        case "groq":
            return OpenAIProvider(settings.groq_api_key, settings.groq_llm_model, GROQ_BASE_URL, name="groq")
        case _:
            return DemoProvider()

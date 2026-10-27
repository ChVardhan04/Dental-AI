"""Model provider abstraction: the application never hard-codes a single AI vendor.

AIProvider
 ├── TemplateProvider   (deterministic, offline; default)
 ├── OpenAIProvider
 ├── AnthropicProvider
 └── LocalModelProvider (any OpenAI-compatible server: Ollama, vLLM, LM Studio ...)
"""
import base64
import json
import logging
import re
from abc import ABC, abstractmethod

import httpx

from app.core.config import settings

logger = logging.getLogger("dentedge.llm")


class ProviderUnavailable(RuntimeError):
    pass


def _parse_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("Provider did not return JSON")
    return json.loads(text[start:end + 1])


class AIProvider(ABC):
    name = "abstract"
    supports_generation = True

    @abstractmethod
    def complete_json(self, system: str, user: str) -> dict: ...

    def vision_json(self, system: str, user: str, image_png: bytes) -> dict:
        raise ProviderUnavailable(f"{self.name} does not support image input")

    def transcribe(self, audio: bytes, filename: str, content_type: str) -> dict:
        raise ProviderUnavailable(f"{self.name} does not provide speech-to-text")


class TemplateProvider(AIProvider):
    """No network calls. Explanations are produced by the deterministic template engine instead."""
    name = "template"
    supports_generation = False

    def complete_json(self, system, user):
        raise ProviderUnavailable("Template provider does not generate free text")


class OpenAICompatibleProvider(AIProvider):
    def __init__(self, name: str, base_url: str, api_key: str, model: str):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def _headers(self):
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _chat(self, messages: list[dict]) -> dict:
        body = {"model": self.model, "messages": messages, "temperature": 0.1, "response_format": {"type": "json_object"}}
        try:
            r = httpx.post(f"{self.base_url}/chat/completions", headers=self._headers(), json=body, timeout=settings.llm_timeout_seconds)
            r.raise_for_status()
            return _parse_json(r.json()["choices"][0]["message"]["content"])
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise ProviderUnavailable(f"{self.name} request failed: {exc}") from exc

    def complete_json(self, system, user):
        return self._chat([{"role": "system", "content": system}, {"role": "user", "content": user}])

    def vision_json(self, system, user, image_png):
        b64 = base64.b64encode(image_png).decode()
        return self._chat([{"role": "system", "content": system}, {"role": "user", "content": [
            {"type": "text", "text": user}, {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}]}])

    def transcribe(self, audio, filename, content_type):
        url = (settings.local_speech_base_url or self.base_url).rstrip("/")
        try:
            r = httpx.post(f"{url}/audio/transcriptions", headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {},
                           files={"file": (filename, audio, content_type)},
                           data={"model": "whisper-1", "response_format": "verbose_json", "prompt": DENTAL_STT_PROMPT},
                           timeout=max(60, settings.llm_timeout_seconds))
            r.raise_for_status()
            data = r.json()
            segments = [{"start": s.get("start"), "end": s.get("end"), "text": s.get("text", "").strip()} for s in data.get("segments", [])]
            return {"text": data.get("text", ""), "segments": segments, "language": data.get("language")}
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderUnavailable(f"Speech provider request failed: {exc}") from exc


class AnthropicProvider(AIProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def _call(self, system: str, content) -> dict:
        try:
            r = httpx.post("https://api.anthropic.com/v1/messages", timeout=settings.llm_timeout_seconds,
                           headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                           json={"model": self.model, "max_tokens": 1500, "temperature": 0.1, "system": system,
                                 "messages": [{"role": "user", "content": content}]})
            r.raise_for_status()
            text = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
            return _parse_json(text)
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise ProviderUnavailable(f"anthropic request failed: {exc}") from exc

    def complete_json(self, system, user):
        return self._call(system, user + "\n\nRespond with a single JSON object only.")

    def vision_json(self, system, user, image_png):
        b64 = base64.b64encode(image_png).decode()
        return self._call(system, [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                                   {"type": "text", "text": user + "\n\nRespond with a single JSON object only."}])


DENTAL_STT_PROMPT = ("Dental consultation. Terms: caries, gingiva, gingivitis, periodontal, probing depth, bleeding on probing, furcation, "
                     "mobility, recession, molar, premolar, incisor, canine, mesial, distal, buccal, lingual, occlusal, bitewing, periapical.")


def get_llm_provider() -> AIProvider:
    p = settings.llm_provider.lower()
    if p == "openai" and settings.openai_api_key:
        return OpenAICompatibleProvider("openai", "https://api.openai.com/v1", settings.openai_api_key, settings.llm_model or "gpt-4o-mini")
    if p == "anthropic" and settings.anthropic_api_key:
        return AnthropicProvider(settings.anthropic_api_key, settings.llm_model or "claude-sonnet-4-5")
    if p == "local":
        return OpenAICompatibleProvider("local", settings.local_llm_base_url, "", settings.llm_model or "llama3.1")
    if p not in {"template", "mock"}:
        logger.warning("LLM provider '%s' is not fully configured; using deterministic templates", p)
    return TemplateProvider()


def get_speech_provider() -> AIProvider | None:
    p = settings.speech_provider.lower()
    if p == "openai" and settings.openai_api_key:
        return OpenAICompatibleProvider("openai-whisper", "https://api.openai.com/v1", settings.openai_api_key, "whisper-1")
    if p == "local" and settings.local_speech_base_url:
        return OpenAICompatibleProvider("local-whisper", settings.local_speech_base_url, "", "whisper-1")
    return None

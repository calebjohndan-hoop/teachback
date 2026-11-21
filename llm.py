"""Gemini wrapper. Every call says which task it is for, so the offline demo
brain (mock.py) can stand in for Gemini with the same interface."""
from __future__ import annotations

import json
import logging
import re
import time

log = logging.getLogger("teachback")

DEFAULT_MODEL = "gemini-flash-latest"

_RESOLVED: dict[str, str] = {}  # wanted model -> model that actually exists


class LLMError(Exception):
    pass


def parse_json(text: str) -> dict:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.S)
        if m:
            return json.loads(m.group(0))
        raise


def _version(name: str) -> float:
    m = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
    return float(m.group(1)) if m else 0.0


def pick_model(available: list[str], wanted: str) -> str:
    """Use the requested model if it exists, else the newest general-purpose Flash."""
    if wanted in available:
        return wanted
    if "gemini-flash-latest" in available:
        return "gemini-flash-latest"
    skip = ("lite", "image", "tts", "audio", "live", "embedding", "thinking", "8b")
    flash = [n for n in available if "flash" in n and not any(s in n for s in skip)]
    if not flash:
        return wanted
    flash.sort(key=lambda n: (_version(n), "preview" not in n and "exp" not in n), reverse=True)
    return flash[0]


class GeminiLLM:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        from google import genai
        from google.genai import types

        self._types = types
        self._client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=45_000))
        wanted = model or DEFAULT_MODEL
        self.model = _RESOLVED.get(wanted, wanted)
        self._wanted = wanted

    def _resolve(self) -> bool:
        """Called only when the model is missing: switch to one that exists."""
        try:
            names = []
            for m in self._client.models.list(config={"page_size": 100}):
                actions = getattr(m, "supported_actions", None) or []
                if actions and "generateContent" not in actions:
                    continue
                names.append((m.name or "").removeprefix("models/"))
        except Exception as e:  # noqa: BLE001
            log.warning("model list failed: %s", e)
            return False
        chosen = pick_model(names, self.model)
        log.warning("model %s unavailable, switching to %s", self.model, chosen)
        if chosen == self.model:
            return False
        self.model = _RESOLVED[self._wanted] = chosen
        return True

    def _call(self, system: str, prompt: str, temperature: float, as_json: bool) -> str:
        config = self._types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            response_mime_type="application/json" if as_json else "text/plain",
        )
        t0 = time.time()
        try:
            resp = self._client.models.generate_content(model=self.model, contents=prompt, config=config)
        except Exception as e:  # noqa: BLE001
            if ("NOT_FOUND" in str(e) or "404" in str(e)) and self._resolve():
                resp = self._client.models.generate_content(model=self.model, contents=prompt, config=config)
            else:
                log.warning("gemini %s failed after %.1fs: %s", self.model, time.time() - t0, e)
                raise
        log.warning("gemini %s ok in %.1fs", self.model, time.time() - t0)
        return resp.text or ""

    def json(self, task: str, system: str, prompt: str, context: dict | None = None, temperature: float = 0.2) -> dict:
        last: Exception | None = None
        for _ in range(2):  # one retry on bad JSON / transient error
            try:
                data = parse_json(self._call(system, prompt, temperature, True))
                if isinstance(data, dict):
                    return data
                last = ValueError("model returned non-object JSON")
            except Exception as e:  # noqa: BLE001
                last = e
        raise LLMError(f"Gemini failed on '{task}': {last}")

    def text(self, task: str, system: str, prompt: str, context: dict | None = None, temperature: float = 0.8) -> str:
        try:
            out = self._call(system, prompt, temperature, False).strip()
        except Exception as e:  # noqa: BLE001
            raise LLMError(f"Gemini failed on '{task}': {e}") from e
        if not out:
            raise LLMError(f"Gemini returned an empty reply on '{task}'")
        return out

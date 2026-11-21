"""Gemini wrapper. Every call says which task it is for, so the offline demo
brain (mock.py) can stand in for Gemini with the same interface."""
from __future__ import annotations

import json
import logging
import re
import time

log = logging.getLogger("teachback")

DEFAULT_MODEL = "gemini-flash-latest"

_RESOLVED: dict[str, str] = {}  # wanted model -> model that actually worked
_AVAILABLE: list[str] | None = None
RETRYABLE = ("404", "NOT_FOUND", "429", "RESOURCE_EXHAUSTED", "500", "503", "UNAVAILABLE",
             "504", "DEADLINE", "timed out", "Timeout", "timeout")


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
        self._client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=30_000))
        wanted = model or DEFAULT_MODEL
        self.model = _RESOLVED.get(wanted, wanted)
        self._wanted = wanted
        self._no_thinking_cfg = False

    def _available(self) -> list[str]:
        global _AVAILABLE
        if _AVAILABLE is None:
            names = []
            try:
                for m in self._client.models.list(config={"page_size": 100}):
                    actions = getattr(m, "supported_actions", None) or []
                    if actions and "generateContent" not in actions:
                        continue
                    names.append((m.name or "").removeprefix("models/"))
            except Exception as e:  # noqa: BLE001
                log.warning("model list failed: %s", e)
            _AVAILABLE = names
        return _AVAILABLE

    def _candidates(self) -> list[str]:
        """Current model first, then other usable Flash models, newest first."""
        names = self._available()
        first = pick_model(names, self.model) if names else self.model
        skip = ("image", "tts", "audio", "live", "embedding", "8b")
        others = [n for n in names if "flash" in n and not any(s in n for s in skip) and n != first]
        others.sort(key=lambda n: (_version(n), "lite" not in n, "preview" not in n and "exp" not in n), reverse=True)
        return [first] + others[:3]

    def _thinking(self):
        """Keep reasoning short: TeachBack needs quick, simple replies."""
        if self._no_thinking_cfg:
            return None
        lvl = "MINIMAL" if "MINIMAL" in self._types.ThinkingLevel.__members__ else "LOW"
        return self._types.ThinkingConfig(thinking_level=lvl)

    def _once(self, model: str, system: str, prompt: str, temperature: float, as_json: bool) -> str:
        config = self._types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            response_mime_type="application/json" if as_json else "text/plain",
            thinking_config=self._thinking(),
        )
        try:
            return self._client.models.generate_content(model=model, contents=prompt, config=config).text or ""
        except Exception as e:  # noqa: BLE001
            if "thinking" in str(e).lower() and not self._no_thinking_cfg:
                self._no_thinking_cfg = True
                config.thinking_config = None
                return self._client.models.generate_content(model=model, contents=prompt, config=config).text or ""
            raise

    def _call(self, system: str, prompt: str, temperature: float, as_json: bool) -> str:
        """Try the current model; if it is missing, overloaded or too slow, fall back."""
        tried: list[str] = []
        last: Exception | None = None
        try_list = [self.model]
        while try_list:
            model = try_list.pop(0)
            if model in tried:
                continue
            tried.append(model)
            t0 = time.time()
            try:
                out = self._once(model, system, prompt, temperature, as_json)
                log.warning("gemini %s ok in %.1fs", model, time.time() - t0)
                if model != self.model:
                    self.model = _RESOLVED[self._wanted] = model
                return out
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                log.warning("gemini %s failed after %.1fs: %s", model, time.time() - t0, msg[:200])
                last = e
                if not any(s in msg for s in RETRYABLE) or len(tried) >= 4:
                    break
                if len(tried) == 1:
                    try_list = [m for m in self._candidates() if m not in tried]
        raise last if last else LLMError("no model available")

    def json(self, task: str, system: str, prompt: str, context: dict | None = None, temperature: float = 0.2) -> dict:
        last: Exception | None = None
        for _ in range(2):  # one retry, only for malformed JSON
            try:
                raw = self._call(system, prompt, temperature, True)
            except Exception as e:  # noqa: BLE001
                raise LLMError(f"Gemini is busy or unreachable right now ({task}). Please try again. [{str(e)[:160]}]") from e
            try:
                data = parse_json(raw)
                if isinstance(data, dict):
                    return data
                last = ValueError("model returned non-object JSON")
            except Exception as e:  # noqa: BLE001
                last = e
        raise LLMError(f"Gemini returned unreadable output on '{task}': {last}")

    def text(self, task: str, system: str, prompt: str, context: dict | None = None, temperature: float = 0.8) -> str:
        try:
            out = self._call(system, prompt, temperature, False).strip()
        except Exception as e:  # noqa: BLE001
            raise LLMError(f"Gemini is busy or unreachable right now ({task}). [{str(e)[:160]}]") from e
        if not out:
            raise LLMError(f"Gemini returned an empty reply on '{task}'")
        return out

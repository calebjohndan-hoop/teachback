"""Gemini wrapper. Every call says which task it is for, so the offline demo
brain (mock.py) can stand in for Gemini with the same interface."""
from __future__ import annotations

import json
import re

DEFAULT_MODEL = "gemini-2.5-flash"


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


class GeminiLLM:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        from google import genai
        from google.genai import types

        self._types = types
        self._client = genai.Client(api_key=api_key)
        self.model = model or DEFAULT_MODEL

    def _call(self, system: str, prompt: str, temperature: float, as_json: bool) -> str:
        config = self._types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            response_mime_type="application/json" if as_json else "text/plain",
        )
        resp = self._client.models.generate_content(model=self.model, contents=prompt, config=config)
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

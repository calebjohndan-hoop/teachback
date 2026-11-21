"""Offline demo brain: a keyword-based stand-in for Gemini so the app runs with
no API key (handy for judges, testing, and demos with bad Wi-Fi). It is far
dumber than Gemini but uses the exact same interface and JSON shapes."""
from __future__ import annotations

import re

# name -> (description, weight, keywords)
OHM = {
    "Voltage": ("Voltage is the electrical push (potential difference) that drives current, in volts.", 3,
                ["voltage", "potential", "push", "volt"]),
    "Current": ("Current is the rate of flow of electric charge, measured in amperes.", 3,
                ["current", "flow", "amp", "charge"]),
    "Resistance": ("Resistance opposes the flow of current and is measured in ohms.", 3,
                   ["resist", "oppos", "ohm"]),
    "V = IR relationship": ("Voltage equals current times resistance, so current is proportional to voltage at fixed resistance.", 3,
                            ["v ir", "v i r", "proportional", "times", "multiply", "i v r", "divide"]),
    "Worked example": ("A numeric example that applies the formula correctly.", 2,
                       ["example", "for instance", "if you have", "say you", "let s say"]),
    "Limits of Ohm's law": ("It only holds for ohmic conductors at constant temperature, not for devices like diodes.", 1,
                            ["temperature", "diode", "non ohmic", "only works", "doesn t apply", "does not apply"]),
}
OHM_MISCONCEPTIONS = {
    "Resistance": ["more resistance means more current", "resistance increases current", "higher resistance more current"],
    "V = IR relationship": ["voltage equals current divided by resistance", "voltage is current divided by resistance"],
}

GENERIC = {
    "Core definition": ("A clear statement of what the topic is.", 3, ["is a", "is the", "means", "defined", "refers to"]),
    "How it works": ("The mechanism or process behind it.", 3, ["because", "works", "happens", "which causes", "so that", "process"]),
    "Why it matters": ("Why it is important or where it is used.", 2, ["important", "matters", "used", "useful", "helps"]),
    "An example": ("A concrete example that illustrates it.", 2, ["example", "for instance", "imagine", "like when", "say you"]),
    "Limits or common mistakes": ("Where it does not apply or what people often get wrong.", 1,
                                  ["mistake", "limit", "except", "doesn t", "does not", "however", "but not"]),
}

STUDENT_LINES = {
    "kid": {
        "opening": "Hi teacher! I'm ten and I know NOTHING about {topic}. What is it?",
        "missing": "Ooh okay! But what's {name}? Can you tell me like I'm ten?",
        "vague": "Hmm I kinda get it... can you give me an example of {name} from real life?",
        "misconception": "Wait, wait. That part about {name} confused me... is that really how it works?",
    },
    "skeptic": {
        "opening": "Good morning. I'm told you can explain {topic}. Please begin with a precise definition.",
        "missing": "You haven't addressed {name}. How would you define it precisely?",
        "vague": "That's rather imprecise. What exactly do you mean regarding {name}, and how do we know?",
        "misconception": "Hm. Your claim about {name} seems inconsistent. Can you justify it?",
    },
    "whyguy": {
        "opening": "Yo, so what even is {topic}? Start from zero, I'm lost.",
        "missing": "Okay cool, but what about {name}? Where does that come in?",
        "vague": "But why though? Like why does {name} work that way?",
        "misconception": "Hold up, that bit about {name} sounds off... why would that be true?",
    },
}


def _table(topic: str) -> dict:
    return OHM if "ohm" in topic.lower() else GENERIC


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s.lower()).split())


STOP = {"which", "their", "about", "there", "these", "those", "where", "would", "should", "could",
        "explanation", "correct", "include", "concept", "between", "other", "using", "being"}


def _derived_keywords(name: str, description: str) -> list[str]:
    """For concepts the offline brain didn't invent (e.g. a Gemini-built or re-teach plan),
    use the meaningful words of the concept itself as its keywords."""
    words = re.findall(r"[a-z]{5,}", f"{name} {description}".lower())
    out = []
    for w in words:
        stem = w[:6]
        if w not in STOP and stem not in out:
            out.append(stem)
    return out[:8]


class MockLLM:
    model = "offline-demo"

    def json(self, task: str, system: str, prompt: str, context: dict | None = None, temperature: float = 0.2) -> dict:
        ctx = context or {}
        if task == "concept_map":
            table = _table(ctx.get("topic", ""))
            return {"concepts": [{"name": n, "description": d, "weight": w} for n, (d, w, _) in table.items()]}
        if task == "evaluate":
            return self._evaluate(ctx)
        if task == "report":
            return self._report(ctx)
        raise ValueError(f"unknown task {task}")

    def text(self, task: str, system: str, prompt: str, context: dict | None = None, temperature: float = 0.8) -> str:
        ctx = context or {}
        lines = STUDENT_LINES.get(ctx.get("persona", "kid"), STUDENT_LINES["kid"])
        return lines.get(ctx.get("mode", "opening"), lines["missing"]).format(
            topic=ctx.get("topic", "this"), name=ctx.get("target", "that part")
        )

    def _evaluate(self, ctx: dict) -> dict:
        table = _table(ctx.get("topic", ""))
        sentences = _sentences(ctx.get("teacher_text", ""))
        out = []
        for c in ctx.get("concepts", []):
            if c["name"] in table:
                _, _, keywords = table[c["name"]]
            else:
                keywords = _derived_keywords(c["name"], c.get("description", ""))
            hits = [s for s in sentences if any(k in _norm(s) for k in keywords)]
            distinct = {k for k in keywords for s in hits if k in _norm(s)}
            bad = [s for s in sentences for m in OHM_MISCONCEPTIONS.get(c["name"], []) if table is OHM and m in _norm(s)]
            if bad:
                status, evidence = "misconception", bad[-1]
            elif hits:
                best = max(hits, key=len)
                status = "clear" if len(distinct) >= 2 and len(best) >= 30 else "partial"
                evidence = best
            else:
                status, evidence = "not_covered", ""
            out.append({"id": c["id"], "status": status, "evidence": " ".join(evidence.split()[:25]),
                        "note": {"clear": "Nicely explained.", "partial": "Add more detail or an example.",
                                 "misconception": "Double-check this claim.", "not_covered": "Not mentioned yet."}[status]})
        return {"concepts": out, "bonus": []}

    def _report(self, ctx: dict) -> dict:
        weak = [c for c in ctx.get("concepts", []) if c["status"] != "clear"]
        return {
            "summary": f"You covered {len(ctx.get('concepts', [])) - len(weak)} of {len(ctx.get('concepts', []))} key ideas. "
                       "(Offline demo mode: add a Gemini key for a real AI debrief.)",
            "corrections": [{"concept": c["name"], "correct_idea": c["description"]} for c in weak],
            "next_steps": ["Re-teach the weakest concept using a real-life example.",
                           "Try again with the Skeptical Professor for tougher questions."],
        }

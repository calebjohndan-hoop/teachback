"""Orchestration: one function per user action. Each one mixes AI calls with
the deterministic rules in engine.py."""
from __future__ import annotations

import prompts as P
from engine import (
    FOCUS_MODE, Concept, Session, Turn, apply_evaluation, check_finished, pick_target,
)
from llm import LLMError

MAX_MESSAGE = 1500


def _concept_ctx(session: Session) -> list[dict]:
    return [{"id": c.id, "name": c.name, "status": c.status, "description": c.description} for c in session.concepts]


def parse_concepts(data: dict) -> list[Concept]:
    raw = data.get("concepts") if isinstance(data, dict) else None
    out: list[Concept] = []
    seen: set[str] = set()
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        name = " ".join(str(item.get("name", "")).split())[:60]
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        try:
            weight = int(item.get("weight", 2))
        except (TypeError, ValueError):
            weight = 2
        desc = " ".join(str(item.get("description", "")).split())[:220]
        out.append(Concept(id=f"c{len(out) + 1}", name=name, description=desc or name, weight=max(1, min(3, weight))))
        if len(out) == 7:
            break
    return out


def _student_reply(llm, session: Session, target: Concept | None, mode: str) -> str:
    ctx = {"persona": session.persona, "mode": mode, "topic": session.topic, "target": target.name if target else ""}
    try:
        return llm.text("student", *P.student_prompt(session, target, mode), context=ctx)
    except LLMError:
        # Graceful fallback so one failed call never breaks the lesson.
        if target is None:
            return f"Hi! Can you explain {session.topic} to me from the start?"
        return f"Hmm, can you tell me more about {target.name}?"


def new_session(llm, topic: str, persona: str, level: str, max_rounds: int, challenge: bool = False) -> Session:
    topic = " ".join(topic.split())[:80]
    if not topic:
        raise LLMError("Type a topic first.")
    data = llm.json("concept_map", *P.concept_map_prompt(topic, level), context={"topic": topic})
    concepts = parse_concepts(data)
    if len(concepts) < 3:
        raise LLMError("Couldn't build a lesson plan for that topic. Try naming a specific concept.")
    session = Session(topic=topic, persona=persona, level=level, max_rounds=max_rounds,
                      challenge=challenge, concepts=concepts)
    session.turns.append(Turn("student", _student_reply(llm, session, None, "opening")))
    return session


def teacher_turn(llm, session: Session, message: str) -> None:
    message = message.strip()[:MAX_MESSAGE]
    if not message or session.finished:
        return
    session.turns.append(Turn("teacher", message))
    ctx = {"topic": session.topic, "concepts": _concept_ctx(session), "teacher_text": session.teacher_text()}
    try:
        result = llm.json("evaluate", *P.evaluate_prompt(session), context=ctx)
    except LLMError:
        session.turns.pop()  # let the user resend the same message
        raise
    apply_evaluation(session, result)
    if check_finished(session):
        return
    target = pick_target(session.concepts)
    session.turns.append(Turn("student", _student_reply(llm, session, target, FOCUS_MODE[target.status])))


def finish(llm, session: Session) -> dict:
    session.finished = True
    if session.report is not None:
        return session.report
    try:
        data = llm.json("report", *P.report_prompt(session),
                        context={"topic": session.topic, "concepts": _concept_ctx(session)}, temperature=0.3)
    except LLMError:
        data = {}
    weak = [c for c in session.concepts if c.status != "clear"]
    corrections = [
        {"concept": str(x.get("concept", ""))[:80], "correct_idea": str(x.get("correct_idea", ""))[:400]}
        for x in data.get("corrections", []) if isinstance(x, dict) and x.get("correct_idea")
    ] or [{"concept": c.name, "correct_idea": c.description} for c in weak]
    steps = [str(s)[:200] for s in data.get("next_steps", []) if s][:3] or [
        "Re-teach your weakest concept using an everyday example."]
    session.report = {
        "summary": str(data.get("summary", "")).strip() or "Here's how your lesson went.",
        "corrections": corrections,
        "next_steps": steps,
    }
    return session.report

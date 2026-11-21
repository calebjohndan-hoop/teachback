"""Orchestration: one function per user action. Each one mixes AI calls with
the deterministic rules in engine.py."""
from __future__ import annotations

import re

import prompts as P
from engine import (
    FOCUS_MODE, Concept, Session, Turn, apply_evaluation, check_finished, looks_like_gaming, pick_target,
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


def clean_reply(text: str) -> str:
    """Strip stray XML-ish tags, speaker labels and wrapping quotes the model sometimes adds."""
    text = re.sub(r"</?[a-zA-Z_][\w-]*>", "", text or "")
    text = re.sub(r"^\s*(student|reply|response)\s*:\s*", "", text, flags=re.I)
    text = text.strip().strip('"').strip()
    return " ".join(text.split())


def _student_reply(llm, session: Session, target: Concept | None, mode: str) -> str:
    ctx = {"persona": session.persona, "mode": mode, "topic": session.topic, "target": target.name if target else ""}
    try:
        reply = clean_reply(llm.text("student", *P.student_prompt(session, target, mode), context=ctx))
        if reply:
            return reply
        raise LLMError("empty reply")
    except LLMError:
        # Graceful fallback so one failed call never breaks the lesson.
        if target is None:
            return f"Hi! Can you explain {session.topic} to me from the start?"
        return f"Hmm, can you tell me more about {target.name}?"


MAX_NOTES = 15000


def read_notes(data: bytes, name: str) -> str:
    """Pull plain text out of an uploaded PDF, TXT or Markdown file (first ~15k characters)."""
    name = (name or "").lower()
    text = ""
    if name.endswith(".pdf"):
        import io

        from pypdf import PdfReader

        try:
            reader = PdfReader(io.BytesIO(data))
            parts = []
            for page in reader.pages[:40]:
                parts.append(page.extract_text() or "")
                if sum(len(p) for p in parts) > MAX_NOTES:
                    break
            text = "\n".join(parts)
        except Exception as e:  # noqa: BLE001
            raise LLMError(f"Couldn't read that PDF ({e}). Try exporting it again or upload a .txt file.") from e
    else:
        text = data.decode("utf-8", errors="ignore")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) < 80:
        raise LLMError("That file has almost no readable text. If it's a scanned PDF, try a text version.")
    return text[:MAX_NOTES]


def new_session(llm, topic: str, persona: str, level: str, max_rounds: int, challenge: bool = False,
                notes: str = "", notes_name: str = "", focus: list[Concept] | None = None) -> Session:
    topic = " ".join(topic.split())[:80]
    if not topic:
        raise LLMError("Type a topic first.")
    if focus:
        # Re-teach mode: same concepts as before, marks wiped clean.
        concepts = [Concept(id=f"c{i + 1}", name=c.name, description=c.description, weight=c.weight)
                    for i, c in enumerate(focus)]
    else:
        data = llm.json("concept_map", *P.concept_map_prompt(topic, level, notes), context={"topic": topic})
        concepts = parse_concepts(data)
    if len(concepts) < (1 if focus else 3):
        raise LLMError("Couldn't build a lesson plan for that topic. Try naming a specific concept.")
    session = Session(topic=topic, persona=persona, level=level, max_rounds=max_rounds,
                      challenge=challenge, concepts=concepts, notes=notes, notes_name=notes_name,
                      reteach=bool(focus))
    session.turns.append(Turn("student", _student_reply(llm, session, None, "opening")))
    return session


def reteach(llm, old: Session) -> Session:
    """Start a fresh lesson on only the concepts that weren't clear last time."""
    weak = [c for c in old.concepts if c.status != "clear"] or old.concepts
    rounds = max(3, min(old.max_rounds, len(weak) + 2))
    return new_session(llm, old.topic, old.persona, old.level, rounds, old.challenge,
                       old.notes, old.notes_name, focus=weak)


def teacher_turn(llm, session: Session, message: str) -> None:
    message = message.strip()[:MAX_MESSAGE]
    if not message or session.finished:
        return
    session.turns.append(Turn("teacher", message))
    if looks_like_gaming(message):
        # Not graded at all: the examiner never sees it, so it can't be talked into free marks.
        session.blocked += 1
        session.last_changes = []
        session.turns.append(Turn("student", "Nice try! I only learn from real teaching, so that one "
                                             "doesn't count. Can you explain it properly?"))
        check_finished(session)
        return
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

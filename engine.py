"""Deterministic core of TeachBack: session state, scoring, target picking and
quote verification. Nothing in here calls an AI model, so it is fully testable."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

STATUSES = ("not_covered", "partial", "clear", "misconception")
STATUS_POINTS = {"not_covered": 0.0, "misconception": 0.0, "partial": 0.5, "clear": 1.0}
STATUS_LABELS = {
    "not_covered": "Not covered",
    "partial": "Partly explained",
    "clear": "Clear",
    "misconception": "Misconception",
}


@dataclass
class Concept:
    id: str
    name: str
    description: str
    weight: int = 2  # 1 = nice to have, 3 = essential
    status: str = "not_covered"
    evidence: str = ""
    note: str = ""


@dataclass
class Turn:
    role: str  # "student" or "teacher"
    text: str


@dataclass
class Session:
    topic: str
    persona: str
    level: str
    max_rounds: int
    challenge: bool = False
    concepts: list[Concept] = field(default_factory=list)
    turns: list[Turn] = field(default_factory=list)
    verified: int = 0
    rejected: int = 0
    last_changes: list[tuple[str, str, str]] = field(default_factory=list)
    finished: bool = False
    report: dict | None = None

    @property
    def rounds_done(self) -> int:
        return sum(1 for t in self.turns if t.role == "teacher")

    def teacher_text(self) -> str:
        return "\n".join(t.text for t in self.turns if t.role == "teacher")

    def concept(self, cid: str) -> Concept | None:
        return next((c for c in self.concepts if c.id == cid), None)


def score(concepts: list[Concept]) -> int:
    """Weighted understanding score, 0 to 100. Computed in code, never by the AI."""
    total = sum(c.weight for c in concepts)
    if not total:
        return 0
    earned = sum(c.weight * STATUS_POINTS.get(c.status, 0.0) for c in concepts)
    return round(100 * earned / total)


def _norm(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def verify_quote(quote: str, source: str, threshold: float = 0.85) -> bool:
    """True if `quote` really appears in `source` (ignoring case/punctuation,
    tolerating tiny copy differences). This is what stops the examiner model
    from inventing evidence the teacher never said."""
    q, s = _norm(quote), _norm(source)
    if len(q) < 6 or not s:
        return False
    if q in s:
        return True
    # Fuzzy: compare the quote against every same-length window of the source words.
    words, n = s.split(), len(q.split())
    for size in {max(1, n - 1), n, n + 1}:
        for i in range(0, max(1, len(words) - size + 1)):
            window = " ".join(words[i:i + size])
            if SequenceMatcher(None, window, q, autojunk=False).ratio() >= threshold:
                return True
    return False


def apply_evaluation(session: Session, result: dict) -> list[tuple[str, str, str]]:
    """Merge the examiner's JSON into the session. A status only changes when the
    supporting quote is verified against what the teacher actually wrote."""
    teacher = session.teacher_text()
    items = result.get("concepts", []) if isinstance(result, dict) else []
    changes: list[tuple[str, str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        concept = session.concept(str(item.get("id", "")).strip())
        if concept is None:
            continue
        status = str(item.get("status", "")).strip().lower()
        if status not in STATUSES or status == concept.status:
            continue
        if status == "not_covered":
            continue  # never take credit away because the model forgot something
        if concept.status == "clear" and status == "partial":
            continue  # ignore noisy downgrades; only a verified misconception can undo "clear"
        evidence = " ".join(str(item.get("evidence", "")).split())
        if not verify_quote(evidence, teacher):
            session.rejected += 1
            continue
        session.verified += 1
        old = concept.status
        concept.status = status
        concept.evidence = evidence
        concept.note = " ".join(str(item.get("note", "")).split())[:160]
        changes.append((concept.id, old, status))
    session.last_changes = changes
    return changes


FOCUS_ORDER = {"misconception": 0, "not_covered": 1, "partial": 2}
FOCUS_MODE = {"misconception": "misconception", "not_covered": "missing", "partial": "vague"}


def pick_target(concepts: list[Concept]) -> Concept | None:
    """Which concept the student should push on next: misconceptions first, then
    the most important uncovered idea, then vague ones."""
    candidates = [c for c in concepts if c.status in FOCUS_ORDER]
    if not candidates:
        return None
    position = {c.id: i for i, c in enumerate(concepts)}
    return min(candidates, key=lambda c: (FOCUS_ORDER[c.status], -c.weight, position[c.id]))


def check_finished(session: Session) -> bool:
    all_clear = bool(session.concepts) and all(c.status == "clear" for c in session.concepts)
    if all_clear or session.rounds_done >= session.max_rounds:
        session.finished = True
    return session.finished


def grade(points: int) -> tuple[str, str]:
    if points >= 85:
        return "Master Teacher", "🏆"
    if points >= 65:
        return "Solid Teacher", "🌟"
    if points >= 40:
        return "Getting There", "📈"
    return "Keep Practising", "🌱"


def transcript_markdown(session: Session, student_name: str) -> str:
    lines = [f"# TeachBack session: {session.topic}", "", f"Score: {score(session.concepts)}/100", ""]
    for t in session.turns:
        who = "You (teacher)" if t.role == "teacher" else student_name
        lines.append(f"**{who}:** {t.text}\n")
    lines.append("## Concept results\n")
    for c in session.concepts:
        lines.append(f"- **{c.name}**: {STATUS_LABELS[c.status]}" + (f" (\"{c.evidence}\")" if c.evidence else ""))
    return "\n".join(lines)

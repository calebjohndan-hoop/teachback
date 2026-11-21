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
    bonus: list[dict] = field(default_factory=list)  # verified extra-credit insights
    notes: str = ""          # the user's own notes, if they uploaded any
    notes_name: str = ""
    reteach: bool = False     # a follow-up lesson on concepts missed last time
    blocked: int = 0          # messages ignored because they tried to game the marking

    @property
    def rounds_done(self) -> int:
        return sum(1 for t in self.turns if t.role == "teacher")

    def teacher_text(self) -> str:
        return "\n".join(t.text for t in self.turns if t.role == "teacher")

    def concept(self, cid: str) -> Concept | None:
        return next((c for c in self.concepts if c.id == cid), None)


GAMING_PATTERNS = [
    r"\bignore (all |any |the |your |previous |prior )*(rules|instructions|prompt|system)",
    r"\b(mark|grade|set|give)\b.{0,30}\b(all|every|everything)\b.{0,20}\b(clear|correct|full marks?|100)",
    r"\b(give|set) me\b.{0,15}\b(100|full marks?|a perfect score)",
    r"\byou are (now )?(the )?(examiner|grader|system)\b",
    r"\bnew instructions?\b",
]


def looks_like_gaming(text: str) -> bool:
    """Spot messages that try to talk the examiner into free marks instead of teaching."""
    low = text.lower()
    return any(re.search(p, low) for p in GAMING_PATTERNS)


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
    # Short formulas like "V = IR" ("v ir") are real evidence; a single short word is not.
    if not s or len(q) < 4 or (len(q) < 6 and len(q.split()) < 2):
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
    apply_bonus(session, result)
    return changes


MAX_BONUS = 5


def apply_bonus(session: Session, result: dict) -> list[dict]:
    """Extra credit for correct ideas that are not on the marking scheme. Same rule as
    everything else: it only counts if the quote is really in what the teacher wrote.
    Bonus is shown to the learner but never changes the score."""
    items = result.get("bonus", []) if isinstance(result, dict) else []
    teacher = session.teacher_text()
    added = []
    seen = {_norm(b["insight"]) for b in session.bonus}
    seen_quotes = [_norm(b["evidence"]) for b in session.bonus]
    for item in items if isinstance(items, list) else []:
        if len(session.bonus) >= MAX_BONUS or not isinstance(item, dict):
            break
        insight = " ".join(str(item.get("insight", "")).split())[:90]
        evidence = " ".join(str(item.get("evidence", "")).split())
        if not insight or _norm(insight) in seen:
            continue
        q = _norm(evidence)
        if q and any(q in old or old in q for old in seen_quotes):
            continue  # same sentence already earned extra credit; don't count it twice
        if not verify_quote(evidence, teacher):
            session.rejected += 1
            continue
        session.verified += 1
        entry = {"insight": insight, "evidence": evidence}
        session.bonus.append(entry)
        seen.add(_norm(insight))
        seen_quotes.append(q)
        added.append(entry)
    return added


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
    if session.bonus:
        lines.append("\n## Extra credit\n")
        for b in session.bonus:
            lines.append(f"- {b['insight']} (\"{b['evidence']}\")")
    return "\n".join(lines)

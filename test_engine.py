import coach
from engine import (
    Concept, Session, Turn, apply_evaluation, pick_target, score, verify_quote,
)
from llm import parse_json
from mock import MockLLM


def make_session(*statuses):
    s = Session(topic="t", persona="kid", level="college", max_rounds=5)
    s.concepts = [Concept(id=f"c{i+1}", name=f"n{i}", description="d", weight=w, status=st)
                  for i, (st, w) in enumerate(statuses)]
    return s


def test_score_weighted():
    s = make_session(("clear", 3), ("partial", 2), ("not_covered", 1))
    assert score(s.concepts) == round(100 * (3 + 1) / 6)
    assert score([]) == 0


def test_verify_quote():
    src = "Voltage is the push that makes charge flow, like water pressure."
    assert verify_quote("voltage is the PUSH that makes charge flow", src)
    assert verify_quote("Voltage is the push that make charge flow", src)  # tiny typo ok
    assert not verify_quote("voltage is measured in amperes", src)
    assert not verify_quote("", src)
    assert not verify_quote("push", src)  # too short to count


def test_apply_evaluation_rejects_invented_quotes():
    s = make_session(("not_covered", 3), ("not_covered", 2))
    s.turns.append(Turn("teacher", "Current is the flow of charge through a wire."))
    apply_evaluation(s, {"concepts": [
        {"id": "c1", "status": "clear", "evidence": "Current is the flow of charge through a wire", "note": "good"},
        {"id": "c2", "status": "clear", "evidence": "Resistance is measured in ohms", "note": "made up"},
    ]})
    assert s.concepts[0].status == "clear"
    assert s.concepts[1].status == "not_covered"
    assert (s.verified, s.rejected) == (1, 1)


def test_no_downgrade_except_misconception():
    s = make_session(("clear", 3))
    s.turns.append(Turn("teacher", "More resistance means more current flows."))
    apply_evaluation(s, {"concepts": [{"id": "c1", "status": "not_covered", "evidence": ""}]})
    assert s.concepts[0].status == "clear"
    apply_evaluation(s, {"concepts": [{"id": "c1", "status": "partial", "evidence": "More resistance means more current"}]})
    assert s.concepts[0].status == "clear"
    apply_evaluation(s, {"concepts": [{"id": "c1", "status": "misconception", "evidence": "More resistance means more current"}]})
    assert s.concepts[0].status == "misconception"


def test_garbage_evaluation_is_ignored():
    s = make_session(("not_covered", 3))
    s.turns.append(Turn("teacher", "hello"))
    for junk in [None, [], {"concepts": "x"}, {"concepts": [1, {"id": "zz"}, {"id": "c1", "status": "great"}]}]:
        apply_evaluation(s, junk)
    assert s.concepts[0].status == "not_covered"


def test_pick_target_priority():
    s = make_session(("partial", 3), ("not_covered", 1), ("not_covered", 3), ("clear", 3))
    assert pick_target(s.concepts).id == "c3"
    s.concepts[1].status = "misconception"
    assert pick_target(s.concepts).id == "c2"
    for c in s.concepts:
        c.status = "clear"
    assert pick_target(s.concepts) is None


def test_parse_concepts_cleans_input():
    data = {"concepts": [{"name": "A", "weight": 9}, {"name": "a"}, {"name": ""}, "junk",
                         {"name": "B", "weight": "x", "description": "desc"}]}
    cs = coach.parse_concepts(data)
    assert [c.name for c in cs] == ["A", "B"]
    assert cs[0].weight == 3 and cs[1].weight == 2


def test_parse_json_handles_fences():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Sure! {"a": 2} done') == {"a": 2}


def test_full_lesson_with_offline_brain():
    llm = MockLLM()
    s = coach.new_session(llm, "Ohm's law", "skeptic", "college", 4)
    assert len(s.concepts) == 6 and s.turns[0].role == "student"
    coach.teacher_turn(llm, s, "Voltage is the electrical push, the potential difference measured in volts.")
    assert s.concept("c1").status == "clear"
    assert s.turns[-1].role == "student"
    coach.teacher_turn(llm, s, "More resistance means more current, because resistance opposes nothing.")
    assert s.concept("c3").status == "misconception"
    assert "Resistance" in s.turns[-1].text  # student pushes on the misconception
    coach.teacher_turn(llm, s, "Current is the flow of charge, measured in amps. V = IR, so current is proportional to voltage.")
    coach.teacher_turn(llm, s, "For example, if you have 10 volts across 5 ohms you get 2 amps.")
    assert s.finished
    report = coach.finish(llm, s)
    assert report["corrections"] and report["next_steps"]
    assert 0 < score(s.concepts) < 100

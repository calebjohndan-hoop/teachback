"""TeachBack: learn anything by teaching it to an AI student."""
from __future__ import annotations

import html
import os

import streamlit as st

import coach
from engine import STATUS_LABELS, grade, score, transcript_markdown
from llm import DEFAULT_MODEL, GeminiLLM, LLMError
from mock import MockLLM
from prompts import LEVELS, PERSONAS

st.set_page_config(page_title="TeachBack", page_icon="🎓", layout="wide")

QUICK_TOPICS = ["Ohm's law", "Pointers in C", "How vaccines work", "Supply and demand"]
STATUS_ICON = {"clear": "✅", "partial": "🟡", "misconception": "❌", "not_covered": "⚪"}

st.markdown(
    """
<style>
.block-container {padding-top: 2rem; max-width: 1200px;}
.tb-title {font-size: 2.6rem; font-weight: 800; margin-bottom: 0;
  background: linear-gradient(90deg, #a78bfa, #60a5fa 60%, #34d399);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;}
.tb-sub {opacity: .75; margin-top: .2rem; font-size: 1.05rem;}
.tb-card {background: rgba(255,255,255,.035); border: 1px solid rgba(255,255,255,.08);
  border-radius: 14px; padding: 1rem 1.1rem; margin-bottom: .8rem;}
.tb-score {font-size: 3.4rem; font-weight: 800; line-height: 1;}
.tb-score small {font-size: 1.1rem; opacity: .6; font-weight: 500;}
.tb-label {text-transform: uppercase; letter-spacing: .08em; font-size: .72rem; opacity: .6; margin-bottom: .35rem;}
.tb-chip {display: flex; justify-content: space-between; gap: .6rem; align-items: center;
  padding: .55rem .75rem; border-radius: 10px; margin-bottom: .45rem; border: 1px solid; font-size: .93rem;}
.tb-chip span.s {font-size: .75rem; opacity: .8; white-space: nowrap;}
.st-clear {background: rgba(52,211,153,.12); border-color: rgba(52,211,153,.5);}
.st-partial {background: rgba(251,191,36,.10); border-color: rgba(251,191,36,.5);}
.st-misconception {background: rgba(248,113,113,.12); border-color: rgba(248,113,113,.55);}
.st-not_covered {background: rgba(148,163,184,.06); border-color: rgba(148,163,184,.25);}
.tb-quote {border-left: 3px solid #a78bfa; padding-left: .7rem; opacity: .9; font-style: italic; margin: .3rem 0;}
.tb-ai {font-size: .78rem; opacity: .65;}
</style>
""",
    unsafe_allow_html=True,
)


# ---------- model selection ----------
def api_key() -> str:
    key = st.session_state.get("user_key", "") or os.getenv("GEMINI_API_KEY", "")
    if not key:
        try:
            key = st.secrets.get("GEMINI_API_KEY", "")
        except Exception:  # no secrets file
            key = ""
    return key.strip()


def get_llm():
    key = api_key()
    if key:
        model = st.session_state.get("model_name") or os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
        return GeminiLLM(key, model)
    return MockLLM()


def set_topic(t: str) -> None:
    st.session_state.topic = t


def reset() -> None:
    st.session_state.pop("session", None)


def restart_same() -> None:
    s = st.session_state.get("session")
    if s:
        st.session_state.topic = s.topic
    reset()


# ---------- sidebar ----------
with st.sidebar:
    st.markdown("### ⚙️ Settings")
    env_key = bool(os.getenv("GEMINI_API_KEY")) or bool(api_key() and not st.session_state.get("user_key"))
    if env_key:
        st.success("Gemini connected")
    else:
        st.text_input("Gemini API key", type="password", key="user_key",
                      help="Free key from aistudio.google.com. Stays in this browser session only.")
        if not st.session_state.get("user_key"):
            st.info("No key: running **Demo mode** with a simple offline brain. "
                    "Add a key for a real AI student.")
    st.text_input("Model", value=os.getenv("GEMINI_MODEL", DEFAULT_MODEL), key="model_name")
    st.markdown("---")
    st.markdown(
        "**How it works**\n\n"
        "1. AI builds a hidden checklist of what a great explanation covers.\n"
        "2. You teach; an AI examiner grades each idea.\n"
        "3. Your student asks about whatever you explained worst.\n\n"
        "🔎 **No made-up credit:** the examiner must quote your exact words, and the app "
        "checks every quote in code before it changes your score."
    )


# ---------- views ----------
def render_header() -> None:
    st.markdown('<p class="tb-title">TeachBack</p>', unsafe_allow_html=True)
    st.markdown('<p class="tb-sub">The fastest way to find out if you really understand something: '
                'teach it to an AI student who asks the hard questions.</p>', unsafe_allow_html=True)


def render_setup() -> None:
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.text_input("What will you teach today?", key="topic", max_chars=80,
                      placeholder="e.g. Pointers in C, Ohm's law, photosynthesis")
        cols = st.columns(len(QUICK_TOPICS))
        for i, t in enumerate(QUICK_TOPICS):
            cols[i].button(t, key=f"quick_{i}", on_click=set_topic, args=(t,), use_container_width=True)
        st.radio("Level", list(LEVELS), key="level", horizontal=True, index=1,
                 format_func=lambda k: {"school": "School", "college": "College", "advanced": "Advanced"}[k])
        st.slider("Rounds", 3, 10, 6, key="rounds", help="How many times you explain before the lesson ends.")
        st.toggle("Challenge mode: hide the concept checklist", key="challenge")
    with right:
        st.radio("Pick your student", list(PERSONAS), key="persona",
                 format_func=lambda k: f"{PERSONAS[k]['emoji']}  {PERSONAS[k]['name']}")
        p = PERSONAS[st.session_state.get("persona", "kid")]
        st.markdown(f'<div class="tb-card">{p["emoji"]} <b>{html.escape(p["name"])}</b><br>'
                    f'<span style="opacity:.75">{html.escape(p["blurb"])}</span></div>', unsafe_allow_html=True)

    topic = st.session_state.get("topic", "").strip()
    if st.button("🎓 Start teaching", type="primary", key="start", disabled=not topic):
        with st.spinner("Your student is finding a seat..."):
            try:
                st.session_state.session = coach.new_session(
                    get_llm(), topic, st.session_state.persona, st.session_state.level,
                    st.session_state.rounds, st.session_state.get("challenge", False))
            except LLMError as e:
                st.error(str(e))
                return
        st.rerun()


def render_dashboard(s) -> None:
    pts = score(s.concepts)
    st.markdown(f'<div class="tb-card"><div class="tb-label">Understanding meter</div>'
                f'<div class="tb-score">{pts}<small> / 100</small></div></div>', unsafe_allow_html=True)
    st.progress(pts / 100)
    st.caption(f"Round {min(s.rounds_done, s.max_rounds)} of {s.max_rounds}")

    changed = {cid for cid, _, _ in s.last_changes}
    chips = []
    for c in s.concepts:
        hidden = s.challenge and c.status == "not_covered" and not s.finished
        name = "🔒 Hidden concept" if hidden else html.escape(c.name)
        flash = " ✨" if c.id in changed else ""
        tip = html.escape(c.note or c.description) if not hidden else "Explain more to unlock"
        chips.append(f'<div class="tb-chip st-{c.status}" title="{tip}"><span>{name}{flash}</span>'
                     f'<span class="s">{STATUS_ICON[c.status]} {STATUS_LABELS[c.status]}</span></div>')
    st.markdown('<div class="tb-label">Concept map</div>' + "".join(chips), unsafe_allow_html=True)
    st.caption(f"🔎 Evidence check: {s.verified} quotes verified · {s.rejected} rejected")

    c1, c2 = st.columns(2)
    if c1.button("Finish lesson", key="finish", use_container_width=True, disabled=s.rounds_done == 0):
        s.finished = True
        st.rerun()
    c2.button("Start over", key="restart", on_click=reset, use_container_width=True)


def render_lesson(s) -> None:
    persona = PERSONAS[s.persona]
    left, right = st.columns([3, 2], gap="large")
    with right:
        render_dashboard(s)
    with left:
        st.markdown(f"#### Teaching **{html.escape(s.topic)}** to {persona['emoji']} {persona['name']}")
        for t in s.turns:
            if t.role == "student":
                st.chat_message("assistant", avatar=persona["emoji"]).markdown(t.text)
            else:
                st.chat_message("user", avatar="🧑‍🏫").markdown(t.text)

    msg = st.chat_input("Explain it to your student...", max_chars=coach.MAX_MESSAGE, key="chat")
    if msg:
        with left:
            st.chat_message("user", avatar="🧑‍🏫").markdown(msg)
            with st.chat_message("assistant", avatar=persona["emoji"]):
                with st.spinner("Thinking about what you said..."):
                    try:
                        coach.teacher_turn(get_llm(), s, msg)
                    except LLMError as e:
                        st.error(f"Couldn't reach the AI, your message wasn't counted. Try again. ({e})")
                        return
        st.rerun()


def render_report(s) -> None:
    persona = PERSONAS[s.persona]
    if s.report is None:
        with st.spinner("Writing your lesson debrief..."):
            coach.finish(get_llm(), s)
    r = s.report
    pts = score(s.concepts)
    title, icon = grade(pts)

    left, right = st.columns([2, 3], gap="large")
    with left:
        st.markdown(f'<div class="tb-card"><div class="tb-label">Final score · {html.escape(s.topic)}</div>'
                    f'<div class="tb-score">{pts}<small> / 100</small></div>'
                    f'<h3 style="margin:.4rem 0 0">{icon} {title}</h3></div>', unsafe_allow_html=True)
        counts = {k: sum(1 for c in s.concepts if c.status == k) for k in STATUS_LABELS}
        m = st.columns(4)
        m[0].metric("Clear", counts["clear"])
        m[1].metric("Partial", counts["partial"])
        m[2].metric("Wrong", counts["misconception"])
        m[3].metric("Missed", counts["not_covered"])
        st.markdown(f"**Debrief:** {html.escape(r['summary'])}")
        st.markdown("**Next steps**")
        for step in r["next_steps"]:
            st.markdown(f"- {html.escape(step)}")
        st.download_button("⬇️ Download transcript", transcript_markdown(s, persona["name"]),
                           file_name="teachback_session.md", use_container_width=True)
        b1, b2 = st.columns(2)
        b1.button("Teach it again", key="again", on_click=restart_same, use_container_width=True, type="primary")
        b2.button("New topic", key="new", on_click=reset, use_container_width=True)

    with right:
        st.markdown("#### Concept by concept")
        for c in s.concepts:
            quote = f'<div class="tb-quote">"{html.escape(c.evidence)}"</div>' if c.evidence else ""
            note = f'<div style="opacity:.75">{html.escape(c.note)}</div>' if c.note else ""
            st.markdown(f'<div class="tb-chip st-{c.status}" style="display:block">'
                        f'<b>{STATUS_ICON[c.status]} {html.escape(c.name)}</b> · '
                        f'<span class="s">{STATUS_LABELS[c.status]}</span>{quote}{note}</div>',
                        unsafe_allow_html=True)
        if r["corrections"]:
            st.markdown("#### What to fix")
            st.markdown('<div class="tb-ai">AI-generated explanations. Double-check against your textbook.</div>',
                        unsafe_allow_html=True)
            for x in r["corrections"]:
                st.markdown(f"**{html.escape(x['concept'])}**: {html.escape(x['correct_idea'])}")


render_header()
session = st.session_state.get("session")
if session is None:
    render_setup()
elif session.finished:
    render_report(session)
else:
    render_lesson(session)

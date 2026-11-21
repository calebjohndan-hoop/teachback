"""TeachBack: learn anything by teaching it to an AI student."""
from __future__ import annotations

import html
import os

import streamlit as st

import coach
from engine import STATUS_LABELS, grade, score, transcript_markdown
from llm import DEFAULT_MODEL, FallbackLLM, GeminiLLM, LLMError
from mock import MockLLM
from prompts import LEVELS, PERSONAS

st.set_page_config(page_title="TeachBack", page_icon="🎓", layout="wide")

QUICK_TOPICS = ["Ohm's law", "Pointers in C", "How vaccines work", "Supply and demand"]
MARK = {"clear": "✓", "partial": "½", "misconception": "✗", "not_covered": "○"}

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:wght@400;700&family=Caveat:wght@600;700&display=swap');
:root {
  --paper: #F6F8FB; --ink: #1B2A4A; --ink-soft: #55627D; --rule: #C9D8EE;
  --red: #C8372D; --green: #2F7D4F; --amber: #A86A12; --hi: #FFF1A6;
  --card: #FFFFFF; --sheet: #FFFFFF; --margin: rgba(200,55,45,.35); --focus: #1F4FA8;
}
/* dark mode: the same exercise book, read under a desk lamp */
html[data-tb-theme="dark"] {
  --paper: #12151C; --ink: #E8ECF4; --ink-soft: #A7B1C6; --rule: #2B3448;
  --red: #FF8A7A; --green: #6BD49A; --amber: #F4BE62; --hi: rgba(250,204,21,.32);
  --card: #1A1F2B; --sheet: #161B26; --margin: rgba(255,138,122,.45); --focus: #8FB3FF;
}
.st-key-tbjs, .st-key-tbscroll {position: absolute !important; width: 0 !important; height: 0 !important; overflow: hidden !important;}
.stApp, .stApp p, .stApp label, .stApp input, .stApp textarea, .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp li {
  font-family: 'Atkinson Hyperlegible', system-ui, sans-serif !important;
}
.block-container {padding-top: 3.5rem; max-width: 1180px;}
.tb-title {font-size: 2.9rem !important; font-weight: 700 !important; color: var(--ink);
  letter-spacing: -.02em; line-height: 1.15 !important; margin: 0; padding: .1em 0 0;}
.tb-title .mark {font-family: 'Caveat', cursive !important; color: var(--red); font-size: .62em;
  font-weight: 700; margin-left: .35em; display: inline-block; transform: rotate(-6deg) translateY(-.35em);}
.tb-sub {color: var(--ink-soft); margin: .25rem 0 1.6rem; font-size: 1.1rem !important; max-width: 62ch;}
.tb-label {color: var(--ink-soft); font-size: .95rem; margin: 0 0 .4rem; font-weight: 700;}
.tb-card {background: var(--card); border: 1px solid var(--rule); border-radius: 6px; padding: 1rem 1.1rem;
  margin-bottom: .8rem; border-left: 3px solid var(--red);}
.tb-card b {color: var(--ink);}

/* the one bold element: a red-pen mark */
.tb-grade {display: inline-flex; align-items: baseline; gap: .15em; font-family: 'Caveat', cursive !important;
  color: var(--red); font-size: 4.2rem; line-height: 1; padding: .15em .55em .1em;
  border: 3px solid var(--red); border-radius: 50% 46% 52% 48% / 55% 50% 50% 45%;
  transform: rotate(-4deg); margin: .2rem 0 .6rem .3rem;}
.tb-grade small {font-size: 1.6rem; opacity: .85;}
.tb-verdict {font-family: 'Caveat', cursive !important; color: var(--red); font-size: 1.9rem; margin: 0 0 .4rem .2rem;}
.tb-round {color: var(--ink-soft); font-size: .92rem; margin: 0 0 1rem;}

/* marking scheme */
.tb-row {display: flex; align-items: flex-start; gap: .7rem; padding: .45rem 0; border-bottom: 1px solid var(--rule);}
.tb-row:last-child {border-bottom: none;}
.tb-tick {font-family: 'Caveat', cursive !important; font-size: 1.7rem; line-height: 1; width: 1.4rem; text-align: center; flex: none;}
.tb-row .name {color: var(--ink); font-size: .98rem; line-height: 1.35;}
.tb-row .state {color: var(--ink-soft); font-size: .82rem;}
.m-clear .tb-tick {color: var(--green);}
.m-partial .tb-tick {color: var(--amber);}
.m-misconception .tb-tick {color: var(--red);}
.m-misconception .nm {text-decoration: underline wavy var(--red); text-underline-offset: 4px;}
.m-not_covered .tb-tick {color: var(--ink-soft); opacity: .45; font-size: 1.2rem;}
.m-bonus .tb-tick {color: var(--green);}
.m-bonus .state {color: var(--green);}
.tb-source {color: var(--ink-soft); font-size: .88rem; margin: -.4rem 0 .8rem;}
.stApp [data-testid="stMarkdownContainer"] :is(p, li, strong, em),
.stApp [data-testid="stMetricValue"], .stApp [data-testid="stMetricLabel"] p,
.stApp [data-testid="stCaptionContainer"], .stApp [data-testid="stFileUploaderDropzoneInstructions"] span {
  font-family: 'Atkinson Hyperlegible', system-ui, sans-serif !important;}
.stApp [data-testid="stMetricValue"] {color: var(--ink);}
.m-not_covered .name {color: var(--ink-soft);}
.tb-new {font-family: 'Caveat', cursive !important; color: var(--red); font-size: 1.05rem; margin-left: .3rem;}
.tb-evidence {color: var(--ink-soft); font-size: .85rem; margin: .7rem 0 1rem;}
.tb-quote {background: linear-gradient(180deg, transparent 35%, var(--hi) 35%, var(--hi) 92%, transparent 92%);
  color: var(--ink); padding: 0 .15em; display: inline; line-height: 1.7;}
.tb-note {color: var(--ink-soft); font-size: .88rem; margin-top: .2rem;}
.tb-ai {color: var(--ink-soft); font-size: .85rem; margin-bottom: .6rem;}

/* the exercise-book page for the lesson */
.st-key-chatbox {background-color: var(--sheet) !important;
  background-image: linear-gradient(90deg, transparent 2.6rem, var(--margin) 2.6rem, var(--margin) calc(2.6rem + 1px), transparent calc(2.6rem + 1px)),
    repeating-linear-gradient(180deg, transparent 0, transparent 1.85rem, var(--rule) 1.85rem, var(--rule) calc(1.85rem + 1px)) !important;
  border-radius: 6px;}
[data-testid="stChatMessage"] {background: transparent !important; padding: .9rem .6rem 0 .3rem !important;}
.st-key-chatbox [data-testid="stChatMessage"] p {line-height: 1.85rem !important; margin: 0 !important;
  font-family: 'Atkinson Hyperlegible', system-ui, sans-serif !important; font-size: 1.02rem !important; color: var(--ink);}
.stButton button {border-radius: 6px;}
.stApp button:focus-visible, .stApp input:focus-visible, .stApp textarea:focus-visible {outline: 3px solid var(--focus) !important; outline-offset: 2px;}
@media (prefers-reduced-motion: reduce) {* {scroll-behavior: auto !important;}}
@media (max-width: 640px) {.tb-title {font-size: 2.2rem !important;} .tb-grade {font-size: 3.2rem;} .block-container {padding-top: 2.5rem;}}
</style>
""",
    unsafe_allow_html=True,
)


def theme_sync() -> None:
    """Keep the custom styling in step with Streamlit's light/dark theme, live, by reading the
    app's real background colour (st.context.theme can lag behind a theme switch)."""
    try:
        if st.context.theme.type == "dark":
            st.markdown('<style>:root{--paper:#12151C;--ink:#E8ECF4;--ink-soft:#A7B1C6;--rule:#2B3448;'
                        '--red:#FF8A7A;--green:#6BD49A;--amber:#F4BE62;--hi:rgba(250,204,21,.32);'
                        '--card:#1A1F2B;--sheet:#161B26;--margin:rgba(255,138,122,.45);--focus:#8FB3FF;}</style>',
                        unsafe_allow_html=True)
    except Exception:  # noqa: BLE001
        pass
    with st.container(key="tbjs"):
        st.iframe("""<script>
          const d = window.parent.document;
          const lum = c => { const m = (c || '').match(/[\\d.]+/g); if (!m) return 1;
            return (0.299 * m[0] + 0.587 * m[1] + 0.114 * m[2]) / 255; };
          const sync = () => { const app = d.querySelector('.stApp'); if (!app) return;
            const dark = lum(getComputedStyle(app).backgroundColor) < 0.5;
            const want = dark ? 'dark' : 'light';
            if (d.documentElement.getAttribute('data-tb-theme') !== want)
              d.documentElement.setAttribute('data-tb-theme', want); };
          sync(); setInterval(sync, 400);
        </script>""", height=1)


theme_sync()


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
        return FallbackLLM(GeminiLLM(key, model), MockLLM())
    return MockLLM()


def run(fn, *args, **kwargs):
    """Call a coach action and remember if Gemini was down so we can tell the user."""
    llm = get_llm()
    out = fn(llm, *args, **kwargs)
    if getattr(llm, "degraded", False):
        st.session_state.degraded = True
    return out


def scroll_to_top() -> None:
    # Streamlit's chat layout sticks the page to the bottom; pull it back up once it settles.
    with st.container(key="tbscroll"):
        _scroll_script()


def _scroll_script() -> None:
    st.iframe("""<script>
      const go = () => {
        const d = window.parent.document;
        d.querySelectorAll('[data-testid="stAppScrollToBottomContainer"], .stMain, [data-testid="stMain"]')
          .forEach(e => e.scrollTo({top: 0}));
      };
      [50, 300, 700, 1200].forEach(ms => setTimeout(go, ms));
    </script>""", height=1)


def start_session(session) -> None:
    st.session_state.session = session
    st.session_state.scroll_top = True


def set_topic(t: str) -> None:
    st.session_state.topic = t


def reset() -> None:
    st.session_state.pop("session", None)
    st.session_state.pop("degraded", None)
    st.session_state.pop("pending_msg", None)


def restart_same() -> None:
    s = st.session_state.get("session")
    if s:
        st.session_state.topic = s.topic
    reset()


# ---------- sidebar ----------
def record_progress(s) -> None:
    """Remember each finished lesson so learners can see re-teaching pay off."""
    hist = st.session_state.setdefault("history", [])
    key = id(s)
    if any(h["key"] == key for h in hist):
        return
    hist.append({"key": key, "topic": s.topic, "score": score(s.concepts), "reteach": s.reteach})


with st.sidebar:
    if api_key():
        st.success("Gemini connected")
    else:
        st.text_input("Gemini API key", type="password", key="user_key",
                      help="Free key from aistudio.google.com. Stays in this browser session only.")
        st.info("No key: running **Demo mode** with a simple offline brain. Add a key for a real AI student.")

    hist = st.session_state.get("history", [])
    st.markdown("#### Your progress")
    if hist:
        for h in reversed(hist[-8:]):
            label = "re-teach" if h["reteach"] else "lesson"
            st.markdown(f"**{h['score']}/100** · {html.escape(h['topic'])} ({label})")
    else:
        st.caption("Finish a lesson and your marks show up here, so you can see re-teaching pay off.")

    st.markdown("---")
    st.markdown(
        "**How it works**\n\n"
        "1. AI builds a marking scheme for your topic, or from your own notes.\n"
        "2. You teach; an AI examiner marks each idea and can give extra credit.\n"
        "3. Your student asks about whatever you explained worst.\n"
        "4. Re-teach just the ideas you missed.\n\n"
        "🔎 **No made-up credit:** the examiner must quote your exact words, and the app "
        "checks every quote in code before it changes your mark."
    )
    st.caption("🌙 Dark mode follows your device. To switch, open the ⋮ menu (top right) → Settings → Theme.")
    with st.expander("Advanced"):
        st.text_input("Gemini model", value=os.getenv("GEMINI_MODEL", DEFAULT_MODEL), key="model_name",
                      help="If this model is busy or retired, TeachBack switches to another automatically.")


# ---------- views ----------
def render_header() -> None:
    st.markdown('<div class="tb-title">TeachBack<span class="mark">✓</span></div>', unsafe_allow_html=True)
    st.markdown('<div class="tb-sub">Teach any topic to an AI student. It asks the hard questions, '
                'marks your explanation, and shows you exactly what you still need to learn.</div>',
                unsafe_allow_html=True)


def render_setup() -> None:
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.text_input("What will you teach today?", key="topic", max_chars=80,
                      placeholder="Pointers in C, Ohm's law, photosynthesis...")
        cols = st.columns(len(QUICK_TOPICS))
        for i, t in enumerate(QUICK_TOPICS):
            cols[i].button(t, key=f"quick_{i}", on_click=set_topic, args=(t,), use_container_width=True)
        st.radio("Level", list(LEVELS), key="level", horizontal=True, index=1,
                 format_func=lambda k: {"school": "School", "college": "College", "advanced": "Advanced"}[k])
        st.slider("Rounds", 3, 10, 6, key="rounds", help="How many times you explain before the lesson ends.")
        st.toggle("Challenge mode: hide the marking scheme", key="challenge")
        st.file_uploader("Your own notes (optional)", type=["pdf", "txt", "md"], key="notes_file",
                         help="Upload lecture notes or a textbook chapter and the marking scheme is built "
                              "from them, so you're marked on what your course actually teaches.")
    with right:
        st.radio("Your student", list(PERSONAS), key="persona",
                 format_func=lambda k: f"{PERSONAS[k]['emoji']}  {PERSONAS[k]['name']}")
        p = PERSONAS[st.session_state.get("persona", "kid")]
        st.markdown(f'<div class="tb-card">{p["emoji"]} <b>{html.escape(p["name"])}</b><br>'
                    f'<span style="color:var(--ink-soft)">{html.escape(p["blurb"])}</span></div>',
                    unsafe_allow_html=True)

    topic = st.session_state.get("topic", "").strip()
    if st.button("Start teaching", type="primary", key="start", disabled=not topic):
        st.session_state.pop("degraded", None)
        with st.spinner("Your student is finding a seat..."):
            try:
                notes, notes_name = "", ""
                f = st.session_state.get("notes_file")
                if f is not None:
                    notes, notes_name = coach.read_notes(f.getvalue(), f.name), f.name
                    if len(notes) >= coach.MAX_NOTES:
                        notes_name += " (first part only, it's a long file)"
                start_session(run(coach.new_session, topic, st.session_state.persona, st.session_state.level,
                                  st.session_state.rounds, st.session_state.get("challenge", False),
                                  notes, notes_name))
            except LLMError as e:
                st.error(str(e))
                return
        st.rerun()
    st.caption("Tip: slip in a mistake on purpose and see if your student catches it.")


def marking_rows(s, with_quotes: bool = False) -> str:
    changed = {cid for cid, _, _ in s.last_changes}
    rows = []
    for c in s.concepts:
        hidden = s.challenge and c.status == "not_covered" and not s.finished
        name = "Hidden until you explain it" if hidden else html.escape(c.name)
        new = '<span class="tb-new">new</span>' if c.id in changed and not with_quotes else ""
        tip = "" if hidden else html.escape(c.note or c.description)
        extra = ""
        if with_quotes:
            if c.evidence:
                extra += f'<div style="margin-top:.25rem"><span class="tb-quote">{html.escape(c.evidence)}</span></div>'
            if c.note:
                extra += f'<div class="tb-note">{html.escape(c.note)}</div>'
        rows.append(f'<div class="tb-row m-{c.status}" title="{tip}"><span class="tb-tick" aria-hidden="true">{MARK[c.status]}</span>'
                    f'<div><div class="name"><span class="nm">{name}</span>{new}</div><div class="state">{STATUS_LABELS[c.status]}</div>'
                    f'{extra}</div></div>')
    for b in s.bonus:
        extra = ""
        if with_quotes:
            extra = f'<div style="margin-top:.25rem"><span class="tb-quote">{html.escape(b["evidence"])}</span></div>'
        rows.append(f'<div class="tb-row m-bonus"><span class="tb-tick" aria-hidden="true">+</span><div>'
                    f'<div class="name">{html.escape(b["insight"])}</div><div class="state">Extra credit: '
                    f'a good idea that wasn\'t on the scheme</div>{extra}</div></div>')
    return "".join(rows)


def notices(s) -> None:
    if st.session_state.get("degraded"):
        st.info("Gemini is busy right now, so your student switched to the offline backup brain. "
                "Marking is simpler until Gemini is back; just keep teaching.")


def render_dashboard(s) -> None:
    pts = score(s.concepts)
    st.markdown(f'<div class="tb-label">Your mark so far</div>'
                f'<div class="tb-grade" role="img" aria-label="Your mark so far: {pts} out of 100">'
                f'{pts}<small>/100</small></div>'
                f'<div class="tb-round">Round {min(s.rounds_done, s.max_rounds)} of {s.max_rounds}</div>'
                f'<div class="tb-label">Marking scheme</div>'
                + (f'<div class="tb-source">Built from your notes: {html.escape(s.notes_name)}</div>' if s.notes_name else '')
                + f'{marking_rows(s)}'
                f'<div class="tb-evidence">{s.verified} quotes checked against your own words, '
                f'{s.rejected} rejected'
                + (f', {s.blocked} attempt{"s" if s.blocked != 1 else ""} to game the marks ignored' if s.blocked else '')
                + '</div>', unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    busy = bool(st.session_state.get("pending_msg"))
    if c1.button("Finish lesson", key="finish", use_container_width=True, disabled=s.rounds_done == 0 or busy):
        s.finished = True
        st.rerun()
    c2.button("Start over", key="restart", on_click=reset, use_container_width=True)


def render_lesson(s) -> None:
    persona = PERSONAS[s.persona]
    if st.session_state.pop("scroll_top", False):
        scroll_to_top()
    notices(s)
    left, right = st.columns([3, 2], gap="large")
    with right:
        render_dashboard(s)
    with left:
        what = "Re-teaching what you missed in" if s.reteach else "You're teaching"
        st.markdown(f"#### {what} {html.escape(s.topic)} to the {persona['name']} {persona['emoji']}")
        chat = st.container(height=460, border=True, key="chatbox")
        with chat:
            for t in s.turns:
                if t.role == "student":
                    st.chat_message("assistant", avatar=persona["emoji"]).markdown(t.text)
                else:
                    st.chat_message("user", avatar="🧑‍🏫").markdown(t.text)

    # Two-step send: store the message, rerun with the input locked, then mark it.
    # This stops a second message (or Finish) from cutting the first one off mid-reply.
    pending = st.session_state.get("pending_msg")
    msg = st.chat_input("Your student is thinking..." if pending else "Explain it to your student...",
                        max_chars=coach.MAX_MESSAGE, key="chat", disabled=bool(pending))
    if msg and not pending:
        st.session_state.pending_msg = msg
        st.rerun()
    if pending:
        with chat:
            if not (s.turns and s.turns[-1].role == "teacher" and s.turns[-1].text.endswith(pending)):
                st.chat_message("user", avatar="🧑‍🏫").markdown(pending)
            with st.chat_message("assistant", avatar=persona["emoji"]):
                with st.spinner("Marking your explanation..."):
                    try:
                        run(coach.teacher_turn, s, pending)
                    except LLMError as e:
                        st.session_state.pending_msg = None
                        st.error(f"Your message wasn't counted because the AI didn't respond. Send it again. ({e})")
                        return
        st.session_state.pending_msg = None
        st.rerun()


def render_report(s) -> None:
    persona = PERSONAS[s.persona]
    if st.session_state.pop("scroll_top", False):
        scroll_to_top()
    if s.report is None:
        with st.spinner("Writing your report..."):
            run(coach.finish, s)
        record_progress(s)
        st.session_state.scroll_top = True
        st.rerun()
    notices(s)
    r = s.report
    pts = score(s.concepts)
    title, _ = grade(pts)

    left, right = st.columns([2, 3], gap="large")
    with left:
        st.markdown(f'<div class="tb-label">Final mark for {html.escape(s.topic)}</div>'
                    f'<div class="tb-grade" role="img" aria-label="Final mark: {pts} out of 100">{pts}<small>/100</small></div>'
                    f'<div class="tb-verdict">{title}</div>', unsafe_allow_html=True)
        counts = {k: sum(1 for c in s.concepts if c.status == k) for k in STATUS_LABELS}
        m = st.columns(4)
        m[0].metric("Clear", counts["clear"])
        m[1].metric("Partial", counts["partial"])
        m[2].metric("Wrong", counts["misconception"])
        m[3].metric("Missed", counts["not_covered"])
        st.markdown(f"**Teacher's comment:** {html.escape(r['summary'])}")
        st.markdown("**Next steps**")
        for step in r["next_steps"]:
            st.markdown(f"- {html.escape(step)}")
        st.download_button("Download transcript", transcript_markdown(s, persona["name"]),
                           file_name="teachback_session.md", use_container_width=True)
        weak = [c for c in s.concepts if c.status != "clear"]
        if weak and st.button(f"Re-teach the {len(weak)} idea{'s' if len(weak) != 1 else ''} you missed",
                              key="reteach", type="primary", use_container_width=True):
            st.session_state.pop("degraded", None)
            with st.spinner("Setting up a lesson on just those ideas..."):
                try:
                    start_session(run(coach.reteach, s))
                except LLMError as e:
                    st.error(str(e))
                    return
            st.rerun()
        b1, b2 = st.columns(2)
        b1.button("Teach it again", key="again", on_click=restart_same, use_container_width=True)
        b2.button("New topic", key="new", on_click=reset, use_container_width=True)

    with right:
        st.markdown("#### Marking scheme")
        st.markdown('<div class="tb-ai">Highlighted text is what you actually said.</div>'
                    + marking_rows(s, with_quotes=True), unsafe_allow_html=True)
        if r["corrections"]:
            st.markdown("#### What to fix")
            st.markdown('<div class="tb-ai">Written by AI. Check these against your textbook.</div>',
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

# TeachBack 🎓

**Learn anything by teaching it to an AI student who asks the hard questions.**

Explaining something is the fastest way to find out whether you really understand it. TeachBack flips AI tutoring around: *you* are the teacher, and an AI student (a curious kid, a skeptical professor, or a "but why?" classmate) keeps questioning you until the gaps in your understanding show up. At the end you get a score, a concept-by-concept breakdown that quotes your own words, and corrections for anything you got wrong.

## How it works

1. **Lesson plan.** Gemini builds a rubric of 5 to 7 key concepts a great explanation of your topic must cover, each weighted by importance.
2. **You teach.** Type your explanation in the chat.
3. **Examiner grades.** A separate Gemini call grades every concept as *clear*, *partial*, *misconception* or *not covered* and must quote your exact words as evidence.
4. **Evidence check (in code).** Before your score changes, TeachBack verifies the quote really appears in what you wrote. Invented evidence is rejected and counted.
5. **Student pushes back.** Code picks the weakest concept (misconceptions first, then the most important missing idea) and the student asks about it in character, without ever giving away the answer.
6. **Debrief.** Final score, grade, your quoted evidence per concept, AI-written corrections, next steps, and a downloadable transcript.

```
topic ──► [Gemini: rubric] ──► concepts
you ──► [Gemini: examiner JSON] ──► [code: verify quotes] ──► status + score (code)
                                         │
                       [code: pick weakest concept] ──► [Gemini: student persona] ──► question
```

## Responsible AI

- **No made-up credit.** The score is computed in Python from verified statuses, never by the model. Every status change needs a quote that is checked against the teacher's real text.
- **No noisy downgrades.** Credit is never taken away because the model forgot something; only a verified misconception can undo a "clear".
- **The student never teaches.** The persona prompt forbids revealing answers, so the learning comes from you.
- **Prompt-injection guards.** User text is wrapped in tags and treated as data.
- **Clear labelling.** Corrections in the report are marked as AI-generated with a reminder to double-check.
- **Graceful failure.** If a Gemini call fails, your message is not counted and you can resend it; a failed student reply falls back to a safe question.

## Features

- 3 student personas, 3 difficulty levels, 3 to 10 rounds
- Live understanding meter and colour-coded concept map
- Challenge mode: hides the checklist so you have to work out what matters
- Demo mode: runs with no API key using an offline keyword brain (best with the "Ohm's law" quick pick)

## Run it locally (Windows)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
set GEMINI_API_KEY=your-key-here
streamlit run app.py
```

Get a free key at https://aistudio.google.com/apikey. You can also paste the key in the app's sidebar instead of setting it. Change the model in the sidebar or with `GEMINI_MODEL` (default `gemini-flash-latest`; if a model is retired the app automatically switches to the newest available Flash model).

## Deploy (Streamlit Community Cloud)

1. Push this folder to a public GitHub repo.
2. On share.streamlit.io, create an app pointing to `app.py`.
3. In the app's **Secrets**, add `GEMINI_API_KEY = "your-key"`.

## Tests

```bash
pip install pytest
python -m pytest -q
```

Covers scoring, quote verification, target picking, malformed AI output, and a full click-through of the UI in demo mode.

## Tech

Python · Streamlit · Google Gemini (`google-genai`) · structured JSON output · difflib-based quote verification

## Project structure

```
app.py         Streamlit UI
engine.py      deterministic core: scoring, quote checks, target picking
coach.py       orchestrates each user action
prompts.py     personas and prompt builders
llm.py         Gemini wrapper with retry and JSON parsing
mock.py        offline demo brain
test_*.py      pytest suite
```

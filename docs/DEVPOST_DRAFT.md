# Devpost draft — PathPilot AI (DRAFT, not submitted)

Prepared 2026-11-26 (Day 3) for Xiangfeng's review. Devpost materials must be
in English. Nothing here has been submitted — submission is the user's step.
Deadline: 15:00 PST 28 Nov 2026 (07:00 Beijing 29 Nov 2026).

Live demo: https://pathpilot-ai-vert.vercel.app/
Code: https://github.com/Ding-hub6029/PathPilot-AI
Backend: https://pathpilot-ai-co9k.onrender.com (Render free tier — sleeps after
15 min idle; open /api/v1/health first and wait ~1 min before recording or demoing).

## Numbers used below — all verified in-repo as of 2026-11-28 12:05 CST

- 894 programmes across 148 institutions (QS top 100): 886 expansion
  programmes, of which 593 are matchable by the rules engine and 293 are
  display-only (insufficient structured data — shown as unknown, never
  guessed), plus 8 deeply verified programmes with their own evaluators.
- 8 deeply verified programmes (UK/SG, UG + taught masters) with 72 facts from
  29 official sources; the 881 expansion programmes come from official
  programme pages only.
- Rankings: QS 2027 + THE 2027 + ARWU 2026 top 100 each = 300 entries.
- 41 applicants / 53 offers (labelled netizen-shared, unverified, with source links),
  18 school reviews, 9 news link-outs + 3 policy cards.
- 6 locales (EN, ZH-CN, ES, FR, PT-BR, AR with RTL).
- Climate data for 80 cities; real-model chat (DeepSeek) with grounded answers,
  /explain, profile parsing, improvement plans, 12-case evaluation set.
- Tests: 904 pytest passed; production build passes.

Do NOT claim in the submission: admission probabilities (the product gives
none), full coverage of every programme of every school (expansion is
computer + business + engineering so far, not every field), or that THE/ARWU
values are licensed (they are labelled: THE consent not obtained, ARWU reuse
permission not verified).

## Devpost description (paste-ready draft)

**Inspiration**
Choosing a university abroad means comparing requirements published in
different languages, formats and currencies — and most tools answer with a
guess. PathPilot AI answers only from what universities officially publish,
and says "unknown" when the evidence is not there.

**What it does**
PathPilot AI is an evidence-based university selection assistant. Tell it your
background — Gaokao, A-level, IB, SAT/AP, Singapore A-level or another route —
and your preferences in a chat with 小罗盘 (Little Compass), and it recommends
programmes from 894 programmes at 148 institutions (QS top 100), each checked
against official minimum requirements: academics, English, fees, deadlines.
A real AI model (DeepSeek) powers the chat, explains every verdict with
citations, parses a pasted background into a profile, and builds an
improvement plan. Rankings from QS, THE and ARWU sit alongside the
recommendations but never affect eligibility. The whole product works in six
languages, including Arabic (RTL).

**How we built it**
FastAPI backend with a pure rules engine (MET / NOT_MET / UNKNOWN /
NOT_APPLICABLE), a Next.js frontend, and a verified-data pipeline: every fact
carries its official source, excerpt and retrieval date. Expansion programmes
are evaluated only on verified structured data through a generic evaluator.
Climate preference (80 cities) reorders results — it never changes a verdict.
904 automated tests pass; the backend runs on Render, the frontend on Vercel.

**Challenges we ran into**
Official requirements are scattered and sometimes contradictory; we refused to
fill gaps with plausible numbers, which meant building an honest UNKNOWN state
into every screen. A third-party AI gateway outage during the final night
taught us to fail honestly too: when the model is unreachable, the assistant
says so instead of faking an answer.

**What's next**
Finish programme coverage beyond computer, business and engineering; add the
action-comparison view; extend improvement plans to all expansion programmes.

## Video script — ~90 seconds (record on the phone, English narration)

Superseded: the video is now recorded by Muse (screen-recording on the VM,
60 fps, no black leader) with the full 3:12 English narration — see
docs/VIDEO_NARRATION_SCRIPT.md and narration-full.srt (40 subtitle cues).
The shot table below is the old 90-second phone plan, kept for reference.

Warm-up first: open the backend health URL, wait for {"status":"ok"}, then
start recording. Record in English UI (first-open default).

| Time | Shot | Narration |
|---|---|---|
| 0:00–0:10 | Home page: cases + news carousel, then scroll to rankings | "Choosing a university abroad shouldn't mean trusting a guess. PathPilot checks what universities officially publish." |
| 0:10–0:30 | Start eligibility check; pick a field first (e.g. Computer Science), enter Gaokao 680 + IELTS 7.0 | "Tell it your background — Gaokao, A-level, IB — and it checks you against real minimum requirements." |
| 0:30–0:50 | Results: cards with MET / NOT_MET / UNKNOWN chips; open one programme, show evidence drawer with official source link | "Every verdict shows its evidence. Unknown stays unknown — nothing is invented." |
| 0:50–1:10 | Chat with 小罗盘: "I like very cold places, what do you recommend?" — answer cites Edinburgh, Durham, Lund | "Ask in plain words. The AI answers from verified data — cold means Edinburgh, not Singapore." |
| 1:10–1:30 | Rankings page (top-to-bottom, crests), then improvement plan / report | "Rankings for context, a plan for what to improve next. Built for the Global AI Builder's Challenge 2026." |

Recording notes: keep each shot steady; if the backend is asleep the first
tap will look stuck for ~50 s — warm it up first (see top of this file).
Do not show the API key, the vault page, or any login screen.

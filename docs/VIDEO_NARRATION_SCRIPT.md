# PathPilot AI — Video narration script (English, ~3:30)

Prepared 2026-11-27 for Xiangfeng. Full English narration for the 2–4 minute
hackathon video. The voice is Xiangfeng's own, cloned locally with Qwen3-TTS
(free, Apache-2.0) from his self-introduction recording — test line verified
2026-11-27 (test-en.wav, transcribed back word-perfect).

Numbers below are current as of 2026-11-27 16:00 CST: 894 programmes
(593 matchable), 148 institutions (QS top 100), rankings QS 2027 + THE 2027 +
ARWU 2026 (300 records), 41 applicants / 53 offers, 18 reviews, 6 locales,
80 climate cities, 709 pytest passed. Do NOT claim: admission probabilities,
full coverage of every programme of every school, or that the AI model is
always online (the gateway drops out for minutes at a time — see §6).

Recording notes: warm up the backend first (open
https://pathpilot-ai-co9k.onrender.com/api/v1/health, wait for
{"status":"ok"}). Record the AI-chat shots only when the gateway is up —
check with one quick test question first; if the model is down, the chat
shows honest template replies, which is fine for the "honest fallback" shot
but not for the AI demo shots. Record in the English UI (first-open
default). Do not show any API key, vault page, or login screen.

## 0:00–0:20 — Hook: the problem

Shot: Home page — cases + news carousel, then scroll to rankings.

> "Choosing a university abroad shouldn't mean trusting a guess.
> Requirements are scattered across a hundred university websites —
> different languages, different formats, different currencies. And most
> tools answer with a number they invented, like a 73 percent chance of
> admission. PathPilot checks what universities actually publish."

## 0:20–0:50 — Principle: three rules

Shot: Results cards with MET / NOT_MET / UNKNOWN chips; open one programme,
show the evidence drawer with the official source link.

> "PathPilot runs on three rules. One: every fact comes from an official
> source, with a link and a verification date. Two: unknown is a real
> answer — if no university publishes the number, we say unknown instead
> of inventing one. Three: we never give admission probabilities, because
> no one can compute them honestly."

## 0:50–1:30 — Core demo

Shot: Start the eligibility check in the pet chat; pick a field first
(Computer Science), enter Gaokao 680 and IELTS 7.0; results appear; open
the ETH card and the evidence drawer. Let the demo play under the words.

> "Tell it your background in plain words — Gaokao, A-level, IB, SAT —
> and it checks you against the real minimum requirements: academics,
> English, fees, deadlines. Every verdict shows its evidence. Unknown
> stays unknown — nothing is invented."

## 1:30–2:20 — Innovation: what other tools don't do

Shots, in order: simulate panel (budget +10,000 pounds → 74 rules flip);
why-not MIT (gap 931 pounds, fix: budget 50,932); devil's advocate
(Zurich 14 programmes vs Lausanne 11 — a difference of 3); improvement
plan (German C1, 8-week plan); the reliability boundary line; Gaokao
route (UCL foundation year; Imperial does not accept Gaokao); FX
(CHF 4,380 ≈ GBP 4,018).

> "Here is what other tools don't do. Change one thing — say, your
> budget — and PathPilot shows exactly what flips: ten thousand pounds
> more turns 74 rules green. Ask why not MIT, and it names the one gap:
> 931 pounds short on fees. Turn on devil's advocate, and it argues
> against your own preferences — with numbers the engine computed, not
> the model. And every AI sentence is checked against verified data, with
> a clear line: engine numbers are facts, model words may be wrong. Even
> the hard cases are honest: no university publishes a Gaokao conversion,
> so instead of inventing one, PathPilot shows the real route — a
> foundation year, or the test you actually need."

## 2:20–2:50 — Scale and design

Shots: rankings page; language switcher — switch to Arabic briefly, then
back to English (mention it in one line); programme browse; cases carousel.

> "Under the hood: 894 programmes at 148 universities, checked against
> official requirements in six languages — including Arabic, right to
> left. Rankings from QS, THE and ARWU for context, never for
> eligibility. 709 automated tests guard every release."

## 2:50–3:15 — Honest improvements

Shot: the offline footer line / template fallback on screen, then the
"what's next" list.

> "We're honest about what's not finished. The AI gateway we rely on
> drops out for minutes at a time — when it does, the assistant says so
> instead of faking an answer. Coverage beyond computing, business and
> engineering is still growing, and the action-comparison view isn't built
> yet."

## 3:15–3:35 — Future

Shot: back to the home page, closing on the logo.

> "Next: every programme of every top-100 university, in every field;
> alerts when a university changes its requirements; and a more reliable
> model connection — so the AI is there whenever you ask."

## 3:35–3:40 — Close

> "PathPilot AI — choose by evidence, not by guess. Try it live, link
> below."

## Word count / timing

Narration is ~400 words ≈ 2:40 at a natural pace; the remaining ~50
seconds are the demo itself playing under sections 3 and 4. If the video
runs long, cut the Gaokao sentence in §4 first; if it runs short, hold
the rankings shot in §5 a beat longer.

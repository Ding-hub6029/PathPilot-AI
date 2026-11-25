# AI Integration — PathPilot AI (Day 3)

How the real model is wired in, what it may and may not do, and what still
needs a key. The competition rubric gives AI integration & development
30 of 100 points — the largest slice — so this module is the difference
between a rules engine with a chat skin and a genuinely AI-integrated
product. The rules engine always stays authoritative: the model explains,
drafts and converses; it never decides eligibility.

## Status

| Item | State |
|---|---|
| Provider client (`backend/ai/provider.py`) | Done: OpenAI-compatible (OpenAI, DeepSeek) + Google Gemini |
| Grounded generation + citation checking (`backend/ai/grounding.py`) | Done, spec Ch13 validation chain |
| Versioned prompts (`backend/ai/prompts.py`) | `ai-prompts-v1` |
| Model-written `/explain` | Done, template fallback |
| Pet free-text chat (`POST /api/v1/assistant/chat`) | Done, template fallback |
| Free-text profile parsing (`POST /api/v1/profile/parse`) | Done, model + regex paths |
| Improvement plans FR13/FR14 (`POST /api/v1/improvement-plan` + reassess) | Done, model + template paths |
| 12-case AI evaluation set (spec Ch17) | Done, `GET /api/v1/ai/evaluation` |
| Live model verification | **Awaiting a working key (see below)** |

## Provider setup — the user supplies the key

No key is bought, stored or committed by the agent. Set these in the
deployment platform's environment variables (Render dashboard → Environment,
or a local `.env` copied from `backend/.env.example` — never commit `.env`):

| Variable | Meaning |
|---|---|
| `AI_PROVIDER` | `openai` \| `deepseek` \| `gemini` |
| `AI_MODEL` | Model id, e.g. `gpt-4o-mini`, `deepseek-chat`, `gemini-2.0-flash` |
| `AI_API_KEY` | The provider key |
| `AI_BASE_URL` | Optional override. Third-party OpenAI-compatible gateways go here |
| `AI_TIMEOUT_MS` | Total call budget in ms (default 20000, spec Ch13/Ch17 ceiling) |
| `AI_MAX_TOKENS` | Max output tokens per call (default 1200) |

Check status any time: `GET /api/v1/ai/status` returns `ai_status`,
provider, model, `api_key_configured` (boolean only — never the key),
supported providers and the prompt version. With no key it reports
`ai_status: "unavailable"` and every AI endpoint falls back honestly to
the rules/template behaviour; a model answer is never faked.

### Current key status (2026-11-25, updated ~20:10)

**Working gateway: shenjyai.cc (神经元 Axon).** The user redeemed a code
there (account balance $5.00, key named "PathPilot DeepSeek") and the key
was tested live: a chat-completions call to
`https://www.shenjyai.cc/v1/chat/completions` with model
`deepseek-v4.1-flash` returned a completion ("OK"), and `/v1/models`
returns 200. Configure it as:

```
AI_PROVIDER=deepseek
AI_MODEL=deepseek-v4.1-flash
AI_BASE_URL=https://www.shenjyai.cc/v1
AI_API_KEY=<the key, from the Secure Vault shenjyai connector>
```

The provider wiring for this exact gateway was verified with a mock
transport: it POSTs to `https://www.shenjyai.cc/v1/chat/completions`
with `model: deepseek-v4.1-flash` and Bearer auth. A backend started with
these variables (and no key yet) reports `provider: deepseek`,
`model: deepseek-v4.1-flash`, `api_key_configured: false`,
`ai_status: "unavailable"` and falls back honestly to templates.

**Do NOT use ai11.shop any more.** The earlier ai11.shop key was rejected
with `"Invalid token"` (`new_api_error`) on both `/chat/completions` and
`/models` and remains invalid.

The shenjyai key still needs to be stored in the Secure Vault under a new
shenjyai connector (link sent to the user 2026-11-25); until it is stored,
the backend cannot make a live model call from its own environment — the
live verification through the app awaits that step. The key value is not
stored, logged or repeated anywhere in this repo.

## Architecture

```
backend/ai/
  provider.py    OpenAI-compatible + Gemini clients, env-only config,
                 sanitised ProviderError (never contains the key)
  grounding.py   Verified-context builder + citation checker (Ch13 chain)
  prompts.py     Versioned system prompts (ai-prompts-v1)
  explain.py     Model-written /explain (structured JSON -> text), template fallback
  chat.py        Pet free-text chat (retrieval -> model -> validate -> template fallback)
  parse.py       Free-text profile parsing (model + regex paths)
  plans.py       FR13/FR14 gap diagnosis, tasks, store, reassessment
  evaluation.py  Frozen 12-case evaluation set + runner + metrics
  gaokao_routes.py  Verified Gaokao route facts (official pages only)
  assistant.py   Template pet (3-question fast path, unchanged)
backend/app/
  router_chat.py   POST /assistant/chat, POST /profile/parse
  router_plans.py  POST/GET /improvement-plan, task status, reassess, export
  router_eval.py   GET /ai/evaluation
  errors.py        Shared error-response helper for routers
```

## Grounding rules (the model never free-writes facts)

- The model only ever sees VERIFIED catalogue data as context: v2
  programme requirements/fees/deadlines (source manifest), expansion
  programmes, ranking entries, and the verified Gaokao route facts.
- Output must be the spec Ch13 JSON schema: `{summary, claims: [{text,
  kind, rule_ids, evidence_ids}], unknowns, actions, limitations}` with
  `kind` in `fact | inference | limitation | recommendation`.
- Citation check (spec Ch13 validation chain): schema + length; every
  evidence/rule id must be in the supplied whitelist; rule status is
  immutable (a claim may not contradict the engine); numbers/dates/
  currencies in a fact claim must appear in the cited evidence;
  no admission probabilities or guarantees in any of the six locales;
  no raw URLs in model text — URLs resolve server-side from ids only.
- One repair retry on validation failure (within the 20 s budget), then
  the deterministic template. Rejected outputs reach the user only as
  templates, and the rejection is counted in the evaluation metrics,
  never hidden.
- The model never sees names, emails, phone numbers or student IDs: the
  profile sent contains grades/scores/budget only, and the pet's
  personal-data guard refuses such messages before they reach the model.

## Endpoints

| Endpoint | Model behaviour |
|---|---|
| `GET /api/v1/ai/status` | Provider/model/key-configured/prompt version; never the key |
| `POST /api/v1/explain` | Model-written explanation from the server-side recomputed evaluation + `explanation_structured` (the validated JSON); template when no key or on failure |
| `POST /api/v1/assistant/chat` | Free-text pet chat, grounded, ≤3 lines, conclusion first, one evidence link; template `ask()` fallback |
| `POST /api/v1/profile/parse` | Free text → structured profile + `confirmation_required: true`; model or regex; never applied without confirmation |
| `POST /api/v1/improvement-plan` | Gap diagnosis + personalised UG/TM plan, weekly schedule |
| `GET /api/v1/improvement-plan/{id}` / `/export` | Stored plan / JSON export |
| `POST /api/v1/improvement-plan/{id}/tasks/{task_id}` | Status todo/in_progress/done/to_verify |
| `POST /api/v1/improvement-plan/reassess` | Engine-recomputed diff from a confirmed profile patch; task completion alone changes nothing |
| `GET /api/v1/ai/evaluation?mode=template\|model` | Frozen 12-case report with metrics |

Rate limits: the AI endpoints share a 10/min/IP bucket (`/assistant/chat`,
`/profile/parse`, `/improvement-plan*`, `/ai/evaluation`); `/explain`
keeps its own 10/min bucket; everything else is 60/min.

## The 12-case evaluation set (spec Ch17)

Frozen cases in `backend/ai/evaluation.py`: 2 ordinary, 4 boundary,
2 evidence-unknown/conflict, 2 prompt-injection, 2 service/structure-
failure. Each case pins reference facts, the allowed explanation scope and
forbidden assertions; synthetic applicant profiles only. Metrics (all with
denominators): schema validity, citation-id legality, false-MET assertions,
should-be-unknown-but-definite assertions, degradation success, latency,
cost. Release gate: citation legality 100%, structural compliance 100%,
false qualification assertions 0.

Template-path run (2026-11-25, live :8002): **12/12 passed, gate passed** —
schema 12/12, citation legality 78/78 (100%), false-MET 0,
should-be-unknown-but-definite 0, degradations 4/4, rejections 4/4
(injection + failure cases, reported separately, not hidden). Semantic
support is sampled = 0 (needs human sampling, never faked). Cost $0.00
(template/mock only).

## What still needs the user's key to go live

Everything works today in template mode (honest `ai_status:
"unavailable"`). With a working key, these switch to the model with no
code change: model-written `/explain` text, pet free-text chat answers,
profile-parse model path, and model-drafted improvement tasks. The
evaluation set's `mode=model` run is the way to verify the live model
against the frozen cases before relying on it.

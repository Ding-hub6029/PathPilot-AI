"""Round 15 (W3: append-only chat history + first-reply budget).

Covers, with no real API key and no network:

- F1 (mid-chat model drop rewrites the chat): `markTurnOffline` in
  frontend/src/lib/chat.ts marks the dropped turn offline IN PLACE —
  earlier turns keep their exact questions/replies/order, the
  dropped turn keeps its question verbatim, nothing is removed or
  reordered. (The component half — PrefChat.preserveFailedAnswer
  must call it instead of filtering the turn out, and the guided
  branch must render the kept turns above the guided continuation —
  is a PrefChat.tsx patch for W1; see the patch in the test docstring
  below and in the Round 15 report. The pet already appends: its
  goOffline pushes a new turn and never filters `messages`.)
- F2 (first reply took 1–2 min): `fetchJsonChat` in
  frontend/src/lib/api.ts bounds one chat turn to ~20 s total (18 s
  attempt, no retry on a slow abort), while fast failures (backend
  waking) still retry inside the budget. The node harness below pins
  the mechanism with small override budgets so it runs in seconds;
  the real 18 s / 20 s values were measured one-off against a
  hanging fetch (BEFORE: old 40 s/90 s pattern threw after 90.0 s
  in 3 attempts; AFTER: fetchJsonChat threw after ~20 s in 1
  attempt — see the Round 15 report).
- F2 backend half: with a real hanging gateway (local HTTP server
  that never responds), POST /api/v1/assistant/pref-chat still
  answers in ~15 s (the single 15 s model call, then the template),
  the second turn fails fast on the circuit breaker, and the pet
  chat shares the breaker. So the 1–2 min first reply cannot come
  from one backend turn — it was the frontend's 40 s attempt / 90 s
  retry budget stacking on top.

PrefChat.tsx patch (W1 — NOT applied here, this worker may not edit
that file):
  1. Import: add `markTurnOffline` to the lib/chat import.
  2. preserveFailedAnswer: replace
       setTurns((prev) => prev.filter((x) => x.id !== turnId));
     with
       setTurns((prev) => markTurnOffline(prev, turnId));
     (the rest — local mapping / failedText prefill / enterGuidedMode
     / why re-arm — is unchanged; the turn stays visible as an
     offline turn under its own question).
  3. Guided branch: render `{renderPrefTurns()}` immediately inside
     the `<>` of the `mode === 'guided'` branch, above the
     `wizard.chatPrefOffline` banner, so earlier model turns stay
     visible and the guided continuation appends below them.
  4. Chat calls: replace the three fetchJsonPatient chat calls
     (sendToPrefChat, askModel, submitFreeText /profile/parse) with
     fetchJsonChat, dropping the `attemptTimeoutMs: 40000` option
     (keep `onRetry: () => setWaking(true)`).

Run from the project root:
    .venv/bin/pytest tests/test_r15_w3.py -q -p no:cacheprovider
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai.provider import reset_gateway_breaker
from app.main import app as main_app

ROOT = Path(__file__).resolve().parents[1]
client = TestClient(main_app)

_NODE_HARNESS = r"""
const chat = require(OUT + '/chat.js');
const api = require(OUT + '/api.js');
let fail = 0;
const check = (name, got, want) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g !== w) { console.log('FAIL ' + name + ' -> ' + g + ' want ' + w); fail++; }
  else console.log('PASS ' + name);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// --- F1: markTurnOffline is append-only -------------------------------
// Audit conversation (re-test task 9): Switzerland named, climate
// answered, then the model drops on the city turn.
const turns = [
  { id: 1, question: '瑞士', reply: { lines: ['瑞士记下了。'], ai_status: 'available' }, replyLocale: 'zh-CN', offline: false, pending: false },
  { id: 2, question: '凉爽', reply: { lines: ['凉爽记下了。'], ai_status: 'available' }, replyLocale: 'zh-CN', offline: false, pending: false },
  { id: 3, question: '苏黎世', reply: null, replyLocale: null, offline: false, pending: true },
];
const before = JSON.parse(JSON.stringify(turns));
const after = chat.markTurnOffline(turns, 3);
check('F1 drop keeps the turn count', after.length, 3);
check('F1 earlier turns byte-identical', after.slice(0, 2), before.slice(0, 2));
check('F1 earlier turns are the same objects', after[0] === turns[0] && after[1] === turns[1], true);
check('F1 dropped turn keeps its question', after[2].question, '苏黎世');
check('F1 dropped turn is offline, not pending', [after[2].offline, after[2].pending], [true, false]);
check('F1 dropped turn has no reply when the call failed', after[2].reply, null);
check('F1 input turns are not mutated', turns, before);
// A template reply that arrived is kept, labelled offline.
const template = { lines: ['模板回答。'], ai_status: 'unavailable' };
const kept = chat.markTurnOffline(turns, 3, template, 'zh-CN');
check('F1 template reply is kept on the dropped turn', kept[2].reply, template);
check('F1 template turn keeps its locale and is offline', [kept[2].replyLocale, kept[2].offline, kept[2].pending], ['zh-CN', true, false]);
check('F1 template path keeps earlier turns', kept.slice(0, 2), before.slice(0, 2));
// An unknown id changes nothing.
check('F1 unknown turn id is a no-op', chat.markTurnOffline(turns, 99), turns);

// --- F2: fetchJsonChat bounds one turn --------------------------------
let attempts = 0;
const hangingFetch = (_url, init) => {
  attempts++;
  return new Promise((_res, rej) => {
    init?.signal?.addEventListener('abort', () => {
      const e = new Error('aborted'); e.name = 'AbortError'; rej(e);
    });
  });
};
const fastFailFetch = (_url, _init) => { attempts++; return Promise.reject(new TypeError('fetch failed')); };
const okFetch = (_url, _init) => { attempts++; return Promise.resolve({ ok: true, json: async () => ({ hello: 1 }) }); };

(async () => {
  // A hanging fetch under fetchJsonChat (small overrides so the test
  // runs in ~1 s, not 20 s — note the 1000 ms floor on the
  // per-attempt timer in fetchJsonPatient, so overrides stay above
  // it): ONE attempt, then the honest throw.
  globalThis.fetch = hangingFetch;
  attempts = 0;
  let t0 = Date.now();
  try { await api.fetchJsonChat('/api/assistant/pref-chat', { method: 'POST', body: '{}' }, { attemptTimeoutMs: 1200, budgetMs: 5000 }); check('F2 hanging fetchJsonChat throws', false, true); }
  catch (e) { check('F2 hanging fetchJsonChat throws AbortError', e.name, 'AbortError'); }
  check('F2 hanging fetchJsonChat makes exactly 1 attempt', attempts, 1);
  check('F2 hanging fetchJsonChat settles in ~one attempt, not the budget', Date.now() - t0 < 2500, true);
  // Same, via fetchJsonPatient with retryOnTimeout=false directly.
  attempts = 0;
  t0 = Date.now();
  try { await api.fetchJsonPatient('/api/assistant/pref-chat', { method: 'POST', body: '{}' }, { attemptTimeoutMs: 1200, budgetMs: 5000, retryOnTimeout: false }); check('F2 retryOnTimeout=false throws', false, true); }
  catch (e) { check('F2 retryOnTimeout=false throws AbortError', e.name, 'AbortError'); }
  check('F2 retryOnTimeout=false makes exactly 1 attempt', attempts, 1);
  check('F2 retryOnTimeout=false settles in ~one attempt', Date.now() - t0 < 2500, true);
  // The OLD behaviour (retryOnTimeout default true) still retries a
  // slow abort while budget remains: 2 attempts in ~4.4 s
  // (1200 ms attempt + 2000 ms sleep + 1200 ms attempt).
  attempts = 0;
  t0 = Date.now();
  try { await api.fetchJsonPatient('/api/assistant/pref-chat', { method: 'POST', body: '{}' }, { attemptTimeoutMs: 1200, budgetMs: 6000 }); check('F2 old patient fetch throws', false, true); }
  catch (e) { check('F2 old patient fetch throws AbortError', e.name, 'AbortError'); }
  check('F2 old patient fetch retries a slow abort', attempts >= 2, true);
  check('F2 old patient fetch takes ~2 attempts + sleep', Date.now() - t0 >= 3000, true);
  // A fast failure (backend waking) still retries under fetchJsonChat.
  globalThis.fetch = fastFailFetch;
  attempts = 0;
  t0 = Date.now();
  try { await api.fetchJsonChat('/api/assistant/pref-chat', { method: 'POST', body: '{}' }, { attemptTimeoutMs: 5000, budgetMs: 5000 }); check('F2 fast-fail fetchJsonChat throws', false, true); }
  catch (e) { check('F2 fast-fail fetchJsonChat throws TypeError', e.name, 'TypeError'); }
  check('F2 fast-fail fetchJsonChat still retries (waking backend)', attempts >= 2, true);
  check('F2 fast-fail retries stay inside the budget', Date.now() - t0 < 6000, true);
  // A healthy fetch resolves through fetchJsonChat.
  globalThis.fetch = okFetch;
  attempts = 0;
  check('F2 fetchJsonChat returns the parsed body', await api.fetchJsonChat('/api/x', {}), { hello: 1 });
  check('F2 healthy fetchJsonChat makes 1 attempt', attempts, 1);
  console.log(fail ? 'HARNESS FAILURES: ' + fail : 'HARNESS OK');
  process.exit(fail ? 1 : 0);
})().catch((e) => { console.log('HARNESS ERROR ' + (e && e.stack || e)); process.exit(1); });
"""


def test_r15_append_only_drop_and_chat_budget(tmp_path):
    """Round 15 F1+F2 (frontend): a mid-chat drop keeps every turn,
    and one chat turn is bounded with no retry on a slow abort."""
    outdir = tmp_path / "r15_w3"
    fe = ROOT / "frontend"
    res = subprocess.run(
        ["npx", "tsc", "src/lib/api.ts", "src/lib/chat.ts",
         "src/lib/types.ts",
         "--module", "commonjs", "--target", "es2020", "--jsx", "react-jsx",
         "--outDir", str(outdir), "--skipLibCheck", "--esModuleInterop",
         "--resolveJsonModule"],
        cwd=str(fe), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / "r15_harness.js"
    harness.write_text(
        _NODE_HARNESS.replace("OUT", repr(str(outdir))),
        encoding="utf-8")
    env = {"PATH": os.environ["PATH"],
           "NODE_PATH": str(fe / "node_modules")}
    node = subprocess.run(
        ["node", str(harness)],
        capture_output=True, text=True, timeout=120, env=env)
    assert node.returncode == 0, node.stdout + node.stderr
    assert "FAIL" not in node.stdout
    assert "HARNESS OK" in node.stdout


class _HangHandler(BaseHTTPRequestHandler):
    """A gateway that accepts the connection and then never answers."""

    def _hang(self):
        time.sleep(30)

    def do_GET(self):
        self._hang()

    def do_POST(self):
        self._hang()

    def log_message(self, *args):
        pass


@pytest.fixture
def _hanging_gateway(monkeypatch):
    """Local hanging gateway + dummy provider env (never a real key)."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _HangHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    monkeypatch.setenv("AI_PROVIDER", "deepseek")
    monkeypatch.setenv("AI_MODEL", "hang-test-model")
    monkeypatch.setenv("AI_API_KEY", "dummy-test-key")
    monkeypatch.setenv("AI_BASE_URL", f"http://127.0.0.1:{port}/v1")
    reset_gateway_breaker()
    try:
        yield
    finally:
        reset_gateway_breaker()
        server.shutdown()
        server.server_close()


def test_r15_hanging_gateway_pref_chat_answers_within_budget(_hanging_gateway):
    """Round 15 F2 (backend): a hanging gateway must not produce a
    1–2 min first pref-chat reply — one turn is a single 15 s model
    call, then the template. The second turn fails fast on the
    circuit breaker, and the pet chat shares it."""
    body = {"message": "瑞士", "locale": "zh-CN", "known": {}, "history": []}
    t0 = time.monotonic()
    r = client.post("/api/v1/assistant/pref-chat", json=body)
    first_s = time.monotonic() - t0
    assert r.status_code == 200, r.text
    assert r.json()["ai_status"] == "unavailable"
    assert len(r.json()["lines"]) >= 1  # template fallback, not a hang
    assert first_s < 22, f"hanging gateway: first pref-chat turn took {first_s:.1f}s"
    assert first_s > 10, f"first turn suspiciously fast ({first_s:.1f}s): the 15 s model timeout did not run"

    t0 = time.monotonic()
    r2 = client.post("/api/v1/assistant/pref-chat", json=body)
    second_s = time.monotonic() - t0
    assert r2.status_code == 200, r2.text
    assert r2.json()["ai_status"] == "unavailable"
    assert second_s < 5, f"breaker did not fail fast: second turn took {second_s:.1f}s"

    t0 = time.monotonic()
    r3 = client.post("/api/v1/assistant/chat",
                     json={"message": "瑞士有哪些好学校？", "locale": "zh-CN", "history": []})
    third_s = time.monotonic() - t0
    assert r3.status_code == 200, r3.text
    assert r3.json()["ai_status"] == "unavailable"
    assert third_s < 5, f"pet chat did not share the breaker: took {third_s:.1f}s"


def test_r15_plan_template_label_all_locales():
    """Round 15 F3 (cheap confirm): the plan page's template label —
    shown whenever ai_status is not 'available' (PlanPanel.tsx:217)
    next to the honest 'AI 服务调用失败' assumption
    (backend/ai/plans.py `assume.provider_failed`) — exists in all
    6 locales, so no locale regresses to an unlabelled template."""
    messages_dir = ROOT / "frontend" / "messages"
    plans = Path(__file__).resolve().parents[1] / "backend" / "ai" / "plans.py"
    plans_src = plans.read_text(encoding="utf-8")
    assert plans_src.count("assume.provider_failed") >= 6 + 1  # 6 locales + use site
    for name in ("en.json", "zh-CN.json", "es.json", "fr.json", "pt-BR.json", "ar.json"):
        data = json.loads((messages_dir / name).read_text(encoding="utf-8"))
        label = data.get("plan.templateLabel", "")
        assert label, f"{name}: plan.templateLabel missing"
        assert "AI" in label or "IA" in label or "ذكاء" in label, f"{name}: template label does not name the AI model: {label!r}"

"""P0 fixes for live re-test task 6 (2026-11-26 21:59-22:11 CST).

Covers, with no API key and no network:
- P2: every fee-UNKNOWN reason mapping (backend adapter +
  frontend mirror) — the Alberta / ANU cards showed "未提供这项检查
  所需的信息" with a GBP 50,000 budget supplied, because a missing
  fee amount and a per-credit fee both fell through to
  'missing-info'. Includes a sweep over ALL matchable expansion
  programmes: with a budget supplied, no exp-fee UNKNOWN may carry
  'missing-info'.
- P0-3: pref-chat reason capture in both paths — the model-up chip
  tap (no reason given, none invented), the gateway-down fallback
  (full sentence keeps country + reason), and the why-answer
  ("因为那边环境优美" with Switzerland known keeps the note). The
  bare-reason case is pinned as the frontend's job: the server does
  not guess a note from a bare "环境优美" (it could be any
  preference's answer); the why-follow-up stores it directly.
- P0-4: input preservation across the fallback switch, via a node
  harness over the compiled frontend (mapFailedPrefAnswer): the
  re-test's lost salary answer, countries + reason, city, climate,
  and the never-map-a-question rule.

Run from the project root:
    .venv/bin/pytest tests/test_p0_retest6.py -q -p no:cacheprovider
"""
from __future__ import annotations

import json
import subprocess
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from ai.pref_chat import _deterministic_extract, pref_answer
from ai.provider import ProviderAdapter
from app.adapter import _derive_reason_key, rule_to_frontend
from app.data import EXPANSION_PROGRAMS
from app.schemas import (Budget, Language, MastersProfile, StudentProfile,
                         UndergradProfile)
from domain.expansion_eval import evaluate_expansion

ROOT = Path(__file__).resolve().parents[1]


# --- Audit profile (re-test task 6) -------------------------------------------
# China Gaokao, undergraduate, Computer Science, Gaokao 680/750,
# IELTS 7.0 (L7 R7 W6.5 S7), budget GBP 50,000, 2027 entry, overseas
# residency, preference Switzerland / cool / university-town / Zurich.

def _audit_ug(budget: Decimal | None = Decimal("50000"),
              budget_currency: str = "GBP",
              budget_period: str = "per_year"):
    lang = Language(exam="ielts", overall=7.0, listening=7.0, reading=7.0,
                    writing=6.5, speaking=7.0)
    return StudentProfile(
        application_track="undergraduate",
        undergrad_profile=UndergradProfile(
            qualification_type="other", curriculum="cn_gaokao",
            gaokao_score=680, gaokao_total=750, residency="overseas",
            intake_year=2027, graduation_status="final"),
        language=lang,
        budget=(Budget(amount=budget, currency=budget_currency,
                       period=budget_period) if budget is not None else None))


def _audit_tm(budget: Decimal | None = Decimal("50000"),
              budget_currency: str = "GBP",
              budget_period: str = "total"):
    lang = Language(exam="ielts", overall=7.0, listening=7.0, reading=7.0,
                    writing=6.5, speaking=7.0)
    return StudentProfile(
        application_track="taught_masters",
        masters_profile=MastersProfile(
            degree_subject="computer science",
            degree_class="first_class", residency="overseas",
            intake_year=2027),
        language=lang,
        budget=(Budget(amount=budget, currency=budget_currency,
                       period=budget_period) if budget is not None else None))


def _fee_rule(profile, pid: str):
    rules = {r.rule_id: r for r in evaluate_expansion(profile, EXPANSION_PROGRAMS[pid])}
    return rules["exp-fee"]


# --- P2: fee UNKNOWN reason mapping --------------------------------------------

def test_p2_alberta_fee_not_published_reason_key():
    """Alberta CS AI BSc states no fee amount: UNKNOWN with reasonKey
    'fee-not-published', never 'missing-info' — the audit profile
    supplies a GBP 50,000 budget, so "information not provided" is
    false on its face."""
    r = _fee_rule(_audit_ug(), "alberta-cs-ai-bsc-2027")
    assert r.status == "UNKNOWN"
    assert "No tuition fee amount is stated" in r.detail
    out = rule_to_frontend(r)
    assert out["reasonKey"] == "fee-not-published"
    assert out["expected"] == "No tuition fee amount published"


def test_p2_anu_advcomp_fee_not_published_reason_key():
    """ANU Advanced Computing (Hons) states no fee amount: same key."""
    r = _fee_rule(_audit_ug(), "anu-advcomp-hons-2027")
    assert r.status == "UNKNOWN"
    assert rule_to_frontend(r)["reasonKey"] == "fee-not-published"


def test_p2_per_credit_fee_reason_key():
    """HKPolyU IT MSc charges per credit: UNKNOWN with reasonKey
    'fee-per-credit' — the profile has no credit count, which is not
    user information withheld."""
    r = _fee_rule(_audit_tm(), "hkpolyu-it-msc-2027")
    assert r.status == "UNKNOWN"
    assert "per credit" in r.detail
    assert rule_to_frontend(r)["reasonKey"] == "fee-per-credit"


def test_p2_no_amount_no_budget_is_fee_not_published():
    """Guard: with NO budget supplied AND no stated amount, the
    amount-missing branch fires first (the fee cannot be compared
    whatever the budget is), so the key is 'fee-not-published' —
    'missing-info' is reserved for a stated fee with no budget,
    covered by the next test."""
    r = _fee_rule(_audit_ug(budget=None), "alberta-cs-ai-bsc-2027")
    assert r.status == "UNKNOWN"
    assert rule_to_frontend(r)["reasonKey"] == "fee-not-published"


def test_p2_stated_fee_no_budget_still_missing_info():
    """A stated fee with no budget is genuinely missing user info."""
    r = _fee_rule(_audit_ug(budget=None), "anu-computing-bachelor-2027")
    assert r.status == "UNKNOWN"
    assert "No budget supplied" in r.detail
    assert rule_to_frontend(r)["reasonKey"] == "missing-info"


def test_p2_period_mismatch_and_fx_keys_unchanged():
    """The other fee UNKNOWN branches keep their keys (regression
    guard for the mapping edit)."""
    # ANU fee is per_year; a total budget cannot be compared with it.
    r = _fee_rule(_audit_ug(budget_period="total"), "anu-computing-bachelor-2027")
    assert r.status == "UNKNOWN"
    assert rule_to_frontend(r)["reasonKey"] == "budget-mismatch"
    # THB has no reference rate: cannot be converted, never a mismatch.
    r = _fee_rule(_audit_ug(budget=Decimal("800000"), budget_currency="THB"),
                  "anu-computing-bachelor-2027")
    assert r.status == "UNKNOWN"
    assert rule_to_frontend(r)["reasonKey"] == "fx-cannot-convert"


def test_p2_derive_reason_key_direct():
    """Unit pins for the adapter mapping (detail string -> key)."""
    assert _derive_reason_key(
        "exp-fee", "UNKNOWN",
        "No tuition fee amount is stated on the official programme page, so the fee cannot be compared with the budget.") == "fee-not-published"
    assert _derive_reason_key(
        "exp-fee", "UNKNOWN",
        "Tuition is HKD 9,500 per credit; the profile has no credit count, so a per-credit fee cannot be compared with the budget.") == "fee-per-credit"
    assert _derive_reason_key(
        "exp-fee", "UNKNOWN", "No budget supplied.") == "missing-info"
    assert _derive_reason_key(
        "exp-fee", "UNKNOWN",
        "Budget period (total) does not match the fee period (per_year), so it cannot be compared with the fee.") == "budget-mismatch"


def test_p2_no_missing_info_fee_unknown_with_budget_supplied():
    """Sweep: with a budget supplied, NO matchable expansion
    programme's exp-fee UNKNOWN may carry 'missing-info'. Every such
    UNKNOWN is one of the four real causes (fee not published,
    per-credit, period mismatch, cannot convert)."""
    profile = _audit_ug()
    bad: list[tuple[str, str]] = []
    checked = 0
    for pid, prog in EXPANSION_PROGRAMS.items():
        if not prog.get("matchable"):
            continue
        rules = {r.rule_id: r for r in evaluate_expansion(profile, prog)}
        fee = rules.get("exp-fee")
        if fee is None or fee.status != "UNKNOWN":
            continue
        checked += 1
        key = rule_to_frontend(fee)["reasonKey"]
        if key == "missing-info":
            bad.append((pid, fee.detail))
    assert checked >= 100, f"expected ~107 fee UNKNOWNs, got {checked}"
    assert bad == [], f"{len(bad)} fee UNKNOWNs still map to missing-info: {bad[:5]}"


def test_p2_new_reason_keys_localised_all_locales():
    """The two new reason keys exist in all 6 locale files (the
    renderer looks up `reason.<key>`; a missing key would fall back
    to the English detail string)."""
    for loc in ("en", "zh-CN", "es", "fr", "pt-BR", "ar"):
        data = json.loads((ROOT / "frontend" / "messages" / f"{loc}.json").read_text(encoding="utf-8"))
        assert "reason.fee-not-published" in data, loc
        assert "reason.fee-per-credit" in data, loc
        assert "p0.chatWhyCountry" in data, loc
        assert "{countries}" in data["p0.chatWhyCountry"], loc


# --- P0-3: pref-chat reason capture, both paths ---------------------------------

def _mock_provider(monkeypatch, handler) -> ProviderAdapter:
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setenv("AI_API_KEY", "fake-test-key")
    return ProviderAdapter(_transport=httpx.MockTransport(handler))


def _no_key_provider(monkeypatch) -> ProviderAdapter:
    for var in ("AI_PROVIDER", "AI_MODEL", "AI_API_KEY", "AI_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    return ProviderAdapter()


def _chip_tap_handler(request: httpx.Request) -> httpx.Response:
    """Mock model answering the bare chip tap "瑞士": extracts the
    country, no reason — none was given, and the model must not
    invent one. (The frontend why-follow-up is what asks.)"""
    payload = {
        "summary": "瑞士记下了。",
        "claims": [{"text": "没有已核实的数据可以引用。", "kind": "limitation",
                    "rule_ids": [], "evidence_ids": []}],
        "unknowns": [], "actions": [], "limitations": [],
        "extracted": {"countries": ["CH"]}, "next_question": "climate",
    }
    return httpx.Response(200, json={
        "choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}],
        "usage": {}})


def test_p03_chip_tap_model_up_extracts_country_no_invented_note(monkeypatch):
    """Model-up path, chip tap "瑞士": countries=[CH], NO note key —
    the backend never invents a reason. The reason is collected by
    the frontend why-follow-up (P0-3), not by this call."""
    provider = _mock_provider(monkeypatch, _chip_tap_handler)
    r = pref_answer("瑞士", "zh-CN", known={}, provider=provider)
    assert r["ai_status"] == "available"
    assert r["extracted"]["countries"] == ["CH"]
    assert "note" not in r["extracted"]
    assert r["next_question"] == "climate"


def test_p03_full_sentence_fallback_keeps_reason(monkeypatch):
    """Gateway-down fallback: the volunteered reason survives without
    a model (deterministic extraction)."""
    provider = _no_key_provider(monkeypatch)
    r = pref_answer("我想去瑞士，因为那边环境优美", "zh-CN", known={},
                    provider=provider)
    assert r["ai_status"] == "unavailable"
    assert r["extracted"]["countries"] == ["CH"]
    assert "环境优美" in r["extracted"]["note"]
    assert r["next_question"] == "climate"


def test_p03_why_answer_with_country_known_keeps_note(monkeypatch):
    """The why-follow-up's answer, sent as its own turn while
    Switzerland is known: "因为那边环境优美" keeps the note even
    with the gateway down."""
    provider = _no_key_provider(monkeypatch)
    r = pref_answer("因为那边环境优美", "zh-CN",
                    known={"countries": ["CH"]}, provider=provider)
    assert r["ai_status"] == "unavailable"
    assert r["extracted"] == {"note": "那边环境优美"}
    assert r["next_question"] == "climate"


def test_p03_bare_reason_alone_is_not_guessed(monkeypatch):
    """Pinned limitation: a bare "环境优美" with no 因为 and no
    country in the message yields NO note server-side — it could be
    an answer to any preference question, so the server must not
    guess it is the country reason. The frontend stores the
    why-answer directly (no model call), which is the path that
    covers this case."""
    assert _deterministic_extract("环境优美", {"countries": ["CH"]}) == {}


# --- P0-4: input preservation across the fallback switch -------------------------
# Node harness over the compiled frontend: mapFailedPrefAnswer is the
# pure mapping the fallback switch uses. t() reads the real zh-CN
# messages, so label matching behaves as in the browser.

_NODE_CASES = [
    # (name, text, question, expected patch or None)
    ("salary with currency", "60000 GBP", "salary",
     {"prefSalary": 60000, "prefSalaryCurrency": "GBP"}),
    ("salary bare number (re-test's lost answer)", "60000", "salary",
     {"prefSalary": 60000, "prefSalaryCurrency": "GBP"}),
    ("countries + reason", "瑞士，因为那边环境优美", "countries",
     {"prefCountries": ["CH"], "prefCountriesNote": "瑞士，因为那边环境优美"}),
    ("countries chip word", "瑞士", "countries",
     {"prefCountries": ["CH"]}),
    ("climate cold", "很冷", "climate",
     {"prefClimate": "cool"}),
    ("city free text", "苏黎世", "city",
     {"prefCity": "苏黎世"}),
    ("question is never mapped", "瑞士有哪些好学校？", "countries", None),
    ("unmappable answer", "随便", "climate", None),
]

_NODE_HARNESS = r"""
const pc = require(OUT + '/src/components/PrefChat.js');
const { emptyProfile } = require(OUT + '/src/lib/types.js');
const zh = require(FE + '/messages/zh-CN.json');
const t = (k) => zh[k] ?? k;
const profile = { ...emptyProfile };
const cases = JSON.parse(process.argv[2]);
let fail = 0;
for (const [name, text, q, want] of cases) {
  const got = pc.mapFailedPrefAnswer(text, q, t, profile);
  const gotPatch = got ? got.patch : null;
  if (JSON.stringify(gotPatch) !== JSON.stringify(want)) {
    console.log('FAIL ' + name + ' -> ' + JSON.stringify(gotPatch) + ' want ' + JSON.stringify(want));
    fail++;
  } else {
    console.log('PASS ' + name);
  }
}
process.exit(fail ? 1 : 0);
"""


def test_p04_failed_answer_mapping_preserved(tmp_path):
    """The fallback switch preserves the just-submitted answer: the
    mapping the switch applies (same understanding as the guided
    queue) records salary / countries+reason / city / climate, and
    never maps a question as an answer."""
    outdir = tmp_path / "p0_prefchat"
    fe = ROOT / "frontend"
    res = subprocess.run(
        ["npx", "tsc", "src/components/PrefChat.tsx",
         "--module", "commonjs", "--target", "es2020", "--jsx", "react-jsx",
         "--outDir", str(outdir), "--skipLibCheck", "--esModuleInterop",
         "--resolveJsonModule"],
        cwd=str(fe), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / "p0_harness.js"
    harness.write_text(
        _NODE_HARNESS
        .replace("OUT", repr(str(outdir)))
        .replace("FE", repr(str(fe))), encoding="utf-8")
    env = {"PATH": __import__("os").environ["PATH"],
           "NODE_PATH": str(fe / "node_modules")}
    node = subprocess.run(
        ["node", str(harness), json.dumps(_NODE_CASES, ensure_ascii=False)],
        capture_output=True, text=True, timeout=120, env=env)
    assert node.returncode == 0, node.stdout + node.stderr
    assert "FAIL" not in node.stdout

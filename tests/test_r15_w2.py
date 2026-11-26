"""Round 15, worker W2: localised + substantive improvement plans (Finding 1)
and localised devil/evidence city names (Finding 2).

Pins, against the 2026-11-27 02:23-02:34 browser re-test (audit profile:
China Gaokao, UG, CS, 680/750, IELTS 7.0, budget GBP 50,000, 2027,
Switzerland/cool/university-town/Zurich):

- plan gap text renders fully in the requested locale (all 6): the
  engine's English detail sentence never reaches the plan UI, and no
  raw rule id (e.g. "exp-language") appears in any user-facing plan
  string;
- a language gap for a non-IELTS/TOEFL requirement (German C1) gets a
  concrete weekly study plan (weeks, hours, exam) instead of the
  generic "provide the missing proof for <rule id>" task, and the plan's
  weekly schedule covers it;
- the honest provider-failed template line still renders in all 6
  locales;
- the devil's-advocate reply and the evidence-cities line localise
  city names (苏黎世/洛桑 in zh-CN), with no bare English city names in
  a non-English reply;
- the backend city table matches the frontend's own locale files
  (frontend/messages/*/city.*) for every climate-table city.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.router_plans as router_plans
from ai.chat import answer, devil_conflict_line, evidence_cities_line
from ai.chat import _climate_evidence, localised_city_name
from ai.explain import localised_gap_state
from ai.plans import _template_task, clear_plans, diagnose_gaps
from ai.provider import ChatResult, ProviderError
from app.schemas import Evaluation, RuleResult, StudentProfile

# Audit profile (same as tests/test_plans_expansion.py).
AUDIT_GAOKAO = {
    "application_track": "undergraduate",
    "undergrad_profile": {"curriculum": "cn_gaokao", "gaokao_score": 680,
                          "gaokao_total": 750, "residency": "overseas"},
    "language": {"exam": "ielts", "overall": 7.0, "listening": 7.0,
                 "reading": 7.0, "writing": 6.5, "speaking": 7.0},
    "budget": {"amount": 50000, "currency": "GBP", "period": "per_year"},
    "target_intake": 2027,
}
ETH_CS_BSC = "eth-cs-bsc-2027"

LOCALES = ["en", "zh-CN", "es", "fr", "pt-BR", "ar"]

# No-provider assumption line per locale (template path, no key).
NO_PROVIDER_LINE = {
    "en": "No AI provider is configured",
    "zh-CN": "未配置 AI 服务",
    "es": "No hay ningún proveedor de IA configurado",
    "fr": "Aucun fournisseur d'IA n'est configuré",
    "pt-BR": "Nenhum provedor de IA está configurado",
    "ar": "لم يتم تكوين أي مزود ذكاء اصطناعي",
}
# Provider-failed assumption line per locale (template path, call failed).
PROVIDER_FAILED_LINE = {
    "en": "The AI provider call failed",
    "zh-CN": "AI 服务调用失败",
    "es": "La llamada al proveedor de IA falló",
    "fr": "L'appel au fournisseur d'IA a échoué",
    "pt-BR": "A chamada ao provedor de IA falhou",
    "ar": "فشل الاتصال بمزود الذكاء الاصطناعي",
}

AUDIT_DEVIL_PROFILE = {
    "countries": ["CH"], "climate": "cool", "level": "undergraduate",
    "budget_amount": 50000, "budget_currency": "GBP",
    "budget_period": "per_year", "city": "Zurich",
}


def _app() -> TestClient:
    app = FastAPI()
    app.include_router(router_plans.router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_key_and_clean(monkeypatch):
    class Unavailable:
        available = False
        ai_status = "unavailable"

        def chat(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("no-key path must not call the provider")

    monkeypatch.setattr(router_plans, "get_provider", lambda: Unavailable())
    clear_plans()
    yield
    clear_plans()


def _create(client, locale, **kw):
    body = {"profile": AUDIT_GAOKAO, "program_ids": [ETH_CS_BSC],
            "weekly_hours": kw.get("weekly_hours", 6),
            "budget": {"amount": 50000, "currency": "GBP"},
            "deadline": kw.get("deadline"), "locale": locale}
    resp = client.post("/api/v1/improvement-plan", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _rendered_text(plan: dict) -> str:
    """Every user-facing plan string (gaps, tasks, assumptions,
    limitations) — NOT the machine keys (gap_id / rule_ids / task_id),
    which legitimately still carry rule ids as identifiers."""
    parts: list[str] = []
    for gap in plan["gap_assessment"]["gaps"]:
        parts += [gap["current_state"], gap["what_is_missing"]]
    for task in plan["tasks"]:
        parts += [task["title"], task["rationale"], task["current_state"],
                  task["expected_outcome"], task["uncertainty"]]
        parts += list(task["steps"])
        parts += list(task["prerequisites"])
        parts += list(task["acceptance_checklist"])
        parts += list(task["alternatives"])
    parts += list(plan["assumptions"]) + list(plan["limitations"])
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Finding 1a: plan gap text localised, no raw rule ids
# ---------------------------------------------------------------------------

def test_plan_gap_text_localised_zh_no_english_gap_sentences():
    plan = _create(_app(), "zh-CN")
    assert plan["ai_status"] == "unavailable"
    text = _rendered_text(plan)
    # The engine's English detail sentences never reach the plan UI.
    for marker in ("This programme requires", "cannot be assessed",
                   "No language test supplied", "Gaokao scores are never",
                   "Supply the missing evidence", "Rule exp-"):
        assert marker not in text, marker
    # No raw rule id anywhere in user-facing plan text.
    assert "exp-language" not in text
    assert "exp-academic" not in text
    assert "exp-fee" not in text
    gaps = {g["gap_id"]: g for g in plan["gap_assessment"]["gaps"]}
    language = gaps["gap-eth-cs-bsc-2027-exp-language"]
    # The requirement label stays verbatim; the prose around it is Chinese.
    assert "German C1 (CEFR)" in language["current_state"]
    assert "德语" not in language["current_state"]  # label, not prose
    assert "而不是雅思/托福成绩" in language["current_state"]
    academic = gaps["gap-eth-cs-bsc-2027-exp-academic"]
    assert "高考 680/750" in academic["current_state"]
    assert "高考分数从不换算" in academic["current_state"]


def test_plan_gap_text_localised_all_locales_no_raw_rule_ids():
    client = _app()
    for locale in LOCALES:
        plan = _create(client, locale)
        text = _rendered_text(plan)
        assert "exp-language" not in text, locale
        assert "exp-academic" not in text, locale
        assert "exp-fee" not in text, locale
        # The honest no-provider template line renders in every locale.
        assert any(NO_PROVIDER_LINE[locale] in a
                   for a in plan["assumptions"]), locale


def test_plan_provider_failed_line_all_locales(monkeypatch):
    """The AI-failed template line is correct and localised: the
    provider is configured but its call fails, so the plan falls back
    to templates with ai_status unavailable (not an error)."""
    class Failing:
        available = True
        ai_status = "available"

        def chat(self, *args, **kwargs):
            raise ProviderError("gateway down")

    monkeypatch.setattr(router_plans, "get_provider", lambda: Failing())
    client = _app()
    for locale in LOCALES:
        clear_plans()
        plan = _create(client, locale)
        assert plan["ai_status"] == "unavailable", locale
        assert any(PROVIDER_FAILED_LINE[locale] in a
                   for a in plan["assumptions"]), locale
        text = _rendered_text(plan)
        assert "exp-language" not in text, locale


# ---------------------------------------------------------------------------
# Finding 1b: substantive per-gap tasks (German C1 weekly plan)
# ---------------------------------------------------------------------------

def test_german_c1_gap_gets_weekly_study_plan():
    plan = _create(_app(), "zh-CN")
    gaps = {g["gap_id"]: g for g in plan["gap_assessment"]["gaps"]}
    language_gap = gaps["gap-eth-cs-bsc-2027-exp-language"]
    assert language_gap["kind_hint"] == "language_other"
    task = next(t for t in plan["tasks"]
                if t["gap_id"] == language_gap["gap_id"])
    assert "German C1 (CEFR)" in task["title"]
    assert "exp-language" not in task["title"]
    assert "exp-language" not in task["rationale"]
    assert task["duration_weeks"] == 8
    assert task["weekly_hours"] <= 6
    steps = "\n".join(task["steps"])
    # A real weekly schedule, not "provide the missing proof".
    assert "第 1–2 周" in steps
    assert "第 3–6 周" in steps
    assert "第 7 周" in steps
    assert "第 8 周" in steps
    assert "Goethe-Zertifikat C1" in steps
    assert "德语" in steps
    assert "提供缺失的证明" not in task["title"]
    # The weekly schedule covers the 8-week task.
    scheduled = {tid for w in plan["weekly_schedule"]["weeks"]
                 for tid in w["task_ids"]}
    assert task["task_id"] in scheduled
    assert plan["weekly_schedule"]["total_weeks"] >= 8


def test_french_b2_gap_gets_delf_plan_and_french_name():
    """Same kind, different requirement: French B2 -> DELF B2, with the
    language named in the locale (unit level, fabricated evaluation)."""
    profile = StudentProfile(**AUDIT_GAOKAO)
    evaluation = Evaluation(
        program_id="epfl-cs-bsc-2027", data_version="v1",
        overall_status="UNKNOWN", ai_status="unavailable",
        results=[RuleResult(
            rule_id="exp-language", status="UNKNOWN",
            detail="This programme requires French B2 (CEFR), not an "
                   "IELTS/TOEFL score; the profile has no evidence for "
                   "that requirement, so it cannot be assessed from a "
                   "test score.",
            evidence_ids=["src:epfl-cs-bsc-2027:lang"],
            observed={"ielts_overall": 7.0, "toefl_overall": None},
            threshold={"ielts_overall": None, "toefl_overall": None,
                       "other_requirements": ["French B2 (CEFR)"]})])
    gaps = diagnose_gaps(profile, [evaluation], locale="zh-CN")["gaps"]
    assert len(gaps) == 1
    assert gaps[0]["kind_hint"] == "language_other"
    assert "French B2 (CEFR)" in gaps[0]["current_state"]
    assert "This programme requires" not in gaps[0]["current_state"]
    task = _template_task(gaps[0], {"epfl-cs-bsc-2027": {"id": "epfl-cs-bsc-2027"}},
                          None, 6, None, [], "zh-CN")
    assert "French B2 (CEFR)" in task["title"]
    assert "DELF B2" in "\n".join(task["steps"])
    assert "法语" in "\n".join(task["steps"])
    assert task["duration_weeks"] == 8


def test_toefl_below_minimum_gets_toefl_task_not_ielts():
    """A TOEFL shortfall used to get the IELTS task; it now gets the
    TOEFL task (unit level, fabricated evaluation)."""
    profile = StudentProfile(**AUDIT_GAOKAO)
    evaluation = Evaluation(
        program_id="x-toefl-2027", data_version="v1",
        overall_status="NOT_MET", ai_status="unavailable",
        results=[RuleResult(
            rule_id="x-toefl", status="NOT_MET",
            detail="TOEFL iBT 90 is below 100.",
            evidence_ids=["src:x-toefl-2027:lang"],
            observed=90, threshold={"overall": 100})])
    gaps = diagnose_gaps(profile, [evaluation], locale="en")["gaps"]
    assert gaps[0]["kind_hint"] == "toefl_general"
    task = _template_task(gaps[0], {"x-toefl-2027": {"id": "x-toefl-2027"}},
                          None, 6, None, [], "en")
    assert "TOEFL" in task["title"]
    assert "IELTS" not in task["title"]
    assert "TOEFL iBT 90 is below 100" not in task["current_state"]
    assert "TOEFL: required 100, you have 90" in task["current_state"]


def test_missing_ielts_component_scores_get_scores_task():
    """A components UNKNOWN with a missing writing score gets the
    supply-the-scores task naming the missing component, in locale."""
    profile = StudentProfile(**AUDIT_GAOKAO)
    evaluation = Evaluation(
        program_id="ucl-cs-bsc-2026", data_version="v1",
        overall_status="UNKNOWN", ai_status="unavailable",
        results=[RuleResult(
            rule_id="ucl-ielts-components", status="UNKNOWN",
            detail="Missing component score(s): writing.",
            evidence_ids=["f-ucl-ielts"],
            observed={"listening": 7.0, "reading": 7.0, "writing": None,
                      "speaking": 7.0},
            threshold={"listening": 6.5, "reading": 6.5, "writing": 6.0,
                       "speaking": 6.0})])
    gaps = diagnose_gaps(profile, [evaluation], locale="zh-CN")["gaps"]
    assert gaps[0]["kind_hint"] == "language_scores"
    task = _template_task(gaps[0], {"ucl-cs-bsc-2026": {"id": "ucl-cs-bsc-2026"}},
                          None, 6, None, [], "zh-CN")
    assert "写作" in "\n".join(task["steps"])
    assert "ucl-ielts-components" not in _rendered_text(
        {"gap_assessment": {"gaps": gaps}, "tasks": [task],
         "assumptions": [], "limitations": []})


def test_localised_gap_state_unit_cases():
    """The renderer behind current_state, across families (unit level)."""
    # Gaokao academic UNKNOWN keeps the word Gaokao in English (an
    # existing test pins it) and renders 高考 in Chinese.
    rule = RuleResult(
        rule_id="exp-academic", status="UNKNOWN",
        detail="No A-level threshold is stated for this programme.",
        evidence_ids=[], observed={"curriculum": "cn_gaokao",
                                   "gaokao_score": 680, "gaokao_total": 750},
        threshold=None)
    assert "Gaokao 680/750" in localised_gap_state(rule, "en", "Academic")
    assert "高考 680/750" in localised_gap_state(rule, "zh-CN", "学术要求")
    # IELTS overall NOT_MET renders the numbers, not the detail sentence.
    rule = RuleResult(
        rule_id="ucl-ielts-overall", status="NOT_MET",
        detail="IELTS overall 6.5 is below 7.5.",
        evidence_ids=[], observed=6.5, threshold={"overall": 7.5})
    assert "IELTS overall: required 7.5, you have 6.5" in localised_gap_state(
        rule, "en", "Language")
    assert "雅思总分" in localised_gap_state(rule, "zh-CN", "语言要求")
    assert "IELTS overall 6.5 is below 7.5" not in localised_gap_state(
        rule, "en", "Language")


def test_model_task_rule_ids_sanitised(monkeypatch):
    """A model task that cites a raw rule id in its title gets the
    localised label instead — the plan UI never shows the raw id."""
    class FakeModel:
        available = True

        def chat(self, messages, system=None, timeout_s=None,
                 max_tokens=None, temperature=0.2):
            envelope = json.loads(messages[0]["content"])
            tasks = []
            for gap in envelope["gap_assessment"]["gaps"]:
                tasks.append({
                    "task_id": f"model-{gap['gap_id']}",
                    "gap_id": gap["gap_id"],
                    "category": gap["category"],
                    "target_program_ids": [gap["program_id"]],
                    "title": f"Work on {gap['rule_ids'][0]}",
                    "rationale": "Model task built from the gap assessment.",
                    "current_state": gap["current_state"],
                    "expected_outcome": "New evidence supplied.",
                    "steps": ["Do the work."],
                    "resources": [{"label": "Official programme page",
                                   "url": None,
                                   "search_criteria": "official page"}],
                    "weekly_hours": 3,
                    "cost_range": {"min": 0, "max": 0, "currency": None},
                    "duration_weeks": 2,
                    "prerequisites": [],
                    "deadline": None,
                    "acceptance_checklist": ["New evidence supplied"],
                    "alternatives": ["Record what is still missing."],
                    "uncertainty": "Only new evidence can change the rule.",
                })
            return ChatResult(text=json.dumps({"tasks": tasks}),
                              model="fake", provider="fake", latency_ms=1)

    monkeypatch.setattr(router_plans, "get_provider", lambda: FakeModel())
    plan = _create(_app(), "en")
    assert plan["ai_status"] == "available"
    assert "exp-language" not in _rendered_text(plan)
    assert "exp-academic" not in _rendered_text(plan)


def test_reassess_change_carries_localised_rule_label():
    """Reassessment changes carry rule_label in the plan locale, so the
    UI can render it instead of the raw rule id."""
    client = _app()
    plan = _create(client, "zh-CN")
    resp = client.post("/api/v1/improvement-plan/reassess", json={
        "plan_id": plan["plan_id"],
        "profile_patch": {"budget": {"amount": 100, "currency": "GBP",
                                     "period": "per_year"}}})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["changes"], body
    change = body["changes"][0]
    assert change["rule_id"] == "exp-fee"
    assert change["rule_label"] == "学费"
    assert change["old_status"] == "MET"
    assert change["new_status"] == "NOT_MET"


# ---------------------------------------------------------------------------
# Finding 2: devil / evidence city names localised
# ---------------------------------------------------------------------------

def test_devil_reply_zh_localised_cities(monkeypatch):
    class NoKey:
        available = False

        def chat(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("no-key path must not call the provider")

    r = answer("瑞士适合我吗？我想要凉爽的气候。", "zh-CN",
               provider=NoKey(), mode="devil", profile=AUDIT_DEVIL_PROFILE)
    assert r["ai_status"] == "unavailable"
    assert r["mode"] == "devil"
    assert r["conflicts"] == ["climate"]
    joined = "\n".join(r["lines"])
    assert "苏黎世" in joined and "洛桑" in joined
    assert "Zurich" not in joined and "Lausanne" not in joined
    assert "四季分明" in joined


def test_devil_conflict_line_all_locales():
    conflict = {"kind": "climate", "country": "CH", "wanted": "cool",
                "cities": [("Zurich", "four_seasons", 14),
                           ("Lausanne", "four_seasons", 11)]}
    expected = {"en": ("Zurich", "Lausanne"),
                "zh-CN": ("苏黎世", "洛桑"),
                "es": ("Zurich", "Lausanne"),
                "fr": ("Zurich", "Lausanne"),
                "pt-BR": ("Zurich", "Lausanne"),
                "ar": ("Zurich", "Lausanne")}
    for locale in LOCALES:
        line = devil_conflict_line(conflict, locale)
        for name in expected[locale]:
            assert name in line, (locale, line)
        if locale == "zh-CN":
            assert "Zurich" not in line and "Lausanne" not in line


def test_evidence_cities_line_localised():
    sources, _ = _climate_evidence("cool", countries=["CH"])
    line = evidence_cities_line(sources, "zh-CN")
    assert line is not None
    assert "苏黎世" in line and "洛桑" in line
    assert "Zurich" not in line and "Lausanne" not in line
    line_en = evidence_cities_line(sources, "en")
    assert "Zurich" in line_en and "Lausanne" in line_en


def test_city_table_matches_frontend_messages():
    """The backend city table mirrors frontend/messages/*/city.* for
    every climate-table city in every locale — one source of truth."""
    root = Path(__file__).resolve().parents[1]
    messages = {}
    for locale in LOCALES:
        with open(root / "frontend" / "messages" / f"{locale}.json",
                  encoding="utf-8") as f:
            messages[locale] = json.load(f)
    en = messages["en"]
    cities = {k[5:]: v for k, v in en.items() if k.startswith("city.")}
    assert len(cities) == 80
    for slug, canonical in cities.items():
        for locale in LOCALES:
            expected = messages[locale].get(f"city.{slug}", canonical)
            assert localised_city_name(canonical, locale) == expected, (
                slug, locale)
    # Unknown cities render as stored, never a guessed translation.
    assert localised_city_name("Nowhereville", "zh-CN") == "Nowhereville"

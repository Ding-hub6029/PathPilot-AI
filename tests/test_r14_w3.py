"""Round 14 (W3: panels + pages track) regression tests.

- Simulate: a request carrying only the checked scenarios gets back
  only those scenarios (the frontend's run() sends exactly the checked
  candidates; the backend honours the list as given).
- Template explanations (ai.explain): the deterministic template renders
  in the requested locale with the engine numbers intact.
- Improvement-plan templates (ai.plans): template task titles, gap
  texts, assumptions and limitations render in the requested locale.

NOTE (open, out of W3 scope): the *simulate* template explanation
(``budget GBP 50,000 -> GBP 60,000 mattered most ...``) is produced by
``ai.simulate_explain.template_simulate_text`` and is still English on
every locale — that module and ``backend/app/main.py`` (which computes
leverage over every candidate, not only the requested scenarios) are
not in this track's file set. The tests below pin the template paths
this track does own.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.router_plans as router_plans
from ai.explain import compute_whynot, template_explanation
from ai.plans import evaluate_programs
from app.main import app as main_app
from app.schemas import Evaluation, RuleResult, StudentProfile

client = TestClient(main_app)

# Audit profile (browser re-test task 8): China Gaokao, UG, CS,
# Gaokao 680/750, IELTS 7.0, budget GBP 50,000, 2027 entry.
AUDIT_FLAT = {
    "track": "undergraduate", "curriculum": "cn_gaokao", "field": "computing",
    "gaokaoScore": 680, "gaokaoTotal": 750, "residency": "overseas",
    "intakeYear": 2027,
    "ieltsOverall": 7.0, "ieltsListening": 7, "ieltsReading": 7,
    "ieltsWriting": 6.5, "ieltsSpeaking": 7,
    "budget": 50000, "budgetCurrency": "GBP",
    "prefCountries": ["CH"], "prefClimate": "cool",
    "prefEnvironment": "campus", "prefCity": "Zurich",
}

UG_UCL = {
    "application_track": "undergraduate",
    "undergrad_profile": {
        "qualification_type": "a_level", "curriculum": "uk_alevel",
        "a_level_grades": ["A*", "A*", "A"], "a_level_maths_grade": "A*",
        "gcse_english_grade": "C", "gcse_maths_grade": "4",
        "residency": "overseas"},
    "language": {"exam": "ielts", "overall": 6.5, "listening": 6.5,
                 "reading": 6.5, "writing": 5.5, "speaking": 6.0},
    "budget": {"amount": 48600, "currency": "GBP", "period": "per_year"},
    "target_intake": 2026,
}


def _plans_client() -> TestClient:
    app = FastAPI()
    app.include_router(router_plans.router)
    return TestClient(app)


@pytest.fixture
def _no_key(monkeypatch):
    """No-key path: get_provider returns an unavailable stub."""

    class Unavailable:
        available = False
        ai_status = "unavailable"

        def chat(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("no-key path must not call the provider")

    monkeypatch.setattr(router_plans, "get_provider", lambda: Unavailable())
    yield


# --- Simulate: only checked scenarios are computed -------------------------

def test_simulate_checked_scenarios_only_are_returned():
    """Unchecking the two IELTS options and running only the budget
    scenario must return exactly one scenario entry."""
    r = client.post("/api/v1/simulate", json={
        "baseline_profile": AUDIT_FLAT,
        "scenarios": [{"name": "Budget +£10,000", "patch": {"budget": 60000}}],
        "program_ids": ["ucl-cs-bsc-2026", "eth-cs-bsc-2027"],
        "locale": "zh-CN", "explain": False})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [s["name"] for s in body["scenarios"]] == ["Budget +£10,000"]
    assert body["explanation"]["source"] == "template"


def test_simulate_two_checked_scenarios_return_two():
    r = client.post("/api/v1/simulate", json={
        "baseline_profile": AUDIT_FLAT,
        "scenarios": [
            {"name": "IELTS overall +0.5", "patch": {"ieltsOverall": 7.5}},
            {"name": "Budget +£10,000", "patch": {"budget": 60000}}],
        "program_ids": ["ucl-cs-bsc-2026"],
        "locale": "zh-CN", "explain": False})
    assert r.status_code == 200, r.text
    assert len(r.json()["scenarios"]) == 2


# --- Explain template: locale ----------------------------------------------

def _evaluation() -> Evaluation:
    return Evaluation(
        program_id="ucl-cs-bsc-2026", data_version="v1",
        overall_status="NOT_MET", ai_status="unavailable",
        results=[
            RuleResult(rule_id="ucl-ielts-overall", status="MET",
                       detail="IELTS overall 7.0 meets the 7.0 minimum.",
                       evidence_ids=["src:ucl:ielts"]),
            RuleResult(rule_id="ucl-ielts-components", status="NOT_MET",
                       detail="IELTS writing 5.5 is below the 6.0 minimum.",
                       evidence_ids=["src:ucl:ielts"]),
            RuleResult(rule_id="ucl-academic", status="UNKNOWN",
                       detail="Academic: cannot be decided.",
                       evidence_ids=["src:ucl:academic"]),
        ])


def test_template_explanation_renders_zh_cn():
    text = template_explanation(_evaluation(), "zh-CN")
    # Localised prose, with the header naming the programme.
    assert "对 ucl-cs-bsc-2026 的评估" in text
    assert "达到规定的最低要求" in text
    assert "未达到规定的最低要求" in text
    assert "根据现有证据无法判定" in text
    assert "未配置 AI 服务" in text
    # No English body text survives.
    for fragment in ("Evaluation for", "meets the stated minimum",
                     "does not meet the stated minimum",
                     "cannot be decided from the supplied evidence",
                     "no AI provider is configured"):
        assert fragment not in text, fragment
    # Engine numbers / identifiers survive localisation intact.
    assert "ucl-cs-bsc-2026" in text
    assert "7.0" in text and "5.5" in text and "6.0" in text
    assert "[evidence: src:ucl:ielts]" in text


def test_template_explanation_renders_es_and_en_default():
    text_es = template_explanation(_evaluation(), "es")
    assert "Evaluación de ucl-cs-bsc-2026" in text_es
    assert "no cumple el mínimo establecido" in text_es
    assert "Evaluation for" not in text_es
    assert "7.0" in text_es and "5.5" in text_es
    # Default locale is still English, byte-identical to before.
    text_en = template_explanation(_evaluation())
    assert text_en.startswith("Evaluation for ucl-cs-bsc-2026 (data version v1): overall status NOT_MET.")
    assert "meets the stated minimum" in text_en
    assert "Note: no AI provider is configured" in text_en


# --- Why-not template: locale ----------------------------------------------

def test_whynot_template_renders_zh_cn_with_numbers_intact():
    profile = StudentProfile(**UG_UCL)
    ev = evaluate_programs(profile, ["ucl-cs-bsc-2026"])[0]
    w = compute_whynot(ev, profile=profile, budget_currency="GBP",
                       locale="zh-CN")
    text = w["template_text"]
    assert "ucl-cs-bsc-2026 未达标" in text
    assert "雅思写作" in text
    assert "Cheapest fix" not in text
    assert "Why ucl-cs-bsc-2026 is not met" not in text
    assert "No single change on its own" not in text
    # Engine numbers survive: the 5.5 writing score, the 6.0 minimum
    # and the 0.5 shortfall. (The 48,600 fee is not in this text: the
    # fee rule is MET for this profile, so it has no gap line.)
    assert "5.5" in text
    assert "6.0" in text
    assert "0.5" in text
    # The cheapest-fix label is localised too.
    assert w["cheapest_fix"]["label"] == "将雅思写作从 5.5 提高到 6.0"


def test_whynot_template_en_default_unchanged():
    profile = StudentProfile(**UG_UCL)
    ev = evaluate_programs(profile, ["ucl-cs-bsc-2026"])[0]
    w = compute_whynot(ev, profile=profile, budget_currency="GBP")
    assert "Why ucl-cs-bsc-2026 is not met" in w["template_text"]
    assert ("Cheapest fix (suggestion, not a fact): Raise IELTS Writing "
            "from 5.5 to 6.0" in w["template_text"])
    assert w["cheapest_fix"]["label"] == "Raise IELTS Writing from 5.5 to 6.0"


# --- Improvement-plan templates: locale ------------------------------------

def _create_plan(client, locale):
    body = {"profile": UG_UCL, "program_ids": ["ucl-cs-bsc-2026"],
            "weekly_hours": 6, "budget": None, "deadline": None,
            "locale": locale}
    resp = client.post("/api/v1/improvement-plan", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_plan_templates_render_zh_cn(_no_key):
    plan = _create_plan(_plans_client(), "zh-CN")
    assert plan["ai_status"] == "unavailable"
    assert plan["tasks"], "plan must contain tasks"
    titles = [t["title"] for t in plan["tasks"]]
    assert any("将雅思写作" in title for title in titles)
    assert any("确认入学考试要求" in title for title in titles)
    for task in plan["tasks"]:
        for field in ("title", "rationale", "expected_outcome"):
            assert "Raise IELTS" not in task[field], task["task_id"]
            assert "The AI provider call failed" not in task[field]
        for step in task["steps"]:
            assert "Take one timed IELTS" not in step
    # Gap prose is localised; the boundary assumption is localised too.
    gaps = plan["gap_assessment"]["gaps"]
    assert any("未达到规定的最低要求" in g["what_is_missing"] for g in gaps)
    assert any("未配置 AI 服务" in a for a in plan["assumptions"])
    assert "No AI provider is configured" not in " ".join(plan["assumptions"])
    assert "The AI provider call failed" not in " ".join(plan["assumptions"])


def test_plan_templates_render_fr_and_en_default(_no_key):
    plan_fr = _create_plan(_plans_client(), "fr")
    titles_fr = [t["title"] for t in plan_fr["tasks"]]
    assert any(title.startswith("Augmentez") for title in titles_fr)
    assert not any("Raise IELTS" in t for t in titles_fr)
    assert any("Aucun fournisseur d'IA" in a for a in plan_fr["assumptions"])

    plan_en = _create_plan(_plans_client(), "en")
    titles_en = [t["title"] for t in plan_en["tasks"]]
    assert "Raise IELTS writing to the stated minimum" in titles_en
    assert "Build margin above the stated minimum" in titles_en
    assert any("No AI provider is configured" in a
               for a in plan_en["assumptions"])


def test_plan_template_numbers_and_structure_unchanged(_no_key):
    """Localisation must not change the plan shape: same task ids,
    hours, durations and costs as the English template."""
    plan_en = _create_plan(_plans_client(), "en")
    plan_zh = _create_plan(_plans_client(), "zh-CN")
    by_id_en = {t["task_id"]: t for t in plan_en["tasks"]}
    by_id_zh = {t["task_id"]: t for t in plan_zh["tasks"]}
    assert set(by_id_en) == set(by_id_zh)
    for task_id, task_en in by_id_en.items():
        task_zh = by_id_zh[task_id]
        assert task_zh["weekly_hours"] == task_en["weekly_hours"]
        assert task_zh["duration_weeks"] == task_en["duration_weeks"]
        assert task_zh["cost_range"] == task_en["cost_range"]
        assert task_zh["category"] == task_en["category"]
        assert task_zh["gap_id"] == task_en["gap_id"]
        assert len(task_zh["steps"]) == len(task_en["steps"])
        assert len(task_zh["acceptance_checklist"]) == len(
            task_en["acceptance_checklist"])

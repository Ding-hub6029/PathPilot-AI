"""Improvement plans for expansion programmes (Day 3, W3).

The plans router used to resolve ids against the 8 v2 PROGRAMS only,
so every expansion id 404'd. These tests pin the fix:

- plan creation works for a matchable expansion programme
  (eth-cs-bsc-2027, audit profile: China Gaokao, UG, CS, 680/750,
  IELTS 7.0, budget GBP 50,000, 2027 entry), using the generic
  expansion evaluator;
- task updates and engine-recomputed reassessment work for that plan
  (completing a task alone changes no rule status);
- 404 only for genuinely unknown ids;
- display-only expansion programmes (no evaluable rule) get an honest
  422 PROGRAM_NOT_EVALUABLE — never a plan invented from nothing;
- a mixed v2 + expansion plan works.
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.router_plans as router_plans
from ai.grounding import gaokao_sources, programme_sources
from ai.plans import clear_plans, evaluate_programs

# Audit profile (W3 verification profile): China Gaokao, undergraduate,
# Computer Science, Gaokao 680/750, IELTS 7.0 (L7 R7 W6.5 S7),
# budget GBP 50,000, 2027 entry, overseas residency.
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
# Display-only expansion programme (matchable=false): no evaluable rule.
MICHIGAN_CS_BSE = "michigan-cs-bse-2027"

FORBIDDEN_WORDS = ("guaranteed admission", "admission probability",
                   "chance of admission", "will get in", "will be admitted",
                   "录取概率", "保证录取")
INVENTED_WORDS = ("internship", "research project", "research assistant",
                  "recommendation letter", "letter of recommendation",
                  "summer school", "hackathon win")


def _app() -> TestClient:
    app = FastAPI()
    app.include_router(router_plans.router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_key_and_clean(monkeypatch):
    """No-key path by default: get_provider returns an unavailable stub;
    drop any stored plan between tests."""
    class Unavailable:
        available = False
        ai_status = "unavailable"

        def chat(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("no-key path must not call the provider")

    monkeypatch.setattr(router_plans, "get_provider", lambda: Unavailable())
    clear_plans()
    yield
    clear_plans()


def _create(client, profile, program_ids, **kw):
    body = {"profile": profile, "program_ids": program_ids,
            "weekly_hours": kw.get("weekly_hours", 6),
            "budget": kw.get("budget"),
            "deadline": kw.get("deadline"), "locale": "en"}
    return client.post("/api/v1/improvement-plan", json=body)


def _check_expansion_plan_shape(plan, program_ids, capacity=6):
    assert plan["ai_status"] == "unavailable"  # no key in tests
    gap_ids = {g["gap_id"] for g in plan["gap_assessment"]["gaps"]}
    assert gap_ids, "plan must diagnose at least one gap"
    assert plan["tasks"], "plan must contain tasks"
    catalogue_urls = set()
    for pid in program_ids:
        catalogue_urls |= {s.url for s in programme_sources(pid) if s.url}
        catalogue_urls |= {s.url for s in gaokao_sources(pid) if s.url}
    for task in plan["tasks"]:
        assert task["gap_id"] in gap_ids, task
        assert task["target_program_ids"], task
        assert set(task["target_program_ids"]) <= set(program_ids), task
        assert task["steps"], task
        assert task["acceptance_checklist"], task
        assert task["weekly_hours"] <= capacity, task
        assert task["duration_weeks"] >= 1, task
        text = json.dumps(task, ensure_ascii=False).lower()
        for word in FORBIDDEN_WORDS:
            assert word not in text, (word, task["task_id"])
        for word in INVENTED_WORDS:
            assert word not in text, (word, task["task_id"])
        for res in task["resources"]:
            assert res["url"] is None or res["url"] in catalogue_urls, res
            if res["url"] is None:
                assert res["search_criteria"], res
    for week in plan["weekly_schedule"]["weeks"]:
        assert week["weekly_hours"] <= capacity, week


# ---------------------------------------------------------------------------
# Plan creation for a matchable expansion programme
# ---------------------------------------------------------------------------

def test_create_plan_expansion_eth_audit_profile():
    resp = _create(_app(), AUDIT_GAOKAO, [ETH_CS_BSC],
                   budget={"amount": 50000, "currency": "GBP"})
    assert resp.status_code == 200, resp.text
    plan = resp.json()
    assert plan["track"] == "undergraduate"
    assert plan["program_ids"] == [ETH_CS_BSC]
    assert plan["versions"] == [1]
    # Engine verdicts for the audit profile, via the expansion evaluator:
    # fee CHF 4,380/yr converts to ~GBP 4,018 (reference rate 1 GBP =
    # 1.09 CHF) and is covered by GBP 50,000 -> MET, so no fee gap.
    # German C1 (CEFR) is required and the profile has no German
    # evidence -> UNKNOWN; no A-level threshold is stated and Gaokao is
    # never converted to A-levels -> UNKNOWN. Both are to_confirm gaps.
    gaps = {g["gap_id"]: g for g in plan["gap_assessment"]["gaps"]}
    assert gaps["gap-eth-cs-bsc-2027-exp-language"]["evidence_class"] == "to_confirm"
    assert gaps["gap-eth-cs-bsc-2027-exp-academic"]["evidence_class"] == "to_confirm"
    assert "gap-eth-cs-bsc-2027-exp-fee" not in gaps
    assert "german" in gaps["gap-eth-cs-bsc-2027-exp-language"]["current_state"].lower()
    _check_expansion_plan_shape(plan, [ETH_CS_BSC])
    # At least one task links the official ETH page (verified source).
    urls = {r["url"] for t in plan["tasks"] for r in t["resources"]
            if r["url"]}
    assert any("ethz.ch" in u for u in urls), urls


def test_evaluate_programs_expansion_unit_level():
    from app.schemas import StudentProfile

    profile = StudentProfile(**AUDIT_GAOKAO)
    evaluations = evaluate_programs(profile, [ETH_CS_BSC])
    assert len(evaluations) == 1
    by_rule = {r.rule_id: r.status for r in evaluations[0].results}
    assert by_rule["exp-fee"] == "MET"
    assert by_rule["exp-language"] == "UNKNOWN"
    assert by_rule["exp-academic"] == "UNKNOWN"


def test_create_plan_mixed_v2_and_expansion():
    resp = _create(_app(), AUDIT_GAOKAO,
                   ["ucl-cs-bsc-2026", ETH_CS_BSC],
                   budget={"amount": 50000, "currency": "GBP"})
    assert resp.status_code == 200, resp.text
    plan = resp.json()
    assert plan["program_ids"] == ["ucl-cs-bsc-2026", ETH_CS_BSC]
    gap_programs = {g["program_id"] for g in plan["gap_assessment"]["gaps"]}
    assert gap_programs == {"ucl-cs-bsc-2026", ETH_CS_BSC}
    _check_expansion_plan_shape(plan, ["ucl-cs-bsc-2026", ETH_CS_BSC])


# ---------------------------------------------------------------------------
# Unknown ids 404; display-only programmes get an honest 422
# ---------------------------------------------------------------------------

def test_create_plan_unknown_id_404():
    resp = _create(_app(), AUDIT_GAOKAO, ["no-such-programme-2027"])
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "PROGRAM_NOT_FOUND"


def test_create_plan_display_only_422_no_plan_invented():
    resp = _create(_app(), AUDIT_GAOKAO, [MICHIGAN_CS_BSE])
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["error"]["code"] == "PROGRAM_NOT_EVALUABLE"
    assert "display-only" in body["error"]["message"]
    assert "plan_id" not in body
    # A mixed request fails the same way rather than half-creating.
    resp = _create(_app(), AUDIT_GAOKAO, [ETH_CS_BSC, MICHIGAN_CS_BSE])
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "PROGRAM_NOT_EVALUABLE"


# ---------------------------------------------------------------------------
# Task updates + reassessment for an expansion plan
# ---------------------------------------------------------------------------

def test_expansion_task_update_and_reassess():
    client = _app()
    resp = _create(client, AUDIT_GAOKAO, [ETH_CS_BSC],
                   budget={"amount": 50000, "currency": "GBP"})
    assert resp.status_code == 200, resp.text
    plan = resp.json()
    task_id = plan["tasks"][0]["task_id"]
    url = f"/api/v1/improvement-plan/{plan['plan_id']}/tasks/{task_id}"
    # todo -> done is illegal (must go through in_progress).
    assert client.post(url, json={"status": "done"}).status_code == 422
    resp = client.post(url, json={"status": "in_progress"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "in_progress"
    resp = client.post(url, json={
        "status": "done",
        "user_confirmed_evidence": "I checked the ETH language page."})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "done"
    # Completing the task changes no rule status: reassess with an empty
    # patch is a no-change, and the stored fee rule is still MET.
    resp = client.post("/api/v1/improvement-plan/reassess",
                       json={"plan_id": plan["plan_id"], "profile_patch": {}})
    assert resp.status_code == 200, resp.text
    assert resp.json()["changes"] == []
    assert resp.json()["new_version"] == 1
    stored = client.get(f"/api/v1/improvement-plan/{plan['plan_id']}").json()
    fee = next(r for e in stored["evaluations"] for r in e["results"]
               if r["rule_id"] == "exp-fee")
    assert fee["status"] == "MET"
    # The completed task keeps its status in the stored plan.
    stored_task = next(t for t in stored["tasks"]
                       if t["task_id"] == task_id)
    assert stored_task["status"] == "done"


def test_expansion_reassess_budget_drop_flips_fee_rule():
    client = _app()
    resp = _create(client, AUDIT_GAOKAO, [ETH_CS_BSC],
                   budget={"amount": 50000, "currency": "GBP"})
    assert resp.status_code == 200, resp.text
    plan = resp.json()
    # Drop the budget below the converted fee (~GBP 4,018): the engine
    # recompute must flip exp-fee MET -> NOT_MET and open a
    # hard_requirement gap. Only the engine recompute counts.
    resp = client.post("/api/v1/improvement-plan/reassess", json={
        "plan_id": plan["plan_id"],
        "profile_patch": {"budget": {"amount": 100, "currency": "GBP",
                                     "period": "per_year"}}})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["new_version"] == 2
    assert {"program_id": ETH_CS_BSC, "rule_id": "exp-fee",
            "old_status": "MET", "new_status": "NOT_MET"} in body["changes"]
    remaining = {g["gap_id"]: g for g in body["remaining_gaps"]}
    assert remaining["gap-eth-cs-bsc-2027-exp-fee"]["evidence_class"] == "hard_requirement"
    # Old version is kept.
    stored = client.get(f"/api/v1/improvement-plan/{plan['plan_id']}").json()
    assert [v["version"] for v in stored["versions"]] == [1, 2]

"""Improvement plans (Day 3, spec Ch6 FR13/FR14, tests T18/T19).

Pinned rules:
- gap classification: NOT_MET -> hard_requirement, UNKNOWN -> to_confirm,
  barely-MET -> competitiveness;
- every task maps to a real gap_id and a requested program; resource URLs
  only from the evidence catalogue (an invented URL gets the task dropped
  and replaced by a template task);
- weekly hours fit the stated capacity; no invented activities, jobs,
  research projects, awards or recommendations; no admission-effect
  promises;
- completing a task NEVER changes a rule status — only a reassessment
  recomputed by the engine can; reassess with no patch -> no change;
- reassess with a confirmed new IELTS writing 6.0 flips the UCL writing
  rule to MET and closes the gap.
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.router_plans as router_plans
from ai.grounding import gaokao_sources, programme_sources
from ai.plans import build_tasks, diagnose_gaps, evaluate_programs
from ai.provider import ChatResult
from app.data import PROGRAMS
from app.schemas import StudentProfile


def _app() -> TestClient:
    app = FastAPI()
    app.include_router(router_plans.router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_key(monkeypatch):
    """No-key path by default: get_provider returns an unavailable stub."""
    class Unavailable:
        available = False
        ai_status = "unavailable"

        def chat(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("no-key path must not call the provider")

    monkeypatch.setattr(router_plans, "get_provider", lambda: Unavailable())
    yield


# ---------------------------------------------------------------------------
# Profiles: 2 UG examples + 2 TM examples (spec T18)
# ---------------------------------------------------------------------------

UG_UCL = {
    "application_track": "undergraduate",
    "undergrad_profile": {
        "qualification_type": "a_level", "curriculum": "uk_alevel",
        "a_level_grades": ["A*", "A*", "A"], "a_level_maths_grade": "A*",
        "gcse_english_grade": "C", "gcse_maths_grade": "4",
        "residency": "overseas"},
    "language": {"exam": "ielts", "overall": 6.5, "listening": 6.5,
                 "reading": 6.5, "writing": 5.5, "speaking": 6.0},
    "budget": {"amount": 46700, "currency": "GBP", "period": "per_year"},
    "target_intake": 2026,
}

UG_IMPERIAL_GAOKAO = {
    "application_track": "undergraduate",
    "undergrad_profile": {"curriculum": "cn_gaokao", "gaokao_score": 600,
                          "gaokao_total": 750, "residency": "overseas"},
    "language": {"exam": "ielts", "overall": 7.0, "listening": 7.0,
                 "reading": 7.0, "writing": 7.0, "speaking": 7.0},
    "budget": {"amount": 50000, "currency": "GBP", "period": "per_year"},
}

TM_NUS = {
    "application_track": "taught_masters",
    "masters_profile": {"degree_field": "computing", "honours": True},
    "language": {"exam": "ielts", "overall": 6.0, "listening": 6.0,
                 "reading": 6.0, "writing": 6.0, "speaking": 6.0},
    "budget": {"amount": 69215, "currency": "SGD", "period": "total"},
}

TM_UCL_MSC = {
    "application_track": "taught_masters",
    "masters_profile": {"degree_field": "computing",
                        "degree_class": "upper_second",
                        "maths_alevel_grade": "A"},
    "language": {"exam": "ielts", "overall": 7.0, "listening": 7.0,
                 "reading": 7.0, "writing": 7.0, "speaking": 7.0},
    "budget": {"amount": 44400, "currency": "GBP", "period": "per_year"},
}

FORBIDDEN_WORDS = ("guaranteed admission", "admission probability",
                   "chance of admission", "will get in", "will be admitted",
                   "录取概率", "保证录取")
INVENTED_WORDS = ("internship", "research project", "research assistant",
                  "recommendation letter", "letter of recommendation",
                  "summer school", "hackathon win")


def _create(client, profile, program_ids, **kw):
    body = {"profile": profile, "program_ids": program_ids,
            "weekly_hours": kw.get("weekly_hours", 6),
            "budget": kw.get("budget"),
            "deadline": kw.get("deadline"), "locale": "en"}
    resp = client.post("/api/v1/improvement-plan", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _check_plan_shape(plan, program_ids, capacity):
    assert plan["ai_status"] in ("available", "unavailable")
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
# Gap classification (unit level)
# ---------------------------------------------------------------------------

def test_gap_classification_hard_to_confirm_competitiveness():
    profile = StudentProfile(**UG_UCL)
    evaluations = evaluate_programs(profile, ["ucl-cs-bsc-2026"])
    gaps = {g["gap_id"]: g
            for g in diagnose_gaps(profile, evaluations)["gaps"]}
    # NOT_MET -> hard_requirement
    assert gaps["gap-ucl-cs-bsc-2026-ucl-ielts-components"]["evidence_class"] == "hard_requirement"
    assert gaps["gap-ucl-cs-bsc-2026-ucl-ielts-components"]["category"] == "language"
    # UNKNOWN -> to_confirm
    assert gaps["gap-ucl-cs-bsc-2026-ucl-tara"]["evidence_class"] == "to_confirm"
    # MET exactly at the minimum -> competitiveness, labelled as such
    overall = gaps["gap-ucl-cs-bsc-2026-ucl-ielts-overall"]
    assert overall["evidence_class"] == "competitiveness"
    assert "competitiveness" in overall["what_is_missing"].lower()
    fee = gaps["gap-ucl-cs-bsc-2026-ucl-fee"]
    assert fee["evidence_class"] == "competitiveness"
    assert "within 10%" in fee["what_is_missing"]
    # Rules comfortably MET are not gaps at all.
    assert "gap-ucl-cs-bsc-2026-ucl-academic" not in gaps
    assert "gap-ucl-cs-bsc-2026-ucl-gcse" not in gaps


# ---------------------------------------------------------------------------
# No-key template path: UG plan (T18) x2, TM plan (T18) x2
# ---------------------------------------------------------------------------

def test_ug_plan_ucl_no_key():
    plan = _create(_app(), UG_UCL, ["ucl-cs-bsc-2026"],
                   budget={"amount": 46700, "currency": "GBP"})
    assert plan["track"] == "undergraduate"
    assert plan["ai_status"] == "unavailable"
    assert plan["versions"] == [1]
    _check_plan_shape(plan, ["ucl-cs-bsc-2026"], 6)
    # The writing gap gets the 4-week writing template task.
    writing = [t for t in plan["tasks"]
               if t["gap_id"] == "gap-ucl-cs-bsc-2026-ucl-ielts-components"]
    assert len(writing) == 1
    assert writing[0]["duration_weeks"] == 4
    assert "writing" in writing[0]["title"].lower()
    assert writing[0]["acceptance_checklist"]


def test_ug_plan_imperial_gaokao_no_key():
    plan = _create(_app(), UG_IMPERIAL_GAOKAO, ["imperial-comp-beng-2027"],
                   budget={"amount": 50000, "currency": "GBP"})
    assert plan["track"] == "undergraduate"
    gaps = {g["gap_id"]: g for g in plan["gap_assessment"]["gaps"]}
    # No published Gaokao route -> the academic rule is to_confirm.
    gaokao_gap = gaps["gap-imperial-comp-beng-2027-imp-beng-academic"]
    assert gaokao_gap["evidence_class"] == "to_confirm"
    assert "gaokao" in gaokao_gap["current_state"].lower()
    _check_plan_shape(plan, ["imperial-comp-beng-2027"], 6)
    task = next(t for t in plan["tasks"] if t["gap_id"] == gaokao_gap["gap_id"])
    assert "gaokao" in task["title"].lower()
    assert "never converted" in task["uncertainty"].lower()
    # No invented URLs: every resource URL is a verified catalogue URL.
    assert all(r["url"] is None or r["url"].startswith("http")
               for r in task["resources"])


def test_tm_plan_nus_no_key():
    plan = _create(_app(), TM_NUS, ["nus-mcomp-cs"],
                   budget={"amount": 69215, "currency": "SGD"})
    assert plan["track"] == "taught_masters"
    gaps = {g["gap_id"]: g for g in plan["gap_assessment"]["gaps"]}
    assert gaps["gap-nus-mcomp-cs-nus-language"]["evidence_class"] == "competitiveness"
    assert gaps["gap-nus-mcomp-cs-nus-gre-gmat"]["evidence_class"] == "to_confirm"
    assert gaps["gap-nus-mcomp-cs-nus-fee"]["evidence_class"] == "competitiveness"
    _check_plan_shape(plan, ["nus-mcomp-cs"], 6)


def test_tm_plan_ucl_msc_no_key():
    plan = _create(_app(), TM_UCL_MSC, ["ucl-cs-msc-2027"],
                   budget={"amount": 44400, "currency": "GBP"})
    assert plan["track"] == "taught_masters"
    gaps = {g["gap_id"]: g for g in plan["gap_assessment"]["gaps"]}
    # Computing degree does not meet this conversion MSc -> hard requirement.
    assert gaps["gap-ucl-cs-msc-2027-ucl-msc-academic"]["evidence_class"] == "hard_requirement"
    assert gaps["gap-ucl-cs-msc-2027-ucl-msc-language"]["evidence_class"] == "to_confirm"
    _check_plan_shape(plan, ["ucl-cs-msc-2027"], 6)


def test_flat_wizard_profile_accepted():
    client = _app()
    flat = {"track": "undergraduate", "curriculum": "uk_alevel",
            "alevels": "A*A*A", "mathsGrade": "A*",
            "gcseEnglish": "C", "gcseMaths": "4", "residency": "overseas",
            "ieltsOverall": 6.5, "ieltsListening": 6.5, "ieltsReading": 6.5,
            "ieltsWriting": 5.5, "ieltsSpeaking": 6.0,
            "budget": 46700, "budgetCurrency": "GBP"}
    plan = _create(client, flat, ["ucl-cs-bsc-2026"])
    assert plan["track"] == "undergraduate"
    assert any(g["gap_id"] == "gap-ucl-cs-bsc-2026-ucl-ielts-components"
               for g in plan["gap_assessment"]["gaps"])


def test_unknown_program_404_and_track_mismatch_422():
    client = _app()
    resp = client.post("/api/v1/improvement-plan",
                       json={"profile": UG_UCL, "program_ids": ["no-such-program"]})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "PROGRAM_NOT_FOUND"
    resp = client.post("/api/v1/improvement-plan",
                       json={"profile": UG_UCL, "program_ids": ["nus-mcomp-cs"]})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "TRACK_MISMATCH"


def test_deadline_too_short_says_so_and_offers_alternative():
    # Today is 2026-11-25; a 2026-12-02 deadline leaves 1 week, but the
    # writing task needs 4 weeks.
    plan = _create(_app(), UG_UCL, ["ucl-cs-bsc-2026"],
                   deadline="2026-12-02")
    writing = next(t for t in plan["tasks"]
                   if t["gap_id"] == "gap-ucl-cs-bsc-2026-ucl-ielts-components")
    assert "cannot be finished before the deadline" in writing["uncertainty"]
    assert writing["alternatives"], "a short-term alternative is required"


def test_weekly_hours_within_capacity_and_schedule():
    plan = _create(_app(), UG_UCL, ["ucl-cs-bsc-2026"], weekly_hours=4)
    _check_plan_shape(plan, ["ucl-cs-bsc-2026"], 4)
    for week in plan["weekly_schedule"]["weeks"]:
        assert week["weekly_hours"] <= 4


# ---------------------------------------------------------------------------
# Model path (mock provider via monkeypatched get_provider)
# ---------------------------------------------------------------------------

class _FakeModel:
    available = True
    ai_status = "available"

    def __init__(self, payload_fn):
        self._payload_fn = payload_fn

    def chat(self, messages, system=None, timeout_s=None, max_tokens=None,
             temperature=0.2):
        envelope = json.loads(messages[0]["content"])
        return ChatResult(text=json.dumps(self._payload_fn(envelope)),
                          model="fake", provider="fake", latency_ms=1)


def _valid_model_payload(envelope):
    """One valid task per gap, URLs only from the evidence catalogue."""
    tasks = []
    for gap in envelope["gap_assessment"]["gaps"]:
        pid = gap["program_id"]
        url = next((s.url for s in programme_sources(pid) if s.url), None)
        tasks.append({
            "task_id": f"model-{gap['gap_id']}",
            "gap_id": gap["gap_id"],
            "category": gap["category"],
            "target_program_ids": [pid],
            "title": f"Work on {gap['rule_ids'][0]}",
            "rationale": "Model task built from the gap assessment.",
            "current_state": gap["current_state"],
            "expected_outcome": "New evidence supplied so the engine can re-check the rule.",
            "steps": ["Do the work.", "Supply the new evidence for re-check."],
            "resources": [{"label": "Official programme page", "url": url,
                           "search_criteria": None}],
            "weekly_hours": 3,
            "cost_range": {"min": 0, "max": 0, "currency": None},
            "duration_weeks": 2,
            "prerequisites": [],
            "deadline": envelope["deadline"],
            "acceptance_checklist": ["New evidence supplied for re-check"],
            "alternatives": ["If time runs out, record what is still missing."],
            "uncertainty": "Only new evidence can change the rule.",
        })
    return {"tasks": tasks}


def test_model_path_valid_tasks_used(monkeypatch):
    monkeypatch.setattr(router_plans, "get_provider",
                        lambda: _FakeModel(_valid_model_payload))
    plan = _create(_app(), UG_UCL, ["ucl-cs-bsc-2026"])
    assert plan["ai_status"] == "available"
    assert all(t["task_id"].startswith("model-") for t in plan["tasks"])
    _check_plan_shape(plan, ["ucl-cs-bsc-2026"], 6)


def test_model_invented_url_task_dropped_and_replaced(monkeypatch):
    def payload(envelope):
        out = _valid_model_payload(envelope)
        # Invent a URL for the first task: it must be dropped/replaced.
        out["tasks"][0]["resources"] = [
            {"label": "Invented", "url": "https://invented.example.com/x",
             "search_criteria": None}]
        return out

    monkeypatch.setattr(router_plans, "get_provider",
                        lambda: _FakeModel(payload))
    plan = _create(_app(), UG_UCL, ["ucl-cs-bsc-2026"])
    assert plan["ai_status"] == "available"  # other model tasks survived
    for task in plan["tasks"]:
        for res in task["resources"]:
            assert res["url"] != "https://invented.example.com/x", task
    # The gap of the dropped task is still covered, by a template task.
    first_gap = plan["gap_assessment"]["gaps"][0]["gap_id"]
    replaced = next(t for t in plan["tasks"] if t["gap_id"] == first_gap)
    assert replaced["task_id"] == f"task-{first_gap}"
    assert all(r["url"] is None or r["url"].startswith("http")
               for r in replaced["resources"])


def test_model_forbidden_phrasing_task_dropped(monkeypatch):
    def payload(envelope):
        out = _valid_model_payload(envelope)
        out["tasks"][0]["expected_outcome"] = (
            "This guarantees admission with a 90% chance of admission.")
        return out

    monkeypatch.setattr(router_plans, "get_provider",
                        lambda: _FakeModel(payload))
    plan = _create(_app(), UG_UCL, ["ucl-cs-bsc-2026"])
    for task in plan["tasks"]:
        text = json.dumps(task, ensure_ascii=False).lower()
        assert "guarantees admission" not in text
        assert "chance of admission" not in text


# ---------------------------------------------------------------------------
# Status transitions, completion, reassessment
# ---------------------------------------------------------------------------

def test_status_transitions_and_illegal_transition_422():
    client = _app()
    plan = _create(client, UG_UCL, ["ucl-cs-bsc-2026"])
    task_id = plan["tasks"][0]["task_id"]
    url = f"/api/v1/improvement-plan/{plan['plan_id']}/tasks/{task_id}"
    # todo -> done is illegal (must go through in_progress).
    resp = client.post(url, json={"status": "done"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "ILLEGAL_TRANSITION"
    resp = client.post(url, json={"status": "in_progress"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "in_progress"
    resp = client.post(url, json={"status": "done",
                                  "user_confirmed_evidence": "I finished the timed writing practice."})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "done"
    assert resp.json()["user_confirmed_evidence"]["statement"] == (
        "I finished the timed writing practice.")
    # done -> in_progress is illegal; any -> to_verify is allowed.
    resp = client.post(url, json={"status": "in_progress"})
    assert resp.status_code == 422
    resp = client.post(url, json={"status": "to_verify"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "to_verify"


def test_completing_task_does_not_change_rule_status():
    client = _app()
    plan = _create(client, UG_UCL, ["ucl-cs-bsc-2026"])
    task_id = next(t["task_id"] for t in plan["tasks"]
                   if t["gap_id"] == "gap-ucl-cs-bsc-2026-ucl-ielts-components")
    url = f"/api/v1/improvement-plan/{plan['plan_id']}/tasks/{task_id}"
    client.post(url, json={"status": "in_progress"})
    resp = client.post(url, json={
        "status": "done",
        "user_confirmed_evidence": "I now write at band 6.0."})
    assert resp.status_code == 200, resp.text
    # Reassess with no patch: no change at all.
    resp = client.post("/api/v1/improvement-plan/reassess",
                       json={"plan_id": plan["plan_id"], "profile_patch": {}})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["changes"] == []
    assert body["new_version"] == 1
    assert any(g["gap_id"] == "gap-ucl-cs-bsc-2026-ucl-ielts-components"
               for g in body["remaining_gaps"])
    # The stored evaluations still show the rule NOT_MET.
    stored = client.get(f"/api/v1/improvement-plan/{plan['plan_id']}").json()
    writing = next(r for e in stored["evaluations"]
                   for r in e["results"]
                   if r["rule_id"] == "ucl-ielts-components")
    assert writing["status"] == "NOT_MET"


def test_reassess_flips_writing_rule_and_closes_gap():
    client = _app()
    plan = _create(client, UG_UCL, ["ucl-cs-bsc-2026"])
    resp = client.post("/api/v1/improvement-plan/reassess", json={
        "plan_id": plan["plan_id"],
        "profile_patch": {"language": {"writing": 6.0}}})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["new_version"] == 2
    assert {"program_id": "ucl-cs-bsc-2026", "rule_id": "ucl-ielts-components",
            "old_status": "NOT_MET", "new_status": "MET"} in body["changes"]
    # The hard_requirement gap closes. Because 6.0 is exactly the minimum,
    # the same rule now appears as a competitiveness gap (barely-MET rule);
    # no hard gap for the rule remains.
    remaining = {g["gap_id"]: g for g in body["remaining_gaps"]}
    assert remaining["gap-ucl-cs-bsc-2026-ucl-ielts-components"]["evidence_class"] == "competitiveness"
    assert not any(g["gap_id"] == "gap-ucl-cs-bsc-2026-ucl-ielts-components"
                   and g["evidence_class"] == "hard_requirement"
                   for g in body["remaining_gaps"])
    # Old version is kept.
    stored = client.get(f"/api/v1/improvement-plan/{plan['plan_id']}").json()
    assert [v["version"] for v in stored["versions"]] == [1, 2]
    assert any(g["gap_id"] == "gap-ucl-cs-bsc-2026-ucl-ielts-components"
               and g["evidence_class"] == "hard_requirement"
               for g in stored["versions"][0]["gap_assessment"]["gaps"])
    # A score above the minimum (writing 6.5, speaking 6.5) closes the
    # gap entirely: no gap for the rule remains.
    resp = client.post("/api/v1/improvement-plan/reassess", json={
        "plan_id": plan["plan_id"],
        "profile_patch": {"language": {"writing": 6.5, "speaking": 6.5}}})
    assert resp.status_code == 200, resp.text
    assert resp.json()["new_version"] == 3
    assert not any(g["gap_id"] == "gap-ucl-cs-bsc-2026-ucl-ielts-components"
                   for g in resp.json()["remaining_gaps"])


def test_reassess_unknown_field_422():
    client = _app()
    plan = _create(client, UG_UCL, ["ucl-cs-bsc-2026"])
    resp = client.post("/api/v1/improvement-plan/reassess", json={
        "plan_id": plan["plan_id"],
        "profile_patch": {"ielts_writing": 6.0}})
    assert resp.status_code == 422
    resp = client.post("/api/v1/improvement-plan/reassess", json={
        "plan_id": plan["plan_id"],
        "profile_patch": {"language": {"band": 6.0}}})
    assert resp.status_code == 422


def test_get_and_export_endpoints():
    client = _app()
    plan = _create(client, TM_NUS, ["nus-mcomp-cs"])
    resp = client.get(f"/api/v1/improvement-plan/{plan['plan_id']}")
    assert resp.status_code == 200
    assert resp.json()["plan_id"] == plan["plan_id"]
    assert resp.status_code == 200
    resp = client.get(f"/api/v1/improvement-plan/{plan['plan_id']}/export")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["export_metadata"]["format"] == "json"
    assert body["export_metadata"]["plan_id"] == plan["plan_id"]
    assert body["export_metadata"]["data_version"] == "v2"
    assert client.get("/api/v1/improvement-plan/plan-deadbeef").status_code == 404


def test_no_key_template_path_produces_valid_plans():
    # Direct build_tasks call, no provider at all.
    profile = StudentProfile(**TM_NUS)
    evaluations = evaluate_programs(profile, ["nus-mcomp-cs"])
    gaps = diagnose_gaps(profile, evaluations)
    tasks = build_tasks(gaps, evaluations, [PROGRAMS["nus-mcomp-cs"]],
                        deadline=None, weekly_hours=5,
                        budget={"amount": 69215, "currency": "SGD"},
                        locale="en", provider=None)
    assert tasks
    assert {t["gap_id"] for t in tasks} == {g["gap_id"] for g in gaps["gaps"]}
    for task in tasks:
        assert task["weekly_hours"] <= 5
        assert task["resources"]

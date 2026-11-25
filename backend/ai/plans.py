"""Background-improvement plans (Day 3, spec Ch6 FR13/FR14).

Gap diagnosis + personalised UG/TM plans with weekly tasks and status
tracking (todo / in_progress / done / to_verify).

Hard rules, pinned by the spec:

- Completing a task NEVER changes eligibility by itself. A rule status
  changes only when the user confirms new scores/evidence that satisfy
  the original rule, recomputed by the engine (domain/eligibility).
  ``reassess`` is the only place statuses change, and only from the
  engine's recompute — a client-supplied verdict is never trusted.
- No invented activities, jobs, research projects, awards or
  recommendations. No invented resource links: a resource URL comes
  only from the supplied evidence catalogue, otherwise url=null plus
  search_criteria.
- No admission-effect promises, no percentage improvements.
- A task that cannot finish before the deadline must say so and offer
  a short-term alternative. Weekly hours must fit the user's stated
  capacity. Cost must fit the stated budget when given.

Two paths produce tasks: a model path (provider configured, output
validated, one repair retry, then templates) and a deterministic
template path (no key, provider failure, or validation failure).
"""
from __future__ import annotations

import copy
import json
import re
import secrets
from datetime import date, datetime, timezone
from decimal import Decimal

from ai.grounding import (
    FORBIDDEN_PATTERNS,
    gaokao_sources,
    programme_sources,
)
from ai.prompts import PROMPT_VERSION, plan_system
from ai.provider import ProviderAdapter, ProviderError
from app.data import DATA_VERSION, PROGRAMS
from app.schemas import (
    Budget,
    Evaluation,
    Language,
    MastersProfile,
    StudentProfile,
    UndergradProfile,
)
from domain.eligibility import evaluate, overall_status

TASK_STATUSES = ("todo", "in_progress", "done", "to_verify")

_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "todo": {"in_progress", "to_verify"},
    "in_progress": {"done", "to_verify"},
    "done": {"to_verify"},
    "to_verify": {"to_verify"},
}

_CATEGORIES = ("academic", "language", "professional", "experience", "materials")
_EVIDENCE_CLASSES = ("hard_requirement", "competitiveness", "to_confirm")

_FORBIDDEN_RE = [re.compile(p, re.IGNORECASE) for p in FORBIDDEN_PATTERNS]
# Invented-activity language the templates (and any model text we keep)
# must never contain.
_INVENTED_ACTIVITY_RE = re.compile(
    r"internship|research project|research assistant|award\b|"
    r"recommendation letter|letter of recommendation|volunteer abroad|"
    r"summer school|hackathon win|get a job|find a job|new job",
    re.IGNORECASE)

# In-memory store: plan_id -> plan dict. No persistence by design (Day 3).
PLANS: dict[str, dict] = {}


class PlanError(Exception):
    """Plan error carrying the API error code and HTTP status."""

    def __init__(self, message: str, *, code: str = "VALIDATION_ERROR",
                 status: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


class PlanNotFound(PlanError):
    def __init__(self, plan_id: str) -> None:
        super().__init__(f"No improvement plan with id '{plan_id}'.",
                         code="PLAN_NOT_FOUND", status=404)


class TaskNotFound(PlanError):
    def __init__(self, task_id: str) -> None:
        super().__init__(f"No task with id '{task_id}' in this plan.",
                         code="TASK_NOT_FOUND", status=404)


class IllegalTransition(PlanError):
    def __init__(self, task_id: str, from_status: str, to_status: str) -> None:
        super().__init__(
            f"Task {task_id} cannot move from '{from_status}' to "
            f"'{to_status}'. Allowed: todo -> in_progress -> done, "
            f"and any status -> to_verify.",
            code="ILLEGAL_TRANSITION", status=422)


class InvalidPatch(PlanError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="VALIDATION_ERROR", status=422)


def clear_plans() -> None:
    """Test helper: drop every stored plan."""
    PLANS.clear()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_deadline(value: str | None) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("deadline must be an ISO date string (YYYY-MM-DD)")
    try:
        parts = value.strip().split("-")
        if len(parts) != 3 or len(parts[0]) != 4:
            raise ValueError
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, TypeError):
        raise ValueError(
            f"deadline {value!r} is not a valid ISO date (YYYY-MM-DD)")


def _weeks_until(deadline: str | None) -> int | None:
    d = _parse_deadline(deadline)
    if d is None:
        return None
    return max(0, (d - date.today()).days // 7)


def _num(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _fmt_threshold(threshold: dict | None) -> str:
    if not threshold:
        return "no threshold stated in the verified sources"
    return ", ".join(f"{k}={v}" for k, v in threshold.items())


def _fmt_observed(observed) -> str:
    if observed is None:
        return "not supplied"
    if isinstance(observed, dict):
        return ", ".join(f"{k}={v}" for k, v in observed.items())
    return str(observed)


# ---------------------------------------------------------------------------
# Gap diagnosis (deterministic, always available)
# ---------------------------------------------------------------------------

def _category_for_rule(rule_id: str, detail: str) -> str:
    rid = rule_id.lower()
    if any(k in rid for k in ("ielts", "toefl", "language")):
        return "language"
    if "fee" in rid:
        return "materials"
    if "experience" in detail.lower():
        return "experience"
    return "academic"


def _barely_met(rule) -> str | None:
    """Why a MET rule is only barely met, or None if it is not barely met.

    Barely met = IELTS overall or a component exactly at the minimum, or
    a budget within 10% of the fee.
    """
    if rule.status != "MET" or not rule.threshold:
        return None
    threshold = rule.threshold
    observed = rule.observed
    # Fee rules: budget within 10% of the fee.
    if "fee" in rule.rule_id:
        fee_val = None
        for key in ("gbp_per_year", "sgd_total", "amount"):
            if key in threshold:
                fee_val = _num(threshold[key])
                break
        obs = _num(observed)
        if obs is None and isinstance(observed, dict):
            obs = _num(observed.get("amount"))
        if fee_val is not None and obs is not None:
            if fee_val <= obs <= fee_val * 1.10:
                return (f"budget is within 10% of the fee "
                        f"({obs:g} against a fee of {fee_val:g})")
        return None
    # IELTS overall exactly at the minimum.
    obs = _num(observed)
    if obs is not None:
        for key in ("overall",):
            if key in threshold and obs == _num(threshold[key]):
                return f"IELTS overall is exactly at the minimum ({obs:g})"
        return None
    # IELTS components: a component exactly at its minimum.
    if isinstance(observed, dict):
        each = _num(threshold.get("each_component"))
        if each is not None:
            at_min = [k for k, v in observed.items()
                      if _num(v) is not None and _num(v) == each]
            if at_min:
                return (f"IELTS component(s) exactly at the minimum "
                        f"({', '.join(at_min)} at {each:g})")
        for key, val in threshold.items():
            if key in observed and _num(observed[key]) == _num(val):
                return f"IELTS {key} is exactly at the minimum ({val:g})"
    return None


def diagnose_gaps(profile: StudentProfile, evaluations: list[Evaluation],
                  deadline: str | None = None,
                  weekly_hours: float | None = None,
                  budget: dict | None = None) -> dict:
    """Deterministic gap diagnosis from engine evaluations.

    Every NOT_MET rule -> hard_requirement gap; every UNKNOWN rule ->
    to_confirm gap; a MET rule met only barely -> competitiveness gap,
    clearly labelled as such.
    """
    gaps: list[dict] = []
    for ev in evaluations:
        for rule in ev.results:
            if rule.status == "NOT_MET":
                evidence_class = "hard_requirement"
                missing = (f"Stated minimum not met. Threshold: "
                           f"{_fmt_threshold(rule.threshold)}; observed: "
                           f"{_fmt_observed(rule.observed)}. "
                           f"Supply new scores or evidence that meet the "
                           f"stated minimum so the engine can re-check "
                           f"this rule.")
            elif rule.status == "UNKNOWN":
                evidence_class = "to_confirm"
                missing = (f"Cannot be decided from the supplied evidence. "
                           f"Supply the missing score, document or "
                           f"confirmation the official programme page asks "
                           f"for, so the engine can decide this rule.")
            elif rule.status == "MET":
                reason = _barely_met(rule)
                if reason is None:
                    continue
                evidence_class = "competitiveness"
                missing = (f"Competitiveness gap only: the rule is MET, "
                           f"but {reason}, so there is little margin above "
                           f"the stated minimum. Extra margin is optional "
                           f"and is not required to satisfy the rule.")
            else:  # NOT_APPLICABLE
                continue
            gaps.append({
                "gap_id": f"gap-{ev.program_id}-{rule.rule_id}",
                "program_id": ev.program_id,
                "category": _category_for_rule(rule.rule_id, rule.detail),
                "evidence_class": evidence_class,
                "rule_ids": [rule.rule_id],
                "evidence_ids": list(rule.evidence_ids),
                "current_state": rule.detail,
                "what_is_missing": missing,
            })
    return {"track": profile.application_track, "gaps": gaps}


# ---------------------------------------------------------------------------
# Evidence catalogue
# ---------------------------------------------------------------------------

def _evidence_catalog(program_ids: list[str]) -> list:
    """Verified sources only: programme sources + Gaokao facts."""
    sources = []
    seen: set[str] = set()
    for pid in program_ids:
        try:
            for s in programme_sources(pid):
                if s.id not in seen:
                    seen.add(s.id)
                    sources.append(s)
            for s in gaokao_sources(pid):
                if s.id not in seen:
                    seen.add(s.id)
                    sources.append(s)
        except Exception:
            continue
    return sources


def _catalog_urls(catalogue: list) -> set[str]:
    return {s.url for s in catalogue if s.url}


# ---------------------------------------------------------------------------
# Deterministic template tasks (no-key path)
# ---------------------------------------------------------------------------

def _hours(default: int, capacity: float | None) -> float:
    if capacity is None:
        return float(default)
    if capacity <= 0:
        return 0.0
    return float(min(default, capacity))


def _program_resource(program: dict | None, catalogue: list) -> dict:
    if program is not None:
        for s in catalogue:
            if s.id.startswith(f"src:{program['id']}:") and s.url:
                return {"label": (f"Official requirements — "
                                  f"{program.get('official_name') or program['id']}"),
                        "url": s.url, "search_criteria": None}
    return {"label": "Official programme page",
            "url": None,
            "search_criteria": "official programme entry requirements"}


def _gaokao_resource(program: dict | None, catalogue: list) -> dict:
    for s in catalogue:
        if s.id.startswith("gaokao-") and s.url:
            return {"label": f"Verified Gaokao route facts — {s.title}",
                    "url": s.url, "search_criteria": None}
    name = (program or {}).get("institution") or "the university"
    return {"label": "Gaokao entry route (official university page)",
            "url": None,
            "search_criteria": f"{name} Gaokao entry requirements official site"}


def _finish_note(duration_weeks: int, deadline: str | None,
                 alternatives: list[str]) -> str:
    """Deadline feasibility note; also guarantees a short-term alternative."""
    weeks_left = _weeks_until(deadline)
    if deadline is None:
        return ("No deadline was given, so no finish-by date is set for "
                "this task.")
    if weeks_left is None:
        return ""
    if duration_weeks > weeks_left:
        return (f"This task needs {duration_weeks} weeks but only "
                f"{weeks_left} week(s) remain before the deadline "
                f"({deadline}), so it cannot be finished before the "
                f"deadline. Use the short-term alternative below for the "
                f"remaining time.")
    return (f"{weeks_left} week(s) remain before the deadline ({deadline}); "
            f"this task needs {duration_weeks} week(s).")


def _template_task(gap: dict, programs_by_id: dict, deadline: str | None,
                   weekly_hours: float | None, budget: dict | None,
                   catalogue: list) -> dict:
    """One deterministic template task for a gap. Never invents a URL,
    an activity, or an admission effect."""
    program = programs_by_id.get(gap.get("program_id") or "")
    rule_id = (gap.get("rule_ids") or [""])[0]
    detail = gap.get("current_state", "")
    category = gap.get("category", "academic")
    evidence_class = gap.get("evidence_class", "hard_requirement")
    detail_l = detail.lower()
    currency = (budget or {}).get("currency")

    kind = "academic_prep"
    if "gaokao" in detail_l:
        kind = "gaokao_route"
    elif evidence_class == "competitiveness":
        kind = "strengthen_margin"
    elif evidence_class == "to_confirm":
        if any(k in rule_id for k in ("tara", "tmua", "gre", "gmat", "test")):
            kind = "confirm_test"
        elif category == "experience":
            kind = "experience_evidence"
        else:
            kind = "confirm_evidence"
    elif category == "language":
        kind = "ielts_writing" if ("writing" in detail_l
                                   or "components" in rule_id) else "ielts_general"
    elif category == "materials":
        kind = "budget"
    elif category == "experience":
        kind = "experience_evidence"

    base = {
        "task_id": f"task-{gap['gap_id']}",
        "gap_id": gap["gap_id"],
        "category": category,
        "target_program_ids": [gap["program_id"]] if gap.get("program_id") else [],
        "current_state": detail,
        "prerequisites": [],
        "deadline": deadline,
    }

    if kind == "ielts_writing":
        task = {
            **base,
            "title": "Raise IELTS writing to the stated minimum",
            "rationale": (f"Rule {rule_id} is not met: {detail} Writing is "
                          f"the component below the minimum."),
            "expected_outcome": ("A new IELTS writing score at or above the "
                                 "stated minimum, supplied for re-check by "
                                 "the engine."),
            "steps": [
                "Take one timed IELTS writing task (Task 1 and Task 2) under exam timing.",
                "Compare the attempt with the public IELTS band descriptors for writing and list the specific errors.",
                "Rewrite the weakest paragraph, fixing the listed errors.",
                "Repeat with a fresh timed task; book an IELTS test date only after a timed attempt meets the minimum on self-check.",
            ],
            "resources": [
                _program_resource(program, catalogue),
                {"label": "IELTS official writing practice materials",
                 "url": None,
                 "search_criteria": "IELTS official writing practice materials band descriptors"},
            ],
            "weekly_hours": _hours(5, weekly_hours),
            "cost_range": {"min": 0, "max": None, "currency": None},
            "duration_weeks": 4,
            "prerequisites": ["Access to IELTS writing practice material found via the search criteria below"],
            "acceptance_checklist": [
                "Timed writing attempt completed and compared with the band descriptors",
                "Errors from the attempt listed and corrected in a rewrite",
                "New IELTS writing score supplied for re-check",
            ],
            "alternatives": [
                "If little time remains, use the remaining time for one timed writing task per day instead of general study.",
            ],
            "uncertainty": ("Practice alone does not change the rule; only a "
                            "new test score can. The cost and availability of "
                            "a test sitting are not in the verified sources; "
                            "check the official test provider page."),
        }
    elif kind == "ielts_general":
        task = {
            **base,
            "title": "Raise IELTS overall to the stated minimum",
            "rationale": f"Rule {rule_id} is not met: {detail}",
            "expected_outcome": ("A new IELTS overall score at or above the "
                                 "stated minimum, supplied for re-check by "
                                 "the engine."),
            "steps": [
                "Take one timed IELTS practice test and record the score for each section.",
                "Practise the lowest-scoring section daily, using official practice material.",
                "Retake a timed practice test and compare the section scores with the previous attempt.",
                "Book an IELTS test date only after a timed practice attempt meets the minimum on self-check.",
            ],
            "resources": [
                _program_resource(program, catalogue),
                {"label": "IELTS official practice materials",
                 "url": None,
                 "search_criteria": "IELTS official practice test materials"},
            ],
            "weekly_hours": _hours(6, weekly_hours),
            "cost_range": {"min": 0, "max": None, "currency": None},
            "duration_weeks": 6,
            "prerequisites": ["Access to IELTS practice material found via the search criteria below"],
            "acceptance_checklist": [
                "Timed practice test completed with section scores recorded",
                "Lowest-scoring section practised and re-tested",
                "New IELTS overall score supplied for re-check",
            ],
            "alternatives": [
                "If little time remains, focus the remaining time on the lowest-scoring section only.",
            ],
            "uncertainty": ("Practice alone does not change the rule; only a "
                            "new test score can. The cost and availability of "
                            "a test sitting are not in the verified sources."),
        }
    elif kind == "budget":
        task = {
            **base,
            "title": "Close the budget gap for the target programme fee",
            "rationale": f"Rule {rule_id} is not met: {detail}",
            "expected_outcome": ("A revised budget figure that meets the "
                                 "published fee, or a decision to target a "
                                 "programme whose fee fits the current "
                                 "budget, so the fee rule can be re-checked."),
            "steps": [
                "Write down the published fee from the official programme page linked below.",
                "List the funding already available and the exact shortfall.",
                "Search for funding options using the criteria below and record what each option actually covers.",
                "Update the budget figure in the plan only with amounts that are confirmed.",
            ],
            "resources": [
                _program_resource(program, catalogue),
                {"label": "Funding options for international students",
                 "url": None,
                 "search_criteria": (f"scholarships funding international students "
                                     f"{(program or {}).get('institution') or ''}").strip()},
            ],
            "weekly_hours": _hours(2, weekly_hours),
            "cost_range": {"min": 0, "max": 0, "currency": currency},
            "duration_weeks": 2,
            "prerequisites": [],
            "acceptance_checklist": [
                "Shortfall amount recorded",
                "Funding options checked and recorded with what they cover",
                "Revised budget figure supplied, or a different target programme chosen",
            ],
            "alternatives": [
                "If the fee cannot be met, compare the fees of the other target programmes in this plan and pick one that fits the current budget.",
            ],
            "uncertainty": ("No funding amount is promised here; funding "
                            "availability and amounts are not in the verified "
                            "sources."),
        }
    elif kind == "gaokao_route":
        task = {
            **base,
            "title": "Clarify the Gaokao route for the target programme",
            "rationale": (f"Rule {rule_id} cannot be decided: {detail}"),
            "expected_outcome": ("A route confirmed from an official source "
                                 "(for example a foundation route or another "
                                 "accepted qualification), recorded with its "
                                 "evidence, so the academic rule can be "
                                 "re-checked."),
            "steps": [
                "Read the verified Gaokao facts supplied for this programme.",
                "Check the official page linked in the resources for the routes the university does publish.",
                "If no direct Gaokao route is published, check whether the university publishes a foundation route and its requirements.",
                "Record the chosen route and the evidence for it in the plan.",
            ],
            "resources": [
                _gaokao_resource(program, catalogue),
                _program_resource(program, catalogue),
            ],
            "weekly_hours": _hours(2, weekly_hours),
            "cost_range": {"min": 0, "max": 0, "currency": currency},
            "duration_weeks": 2,
            "prerequisites": [],
            "acceptance_checklist": [
                "Official route (or absence of a direct route) recorded with its source",
                "Next qualification step identified from the official page",
            ],
            "alternatives": [
                "If no route is published for this programme, check the same official source for other programmes at the same university before changing target.",
            ],
            "uncertainty": ("Gaokao scores are never converted to A-level "
                            "grades. If no route is published, the academic "
                            "rule stays UNKNOWN until another accepted "
                            "qualification is supplied."),
        }
    elif kind == "confirm_test":
        task = {
            **base,
            "title": "Confirm the admissions test requirement",
            "rationale": (f"Rule {rule_id} cannot be decided: {detail}"),
            "expected_outcome": ("The test requirement confirmed from the "
                                 "official programme page — whether a test "
                                 "is required and whether a score threshold "
                                 "is published — recorded so the rule can be "
                                 "re-checked."),
            "steps": [
                "Read the official programme page linked below for what the test requirement actually is.",
                "Check whether a score threshold is published; if none is published, record that.",
                "If a test is required, confirm the test date and registration route from the official test provider page.",
            ],
            "resources": [
                _program_resource(program, catalogue),
                {"label": "Official test provider page",
                 "url": None,
                 "search_criteria": "official admissions test registration requirements"},
            ],
            "weekly_hours": _hours(2, weekly_hours),
            "cost_range": {"min": 0, "max": None, "currency": None},
            "duration_weeks": 2,
            "prerequisites": [],
            "acceptance_checklist": [
                "Test requirement (required or not) recorded with its source",
                "Score threshold recorded, or recorded as not published",
            ],
            "alternatives": [
                "If no threshold is published, ask the university admissions office directly and record the reply.",
            ],
            "uncertainty": ("No score threshold is stated in the verified "
                            "sources, so this task can only confirm the "
                            "requirement, not a target score. Test fees are "
                            "not in the verified sources."),
        }
    elif kind == "experience_evidence":
        task = {
            **base,
            "title": "Record existing IT experience for the academic rule",
            "rationale": (f"Rule {rule_id} cannot be decided: {detail}"),
            "expected_outcome": ("The total years of IT experience already "
                                 "held, with the existing evidence for it, "
                                 "supplied so the engine can re-check the "
                                 "rule."),
            "steps": [
                "List IT roles already held, with dates and duties, from existing records.",
                "Gather the existing employment evidence for those roles.",
                "Supply the total years of IT experience in the plan for re-check.",
            ],
            "resources": [
                _program_resource(program, catalogue),
            ],
            "weekly_hours": _hours(3, weekly_hours),
            "cost_range": {"min": 0, "max": 0, "currency": currency},
            "duration_weeks": 4,
            "prerequisites": ["Existing employment records for roles already held"],
            "acceptance_checklist": [
                "IT roles already held listed with dates",
                "Total years of IT experience supplied for re-check",
            ],
            "alternatives": [
                "If no IT experience is held, the academic rule cannot be met through this route; check the official page for the other listed routes.",
            ],
            "uncertainty": ("Only experience already held can be recorded; "
                            "this task does not create new employment. The "
                            "rule stays UNKNOWN until the experience figure "
                            "is supplied."),
        }
    elif kind == "strengthen_margin":
        task = {
            **base,
            "title": "Build margin above the stated minimum",
            "rationale": (f"Competitiveness gap only: {detail} The rule is "
                          f"already MET; this task only adds margin above "
                          f"the minimum."),
            "expected_outcome": ("A score or budget figure above the stated "
                                 "minimum, so the rule has margin when "
                                 "re-checked. Meeting the minimum already "
                                 "satisfies the rule."),
            "steps": [
                "Decide whether extra margin is worth the time before the deadline.",
                "If yes, practise the relevant skill or review the budget for headroom.",
                "Supply the new score or figure for re-check.",
            ],
            "resources": [
                _program_resource(program, catalogue),
                {"label": "Official preparation material",
                 "url": None,
                 "search_criteria": "official preparation material for the stated minimum"},
            ],
            "weekly_hours": _hours(4, weekly_hours),
            "cost_range": {"min": 0, "max": None, "currency": None},
            "duration_weeks": 4,
            "prerequisites": [],
            "acceptance_checklist": [
                "Decision on extra margin recorded",
                "New score or budget figure supplied for re-check, if pursued",
            ],
            "alternatives": [
                "Skip this task: the rule is already MET, so no action is required before the deadline.",
            ],
            "uncertainty": ("Extra margin is optional: the rule is already "
                            "MET. No admission effect is promised."),
        }
    elif kind == "confirm_evidence":
        task = {
            **base,
            "title": f"Supply the missing evidence for {rule_id}",
            "rationale": (f"Rule {rule_id} cannot be decided: {detail}"),
            "expected_outcome": ("The missing score, document or "
                                 "confirmation supplied, so the engine can "
                                 "decide this rule."),
            "steps": [
                "Read the rule detail to see exactly what is missing.",
                "Gather the document or score that the official programme page asks for.",
                "Supply it in the plan so the engine can re-check the rule.",
            ],
            "resources": [
                _program_resource(program, catalogue),
            ],
            "weekly_hours": _hours(2, weekly_hours),
            "cost_range": {"min": 0, "max": 0, "currency": currency},
            "duration_weeks": 2,
            "prerequisites": [],
            "acceptance_checklist": [
                "Missing item identified from the rule detail",
                "Missing score, document or confirmation supplied for re-check",
            ],
            "alternatives": [
                "If the item cannot be supplied before the deadline, record that and keep the rule as UNKNOWN.",
            ],
            "uncertainty": ("Until the missing evidence is supplied, this "
                            "rule stays UNKNOWN."),
        }
    else:  # academic_prep
        task = {
            **base,
            "title": "Prepare for the academic requirement",
            "rationale": f"Rule {rule_id} is not met: {detail}",
            "expected_outcome": ("New qualification evidence that meets the "
                                 "stated academic requirement, supplied so "
                                 "the engine can re-check the rule."),
            "steps": [
                "Read the academic requirement on the official programme page linked below.",
                "List the topics or grades the page states.",
                "Work through the listed topics and record the work completed.",
                "Supply any new qualification evidence for re-check.",
            ],
            "resources": [
                _program_resource(program, catalogue),
            ],
            "weekly_hours": _hours(6, weekly_hours),
            "cost_range": {"min": 0, "max": 0, "currency": currency},
            "duration_weeks": 6,
            "prerequisites": [],
            "acceptance_checklist": [
                "Stated academic requirement listed from the official page",
                "Preparation work completed and recorded",
                "New qualification evidence supplied for re-check, if any",
            ],
            "alternatives": [
                "If the academic requirement cannot be met before the deadline, check the official page for an alternative route it lists.",
            ],
            "uncertainty": ("Preparation alone does not change the rule; "
                            "only new qualification evidence can."),
        }
    note = _finish_note(task["duration_weeks"], deadline, task["alternatives"])
    task["uncertainty"] = f"{task['uncertainty']} {note}".strip()
    task["status"] = "todo"
    return task


def _template_tasks(gap_assessment: dict, programs_by_id: dict,
                    deadline: str | None, weekly_hours: float | None,
                    budget: dict | None, catalogue: list) -> list[dict]:
    return [_template_task(gap, programs_by_id, deadline, weekly_hours,
                           budget, catalogue)
            for gap in gap_assessment.get("gaps", [])]


# ---------------------------------------------------------------------------
# Model path (validated, one repair retry, then templates)
# ---------------------------------------------------------------------------

def _parse_model_json(text: str) -> dict | None:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").strip()
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    try:
        parsed = json.loads(stripped)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _task_text(task: dict) -> str:
    parts = [str(task.get(k) or "") for k in
             ("title", "rationale", "expected_outcome", "uncertainty")]
    parts += [str(s) for s in (task.get("steps") or [])]
    parts += [str(s) for s in (task.get("acceptance_checklist") or [])]
    parts += [str(s) for s in (task.get("alternatives") or [])]
    return "\n".join(parts)


def _validate_model_task(task: dict, gap_by_id: dict, program_ids: list[str],
                         catalogue_urls: set[str],
                         capacity: float | None, budget: dict | None,
                         deadline: str | None) -> list[str]:
    """Validate one model task against the PLAN_SCHEMA contract. Returns
    a list of error strings (empty = valid)."""
    errors: list[str] = []
    if not isinstance(task, dict):
        return ["task is not an object"]
    for field in ("task_id", "gap_id", "category", "title", "rationale",
                  "current_state", "expected_outcome", "uncertainty"):
        if not isinstance(task.get(field), str) or not task[field].strip():
            errors.append(f"task {field!r} must be a non-empty string")
    for field in ("steps", "acceptance_checklist"):
        if (not isinstance(task.get(field), list) or not task[field]
                or not all(isinstance(x, str) and x.strip()
                           for x in task[field])):
            errors.append(f"task {field!r} must be a non-empty list of strings")
    for field in ("prerequisites", "alternatives"):
        if (not isinstance(task.get(field), list)
                or not all(isinstance(x, str) for x in task[field])):
            errors.append(f"task {field!r} must be a list of strings")
    gap = gap_by_id.get(task.get("gap_id") or "")
    if gap is None:
        errors.append(f"task cites unknown gap_id {task.get('gap_id')!r}")
    else:
        if task.get("category") != gap.get("category"):
            errors.append(
                f"task category {task.get('category')!r} does not match "
                f"gap category {gap.get('category')!r}")
    targets = task.get("target_program_ids")
    if (not isinstance(targets, list) or not targets
            or not all(isinstance(p, str) for p in targets)):
        errors.append("task target_program_ids must be a non-empty list of strings")
    elif any(p not in program_ids for p in targets):
        errors.append("task target_program_ids must be a subset of the requested programs")
    elif gap is not None and gap.get("program_id") not in targets:
        errors.append("task target_program_ids must include the gap's program")
    hours = task.get("weekly_hours")
    if not isinstance(hours, (int, float)) or isinstance(hours, bool) or hours < 0:
        errors.append("task weekly_hours must be a non-negative number")
    elif capacity is not None and hours > capacity:
        errors.append(f"task weekly_hours {hours} exceeds capacity {capacity}")
    cost = task.get("cost_range")
    if (not isinstance(cost, dict)
            or not isinstance(cost.get("min"), (int, float, type(None)))
            or not isinstance(cost.get("max"), (int, float, type(None)))):
        errors.append("task cost_range must have numeric min/max (or null)")
    elif (budget and budget.get("amount") is not None
          and cost.get("max") is not None
          and cost["max"] > float(budget["amount"])):
        errors.append("task cost_range max exceeds the stated budget")
    duration = task.get("duration_weeks")
    if not isinstance(duration, int) or isinstance(duration, bool) or duration < 1:
        errors.append("task duration_weeks must be a positive integer")
    elif deadline is not None:
        weeks_left = _weeks_until(deadline)
        if (weeks_left is not None and duration > weeks_left
                and "cannot be finished before the deadline"
                not in _task_text(task).lower()):
            errors.append(
                "task cannot finish before the deadline but does not say so")
    resources = task.get("resources")
    if not isinstance(resources, list):
        errors.append("task resources must be a list")
    else:
        for i, res in enumerate(resources):
            if not isinstance(res, dict) or not isinstance(res.get("label"), str):
                errors.append(f"resources[{i}] must have a string label")
                continue
            url = res.get("url")
            if url is not None and url not in catalogue_urls:
                errors.append(
                    f"resources[{i}] url {url!r} is not in the evidence catalogue")
            if url is None and not res.get("search_criteria"):
                errors.append(
                    f"resources[{i}] has no URL and no search_criteria")
    text = _task_text(task)
    for pat in _FORBIDDEN_RE:
        if pat.search(text):
            errors.append("task contains forbidden admission-probability/guarantee phrasing")
            break
    if _INVENTED_ACTIVITY_RE.search(text):
        errors.append("task mentions an invented activity, job, award or recommendation")
    return errors


def _model_tasks(gap_assessment: dict, evaluations: list[Evaluation],
                 programs: list[dict], deadline: str | None,
                 weekly_hours: float | None, budget: dict | None,
                 locale: str, provider: ProviderAdapter,
                 catalogue: list) -> tuple[list[dict] | None, bool]:
    """Model path. Returns (tasks, model_used). tasks is None only when
    the provider call itself failed; otherwise per-gap template
    replacement keeps every gap covered."""
    program_ids = [p["id"] for p in programs]
    programs_by_id = {p["id"]: p for p in programs}
    gap_by_id = {g["gap_id"]: g for g in gap_assessment.get("gaps", [])}
    catalogue_urls = _catalog_urls(catalogue)
    envelope = {
        "task": "plan",
        "prompt_version": PROMPT_VERSION,
        "locale": locale,
        "gap_assessment": gap_assessment,
        "evaluations": [
            {"program_id": ev.program_id,
             "overall_status": ev.overall_status,
             "results": [{"rule_id": r.rule_id, "status": r.status,
                          "detail": r.detail,
                          "evidence_ids": list(r.evidence_ids)}
                         for r in ev.results]}
            for ev in evaluations],
        "evidence_catalog": [
            {"id": s.id, "url": s.url, "title": s.title, "excerpt": s.excerpt}
            for s in catalogue],
        "deadline": deadline,
        "weekly_hours": weekly_hours,
        "budget": budget,
    }
    messages = [{"role": "user",
                 "content": json.dumps(envelope, ensure_ascii=False)}]

    def _attempt(msgs: list[dict]):
        try:
            result = provider.chat(msgs, system=plan_system(locale),
                                   timeout_s=12.0)
        except ProviderError:
            return None, None
        parsed = _parse_model_json(result.text)
        if parsed is None:
            return None, ["model output was not valid JSON"]
        tasks = parsed.get("tasks")
        if not isinstance(tasks, list):
            return None, ["model output has no tasks list"]
        return tasks, None

    raw_tasks, errors = _attempt(messages)
    if raw_tasks is None:
        if errors is None:
            return None, False  # provider call failed -> templates
        # One repair retry on a validation failure.
        repair = ("Your previous output failed validation. Fix ONLY these "
                  f"problems and output JSON only: {'; '.join(errors)}\n\n"
                  f"Previous output:\n{json.dumps({'tasks': []})}")
        raw_tasks, errors2 = _attempt(
            messages + [{"role": "user", "content": repair}])
        if raw_tasks is None:
            return _template_tasks(gap_assessment, programs_by_id, deadline,
                                   weekly_hours, budget, catalogue), False

    seen_ids: set[str] = set()
    kept: list[dict] = []
    covered: set[str] = set()
    model_used = False
    for raw in raw_tasks:
        errs = _validate_model_task(raw, gap_by_id, program_ids,
                                    catalogue_urls, weekly_hours, budget,
                                    deadline)
        if errs:
            # Drop the invalid task; the template for its gap (if known)
            # is added in the coverage pass below.
            continue
        task = copy.deepcopy(raw)
        if task["task_id"] in seen_ids:
            task["task_id"] = f"{task['task_id']}-{len(seen_ids)}"
        seen_ids.add(task["task_id"])
        task.setdefault("status", "todo")
        task["deadline"] = deadline
        kept.append(task)
        covered.add(task["gap_id"])
        model_used = True
    for gap in gap_assessment.get("gaps", []):
        if gap["gap_id"] not in covered:
            kept.append(_template_task(gap, programs_by_id, deadline,
                                       weekly_hours, budget, catalogue))
    return kept, model_used


def build_tasks_with_status(gap_assessment: dict,
                            evaluations: list[Evaluation],
                            programs: list[dict],
                            deadline: str | None,
                            weekly_hours: float | None,
                            budget: dict | None,
                            locale: str,
                            provider: ProviderAdapter | None) -> tuple[list[dict], str, list[str], list[str]]:
    """Returns (tasks, ai_status, assumptions, limitations)."""
    program_ids = [p["id"] for p in programs]
    programs_by_id = {p["id"]: p for p in programs}
    catalogue = _evidence_catalog(program_ids)
    assumptions = [
        "Completing a task does not change eligibility; a rule status changes only when new scores or evidence are confirmed and recomputed by the engine.",
        "Weekly hours for every task fit the stated capacity; tasks are scheduled so the hours in any one week stay within that capacity.",
        "Costs are 0 unless a cost range states otherwise; test fees are not in the verified sources, so any task involving a test states its cost as unknown.",
    ]
    limitations = [
        "This plan is based only on the engine's rule results and the verified sources in the evidence catalogue; no admission effect is promised and no percentage improvement is given.",
        "Tasks use only URLs from the evidence catalogue; where no verified resource exists, the task gives search criteria instead of a link.",
        "Unknown rules stay unknown until the missing evidence is supplied.",
    ]
    if provider is None or not provider.available:
        tasks = _template_tasks(gap_assessment, programs_by_id, deadline,
                                weekly_hours, budget, catalogue)
        assumptions.insert(
            0, "No AI provider is configured, so these tasks are deterministic templates built from the gap assessment, not model-generated text.")
        return tasks, "unavailable", assumptions, limitations
    tasks, model_used = _model_tasks(
        gap_assessment, evaluations, programs, deadline, weekly_hours,
        budget, locale, provider, catalogue)
    if tasks is None:
        tasks = _template_tasks(gap_assessment, programs_by_id, deadline,
                                weekly_hours, budget, catalogue)
        assumptions.insert(
            0, "The AI provider call failed, so these tasks are deterministic templates built from the gap assessment.")
        return tasks, "unavailable", assumptions, limitations
    if not model_used:
        assumptions.insert(
            0, "The model output did not pass validation, so these tasks are deterministic templates built from the gap assessment.")
        return tasks, "unavailable", assumptions, limitations
    return tasks, "available", assumptions, limitations


def build_tasks(gap_assessment: dict, evaluations: list[Evaluation],
                programs: list[dict], deadline: str | None,
                weekly_hours: float | None, budget: dict | None,
                locale: str, provider: ProviderAdapter | None) -> list[dict]:
    """Task list for a gap assessment (model path when a provider is
    configured, deterministic templates otherwise)."""
    tasks, _, _, _ = build_tasks_with_status(
        gap_assessment, evaluations, programs, deadline, weekly_hours,
        budget, locale, provider)
    return tasks


# ---------------------------------------------------------------------------
# Weekly schedule (stagger tasks so no week's hours exceed capacity)
# ---------------------------------------------------------------------------

def build_weekly_schedule(tasks: list[dict],
                          capacity: float | None) -> dict:
    """Group tasks by week 1..N with hours per week.

    Each task starts at the earliest week where its whole duration fits
    without any week's concurrent hours exceeding capacity. With no
    capacity stated, every task starts in week 1.
    """
    if not tasks:
        return {"weeks": [], "total_weeks": 0}
    load: dict[int, float] = {}
    placement: list[dict] = []
    for task in tasks:
        hours = float(task.get("weekly_hours") or 0)
        duration = int(task.get("duration_weeks") or 1)
        start = 1
        if capacity is not None and hours > 0:
            while any(load.get(w, 0.0) + hours > capacity
                      for w in range(start, start + duration)):
                start += 1
        for w in range(start, start + duration):
            load[w] = load.get(w, 0.0) + hours
        placement.append({"task_id": task["task_id"], "start_week": start,
                          "duration_weeks": duration,
                          "weekly_hours": hours})
    total = max(load) if load else 0
    weeks = []
    for w in range(1, total + 1):
        active = [p for p in placement
                  if p["start_week"] <= w < p["start_week"] + p["duration_weeks"]]
        weeks.append({"week": w,
                      "task_ids": [p["task_id"] for p in active],
                      "weekly_hours": round(load.get(w, 0.0), 2)})
    return {"weeks": weeks, "total_weeks": total}


# ---------------------------------------------------------------------------
# Plan creation / storage
# ---------------------------------------------------------------------------

def evaluate_programs(profile: StudentProfile,
                      program_ids: list[str]) -> list[Evaluation]:
    """Recompute evaluations the same way the app does (engine only,
    ai_status always 'unavailable' here — plans never claim a model
    verdict)."""
    evaluations = []
    for pid in program_ids:
        program = PROGRAMS[pid]
        results = evaluate(profile, program)
        evaluations.append(Evaluation(
            program_id=pid, data_version=DATA_VERSION,
            overall_status=overall_status(results), results=results,
            ai_status="unavailable"))
    return evaluations


def _evaluation_snapshot(evaluations: list[Evaluation]) -> list[dict]:
    return [{"program_id": ev.program_id,
             "overall_status": ev.overall_status,
             "results": [{"rule_id": r.rule_id, "status": r.status}
                         for r in ev.results]}
            for ev in evaluations]


def create_plan(profile: StudentProfile, evaluations: list[Evaluation],
                programs: list[dict], deadline: str | None,
                weekly_hours: float | None, budget: dict | None,
                locale: str,
                provider: ProviderAdapter | None) -> dict:
    """Diagnose gaps, build tasks, store the plan, return it."""
    gap_assessment = diagnose_gaps(profile, evaluations, deadline,
                                   weekly_hours, budget)
    tasks, ai_status, assumptions, limitations = build_tasks_with_status(
        gap_assessment, evaluations, programs, deadline, weekly_hours,
        budget, locale, provider)
    plan_id = f"plan-{secrets.token_hex(4)}"
    created_at = _now_iso()
    program_ids = [p["id"] for p in programs]
    plan: dict = {
        "plan_id": plan_id,
        "created_at": created_at,
        "profile": profile.model_dump(mode="json"),
        "program_ids": program_ids,
        "track": profile.application_track,
        "deadline": deadline,
        "weekly_hours": weekly_hours,
        "budget": budget,
        "locale": locale,
        "gap_assessment": gap_assessment,
        "tasks": tasks,
        "weekly_schedule": build_weekly_schedule(tasks, weekly_hours),
        "assumptions": assumptions,
        "limitations": limitations,
        "ai_status": ai_status,
        "evaluations": _evaluation_snapshot(evaluations),
        "versions": [{
            "version": 1,
            "reason": "created",
            "created_at": created_at,
            "gap_assessment": copy.deepcopy(gap_assessment),
            "tasks": tasks,
        }],
    }
    PLANS[plan_id] = plan
    return copy.deepcopy(plan)


def get_plan(plan_id: str) -> dict:
    plan = PLANS.get(plan_id)
    if plan is None:
        raise PlanNotFound(plan_id)
    return copy.deepcopy(plan)


# ---------------------------------------------------------------------------
# Task status
# ---------------------------------------------------------------------------

def update_task_status(plan_id: str, task_id: str, status: str,
                       user_confirmed_evidence: str | None = None) -> dict:
    """Move a task. Completing a task changes no rule status: evidence
    supplied here is recorded as a user statement only, never as proof."""
    plan = PLANS.get(plan_id)
    if plan is None:
        raise PlanNotFound(plan_id)
    if status not in TASK_STATUSES:
        raise PlanError(
            f"Unknown task status {status!r}; must be one of "
            f"{list(TASK_STATUSES)}.",
            code="VALIDATION_ERROR", status=422)
    task = next((t for t in plan["tasks"] if t.get("task_id") == task_id), None)
    if task is None:
        raise TaskNotFound(task_id)
    current = task.get("status", "todo")
    if status not in _ALLOWED_TRANSITIONS.get(current, set()):
        raise IllegalTransition(task_id, current, status)
    task["status"] = status
    if user_confirmed_evidence is not None:
        task["user_confirmed_evidence"] = {
            "statement": user_confirmed_evidence,
            "note": ("User statement only. It is not verified evidence and "
                     "does not change any rule status; only a reassessment "
                     "recomputed by the engine can do that."),
        }
    return copy.deepcopy(task)


# ---------------------------------------------------------------------------
# Reassessment (engine recompute only — never a client verdict)
# ---------------------------------------------------------------------------

_PROFILE_FIELDS = set(StudentProfile.model_fields)
_NESTED_FIELDS: dict[str, set[str]] = {
    "undergrad_profile": set(UndergradProfile.model_fields),
    "masters_profile": set(MastersProfile.model_fields),
    "language": set(Language.model_fields),
    "budget": set(Budget.model_fields),
}


def _validate_patch_keys(patch: dict) -> None:
    """Reject unknown fields (pydantic would silently ignore them)."""
    if not isinstance(patch, dict):
        raise InvalidPatch("profile_patch must be an object")
    for key, value in patch.items():
        if key not in _PROFILE_FIELDS:
            raise InvalidPatch(f"Unknown profile field {key!r} in profile_patch")
        if isinstance(value, dict) and key in _NESTED_FIELDS:
            for sub in value:
                if sub not in _NESTED_FIELDS[key]:
                    raise InvalidPatch(
                        f"Unknown field {sub!r} in profile_patch.{key}")


def _deep_merge(base: dict, patch: dict) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def reassess(plan_id: str, profile_patch: dict) -> dict:
    """Recompute the plan's evaluations from a profile patch.

    The patch is merged into the stored profile and validated as a
    StudentProfile; only the engine's recompute counts. A new version is
    appended when anything changed; old versions are kept. An empty patch
    returns no change and appends nothing.
    """
    plan = PLANS.get(plan_id)
    if plan is None:
        raise PlanNotFound(plan_id)
    current_version = plan["versions"][-1]["version"]
    current_gaps = plan["gap_assessment"].get("gaps", [])
    unknowns = [g["gap_id"] for g in current_gaps
                if g.get("evidence_class") == "to_confirm"]

    def _no_change(note: str, changes: list | None = None) -> dict:
        return {"plan_id": plan_id, "new_version": current_version,
                "changes": changes or [], "remaining_gaps": copy.deepcopy(current_gaps),
                "unknowns": unknowns, "note": note}

    if not profile_patch:
        return _no_change(
            "No changes: the profile patch was empty, so no evaluation "
            "was recomputed.")
    _validate_patch_keys(profile_patch)
    merged = copy.deepcopy(plan["profile"])
    _deep_merge(merged, profile_patch)
    try:
        profile = StudentProfile(**merged)
    except Exception as exc:
        raise InvalidPatch(f"Patched profile is invalid: {exc}")
    programs = [PROGRAMS[pid] for pid in plan["program_ids"]]
    evaluations = evaluate_programs(profile, plan["program_ids"])
    new_snapshot = _evaluation_snapshot(evaluations)
    old_by_key = {(e["program_id"], r["rule_id"]): r["status"]
                  for e in plan["evaluations"] for r in e["results"]}
    changes = []
    for ev in new_snapshot:
        for r in ev["results"]:
            old = old_by_key.get((ev["program_id"], r["rule_id"]))
            if old is not None and old != r["status"]:
                changes.append({"program_id": ev["program_id"],
                                "rule_id": r["rule_id"],
                                "old_status": old,
                                "new_status": r["status"]})
    new_gap_assessment = diagnose_gaps(
        profile, evaluations, plan.get("deadline"), plan.get("weekly_hours"),
        plan.get("budget"))
    new_gaps = new_gap_assessment.get("gaps", [])
    gaps_same = ([(g["gap_id"], g["evidence_class"]) for g in new_gaps]
                 == [(g["gap_id"], g["evidence_class"]) for g in current_gaps])
    if not changes and gaps_same:
        return _no_change(
            "No changes: the patch did not change any rule status or gap.",
            changes=[])
    # New version: template tasks for the new gaps, preserving the status
    # of tasks that survive (same task_id) from the previous version.
    old_tasks = {t["task_id"]: t for t in plan["tasks"]}
    catalogue = _evidence_catalog(plan["program_ids"])
    programs_by_id = {p["id"]: p for p in programs}
    new_tasks = _template_tasks(new_gap_assessment, programs_by_id,
                                plan.get("deadline"), plan.get("weekly_hours"),
                                plan.get("budget"), catalogue)
    for task in new_tasks:
        old = old_tasks.get(task["task_id"])
        if old is not None:
            task["status"] = old.get("status", "todo")
            if "user_confirmed_evidence" in old:
                task["user_confirmed_evidence"] = old["user_confirmed_evidence"]
    new_version = current_version + 1
    plan["profile"] = profile.model_dump(mode="json")
    plan["gap_assessment"] = new_gap_assessment
    plan["tasks"] = new_tasks
    plan["weekly_schedule"] = build_weekly_schedule(
        new_tasks, plan.get("weekly_hours"))
    plan["evaluations"] = new_snapshot
    plan["versions"].append({
        "version": new_version,
        "reason": "reassessment",
        "created_at": _now_iso(),
        "gap_assessment": copy.deepcopy(new_gap_assessment),
        "tasks": new_tasks,
    })
    new_unknowns = [g["gap_id"] for g in new_gaps
                    if g.get("evidence_class") == "to_confirm"]
    note = (f"Reassessment recomputed {len(plan['program_ids'])} programme(s): "
            f"{len(changes)} rule(s) changed, {len(new_gaps)} gap(s) remain, "
            f"including {len(new_unknowns)} to confirm. Task completion "
            f"alone never changes a rule; only the engine recompute above "
            f"counts.")
    return {"plan_id": plan_id, "new_version": new_version,
            "changes": changes,
            "remaining_gaps": copy.deepcopy(new_gaps),
            "unknowns": new_unknowns, "note": note}

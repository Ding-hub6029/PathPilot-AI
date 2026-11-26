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
from app.data import DATA_VERSION, EXPANSION_MATCHABLE, EXPANSION_PROGRAMS, PROGRAMS
from app.schemas import (
    Budget,
    Evaluation,
    Language,
    MastersProfile,
    StudentProfile,
    UndergradProfile,
)
from domain.eligibility import evaluate, overall_status
from domain.expansion_eval import evaluate_expansion

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


class ProgramNotEvaluable(PlanError):
    """Display-only expansion programme: it has no evaluable rule
    (fee / language / academic threshold) in the verified sources, so
    no plan can be generated from it. Unknown stays unknown — a plan
    must never be invented from nothing."""

    def __init__(self, program_id: str) -> None:
        super().__init__(
            f"Program '{program_id}' is display-only: no evaluable rule "
            f"is published for it in the verified sources, so no "
            f"improvement plan can be generated.",
            code="PROGRAM_NOT_EVALUABLE", status=422)


def resolve_program(program_id: str) -> dict | None:
    """One programme resolution for plans: the 8 v2 programmes first,
    then matchable expansion programmes. Display-only expansion
    programmes and unknown ids are None (callers distinguish them
    with program_is_display_only)."""
    if program_id in PROGRAMS:
        return PROGRAMS[program_id]
    return EXPANSION_MATCHABLE.get(program_id)


def program_is_display_only(program_id: str) -> bool:
    """True when the id exists in the expansion catalogue but is not
    matchable (no evaluable rule / no wizard track). Matchable
    expansion programmes are NOT display-only."""
    return (program_id not in PROGRAMS
            and program_id in EXPANSION_PROGRAMS
            and program_id not in EXPANSION_MATCHABLE)


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
# Localised template strings (Round 14)
#
# The deterministic template tasks, gap texts, assumptions and limitations
# render in the requested locale (all 6). Engine-computed data — rule ids,
# rule detail text, thresholds, observed values, programme names, URLs —
# is inserted unchanged; only the surrounding human-readable prose is
# translated. Search criteria stay in English: they are search queries,
# not prose. An unknown locale falls back to English. ``locale="en"``
# keeps every existing caller and test unchanged.
# ---------------------------------------------------------------------------

_PLAN_STRINGS = {
    "en": {
        "gap.not_met": ("Stated minimum not met. Threshold: {thr}; observed: "
                        "{obs}. Supply new scores or evidence that meet the "
                        "stated minimum so the engine can re-check this rule."),
        "gap.unknown": ("Cannot be decided from the supplied evidence. "
                        "Supply the missing score, document or confirmation "
                        "the official programme page asks for, so the engine "
                        "can decide this rule."),
        "gap.competitiveness": ("Competitiveness gap only: the rule is MET, "
                                "but {reason}, so there is little margin above "
                                "the stated minimum. Extra margin is optional "
                                "and is not required to satisfy the rule."),
        "barely.fee": "budget is within 10% of the fee ({obs} against a fee of {fee})",
        "barely.overall": "IELTS overall is exactly at the minimum ({obs})",
        "barely.components": "IELTS component(s) exactly at the minimum ({comps} at {each})",
        "barely.component": "IELTS {comp} is exactly at the minimum ({val})",
        "finish.none": ("No deadline was given, so no finish-by date is set "
                        "for this task."),
        "finish.too_long": ("This task needs {dur} weeks but only {left} week(s) "
                            "remain before the deadline ({deadline}), so it cannot "
                            "be finished before the deadline. Use the short-term "
                            "alternative below for the remaining time."),
        "finish.fits": ("{left} week(s) remain before the deadline ({deadline}); "
                        "this task needs {dur} week(s)."),
        "res.program": "Official requirements — {name}",
        "res.program_fallback": "Official programme page",
        "res.gaokao": "Verified Gaokao route facts — {title}",
        "res.gaokao_fallback": "Gaokao entry route (official university page)",
        "res.ielts_writing": "IELTS official writing practice materials",
        "res.ielts_general": "IELTS official practice materials",
        "res.funding": "Funding options for international students",
        "res.test_provider": "Official test provider page",
        "res.prep": "Official preparation material",
        "comp.listening": "listening",
        "comp.reading": "reading",
        "comp.writing": "writing",
        "comp.speaking": "speaking",
        "task.ielts_writing.title": "Raise IELTS writing to the stated minimum",
        "task.ielts_writing.rationale": ("Rule {rule_id} is not met: {detail} Writing is "
                                        "the component below the minimum."),
        "task.ielts_writing.expected": ("A new IELTS writing score at or above the "
                                       "stated minimum, supplied for re-check by "
                                       "the engine."),
        "task.ielts_writing.steps": [
            "Take one timed IELTS writing task (Task 1 and Task 2) under exam timing.",
            "Compare the attempt with the public IELTS band descriptors for writing and list the specific errors.",
            "Rewrite the weakest paragraph, fixing the listed errors.",
            "Repeat with a fresh timed task; book an IELTS test date only after a timed attempt meets the minimum on self-check.",
        ],
        "task.ielts_writing.prerequisites": [
            "Access to IELTS writing practice material found via the search criteria below",
        ],
        "task.ielts_writing.acceptance": [
            "Timed writing attempt completed and compared with the band descriptors",
            "Errors from the attempt listed and corrected in a rewrite",
            "New IELTS writing score supplied for re-check",
        ],
        "task.ielts_writing.alternatives": [
            "If little time remains, use the remaining time for one timed writing task per day instead of general study.",
        ],
        "task.ielts_writing.uncertainty": ("Practice alone does not change the rule; only a "
                                          "new test score can. The cost and availability of "
                                          "a test sitting are not in the verified sources; "
                                          "check the official test provider page."),
        "task.ielts_general.title": "Raise IELTS overall to the stated minimum",
        "task.ielts_general.rationale": "Rule {rule_id} is not met: {detail}",
        "task.ielts_general.expected": ("A new IELTS overall score at or above the "
                                       "stated minimum, supplied for re-check by "
                                       "the engine."),
        "task.ielts_general.steps": [
            "Take one timed IELTS practice test and record the score for each section.",
            "Practise the lowest-scoring section daily, using official practice material.",
            "Retake a timed practice test and compare the section scores with the previous attempt.",
            "Book an IELTS test date only after a timed practice attempt meets the minimum on self-check.",
        ],
        "task.ielts_general.prerequisites": [
            "Access to IELTS practice material found via the search criteria below",
        ],
        "task.ielts_general.acceptance": [
            "Timed practice test completed with section scores recorded",
            "Lowest-scoring section practised and re-tested",
            "New IELTS overall score supplied for re-check",
        ],
        "task.ielts_general.alternatives": [
            "If little time remains, focus the remaining time on the lowest-scoring section only.",
        ],
        "task.ielts_general.uncertainty": ("Practice alone does not change the rule; only a "
                                          "new test score can. The cost and availability of "
                                          "a test sitting are not in the verified sources."),
        "task.budget.title": "Close the budget gap for the target programme fee",
        "task.budget.rationale": "Rule {rule_id} is not met: {detail}",
        "task.budget.expected": ("A revised budget figure that meets the "
                                 "published fee, or a decision to target a "
                                 "programme whose fee fits the current "
                                 "budget, so the fee rule can be re-checked."),
        "task.budget.steps": [
            "Write down the published fee from the official programme page linked below.",
            "List the funding already available and the exact shortfall.",
            "Search for funding options using the criteria below and record what each option actually covers.",
            "Update the budget figure in the plan only with amounts that are confirmed.",
        ],
        "task.budget.prerequisites": [],
        "task.budget.acceptance": [
            "Shortfall amount recorded",
            "Funding options checked and recorded with what they cover",
            "Revised budget figure supplied, or a different target programme chosen",
        ],
        "task.budget.alternatives": [
            "If the fee cannot be met, compare the fees of the other target programmes in this plan and pick one that fits the current budget.",
        ],
        "task.budget.uncertainty": ("No funding amount is promised here; funding "
                                    "availability and amounts are not in the verified "
                                    "sources."),
        "task.gaokao_route.title": "Clarify the Gaokao route for the target programme",
        "task.gaokao_route.rationale": "Rule {rule_id} cannot be decided: {detail}",
        "task.gaokao_route.expected": ("A route confirmed from an official source "
                                       "(for example a foundation route or another "
                                       "accepted qualification), recorded with its "
                                       "evidence, so the academic rule can be "
                                       "re-checked."),
        "task.gaokao_route.steps": [
            "Read the verified Gaokao facts supplied for this programme.",
            "Check the official page linked in the resources for the routes the university does publish.",
            "If no direct Gaokao route is published, check whether the university publishes a foundation route and its requirements.",
            "Record the chosen route and the evidence for it in the plan.",
        ],
        "task.gaokao_route.prerequisites": [],
        "task.gaokao_route.acceptance": [
            "Official route (or absence of a direct route) recorded with its source",
            "Next qualification step identified from the official page",
        ],
        "task.gaokao_route.alternatives": [
            "If no route is published for this programme, check the same official source for other programmes at the same university before changing target.",
        ],
        "task.gaokao_route.uncertainty": ("Gaokao scores are never converted to A-level "
                                          "grades. If no route is published, the academic "
                                          "rule stays UNKNOWN until another accepted "
                                          "qualification is supplied."),
        "task.confirm_test.title": "Confirm the admissions test requirement",
        "task.confirm_test.rationale": "Rule {rule_id} cannot be decided: {detail}",
        "task.confirm_test.expected": ("The test requirement confirmed from the "
                                       "official programme page — whether a test "
                                       "is required and whether a score threshold "
                                       "is published — recorded so the rule can be "
                                       "re-checked."),
        "task.confirm_test.steps": [
            "Read the official programme page linked below for what the test requirement actually is.",
            "Check whether a score threshold is published; if none is published, record that.",
            "If a test is required, confirm the test date and registration route from the official test provider page.",
        ],
        "task.confirm_test.prerequisites": [],
        "task.confirm_test.acceptance": [
            "Test requirement (required or not) recorded with its source",
            "Score threshold recorded, or recorded as not published",
        ],
        "task.confirm_test.alternatives": [
            "If no threshold is published, ask the university admissions office directly and record the reply.",
        ],
        "task.confirm_test.uncertainty": ("No score threshold is stated in the verified "
                                          "sources, so this task can only confirm the "
                                          "requirement, not a target score. Test fees are "
                                          "not in the verified sources."),
        "task.experience_evidence.title": "Record existing IT experience for the academic rule",
        "task.experience_evidence.rationale": "Rule {rule_id} cannot be decided: {detail}",
        "task.experience_evidence.expected": ("The total years of IT experience already "
                                              "held, with the existing evidence for it, "
                                              "supplied so the engine can re-check the "
                                              "rule."),
        "task.experience_evidence.steps": [
            "List IT roles already held, with dates and duties, from existing records.",
            "Gather the existing employment evidence for those roles.",
            "Supply the total years of IT experience in the plan for re-check.",
        ],
        "task.experience_evidence.prerequisites": [
            "Existing employment records for roles already held",
        ],
        "task.experience_evidence.acceptance": [
            "IT roles already held listed with dates",
            "Total years of IT experience supplied for re-check",
        ],
        "task.experience_evidence.alternatives": [
            "If no IT experience is held, the academic rule cannot be met through this route; check the official page for the other listed routes.",
        ],
        "task.experience_evidence.uncertainty": ("Only experience already held can be recorded; "
                                                "this task does not create new employment. The "
                                                "rule stays UNKNOWN until the experience figure "
                                                "is supplied."),
        "task.strengthen_margin.title": "Build margin above the stated minimum",
        "task.strengthen_margin.rationale": ("Competitiveness gap only: {detail} The rule is "
                                            "already MET; this task only adds margin above "
                                            "the minimum."),
        "task.strengthen_margin.expected": ("A score or budget figure above the stated "
                                           "minimum, so the rule has margin when "
                                           "re-checked. Meeting the minimum already "
                                           "satisfies the rule."),
        "task.strengthen_margin.steps": [
            "Decide whether extra margin is worth the time before the deadline.",
            "If yes, practise the relevant skill or review the budget for headroom.",
            "Supply the new score or figure for re-check.",
        ],
        "task.strengthen_margin.prerequisites": [],
        "task.strengthen_margin.acceptance": [
            "Decision on extra margin recorded",
            "New score or budget figure supplied for re-check, if pursued",
        ],
        "task.strengthen_margin.alternatives": [
            "Skip this task: the rule is already MET, so no action is required before the deadline.",
        ],
        "task.strengthen_margin.uncertainty": ("Extra margin is optional: the rule is already "
                                              "MET. No admission effect is promised."),
        "task.confirm_evidence.title": "Supply the missing evidence for {rule_id}",
        "task.confirm_evidence.rationale": "Rule {rule_id} cannot be decided: {detail}",
        "task.confirm_evidence.expected": ("The missing score, document or "
                                           "confirmation supplied, so the engine can "
                                           "decide this rule."),
        "task.confirm_evidence.steps": [
            "Read the rule detail to see exactly what is missing.",
            "Gather the document or score that the official programme page asks for.",
            "Supply it in the plan so the engine can re-check the rule.",
        ],
        "task.confirm_evidence.prerequisites": [],
        "task.confirm_evidence.acceptance": [
            "Missing item identified from the rule detail",
            "Missing score, document or confirmation supplied for re-check",
        ],
        "task.confirm_evidence.alternatives": [
            "If the item cannot be supplied before the deadline, record that and keep the rule as UNKNOWN.",
        ],
        "task.confirm_evidence.uncertainty": ("Until the missing evidence is supplied, this "
                                              "rule stays UNKNOWN."),
        "task.academic_prep.title": "Prepare for the academic requirement",
        "task.academic_prep.rationale": "Rule {rule_id} is not met: {detail}",
        "task.academic_prep.expected": ("New qualification evidence that meets the "
                                        "stated academic requirement, supplied so "
                                        "the engine can re-check the rule."),
        "task.academic_prep.steps": [
            "Read the academic requirement on the official programme page linked below.",
            "List the topics or grades the page states.",
            "Work through the listed topics and record the work completed.",
            "Supply any new qualification evidence for re-check.",
        ],
        "task.academic_prep.prerequisites": [],
        "task.academic_prep.acceptance": [
            "Stated academic requirement listed from the official page",
            "Preparation work completed and recorded",
            "New qualification evidence supplied for re-check, if any",
        ],
        "task.academic_prep.alternatives": [
            "If the academic requirement cannot be met before the deadline, check the official page for an alternative route it lists.",
        ],
        "task.academic_prep.uncertainty": ("Preparation alone does not change the rule; "
                                           "only new qualification evidence can."),
        "assume.complete": ("Completing a task does not change eligibility; a rule status changes only when new scores or evidence are confirmed and recomputed by the engine."),
        "assume.hours": ("Weekly hours for every task fit the stated capacity; tasks are scheduled so the hours in any one week stay within that capacity."),
        "assume.cost": ("Costs are 0 unless a cost range states otherwise; test fees are not in the verified sources, so any task involving a test states its cost as unknown."),
        "assume.no_provider": ("No AI provider is configured, so these tasks are deterministic templates built from the gap assessment, not model-generated text."),
        "assume.provider_failed": ("The AI provider call failed, so these tasks are deterministic templates built from the gap assessment."),
        "assume.validation_failed": ("The model output did not pass validation, so these tasks are deterministic templates built from the gap assessment."),
        "limit.based_only": ("This plan is based only on the engine's rule results and the verified sources in the evidence catalogue; no admission effect is promised and no percentage improvement is given."),
        "limit.urls": ("Tasks use only URLs from the evidence catalogue; where no verified resource exists, the task gives search criteria instead of a link."),
        "limit.unknown": "Unknown rules stay unknown until the missing evidence is supplied.",
        "reassess.empty_patch": "No changes: the profile patch was empty, so no evaluation was recomputed.",
        "reassess.no_change": "No changes: the patch did not change any rule status or gap.",
        "reassess.note": ("Reassessment recomputed {n_programs} programme(s): "
                          "{n_changes} rule(s) changed, {n_gaps} gap(s) remain, "
                          "including {n_unknowns} to confirm. Task completion "
                          "alone never changes a rule; only the engine recompute above "
                          "counts."),
        "task.user_statement_note": ("User statement only. It is not verified evidence and "
                                     "does not change any rule status; only a reassessment "
                                     "recomputed by the engine can do that."),
    },
    "zh-CN": {
        "gap.not_met": ("未达到规定的最低要求。最低要求：{thr}；你的情况：{obs}。"
                        "请提供符合最低要求的新分数或证明，以便引擎重新核查此规则。"),
        "gap.unknown": ("根据现有证据无法判定。请提供官方项目页面所要求的缺失分数、"
                        "文件或确认，以便引擎判定此规则。"),
        "gap.competitiveness": ("仅为竞争力差距：该规则已达标，但{reason}，因此高于最低要求"
                                "的余量很小。增加余量是可选的，并非满足该规则所必需。"),
        "barely.fee": "预算在学费的 10% 以内（{obs}，学费为 {fee}）",
        "barely.overall": "雅思总分恰好为最低要求（{obs}）",
        "barely.components": "雅思单项恰好为最低要求（{comps} 为 {each}）",
        "barely.component": "雅思{comp}恰好为最低要求（{val}）",
        "finish.none": "未提供截止日期，因此此任务没有设定完成日期。",
        "finish.too_long": ("此任务需要 {dur} 周，但距离截止日期（{deadline}）只剩 {left} 周，"
                            "因此无法在截止日期前完成。请在剩余时间内使用下面的短期替代方案。"),
        "finish.fits": "距离截止日期（{deadline}）还剩 {left} 周；此任务需要 {dur} 周。",
        "res.program": "官方要求——{name}",
        "res.program_fallback": "官方项目页面",
        "res.gaokao": "已核实的高考入学路径事实——{title}",
        "res.gaokao_fallback": "高考入学路径（大学官网页面）",
        "res.ielts_writing": "雅思官方写作练习材料",
        "res.ielts_general": "雅思官方练习材料",
        "res.funding": "国际学生资助选项",
        "res.test_provider": "官方考试机构页面",
        "res.prep": "官方备考材料",
        "comp.listening": "听力",
        "comp.reading": "阅读",
        "comp.writing": "写作",
        "comp.speaking": "口语",
        "task.ielts_writing.title": "将雅思写作提高到规定的最低要求",
        "task.ielts_writing.rationale": "规则 {rule_id} 未达标：{detail}写作是低于最低要求的单项。",
        "task.ielts_writing.expected": "新的雅思写作分数达到或高于规定的最低要求，并已提交以便引擎重新核查。",
        "task.ielts_writing.steps": [
            "在考试时间限制内完成一次雅思写作任务（小作文和大作文）。",
            "对照公开的雅思写作评分标准，比较本次练习并列出具体错误。",
            "重写最薄弱的段落，改正列出的错误。",
            "用新的限时任务重复练习；只有在限时自测达到最低要求后，再预约雅思考试。",
        ],
        "task.ielts_writing.prerequisites": [
            "可通过下面的搜索条件找到雅思写作练习材料",
        ],
        "task.ielts_writing.acceptance": [
            "已完成限时写作练习并对照评分标准进行了比较",
            "已列出练习中的错误并在重写中改正",
            "已提交新的雅思写作分数以便重新核查",
        ],
        "task.ielts_writing.alternatives": [
            "如果剩余时间不多，请把剩余时间用于每天完成一次限时写作任务，而不是泛泛学习。",
        ],
        "task.ielts_writing.uncertainty": ("只练习不会改变规则；只有新的考试分数才能改变。考试费用和考位情况"
                                          "不在已核实的信息来源中；请查看官方考试机构页面。"),
        "task.ielts_general.title": "将雅思总分提高到规定的最低要求",
        "task.ielts_general.rationale": "规则 {rule_id} 未达标：{detail}",
        "task.ielts_general.expected": "新的雅思总分达到或高于规定的最低要求，并已提交以便引擎重新核查。",
        "task.ielts_general.steps": [
            "完成一次限时雅思模拟考试，记录每一部分的分数。",
            "每天练习得分最低的部分，使用官方练习材料。",
            "再次参加限时模拟考试，并与上一次的各部分分数比较。",
            "只有在限时模拟自测达到最低要求后，再预约雅思考试。",
        ],
        "task.ielts_general.prerequisites": [
            "可通过下面的搜索条件找到雅思练习材料",
        ],
        "task.ielts_general.acceptance": [
            "已完成限时模拟考试并记录各部分分数",
            "已练习得分最低的部分并重新测试",
            "已提交新的雅思总分以便重新核查",
        ],
        "task.ielts_general.alternatives": [
            "如果剩余时间不多，请把剩余时间只用于得分最低的部分。",
        ],
        "task.ielts_general.uncertainty": ("只练习不会改变规则；只有新的考试分数才能改变。考试费用和考位情况"
                                          "不在已核实的信息来源中。"),
        "task.budget.title": "补足目标项目的学费预算缺口",
        "task.budget.rationale": "规则 {rule_id} 未达标：{detail}",
        "task.budget.expected": ("修改后的预算金额达到已公布的学费，或者决定改选学费符合当前预算"
                                 "的项目，以便重新核查学费规则。"),
        "task.budget.steps": [
            "记下下面链接的官方项目页面上公布的学费。",
            "列出已有资金和确切的缺口金额。",
            "按下面的条件搜索资助选项，并记录每个选项实际涵盖的内容。",
            "只用已确认的金额更新计划中的预算数字。",
        ],
        "task.budget.prerequisites": [],
        "task.budget.acceptance": [
            "已记录缺口金额",
            "已核查资助选项并记录各自涵盖的内容",
            "已提供修改后的预算金额，或已改选其他目标项目",
        ],
        "task.budget.alternatives": [
            "如果无法负担该学费，请比较本计划中其他目标项目的学费，选择一个符合当前预算的项目。",
        ],
        "task.budget.uncertainty": "此处不承诺任何资助金额；是否有资助及具体金额不在已核实的信息来源中。",
        "task.gaokao_route.title": "确认目标项目的高考入学路径",
        "task.gaokao_route.rationale": "规则 {rule_id} 无法判定：{detail}",
        "task.gaokao_route.expected": ("已通过官方来源确认入学路径（例如预科路径或其他被接受的学历），"
                                       "并记录了相关证据，以便重新核查学术规则。"),
        "task.gaokao_route.steps": [
            "阅读为本项目提供的已核实的高考事实。",
            "查看资源中链接的官方页面，了解大学实际公布的入学路径。",
            "如果没有公布直接的高考入学路径，请查看大学是否公布预科路径及其要求。",
            "在计划中记录所选路径及其证据。",
        ],
        "task.gaokao_route.prerequisites": [],
        "task.gaokao_route.acceptance": [
            "已记录官方路径（或已确认无直接路径）及其来源",
            "已根据官方页面确定下一步所需的学历",
        ],
        "task.gaokao_route.alternatives": [
            "如果该项目没有公布任何路径，请在更换目标之前，先查看同一官方来源中该大学其他项目的信息。",
        ],
        "task.gaokao_route.uncertainty": ("高考分数从不换算为 A-level 成绩。如果没有公布任何路径，在提供"
                                          "其他被接受的学历之前，学术规则将一直为未知。"),
        "task.confirm_test.title": "确认入学考试要求",
        "task.confirm_test.rationale": "规则 {rule_id} 无法判定：{detail}",
        "task.confirm_test.expected": ("已通过官方项目页面确认考试要求——是否需要考试、是否公布分数门槛——"
                                       "并已记录，以便重新核查此规则。"),
        "task.confirm_test.steps": [
            "阅读下面链接的官方项目页面，了解考试要求的实际情况。",
            "查看是否公布分数门槛；如果没有公布，请记录这一点。",
            "如果需要考试，请通过官方考试机构页面确认考试日期和报名方式。",
        ],
        "task.confirm_test.prerequisites": [],
        "task.confirm_test.acceptance": [
            "已记录考试要求（是否需要）及其来源",
            "已记录分数门槛，或已记录为未公布",
        ],
        "task.confirm_test.alternatives": [
            "如果没有公布分数门槛，请直接询问大学招生办公室并记录回复。",
        ],
        "task.confirm_test.uncertainty": ("已核实的信息来源中没有说明分数门槛，因此此任务只能确认考试要求，"
                                          "不能确定目标分数。考试费用不在已核实的信息来源中。"),
        "task.experience_evidence.title": "为学术规则记录已有的 IT 工作经验",
        "task.experience_evidence.rationale": "规则 {rule_id} 无法判定：{detail}",
        "task.experience_evidence.expected": "已提供已有的 IT 工作总年限及现有证明，以便引擎重新核查此规则。",
        "task.experience_evidence.steps": [
            "根据已有记录，列出担任过的 IT 职位，包括日期和职责。",
            "收集这些职位的现有工作证明。",
            "在计划中提供 IT 工作总年限以便重新核查。",
        ],
        "task.experience_evidence.prerequisites": [
            "担任过的职位的现有工作记录",
        ],
        "task.experience_evidence.acceptance": [
            "已列出担任过的 IT 职位及日期",
            "已提供 IT 工作总年限以便重新核查",
        ],
        "task.experience_evidence.alternatives": [
            "如果没有 IT 工作经验，则无法通过此路径满足学术规则；请查看官方页面列出的其他路径。",
        ],
        "task.experience_evidence.uncertainty": ("只能记录已有的工作经验；此任务不会创造新的工作。在提供工作年限"
                                                "数字之前，此规则一直为未知。"),
        "task.strengthen_margin.title": "在最低要求之上建立余量",
        "task.strengthen_margin.rationale": "仅为竞争力差距：{detail}该规则已经达标；此任务只是在最低要求之上增加余量。",
        "task.strengthen_margin.expected": ("分数或预算数字高于规定的最低要求，以便重新核查时该规则有余量。"
                                           "达到最低要求即已满足该规则。"),
        "task.strengthen_margin.steps": [
            "决定在截止日期之前，是否值得花时间增加余量。",
            "如果值得，请练习相关技能或检查预算是否有余地。",
            "提供新的分数或数字以便重新核查。",
        ],
        "task.strengthen_margin.prerequisites": [],
        "task.strengthen_margin.acceptance": [
            "已记录关于是否增加余量的决定",
            "如果已争取，已提供新的分数或预算数字以便重新核查",
        ],
        "task.strengthen_margin.alternatives": [
            "可以跳过此任务：该规则已经达标，因此在截止日期之前无需采取行动。",
        ],
        "task.strengthen_margin.uncertainty": "增加余量是可选的：该规则已经达标。不承诺任何录取效果。",
        "task.confirm_evidence.title": "为 {rule_id} 提供缺失的证明",
        "task.confirm_evidence.rationale": "规则 {rule_id} 无法判定：{detail}",
        "task.confirm_evidence.expected": "已提供缺失的分数、文件或确认，以便引擎判定此规则。",
        "task.confirm_evidence.steps": [
            "阅读规则详情，了解具体缺失的内容。",
            "收集官方项目页面所要求的文件或分数。",
            "在计划中提供该内容，以便引擎重新核查此规则。",
        ],
        "task.confirm_evidence.prerequisites": [],
        "task.confirm_evidence.acceptance": [
            "已根据规则详情确定缺失的内容",
            "已提供缺失的分数、文件或确认以便重新核查",
        ],
        "task.confirm_evidence.alternatives": [
            "如果在截止日期之前无法提供该内容，请记录这一点，并将此规则保持为未知。",
        ],
        "task.confirm_evidence.uncertainty": "在提供缺失的证明之前，此规则一直为未知。",
        "task.academic_prep.title": "为学术要求做准备",
        "task.academic_prep.rationale": "规则 {rule_id} 未达标：{detail}",
        "task.academic_prep.expected": "已提供符合规定的学术要求的新学历证明，以便引擎重新核查此规则。",
        "task.academic_prep.steps": [
            "阅读下面链接的官方项目页面上的学术要求。",
            "列出页面上说明的科目或成绩。",
            "按列出的科目学习并记录已完成的内容。",
            "提供任何新的学历证明以便重新核查。",
        ],
        "task.academic_prep.prerequisites": [],
        "task.academic_prep.acceptance": [
            "已根据官方页面列出规定的学术要求",
            "已完成备考并记录",
            "如有新的学历证明，已提供以便重新核查",
        ],
        "task.academic_prep.alternatives": [
            "如果在截止日期之前无法满足学术要求，请查看官方页面是否列出其他路径。",
        ],
        "task.academic_prep.uncertainty": "只做准备不会改变规则；只有新的学历证明才能改变。",
        "assume.complete": "完成任务不会改变资格；只有在确认新的分数或证明并由引擎重新计算后，规则状态才会改变。",
        "assume.hours": "每个任务的每周时长都符合所述的时间上限；任务的安排保证任何一周的时长都不超过该上限。",
        "assume.cost": "除非费用范围另有说明，否则费用均为 0；考试费用不在已核实的信息来源中，因此任何涉及考试的任务都会说明费用未知。",
        "assume.no_provider": "未配置 AI 服务，因此这些任务是根据差距评估生成的确定性模板，并非模型生成的文本。",
        "assume.provider_failed": "AI 服务调用失败，因此这些任务是根据差距评估生成的确定性模板。",
        "assume.validation_failed": "模型输出未通过验证，因此这些任务是根据差距评估生成的确定性模板。",
        "limit.based_only": "本计划仅基于引擎的规则结果和证据目录中已核实的信息来源；不承诺任何录取效果，也不提供任何百分比提升。",
        "limit.urls": "任务仅使用证据目录中的链接；如果没有已核实的资源，任务会提供搜索条件而不是链接。",
        "limit.unknown": "在提供缺失的证明之前，未知规则一直为未知。",
        "reassess.empty_patch": "无变化：资料更新为空，因此未重新评估。",
        "reassess.no_change": "无变化：该更新未改变任何规则状态或差距。",
        "reassess.note": ("重新评估已重新计算 {n_programs} 个项目：{n_changes} 项规则发生变化，"
                          "仍有 {n_gaps} 个差距，其中 {n_unknowns} 个待确认。仅完成任务不会改变规则；"
                          "只有上面的引擎重新计算才算数。"),
        "task.user_statement_note": "仅为用户陈述。不是已核实的证明，不会改变任何规则状态；只有由引擎重新计算的重新评估才能改变。",
    },
    "es": {
        "gap.not_met": ("Mínimo establecido no cumplido. Umbral: {thr}; observado: "
                        "{obs}. Aporta nuevas puntuaciones o evidencia que cumplan "
                        "el mínimo establecido para que el motor pueda volver a "
                        "comprobar esta regla."),
        "gap.unknown": ("No se puede decidir con la evidencia proporcionada. Aporta "
                        "la puntuación, el documento o la confirmación que falte y "
                        "que pide la página oficial del programa, para que el motor "
                        "pueda decidir esta regla."),
        "gap.competitiveness": ("Brecha de competitividad únicamente: la regla se cumple, "
                                "pero {reason}, así que hay poco margen por encima del "
                                "mínimo establecido. El margen extra es opcional y no es "
                                "necesario para cumplir la regla."),
        "barely.fee": "el presupuesto está dentro del 10% de la matrícula ({obs} frente a una matrícula de {fee})",
        "barely.overall": "la puntuación general de IELTS está exactamente en el mínimo ({obs})",
        "barely.components": "componente(s) de IELTS exactamente en el mínimo ({comps} en {each})",
        "barely.component": "el {comp} de IELTS está exactamente en el mínimo ({val})",
        "finish.none": "No se dio ninguna fecha límite, así que no se fija fecha de finalización para esta tarea.",
        "finish.too_long": ("Esta tarea necesita {dur} semanas, pero solo quedan {left} semana(s) "
                            "antes de la fecha límite ({deadline}), así que no se puede terminar "
                            "antes de la fecha límite. Usa la alternativa a corto plazo de abajo "
                            "para el tiempo restante."),
        "finish.fits": "Quedan {left} semana(s) antes de la fecha límite ({deadline}); esta tarea necesita {dur} semana(s).",
        "res.program": "Requisitos oficiales — {name}",
        "res.program_fallback": "Página oficial del programa",
        "res.gaokao": "Datos verificados sobre la vía Gaokao — {title}",
        "res.gaokao_fallback": "Vía de acceso Gaokao (página oficial de la universidad)",
        "res.ielts_writing": "Materiales oficiales de práctica de escritura de IELTS",
        "res.ielts_general": "Materiales oficiales de práctica de IELTS",
        "res.funding": "Opciones de financiación para estudiantes internacionales",
        "res.test_provider": "Página oficial del proveedor del examen",
        "res.prep": "Material oficial de preparación",
        "comp.listening": "comprensión auditiva",
        "comp.reading": "lectura",
        "comp.writing": "escritura",
        "comp.speaking": "expresión oral",
        "task.ielts_writing.title": "Sube la escritura de IELTS hasta el mínimo establecido",
        "task.ielts_writing.rationale": "La regla {rule_id} no se cumple: {detail} La escritura es el componente por debajo del mínimo.",
        "task.ielts_writing.expected": "Una nueva puntuación de escritura de IELTS igual o superior al mínimo establecido, aportada para que el motor la vuelva a comprobar.",
        "task.ielts_writing.steps": [
            "Haz una tarea de escritura de IELTS con tiempo (Task 1 y Task 2) con el tiempo del examen.",
            "Compara el intento con los descriptores públicos de banda de escritura de IELTS y anota los errores concretos.",
            "Reescribe el párrafo más débil, corrigiendo los errores anotados.",
            "Repite con una tarea nueva con tiempo; reserva fecha de examen solo después de que un intento con tiempo cumpla el mínimo en tu propia revisión.",
        ],
        "task.ielts_writing.prerequisites": [
            "Acceso a material de práctica de escritura de IELTS encontrado con los criterios de búsqueda de abajo",
        ],
        "task.ielts_writing.acceptance": [
            "Intento de escritura con tiempo completado y comparado con los descriptores de banda",
            "Errores del intento anotados y corregidos en una reescritura",
            "Nueva puntuación de escritura de IELTS aportada para volver a comprobar",
        ],
        "task.ielts_writing.alternatives": [
            "Si queda poco tiempo, usa el tiempo restante para una tarea de escritura con tiempo al día en lugar de estudiar en general.",
        ],
        "task.ielts_writing.uncertainty": ("Practicar por sí solo no cambia la regla; solo una nueva puntuación "
                                          "de examen puede hacerlo. El coste y la disponibilidad de una "
                                          "convocatoria no están en las fuentes verificadas; consulta la "
                                          "página oficial del proveedor del examen."),
        "task.ielts_general.title": "Sube la puntuación general de IELTS hasta el mínimo establecido",
        "task.ielts_general.rationale": "La regla {rule_id} no se cumple: {detail}",
        "task.ielts_general.expected": "Una nueva puntuación general de IELTS igual o superior al mínimo establecido, aportada para que el motor la vuelva a comprobar.",
        "task.ielts_general.steps": [
            "Haz una prueba de práctica de IELTS con tiempo y anota la puntuación de cada sección.",
            "Practica a diario la sección con la puntuación más baja, con material oficial de práctica.",
            "Repite una prueba de práctica con tiempo y compara las puntuaciones por sección con el intento anterior.",
            "Reserva fecha de examen solo después de que un intento de práctica con tiempo cumpla el mínimo en tu propia revisión.",
        ],
        "task.ielts_general.prerequisites": [
            "Acceso a material de práctica de IELTS encontrado con los criterios de búsqueda de abajo",
        ],
        "task.ielts_general.acceptance": [
            "Prueba de práctica con tiempo completada con las puntuaciones por sección anotadas",
            "Sección con la puntuación más baja practicada y vuelta a evaluar",
            "Nueva puntuación general de IELTS aportada para volver a comprobar",
        ],
        "task.ielts_general.alternatives": [
            "Si queda poco tiempo, dedica el tiempo restante solo a la sección con la puntuación más baja.",
        ],
        "task.ielts_general.uncertainty": ("Practicar por sí solo no cambia la regla; solo una nueva puntuación "
                                          "de examen puede hacerlo. El coste y la disponibilidad de una "
                                          "convocatoria no están en las fuentes verificadas."),
        "task.budget.title": "Cierra la brecha de presupuesto para la matrícula del programa objetivo",
        "task.budget.rationale": "La regla {rule_id} no se cumple: {detail}",
        "task.budget.expected": ("Una cifra de presupuesto revisada que cubra la matrícula publicada, "
                                 "o la decisión de apuntar a un programa cuya matrícula se ajuste al "
                                 "presupuesto actual, para que la regla de matrícula pueda volver a "
                                 "comprobarse."),
        "task.budget.steps": [
            "Anota la matrícula publicada en la página oficial del programa enlazada abajo.",
            "Enumera la financiación ya disponible y el déficit exacto.",
            "Busca opciones de financiación con los criterios de abajo y anota lo que cubre realmente cada opción.",
            "Actualiza la cifra de presupuesto del plan solo con cantidades confirmadas.",
        ],
        "task.budget.prerequisites": [],
        "task.budget.acceptance": [
            "Cantidad del déficit anotada",
            "Opciones de financiación revisadas y anotadas con lo que cubren",
            "Cifra de presupuesto revisada aportada, o elegido otro programa objetivo",
        ],
        "task.budget.alternatives": [
            "Si no se puede cubrir la matrícula, compara las matrículas de los demás programas objetivo de este plan y elige uno que se ajuste al presupuesto actual.",
        ],
        "task.budget.uncertainty": "Aquí no se promete ninguna cantidad de financiación; la disponibilidad y las cantidades de financiación no están en las fuentes verificadas.",
        "task.gaokao_route.title": "Aclara la vía Gaokao para el programa objetivo",
        "task.gaokao_route.rationale": "La regla {rule_id} no se puede decidir: {detail}",
        "task.gaokao_route.expected": ("Una vía confirmada por una fuente oficial (por ejemplo, una vía de "
                                       "fundación u otra titulación aceptada), registrada con su evidencia, "
                                       "para que la regla académica pueda volver a comprobarse."),
        "task.gaokao_route.steps": [
            "Lee los datos verificados sobre Gaokao proporcionados para este programa.",
            "Consulta la página oficial enlazada en los recursos para ver las vías que la universidad sí publica.",
            "Si no se publica ninguna vía directa de Gaokao, comprueba si la universidad publica una vía de fundación y sus requisitos.",
            "Registra la vía elegida y la evidencia en el plan.",
        ],
        "task.gaokao_route.prerequisites": [],
        "task.gaokao_route.acceptance": [
            "Vía oficial (o ausencia de vía directa) registrada con su fuente",
            "Siguiente paso de titulación identificado en la página oficial",
        ],
        "task.gaokao_route.alternatives": [
            "Si no se publica ninguna vía para este programa, consulta la misma fuente oficial para otros programas de la misma universidad antes de cambiar de objetivo.",
        ],
        "task.gaokao_route.uncertainty": ("Las puntuaciones de Gaokao nunca se convierten a notas de A-level. "
                                          "Si no se publica ninguna vía, la regla académica seguirá como "
                                          "desconocida hasta que se aporte otra titulación aceptada."),
        "task.confirm_test.title": "Confirma el requisito del examen de admisión",
        "task.confirm_test.rationale": "La regla {rule_id} no se puede decidir: {detail}",
        "task.confirm_test.expected": ("El requisito del examen confirmado en la página oficial del programa "
                                       "— si se exige un examen y si se publica un umbral de puntuación — "
                                       "registrado para que la regla pueda volver a comprobarse."),
        "task.confirm_test.steps": [
            "Lee la página oficial del programa enlazada abajo para ver cuál es realmente el requisito del examen.",
            "Comprueba si se publica un umbral de puntuación; si no se publica ninguno, regístralo.",
            "Si se exige un examen, confirma la fecha y la vía de inscripción en la página oficial del proveedor del examen.",
        ],
        "task.confirm_test.prerequisites": [],
        "task.confirm_test.acceptance": [
            "Requisito del examen (exigido o no) registrado con su fuente",
            "Umbral de puntuación registrado, o registrado como no publicado",
        ],
        "task.confirm_test.alternatives": [
            "Si no se publica ningún umbral, pregunta directamente a la oficina de admisiones de la universidad y registra la respuesta.",
        ],
        "task.confirm_test.uncertainty": ("No se indica ningún umbral de puntuación en las fuentes verificadas, "
                                          "así que esta tarea solo puede confirmar el requisito, no una "
                                          "puntuación objetivo. Las tasas del examen no están en las fuentes "
                                          "verificadas."),
        "task.experience_evidence.title": "Registra la experiencia de TI existente para la regla académica",
        "task.experience_evidence.rationale": "La regla {rule_id} no se puede decidir: {detail}",
        "task.experience_evidence.expected": ("El total de años de experiencia de TI ya acumulados, con la "
                                              "evidencia existente, aportado para que el motor pueda volver "
                                              "a comprobar la regla."),
        "task.experience_evidence.steps": [
            "Enumera los puestos de TI ya ocupados, con fechas y funciones, a partir de los registros existentes.",
            "Reúne la evidencia laboral existente de esos puestos.",
            "Aporta el total de años de experiencia de TI en el plan para volver a comprobar.",
        ],
        "task.experience_evidence.prerequisites": [
            "Registros laborales existentes de los puestos ya ocupados",
        ],
        "task.experience_evidence.acceptance": [
            "Puestos de TI ya ocupados enumerados con fechas",
            "Total de años de experiencia de TI aportado para volver a comprobar",
        ],
        "task.experience_evidence.alternatives": [
            "Si no se tiene experiencia de TI, la regla académica no se puede cumplir por esta vía; consulta la página oficial para ver las demás vías enumeradas.",
        ],
        "task.experience_evidence.uncertainty": ("Solo se puede registrar la experiencia ya acumulada; esta tarea no "
                                                "crea empleo nuevo. La regla seguirá como desconocida hasta que "
                                                "se aporte la cifra de experiencia."),
        "task.strengthen_margin.title": "Crea margen por encima del mínimo establecido",
        "task.strengthen_margin.rationale": "Brecha de competitividad únicamente: {detail} La regla ya se cumple; esta tarea solo añade margen por encima del mínimo.",
        "task.strengthen_margin.expected": ("Una puntuación o cifra de presupuesto por encima del mínimo "
                                           "establecido, para que la regla tenga margen al volver a "
                                           "comprobarse. Cumplir el mínimo ya satisface la regla."),
        "task.strengthen_margin.steps": [
            "Decide si el margen extra merece el tiempo antes de la fecha límite.",
            "Si es así, practica la habilidad pertinente o revisa el presupuesto para ver si hay holgura.",
            "Aporta la nueva puntuación o cifra para volver a comprobar.",
        ],
        "task.strengthen_margin.prerequisites": [],
        "task.strengthen_margin.acceptance": [
            "Decisión sobre el margen extra registrada",
            "Nueva puntuación o cifra de presupuesto aportada para volver a comprobar, si se persiguió",
        ],
        "task.strengthen_margin.alternatives": [
            "Omite esta tarea: la regla ya se cumple, así que no se requiere ninguna acción antes de la fecha límite.",
        ],
        "task.strengthen_margin.uncertainty": "El margen extra es opcional: la regla ya se cumple. No se promete ningún efecto de admisión.",
        "task.confirm_evidence.title": "Aporta la evidencia que falta para {rule_id}",
        "task.confirm_evidence.rationale": "La regla {rule_id} no se puede decidir: {detail}",
        "task.confirm_evidence.expected": "La puntuación, el documento o la confirmación que falta, aportados para que el motor pueda decidir esta regla.",
        "task.confirm_evidence.steps": [
            "Lee el detalle de la regla para ver exactamente qué falta.",
            "Reúne el documento o la puntuación que pide la página oficial del programa.",
            "Aporta el documento en el plan para que el motor pueda volver a comprobar la regla.",
        ],
        "task.confirm_evidence.prerequisites": [],
        "task.confirm_evidence.acceptance": [
            "Elemento que falta identificado a partir del detalle de la regla",
            "Puntuación, documento o confirmación que falta aportados para volver a comprobar",
        ],
        "task.confirm_evidence.alternatives": [
            "Si el elemento no se puede aportar antes de la fecha límite, regístralo y mantén la regla como desconocida.",
        ],
        "task.confirm_evidence.uncertainty": "Hasta que se aporte la evidencia que falta, esta regla seguirá como desconocida.",
        "task.academic_prep.title": "Prepárate para el requisito académico",
        "task.academic_prep.rationale": "La regla {rule_id} no se cumple: {detail}",
        "task.academic_prep.expected": ("Nueva evidencia de titulación que cumpla el requisito académico "
                                        "establecido, aportada para que el motor pueda volver a comprobar "
                                        "la regla."),
        "task.academic_prep.steps": [
            "Lee el requisito académico en la página oficial del programa enlazada abajo.",
            "Enumera los temas o las notas que indica la página.",
            "Trabaja los temas enumerados y registra el trabajo completado.",
            "Aporta cualquier nueva evidencia de titulación para volver a comprobar.",
        ],
        "task.academic_prep.prerequisites": [],
        "task.academic_prep.acceptance": [
            "Requisito académico establecido enumerado a partir de la página oficial",
            "Trabajo de preparación completado y registrado",
            "Nueva evidencia de titulación aportada para volver a comprobar, si la hay",
        ],
        "task.academic_prep.alternatives": [
            "Si el requisito académico no se puede cumplir antes de la fecha límite, consulta la página oficial para ver si enumera una vía alternativa.",
        ],
        "task.academic_prep.uncertainty": "La preparación por sí sola no cambia la regla; solo una nueva evidencia de titulación puede hacerlo.",
        "assume.complete": "Completar una tarea no cambia la elegibilidad; el estado de una regla solo cambia cuando se confirman nuevas puntuaciones o evidencia y el motor lo vuelve a calcular.",
        "assume.hours": "Las horas semanales de cada tarea se ajustan a la capacidad indicada; las tareas se programan para que las horas de una misma semana no superen esa capacidad.",
        "assume.cost": "Los costes son 0 salvo que un rango de costes indique lo contrario; las tasas de examen no están en las fuentes verificadas, así que cualquier tarea con un examen indica su coste como desconocido.",
        "assume.no_provider": "No hay ningún proveedor de IA configurado, así que estas tareas son plantillas deterministas creadas a partir de la evaluación de brechas, no texto generado por un modelo.",
        "assume.provider_failed": "La llamada al proveedor de IA falló, así que estas tareas son plantillas deterministas creadas a partir de la evaluación de brechas.",
        "assume.validation_failed": "La salida del modelo no superó la validación, así que estas tareas son plantillas deterministas creadas a partir de la evaluación de brechas.",
        "limit.based_only": "Este plan se basa únicamente en los resultados de reglas del motor y en las fuentes verificadas del catálogo de evidencia; no se promete ningún efecto de admisión ni se da ninguna mejora porcentual.",
        "limit.urls": "Las tareas usan solo URL del catálogo de evidencia; donde no existe un recurso verificado, la tarea da criterios de búsqueda en lugar de un enlace.",
        "limit.unknown": "Las reglas desconocidas siguen siendo desconocidas hasta que se aporte la evidencia que falta.",
        "reassess.empty_patch": "Sin cambios: la actualización del perfil estaba vacía, así que no se volvió a evaluar nada.",
        "reassess.no_change": "Sin cambios: la actualización no cambió ningún estado de regla ni ninguna brecha.",
        "reassess.note": ("La reevaluación recalculó {n_programs} programa(s): {n_changes} regla(s) "
                          "cambiaron, quedan {n_gaps} brecha(s), incluidas {n_unknowns} por "
                          "confirmar. Completar tareas por sí solo nunca cambia una regla; solo "
                          "cuenta el recálculo del motor de arriba."),
        "task.user_statement_note": "Solo una declaración del usuario. No es evidencia verificada y no cambia ningún estado de regla; solo puede hacerlo una reevaluación recalculada por el motor.",
    },
    "fr": {
        "gap.not_met": ("Minimum requis non atteint. Seuil : {thr} ; observé : {obs}. "
                        "Fournissez de nouveaux scores ou preuves qui atteignent le "
                        "minimum requis pour que le moteur puisse revérifier cette règle."),
        "gap.unknown": ("Impossible à décider à partir des preuves fournies. Fournissez "
                        "le score, le document ou la confirmation manquant que la page "
                        "officielle du programme demande, pour que le moteur puisse "
                        "décider de cette règle."),
        "gap.competitiveness": ("Écart de compétitivité uniquement : la règle est satisfaite, "
                                "mais {reason}, donc la marge au-dessus du minimum requis "
                                "est faible. Une marge supplémentaire est facultative et "
                                "n'est pas nécessaire pour satisfaire la règle."),
        "barely.fee": "le budget est à moins de 10 % des frais ({obs} pour des frais de {fee})",
        "barely.overall": "le score global IELTS est exactement au minimum ({obs})",
        "barely.components": "composante(s) IELTS exactement au minimum ({comps} à {each})",
        "barely.component": "le {comp} IELTS est exactement au minimum ({val})",
        "finish.none": "Aucune date limite n'a été donnée, donc aucune date de fin n'est fixée pour cette tâche.",
        "finish.too_long": ("Cette tâche nécessite {dur} semaines, mais il ne reste que {left} "
                            "semaine(s) avant la date limite ({deadline}), elle ne peut donc "
                            "pas être terminée avant la date limite. Utilisez l'alternative "
                            "à court terme ci-dessous pour le temps restant."),
        "finish.fits": "Il reste {left} semaine(s) avant la date limite ({deadline}) ; cette tâche nécessite {dur} semaine(s).",
        "res.program": "Exigences officielles — {name}",
        "res.program_fallback": "Page officielle du programme",
        "res.gaokao": "Faits vérifiés sur la voie Gaokao — {title}",
        "res.gaokao_fallback": "Voie d'admission Gaokao (page officielle de l'université)",
        "res.ielts_writing": "Matériel officiel d'entraînement à l'écriture IELTS",
        "res.ielts_general": "Matériel officiel d'entraînement IELTS",
        "res.funding": "Options de financement pour les étudiants internationaux",
        "res.test_provider": "Page officielle de l'organisme d'examen",
        "res.prep": "Matériel officiel de préparation",
        "comp.listening": "compréhension orale",
        "comp.reading": "lecture",
        "comp.writing": "écriture",
        "comp.speaking": "expression orale",
        "task.ielts_writing.title": "Augmentez l'écriture IELTS jusqu'au minimum requis",
        "task.ielts_writing.rationale": "La règle {rule_id} n'est pas satisfaite : {detail} L'écriture est la composante sous le minimum.",
        "task.ielts_writing.expected": "Un nouveau score d'écriture IELTS égal ou supérieur au minimum requis, fourni pour une revérification par le moteur.",
        "task.ielts_writing.steps": [
            "Faites un exercice d'écriture IELTS chronométré (tâche 1 et tâche 2) dans le temps de l'examen.",
            "Comparez l'essai aux descripteurs publics de bande d'écriture IELTS et listez les erreurs précises.",
            "Réécrivez le paragraphe le plus faible en corrigeant les erreurs listées.",
            "Recommencez avec un nouvel exercice chronométré ; ne réservez une date d'examen qu'après qu'un essai chronométré a atteint le minimum lors de votre auto-évaluation.",
        ],
        "task.ielts_writing.prerequisites": [
            "Accès au matériel d'entraînement à l'écriture IELTS trouvé via les critères de recherche ci-dessous",
        ],
        "task.ielts_writing.acceptance": [
            "Essai d'écriture chronométré terminé et comparé aux descripteurs de bande",
            "Erreurs de l'essai listées et corrigées dans une réécriture",
            "Nouveau score d'écriture IELTS fourni pour revérification",
        ],
        "task.ielts_writing.alternatives": [
            "S'il reste peu de temps, utilisez le temps restant pour un exercice d'écriture chronométré par jour plutôt que pour des révisions générales.",
        ],
        "task.ielts_writing.uncertainty": ("S'entraîner seul ne change pas la règle ; seul un nouveau score "
                                          "d'examen peut le faire. Le coût et la disponibilité d'une "
                                          "session d'examen ne figurent pas dans les sources vérifiées ; "
                                          "consultez la page officielle de l'organisme d'examen."),
        "task.ielts_general.title": "Augmentez le score global IELTS jusqu'au minimum requis",
        "task.ielts_general.rationale": "La règle {rule_id} n'est pas satisfaite : {detail}",
        "task.ielts_general.expected": "Un nouveau score global IELTS égal ou supérieur au minimum requis, fourni pour une revérification par le moteur.",
        "task.ielts_general.steps": [
            "Faites un test d'entraînement IELTS chronométré et notez le score de chaque section.",
            "Entraînez-vous chaque jour à la section la plus faible, avec du matériel officiel.",
            "Refaites un test d'entraînement chronométré et comparez les scores par section avec la tentative précédente.",
            "Ne réservez une date d'examen qu'après qu'un essai d'entraînement chronométré a atteint le minimum lors de votre auto-évaluation.",
        ],
        "task.ielts_general.prerequisites": [
            "Accès au matériel d'entraînement IELTS trouvé via les critères de recherche ci-dessous",
        ],
        "task.ielts_general.acceptance": [
            "Test d'entraînement chronométré terminé avec les scores par section notés",
            "Section la plus faible entraînée et retestée",
            "Nouveau score global IELTS fourni pour revérification",
        ],
        "task.ielts_general.alternatives": [
            "S'il reste peu de temps, consacrez le temps restant uniquement à la section la plus faible.",
        ],
        "task.ielts_general.uncertainty": ("S'entraîner seul ne change pas la règle ; seul un nouveau score "
                                          "d'examen peut le faire. Le coût et la disponibilité d'une "
                                          "session d'examen ne figurent pas dans les sources vérifiées."),
        "task.budget.title": "Comblez l'écart de budget pour les frais du programme cible",
        "task.budget.rationale": "La règle {rule_id} n'est pas satisfaite : {detail}",
        "task.budget.expected": ("Un montant de budget révisé qui couvre les frais publiés, ou la "
                                 "décision de viser un programme dont les frais correspondent au "
                                 "budget actuel, pour que la règle des frais puisse être revérifiée."),
        "task.budget.steps": [
            "Notez les frais publiés sur la page officielle du programme liée ci-dessous.",
            "Listez le financement déjà disponible et le déficit exact.",
            "Recherchez des options de financement avec les critères ci-dessous et notez ce que chaque option couvre réellement.",
            "Ne mettez à jour le montant du budget dans le plan qu'avec des montants confirmés.",
        ],
        "task.budget.prerequisites": [],
        "task.budget.acceptance": [
            "Montant du déficit enregistré",
            "Options de financement vérifiées et enregistrées avec ce qu'elles couvrent",
            "Montant de budget révisé fourni, ou autre programme cible choisi",
        ],
        "task.budget.alternatives": [
            "Si les frais ne peuvent pas être couverts, comparez les frais des autres programmes cibles de ce plan et choisissez-en un qui correspond au budget actuel.",
        ],
        "task.budget.uncertainty": "Aucun montant de financement n'est promis ici ; la disponibilité et les montants de financement ne figurent pas dans les sources vérifiées.",
        "task.gaokao_route.title": "Clarifiez la voie Gaokao pour le programme cible",
        "task.gaokao_route.rationale": "La règle {rule_id} ne peut pas être décidée : {detail}",
        "task.gaokao_route.expected": ("Une voie confirmée par une source officielle (par exemple une voie "
                                       "de fondation ou une autre qualification acceptée), enregistrée "
                                       "avec sa preuve, pour que la règle académique puisse être "
                                       "revérifiée."),
        "task.gaokao_route.steps": [
            "Lisez les faits Gaokao vérifiés fournis pour ce programme.",
            "Consultez la page officielle liée dans les ressources pour les voies que l'université publie.",
            "Si aucune voie Gaokao directe n'est publiée, vérifiez si l'université publie une voie de fondation et ses exigences.",
            "Enregistrez la voie choisie et sa preuve dans le plan.",
        ],
        "task.gaokao_route.prerequisites": [],
        "task.gaokao_route.acceptance": [
            "Voie officielle (ou absence de voie directe) enregistrée avec sa source",
            "Prochaine étape de qualification identifiée sur la page officielle",
        ],
        "task.gaokao_route.alternatives": [
            "Si aucune voie n'est publiée pour ce programme, consultez la même source officielle pour d'autres programmes de la même université avant de changer de cible.",
        ],
        "task.gaokao_route.uncertainty": ("Les scores Gaokao ne sont jamais convertis en notes A-level. Si "
                                          "aucune voie n'est publiée, la règle académique reste INCONNUE "
                                          "jusqu'à ce qu'une autre qualification acceptée soit fournie."),
        "task.confirm_test.title": "Confirmez l'exigence du test d'admission",
        "task.confirm_test.rationale": "La règle {rule_id} ne peut pas être décidée : {detail}",
        "task.confirm_test.expected": ("L'exigence du test confirmée sur la page officielle du programme "
                                       "— si un test est requis et si un seuil de score est publié — "
                                       "enregistrée pour que la règle puisse être revérifiée."),
        "task.confirm_test.steps": [
            "Lisez la page officielle du programme liée ci-dessous pour voir ce qu'est réellement l'exigence du test.",
            "Vérifiez si un seuil de score est publié ; si aucun n'est publié, notez-le.",
            "Si un test est requis, confirmez la date du test et la voie d'inscription sur la page officielle de l'organisme du test.",
        ],
        "task.confirm_test.prerequisites": [],
        "task.confirm_test.acceptance": [
            "Exigence du test (requise ou non) enregistrée avec sa source",
            "Seuil de score enregistré, ou enregistré comme non publié",
        ],
        "task.confirm_test.alternatives": [
            "Si aucun seuil n'est publié, demandez directement au service des admissions de l'université et enregistrez la réponse.",
        ],
        "task.confirm_test.uncertainty": ("Aucun seuil de score n'est indiqué dans les sources vérifiées, "
                                          "cette tâche peut donc seulement confirmer l'exigence, pas un "
                                          "score cible. Les frais de test ne figurent pas dans les "
                                          "sources vérifiées."),
        "task.experience_evidence.title": "Enregistrez l'expérience informatique existante pour la règle académique",
        "task.experience_evidence.rationale": "La règle {rule_id} ne peut pas être décidée : {detail}",
        "task.experience_evidence.expected": ("Le nombre total d'années d'expérience informatique déjà acquises, "
                                              "avec les preuves existantes, fourni pour que le moteur puisse "
                                              "revérifier la règle."),
        "task.experience_evidence.steps": [
            "Listez les postes informatiques déjà occupés, avec dates et fonctions, à partir des dossiers existants.",
            "Rassemblez les preuves d'emploi existantes pour ces postes.",
            "Fournissez le nombre total d'années d'expérience informatique dans le plan pour revérification.",
        ],
        "task.experience_evidence.prerequisites": [
            "Dossiers d'emploi existants pour les postes déjà occupés",
        ],
        "task.experience_evidence.acceptance": [
            "Postes informatiques déjà occupés listés avec dates",
            "Nombre total d'années d'expérience informatique fourni pour revérification",
        ],
        "task.experience_evidence.alternatives": [
            "Si aucune expérience informatique n'est acquise, la règle académique ne peut pas être satisfaite par cette voie ; consultez la page officielle pour les autres voies listées.",
        ],
        "task.experience_evidence.uncertainty": ("Seule l'expérience déjà acquise peut être enregistrée ; cette "
                                                "tâche ne crée pas de nouvel emploi. La règle reste INCONNUE "
                                                "jusqu'à ce que le nombre d'années d'expérience soit fourni."),
        "task.strengthen_margin.title": "Créez une marge au-dessus du minimum requis",
        "task.strengthen_margin.rationale": "Écart de compétitivité uniquement : {detail} La règle est déjà satisfaite ; cette tâche ajoute seulement une marge au-dessus du minimum.",
        "task.strengthen_margin.expected": ("Un score ou un montant de budget supérieur au minimum requis, "
                                           "pour que la règle ait une marge lors de la revérification. "
                                           "Atteindre le minimum satisfait déjà la règle."),
        "task.strengthen_margin.steps": [
            "Décidez si une marge supplémentaire vaut le temps avant la date limite.",
            "Si oui, entraînez-vous à la compétence concernée ou vérifiez la marge du budget.",
            "Fournissez le nouveau score ou montant pour revérification.",
        ],
        "task.strengthen_margin.prerequisites": [],
        "task.strengthen_margin.acceptance": [
            "Décision sur la marge supplémentaire enregistrée",
            "Nouveau score ou montant de budget fourni pour revérification, si poursuivi",
        ],
        "task.strengthen_margin.alternatives": [
            "Ignorez cette tâche : la règle est déjà satisfaite, aucune action n'est donc requise avant la date limite.",
        ],
        "task.strengthen_margin.uncertainty": "La marge supplémentaire est facultative : la règle est déjà satisfaite. Aucun effet d'admission n'est promis.",
        "task.confirm_evidence.title": "Fournissez la preuve manquante pour {rule_id}",
        "task.confirm_evidence.rationale": "La règle {rule_id} ne peut pas être décidée : {detail}",
        "task.confirm_evidence.expected": "Le score, le document ou la confirmation manquant, fourni pour que le moteur puisse décider de cette règle.",
        "task.confirm_evidence.steps": [
            "Lisez le détail de la règle pour voir exactement ce qui manque.",
            "Rassemblez le document ou le score que la page officielle du programme demande.",
            "Fournissez-le dans le plan pour que le moteur puisse revérifier la règle.",
        ],
        "task.confirm_evidence.prerequisites": [],
        "task.confirm_evidence.acceptance": [
            "Élément manquant identifié à partir du détail de la règle",
            "Score, document ou confirmation manquant fourni pour revérification",
        ],
        "task.confirm_evidence.alternatives": [
            "Si l'élément ne peut pas être fourni avant la date limite, notez-le et gardez la règle comme INCONNUE.",
        ],
        "task.confirm_evidence.uncertainty": "Tant que la preuve manquante n'est pas fournie, cette règle reste INCONNUE.",
        "task.academic_prep.title": "Préparez-vous à l'exigence académique",
        "task.academic_prep.rationale": "La règle {rule_id} n'est pas satisfaite : {detail}",
        "task.academic_prep.expected": ("Une nouvelle preuve de qualification qui satisfait l'exigence "
                                        "académique requise, fournie pour que le moteur puisse "
                                        "revérifier la règle."),
        "task.academic_prep.steps": [
            "Lisez l'exigence académique sur la page officielle du programme liée ci-dessous.",
            "Listez les sujets ou les notes indiqués sur la page.",
            "Travaillez les sujets listés et enregistrez le travail terminé.",
            "Fournissez toute nouvelle preuve de qualification pour revérification.",
        ],
        "task.academic_prep.prerequisites": [],
        "task.academic_prep.acceptance": [
            "Exigence académique requise listée à partir de la page officielle",
            "Travail de préparation terminé et enregistré",
            "Nouvelle preuve de qualification fournie pour revérification, le cas échéant",
        ],
        "task.academic_prep.alternatives": [
            "Si l'exigence académique ne peut pas être satisfaite avant la date limite, consultez la page officielle pour une autre voie qu'elle liste.",
        ],
        "task.academic_prep.uncertainty": "La préparation seule ne change pas la règle ; seule une nouvelle preuve de qualification peut le faire.",
        "assume.complete": "Terminer une tâche ne change pas l'éligibilité ; le statut d'une règle ne change que lorsque de nouveaux scores ou preuves sont confirmés et recalculés par le moteur.",
        "assume.hours": "Les heures hebdomadaires de chaque tâche respectent la capacité indiquée ; les tâches sont planifiées pour que les heures d'une même semaine restent dans cette capacité.",
        "assume.cost": "Les coûts sont de 0 sauf si une fourchette de coûts indique le contraire ; les frais d'examen ne figurent pas dans les sources vérifiées, donc toute tâche impliquant un examen indique son coût comme inconnu.",
        "assume.no_provider": "Aucun fournisseur d'IA n'est configuré, ces tâches sont donc des modèles déterministes construits à partir de l'évaluation des écarts, et non un texte généré par un modèle.",
        "assume.provider_failed": "L'appel au fournisseur d'IA a échoué, ces tâches sont donc des modèles déterministes construits à partir de l'évaluation des écarts.",
        "assume.validation_failed": "La sortie du modèle n'a pas passé la validation, ces tâches sont donc des modèles déterministes construits à partir de l'évaluation des écarts.",
        "limit.based_only": "Ce plan repose uniquement sur les résultats de règles du moteur et les sources vérifiées du catalogue de preuves ; aucun effet d'admission n'est promis et aucune amélioration en pourcentage n'est donnée.",
        "limit.urls": "Les tâches utilisent uniquement des URL du catalogue de preuves ; lorsqu'aucune ressource vérifiée n'existe, la tâche donne des critères de recherche au lieu d'un lien.",
        "limit.unknown": "Les règles inconnues restent inconnues jusqu'à ce que la preuve manquante soit fournie.",
        "reassess.empty_patch": "Aucun changement : la mise à jour du profil était vide, aucune évaluation n'a donc été recalculée.",
        "reassess.no_change": "Aucun changement : la mise à jour n'a modifié aucun statut de règle ni aucun écart.",
        "reassess.note": ("La réévaluation a recalculé {n_programs} programme(s) : {n_changes} règle(s) "
                          "ont changé, {n_gaps} écart(s) subsistent, dont {n_unknowns} à confirmer. "
                          "Terminer des tâches seul ne change jamais une règle ; seul le recalcul "
                          "du moteur ci-dessus compte."),
        "task.user_statement_note": "Déclaration de l'utilisateur uniquement. Ce n'est pas une preuve vérifiée et cela ne change aucun statut de règle ; seule une réévaluation recalculée par le moteur peut le faire.",
    },
    "pt-BR": {
        "gap.not_met": ("Mínimo exigido não atendido. Limite: {thr}; observado: {obs}. "
                        "Forneça novas notas ou evidências que atendam ao mínimo exigido "
                        "para que o mecanismo possa verificar esta regra novamente."),
        "gap.unknown": ("Não é possível decidir com base nas evidências fornecidas. "
                        "Forneça a nota, o documento ou a confirmação que falta e que a "
                        "página oficial do programa pede, para que o mecanismo possa "
                        "decidir esta regra."),
        "gap.competitiveness": ("Lacuna de competitividade apenas: a regra foi atendida, "
                                "mas {reason}, então há pouca margem acima do mínimo exigido. "
                                "Margem extra é opcional e não é necessária para atender à regra."),
        "barely.fee": "o orçamento está dentro de 10% da mensalidade ({obs} contra uma mensalidade de {fee})",
        "barely.overall": "a nota geral do IELTS está exatamente no mínimo ({obs})",
        "barely.components": "componente(s) do IELTS exatamente no mínimo ({comps} em {each})",
        "barely.component": "o {comp} do IELTS está exatamente no mínimo ({val})",
        "finish.none": "Nenhum prazo foi informado, então nenhuma data de conclusão foi definida para esta tarefa.",
        "finish.too_long": ("Esta tarefa precisa de {dur} semanas, mas restam apenas {left} "
                            "semana(s) antes do prazo ({deadline}), então ela não pode ser "
                            "concluída antes do prazo. Use a alternativa de curto prazo abaixo "
                            "para o tempo restante."),
        "finish.fits": "Restam {left} semana(s) antes do prazo ({deadline}); esta tarefa precisa de {dur} semana(s).",
        "res.program": "Requisitos oficiais — {name}",
        "res.program_fallback": "Página oficial do programa",
        "res.gaokao": "Fatos verificados sobre a via Gaokao — {title}",
        "res.gaokao_fallback": "Via de acesso Gaokao (página oficial da universidade)",
        "res.ielts_writing": "Materiais oficiais de prática de escrita do IELTS",
        "res.ielts_general": "Materiais oficiais de prática do IELTS",
        "res.funding": "Opções de financiamento para estudantes internacionais",
        "res.test_provider": "Página oficial do provedor do exame",
        "res.prep": "Material oficial de preparação",
        "comp.listening": "compreensão auditiva",
        "comp.reading": "leitura",
        "comp.writing": "escrita",
        "comp.speaking": "expressão oral",
        "task.ielts_writing.title": "Aumente a escrita do IELTS até o mínimo exigido",
        "task.ielts_writing.rationale": "A regra {rule_id} não foi atendida: {detail} A escrita é o componente abaixo do mínimo.",
        "task.ielts_writing.expected": "Uma nova nota de escrita do IELTS igual ou superior ao mínimo exigido, fornecida para verificação pelo mecanismo.",
        "task.ielts_writing.steps": [
            "Faça uma tarefa de escrita do IELTS com tempo (Task 1 e Task 2) no tempo do exame.",
            "Compare a tentativa com os descritores públicos de banda de escrita do IELTS e liste os erros específicos.",
            "Reescreva o parágrafo mais fraco, corrigindo os erros listados.",
            "Repita com uma nova tarefa com tempo; marque uma data de exame somente depois que uma tentativa com tempo atingir o mínimo na autoavaliação.",
        ],
        "task.ielts_writing.prerequisites": [
            "Acesso a material de prática de escrita do IELTS encontrado com os critérios de busca abaixo",
        ],
        "task.ielts_writing.acceptance": [
            "Tentativa de escrita com tempo concluída e comparada com os descritores de banda",
            "Erros da tentativa listados e corrigidos em uma reescrita",
            "Nova nota de escrita do IELTS fornecida para verificação",
        ],
        "task.ielts_writing.alternatives": [
            "Se restar pouco tempo, use o tempo restante para uma tarefa de escrita com tempo por dia, em vez de estudo geral.",
        ],
        "task.ielts_writing.uncertainty": ("A prática por si só não muda a regra; somente uma nova nota de "
                                          "exame pode mudá-la. O custo e a disponibilidade de uma sessão "
                                          "de exame não estão nas fontes verificadas; consulte a página "
                                          "oficial do provedor do exame."),
        "task.ielts_general.title": "Aumente a nota geral do IELTS até o mínimo exigido",
        "task.ielts_general.rationale": "A regra {rule_id} não foi atendida: {detail}",
        "task.ielts_general.expected": "Uma nova nota geral do IELTS igual ou superior ao mínimo exigido, fornecida para verificação pelo mecanismo.",
        "task.ielts_general.steps": [
            "Faça um teste de prática do IELTS com tempo e registre a nota de cada seção.",
            "Pratique diariamente a seção com a nota mais baixa, usando material oficial de prática.",
            "Refaça um teste de prática com tempo e compare as notas por seção com a tentativa anterior.",
            "Marque uma data de exame somente depois que uma tentativa de prática com tempo atingir o mínimo na autoavaliação.",
        ],
        "task.ielts_general.prerequisites": [
            "Acesso a material de prática do IELTS encontrado com os critérios de busca abaixo",
        ],
        "task.ielts_general.acceptance": [
            "Teste de prática com tempo concluído com as notas por seção registradas",
            "Seção com a nota mais baixa praticada e testada novamente",
            "Nova nota geral do IELTS fornecida para verificação",
        ],
        "task.ielts_general.alternatives": [
            "Se restar pouco tempo, concentre o tempo restante somente na seção com a nota mais baixa.",
        ],
        "task.ielts_general.uncertainty": ("A prática por si só não muda a regra; somente uma nova nota de "
                                          "exame pode mudá-la. O custo e a disponibilidade de uma sessão "
                                          "de exame não estão nas fontes verificadas."),
        "task.budget.title": "Feche a lacuna de orçamento para a mensalidade do programa-alvo",
        "task.budget.rationale": "A regra {rule_id} não foi atendida: {detail}",
        "task.budget.expected": ("Um valor de orçamento revisado que cubra a mensalidade publicada, "
                                 "ou a decisão de mirar um programa cuja mensalidade caiba no "
                                 "orçamento atual, para que a regra de mensalidade possa ser "
                                 "verificada novamente."),
        "task.budget.steps": [
            "Anote a mensalidade publicada na página oficial do programa com link abaixo.",
            "Liste o financiamento já disponível e o déficit exato.",
            "Busque opções de financiamento com os critérios abaixo e registre o que cada opção realmente cobre.",
            "Atualize o valor do orçamento no plano somente com valores confirmados.",
        ],
        "task.budget.prerequisites": [],
        "task.budget.acceptance": [
            "Valor do déficit registrado",
            "Opções de financiamento verificadas e registradas com o que cobrem",
            "Valor de orçamento revisado fornecido, ou outro programa-alvo escolhido",
        ],
        "task.budget.alternatives": [
            "Se a mensalidade não puder ser paga, compare as mensalidades dos outros programas-alvo deste plano e escolha um que caiba no orçamento atual.",
        ],
        "task.budget.uncertainty": "Nenhum valor de financiamento é prometido aqui; a disponibilidade e os valores de financiamento não estão nas fontes verificadas.",
        "task.gaokao_route.title": "Esclareça a via Gaokao para o programa-alvo",
        "task.gaokao_route.rationale": "A regra {rule_id} não pode ser decidida: {detail}",
        "task.gaokao_route.expected": ("Uma via confirmada por uma fonte oficial (por exemplo, uma via de "
                                       "fundação ou outra qualificação aceita), registrada com sua "
                                       "evidência, para que a regra acadêmica possa ser verificada "
                                       "novamente."),
        "task.gaokao_route.steps": [
            "Leia os fatos verificados sobre o Gaokao fornecidos para este programa.",
            "Consulte a página oficial com link nos recursos para ver as vias que a universidade publica.",
            "Se nenhuma via direta de Gaokao for publicada, verifique se a universidade publica uma via de fundação e seus requisitos.",
            "Registre a via escolhida e a evidência no plano.",
        ],
        "task.gaokao_route.prerequisites": [],
        "task.gaokao_route.acceptance": [
            "Via oficial (ou ausência de via direta) registrada com sua fonte",
            "Próximo passo de qualificação identificado na página oficial",
        ],
        "task.gaokao_route.alternatives": [
            "Se nenhuma via for publicada para este programa, consulte a mesma fonte oficial para outros programas da mesma universidade antes de mudar de alvo.",
        ],
        "task.gaokao_route.uncertainty": ("As notas do Gaokao nunca são convertidas em notas de A-level. Se "
                                          "nenhuma via for publicada, a regra acadêmica continuará DESCONHECIDA "
                                          "até que outra qualificação aceita seja fornecida."),
        "task.confirm_test.title": "Confirme o requisito do exame de admissão",
        "task.confirm_test.rationale": "A regra {rule_id} não pode ser decidida: {detail}",
        "task.confirm_test.expected": ("O requisito do exame confirmado na página oficial do programa "
                                       "— se um exame é exigido e se um limite de nota é publicado — "
                                       "registrado para que a regra possa ser verificada novamente."),
        "task.confirm_test.steps": [
            "Leia a página oficial do programa com link abaixo para ver qual é realmente o requisito do exame.",
            "Verifique se um limite de nota é publicado; se nenhum for publicado, registre isso.",
            "Se um exame for exigido, confirme a data do exame e a via de inscrição na página oficial do provedor do exame.",
        ],
        "task.confirm_test.prerequisites": [],
        "task.confirm_test.acceptance": [
            "Requisito do exame (exigido ou não) registrado com sua fonte",
            "Limite de nota registrado, ou registrado como não publicado",
        ],
        "task.confirm_test.alternatives": [
            "Se nenhum limite for publicado, pergunte diretamente ao escritório de admissões da universidade e registre a resposta.",
        ],
        "task.confirm_test.uncertainty": ("Nenhum limite de nota é informado nas fontes verificadas, então "
                                          "esta tarefa só pode confirmar o requisito, não uma nota-alvo. "
                                          "As taxas do exame não estão nas fontes verificadas."),
        "task.experience_evidence.title": "Registre a experiência de TI existente para a regra acadêmica",
        "task.experience_evidence.rationale": "A regra {rule_id} não pode ser decidida: {detail}",
        "task.experience_evidence.expected": ("O total de anos de experiência de TI já acumulados, com a "
                                              "evidência existente, fornecido para que o mecanismo possa "
                                              "verificar a regra novamente."),
        "task.experience_evidence.steps": [
            "Liste os cargos de TI já ocupados, com datas e funções, a partir dos registros existentes.",
            "Reúna as evidências de emprego existentes para esses cargos.",
            "Forneça o total de anos de experiência de TI no plano para verificação.",
        ],
        "task.experience_evidence.prerequisites": [
            "Registros de emprego existentes para os cargos já ocupados",
        ],
        "task.experience_evidence.acceptance": [
            "Cargos de TI já ocupados listados com datas",
            "Total de anos de experiência de TI fornecido para verificação",
        ],
        "task.experience_evidence.alternatives": [
            "Se não houver experiência de TI, a regra acadêmica não pode ser atendida por esta via; consulte a página oficial para ver as outras vias listadas.",
        ],
        "task.experience_evidence.uncertainty": ("Somente a experiência já acumulada pode ser registrada; esta "
                                                "tarefa não cria novo emprego. A regra continuará DESCONHECIDA "
                                                "até que o número de anos de experiência seja fornecido."),
        "task.strengthen_margin.title": "Crie margem acima do mínimo exigido",
        "task.strengthen_margin.rationale": "Lacuna de competitividade apenas: {detail} A regra já foi atendida; esta tarefa apenas adiciona margem acima do mínimo.",
        "task.strengthen_margin.expected": ("Uma nota ou valor de orçamento acima do mínimo exigido, para que "
                                           "a regra tenha margem ao ser verificada novamente. Atender ao "
                                           "mínimo já satisfaz a regra."),
        "task.strengthen_margin.steps": [
            "Decida se a margem extra vale o tempo antes do prazo.",
            "Se sim, pratique a habilidade relevante ou revise o orçamento para ver se há folga.",
            "Forneça a nova nota ou valor para verificação.",
        ],
        "task.strengthen_margin.prerequisites": [],
        "task.strengthen_margin.acceptance": [
            "Decisão sobre a margem extra registrada",
            "Nova nota ou valor de orçamento fornecido para verificação, se buscado",
        ],
        "task.strengthen_margin.alternatives": [
            "Pule esta tarefa: a regra já foi atendida, então nenhuma ação é necessária antes do prazo.",
        ],
        "task.strengthen_margin.uncertainty": "A margem extra é opcional: a regra já foi atendida. Nenhum efeito de admissão é prometido.",
        "task.confirm_evidence.title": "Forneça a evidência que falta para {rule_id}",
        "task.confirm_evidence.rationale": "A regra {rule_id} não pode ser decidida: {detail}",
        "task.confirm_evidence.expected": "A nota, o documento ou a confirmação que falta, fornecidos para que o mecanismo possa decidir esta regra.",
        "task.confirm_evidence.steps": [
            "Leia o detalhe da regra para ver exatamente o que falta.",
            "Reúna o documento ou a nota que a página oficial do programa pede.",
            "Forneça o documento no plano para que o mecanismo possa verificar a regra novamente.",
        ],
        "task.confirm_evidence.prerequisites": [],
        "task.confirm_evidence.acceptance": [
            "Item que falta identificado a partir do detalhe da regra",
            "Nota, documento ou confirmação que falta fornecidos para verificação",
        ],
        "task.confirm_evidence.alternatives": [
            "Se o item não puder ser fornecido antes do prazo, registre isso e mantenha a regra como DESCONHECIDA.",
        ],
        "task.confirm_evidence.uncertainty": "Até que a evidência que falta seja fornecida, esta regra continuará DESCONHECIDA.",
        "task.academic_prep.title": "Prepare-se para o requisito acadêmico",
        "task.academic_prep.rationale": "A regra {rule_id} não foi atendida: {detail}",
        "task.academic_prep.expected": ("Nova evidência de qualificação que atenda ao requisito acadêmico "
                                        "exigido, fornecida para que o mecanismo possa verificar a regra "
                                        "novamente."),
        "task.academic_prep.steps": [
            "Leia o requisito acadêmico na página oficial do programa com link abaixo.",
            "Liste os tópicos ou notas que a página informa.",
            "Estude os tópicos listados e registre o trabalho concluído.",
            "Forneça qualquer nova evidência de qualificação para verificação.",
        ],
        "task.academic_prep.prerequisites": [],
        "task.academic_prep.acceptance": [
            "Requisito acadêmico exigido listado a partir da página oficial",
            "Trabalho de preparação concluído e registrado",
            "Nova evidência de qualificação fornecida para verificação, se houver",
        ],
        "task.academic_prep.alternatives": [
            "Se o requisito acadêmico não puder ser atendido antes do prazo, consulte a página oficial para ver se ela lista uma via alternativa.",
        ],
        "task.academic_prep.uncertainty": "A preparação por si só não muda a regra; somente uma nova evidência de qualificação pode mudá-la.",
        "assume.complete": "Concluir uma tarefa não muda a elegibilidade; o status de uma regra só muda quando novas notas ou evidências são confirmadas e recalculadas pelo mecanismo.",
        "assume.hours": "As horas semanais de cada tarefa cabem na capacidade informada; as tarefas são agendadas para que as horas de uma mesma semana fiquem dentro dessa capacidade.",
        "assume.cost": "Os custos são 0, salvo se um intervalo de custos indicar o contrário; as taxas de exame não estão nas fontes verificadas, então qualquer tarefa que envolva um exame informa seu custo como desconhecido.",
        "assume.no_provider": "Nenhum provedor de IA está configurado, então estas tarefas são modelos deterministas criados a partir da avaliação de lacunas, não texto gerado por modelo.",
        "assume.provider_failed": "A chamada ao provedor de IA falhou, então estas tarefas são modelos deterministas criados a partir da avaliação de lacunas.",
        "assume.validation_failed": "A saída do modelo não passou na validação, então estas tarefas são modelos deterministas criados a partir da avaliação de lacunas.",
        "limit.based_only": "Este plano se baseia apenas nos resultados de regras do mecanismo e nas fontes verificadas do catálogo de evidências; nenhum efeito de admissão é prometido e nenhuma melhoria percentual é dada.",
        "limit.urls": "As tarefas usam apenas URLs do catálogo de evidências; onde não existe recurso verificado, a tarefa dá critérios de busca em vez de um link.",
        "limit.unknown": "As regras desconhecidas continuam desconhecidas até que a evidência que falta seja fornecida.",
        "reassess.empty_patch": "Sem mudanças: a atualização do perfil estava vazia, então nenhuma avaliação foi recalculada.",
        "reassess.no_change": "Sem mudanças: a atualização não mudou nenhum status de regra nem nenhuma lacuna.",
        "reassess.note": ("A reavaliação recalculou {n_programs} programa(s): {n_changes} regra(s) "
                          "mudaram, restam {n_gaps} lacuna(s), incluindo {n_unknowns} a confirmar. "
                          "Concluir tarefas por si só nunca muda uma regra; somente o recálculo "
                          "do mecanismo acima conta."),
        "task.user_statement_note": "Apenas uma declaração do usuário. Não é evidência verificada e não muda nenhum status de regra; somente uma reavaliação recalculada pelo mecanismo pode mudar.",
    },
    "ar": {
        "gap.not_met": ("الحد الأدنى المطلوب غير مستوفى. الحد: {thr}؛ الملاحَظ: {obs}. "
                        "قدّم درجات أو أدلة جديدة تستوفي الحد الأدنى المطلوب حتى يتمكن "
                        "المحرك من إعادة التحقق من هذه القاعدة."),
        "gap.unknown": ("لا يمكن تحديده من الأدلة المقدمة. قدّم الدرجة أو المستند أو "
                        "التأكيد المفقود الذي تطلبه صفحة البرنامج الرسمية، حتى يتمكن "
                        "المحرك من تحديد هذه القاعدة."),
        "gap.competitiveness": ("فجوة تنافسية فقط: القاعدة مستوفاة، لكن {reason}، لذلك الهامش "
                                "فوق الحد الأدنى المطلوب ضئيل. الهامش الإضافي اختياري وليس "
                                "مطلوبًا لاستيفاء القاعدة."),
        "barely.fee": "الميزانية ضمن 10% من الرسوم ({obs} مقابل رسوم قدرها {fee})",
        "barely.overall": "الدرجة العامة في IELTS تساوي الحد الأدنى تمامًا ({obs})",
        "barely.components": "مكوّن (مكوّنات) IELTS يساوي الحد الأدنى تمامًا ({comps} بدرجة {each})",
        "barely.component": "{comp} في IELTS يساوي الحد الأدنى تمامًا ({val})",
        "finish.none": "لم يتم تحديد موعد نهائي، لذا لم يتم تحديد تاريخ إنجاز لهذه المهمة.",
        "finish.too_long": ("تحتاج هذه المهمة إلى {dur} أسابيع، لكن لم يتبقَّ سوى {left} "
                            "أسبوع (أسابيع) قبل الموعد النهائي ({deadline})، لذا لا يمكن "
                            "إنجازها قبل الموعد النهائي. استخدم البديل قصير الأمد أدناه "
                            "للوقت المتبقي."),
        "finish.fits": "تبقّى {left} أسبوع (أسابيع) قبل الموعد النهائي ({deadline})؛ وتحتاج هذه المهمة إلى {dur} أسبوع (أسابيع).",
        "res.program": "المتطلبات الرسمية — {name}",
        "res.program_fallback": "صفحة البرنامج الرسمية",
        "res.gaokao": "حقائق موثقة عن مسار Gaokao — {title}",
        "res.gaokao_fallback": "مسار القبول Gaokao (صفحة الجامعة الرسمية)",
        "res.ielts_writing": "مواد التدريب الرسمية على كتابة IELTS",
        "res.ielts_general": "مواد التدريب الرسمية على IELTS",
        "res.funding": "خيارات التمويل للطلاب الدوليين",
        "res.test_provider": "صفحة مزود الاختبار الرسمية",
        "res.prep": "مادة الإعداد الرسمية",
        "comp.listening": "الاستماع",
        "comp.reading": "القراءة",
        "comp.writing": "الكتابة",
        "comp.speaking": "التحدث",
        "task.ielts_writing.title": "ارفع كتابة IELTS إلى الحد الأدنى المطلوب",
        "task.ielts_writing.rationale": "القاعدة {rule_id} غير مستوفاة: {detail} الكتابة هي المكوّن الأقل من الحد الأدنى.",
        "task.ielts_writing.expected": "درجة جديدة في كتابة IELTS تساوي الحد الأدنى المطلوب أو تتجاوزه، مقدَّمة لإعادة التحقق بواسطة المحرك.",
        "task.ielts_writing.steps": [
            "أدِّ مهمة كتابة IELTS واحدة محددة بوقت (المهمة 1 والمهمة 2) ضمن وقت الاختبار.",
            "قارن المحاولة بمعايير نطاقات الكتابة العامة في IELTS وحدّد الأخطاء المحددة.",
            "أعد كتابة أضعف فقرة مع تصحيح الأخطاء المحددة.",
            "كرر ذلك بمهمة جديدة محددة بوقت؛ واحجز موعد اختبار IELTS فقط بعد أن تستوفي محاولة محددة بوقت الحد الأدنى عند التحقق الذاتي.",
        ],
        "task.ielts_writing.prerequisites": [
            "الوصول إلى مادة تدريب على كتابة IELTS يتم العثور عليها عبر معايير البحث أدناه",
        ],
        "task.ielts_writing.acceptance": [
            "اكتملت محاولة الكتابة المحددة بوقت وتمت مقارنتها بمعايير النطاقات",
            "تم تحديد أخطاء المحاولة وتصحيحها في إعادة الكتابة",
            "تم تقديم درجة جديدة في كتابة IELTS لإعادة التحقق",
        ],
        "task.ielts_writing.alternatives": [
            "إذا كان الوقت المتبقي قليلًا، فاستخدم الوقت المتبقي لمهمة كتابة واحدة محددة بوقت كل يوم بدلًا من الدراسة العامة.",
        ],
        "task.ielts_writing.uncertainty": ("التدريب وحده لا يغيّر القاعدة؛ فقط درجة اختبار جديدة يمكنها ذلك. "
                                          "تكلفة جلسة الاختبار وتوفرها غير موجودتين في المصادر الموثقة؛ "
                                          "راجع صفحة مزود الاختبار الرسمية."),
        "task.ielts_general.title": "ارفع الدرجة العامة في IELTS إلى الحد الأدنى المطلوب",
        "task.ielts_general.rationale": "القاعدة {rule_id} غير مستوفاة: {detail}",
        "task.ielts_general.expected": "درجة عامة جديدة في IELTS تساوي الحد الأدنى المطلوب أو تتجاوزه، مقدَّمة لإعادة التحقق بواسطة المحرك.",
        "task.ielts_general.steps": [
            "أدِّ اختبار تدريب IELTS واحدًا محددًا بوقت وسجّل الدرجة لكل قسم.",
            "تدرّب يوميًا على القسم الأقل درجة باستخدام مادة تدريب رسمية.",
            "أعد اختبار تدريب محددًا بوقت وقارن درجات الأقسام بالمحاولة السابقة.",
            "احجز موعد اختبار IELTS فقط بعد أن تستوفي محاولة تدريب محددة بوقت الحد الأدنى عند التحقق الذاتي.",
        ],
        "task.ielts_general.prerequisites": [
            "الوصول إلى مادة تدريب على IELTS يتم العثور عليها عبر معايير البحث أدناه",
        ],
        "task.ielts_general.acceptance": [
            "اكتمل اختبار التدريب المحدد بوقت مع تسجيل درجات الأقسام",
            "تم التدريب على القسم الأقل درجة وإعادة اختباره",
            "تم تقديم درجة عامة جديدة في IELTS لإعادة التحقق",
        ],
        "task.ielts_general.alternatives": [
            "إذا كان الوقت المتبقي قليلًا، فركّز الوقت المتبقي على القسم الأقل درجة فقط.",
        ],
        "task.ielts_general.uncertainty": ("التدريب وحده لا يغيّر القاعدة؛ فقط درجة اختبار جديدة يمكنها ذلك. "
                                          "تكلفة جلسة الاختبار وتوفرها غير موجودتين في المصادر الموثقة."),
        "task.budget.title": "سد فجوة الميزانية لرسوم البرنامج المستهدف",
        "task.budget.rationale": "القاعدة {rule_id} غير مستوفاة: {detail}",
        "task.budget.expected": ("مبلغ ميزانية منقّح يغطي الرسوم المنشورة، أو قرار باستهداف برنامج "
                                 "تناسب رسومه الميزانية الحالية، حتى يمكن إعادة التحقق من قاعدة الرسوم."),
        "task.budget.steps": [
            "دوّن الرسوم المنشورة من صفحة البرنامج الرسمية المرتبطة أدناه.",
            "حدّد التمويل المتاح بالفعل والعجز الدقيق.",
            "ابحث عن خيارات التمويل باستخدام المعايير أدناه وسجّل ما يغطيه كل خيار فعلًا.",
            "حدّث مبلغ الميزانية في الخطة فقط بالمبالغ المؤكدة.",
        ],
        "task.budget.prerequisites": [],
        "task.budget.acceptance": [
            "تم تسجيل مبلغ العجز",
            "تم التحقق من خيارات التمويل وتسجيل ما تغطيه",
            "تم تقديم مبلغ ميزانية منقّح أو اختيار برنامج مستهدف مختلف",
        ],
        "task.budget.alternatives": [
            "إذا تعذّر دفع الرسوم، فقارن رسوم البرامج المستهدفة الأخرى في هذه الخطة واختر برنامجًا يناسب الميزانية الحالية.",
        ],
        "task.budget.uncertainty": "لا يُوعد بأي مبلغ تمويل هنا؛ فتوفر التمويل ومبالغه غير موجودين في المصادر الموثقة.",
        "task.gaokao_route.title": "وضّح مسار Gaokao للبرنامج المستهدف",
        "task.gaokao_route.rationale": "تعذّر تحديد القاعدة {rule_id}: {detail}",
        "task.gaokao_route.expected": ("مسار مؤكد من مصدر رسمي (مثل مسار تأسيسي أو مؤهل آخر مقبول)، "
                                       "مسجَّل مع دليله، حتى يمكن إعادة التحقق من القاعدة الأكاديمية."),
        "task.gaokao_route.steps": [
            "اقرأ حقائق Gaokao الموثقة المقدمة لهذا البرنامج.",
            "تحقق من الصفحة الرسمية المرتبطة في الموارد لمعرفة المسارات التي تنشرها الجامعة.",
            "إذا لم يُنشر مسار Gaokao مباشر، فتحقق مما إذا كانت الجامعة تنشر مسارًا تأسيسيًا ومتطلباته.",
            "سجّل المسار المختار والدليل عليه في الخطة.",
        ],
        "task.gaokao_route.prerequisites": [],
        "task.gaokao_route.acceptance": [
            "تم تسجيل المسار الرسمي (أو عدم وجود مسار مباشر) مع مصدره",
            "تم تحديد الخطوة التالية للمؤهل من الصفحة الرسمية",
        ],
        "task.gaokao_route.alternatives": [
            "إذا لم يُنشر أي مسار لهذا البرنامج، فتحقق من المصدر الرسمي نفسه لبرامج أخرى في الجامعة نفسها قبل تغيير الهدف.",
        ],
        "task.gaokao_route.uncertainty": ("درجات Gaokao لا تُحوَّل أبدًا إلى درجات A-level. وإذا لم يُنشر أي "
                                          "مسار، فستبقى القاعدة الأكاديمية غير معروفة حتى يتم تقديم مؤهل "
                                          "آخر مقبول."),
        "task.confirm_test.title": "أكّد متطلب اختبار القبول",
        "task.confirm_test.rationale": "تعذّر تحديد القاعدة {rule_id}: {detail}",
        "task.confirm_test.expected": ("متطلب الاختبار مؤكد من صفحة البرنامج الرسمية — ما إذا كان الاختبار "
                                       "مطلوبًا وما إذا كان حد الدرجة منشورًا — مسجَّل حتى يمكن إعادة "
                                       "التحقق من القاعدة."),
        "task.confirm_test.steps": [
            "اقرأ صفحة البرنامج الرسمية المرتبطة أدناه لمعرفة ما هو متطلب الاختبار فعلًا.",
            "تحقق مما إذا كان حد الدرجة منشورًا؛ وإذا لم يكن منشورًا فسجّل ذلك.",
            "إذا كان الاختبار مطلوبًا، فأكّد موعد الاختبار وطريقة التسجيل من صفحة مزود الاختبار الرسمية.",
        ],
        "task.confirm_test.prerequisites": [],
        "task.confirm_test.acceptance": [
            "تم تسجيل متطلب الاختبار (مطلوب أم لا) مع مصدره",
            "تم تسجيل حد الدرجة أو تسجيله على أنه غير منشور",
        ],
        "task.confirm_test.alternatives": [
            "إذا لم يُنشر أي حد، فاسأل مكتب القبول في الجامعة مباشرة وسجّل الرد.",
        ],
        "task.confirm_test.uncertainty": ("لم يُذكر أي حد للدرجة في المصادر الموثقة، لذا فإن هذه المهمة يمكنها "
                                          "فقط تأكيد المتطلب وليس الدرجة المستهدفة. رسوم الاختبار غير "
                                          "موجودة في المصادر الموثقة."),
        "task.experience_evidence.title": "سجّل خبرة تكنولوجيا المعلومات الحالية للقاعدة الأكاديمية",
        "task.experience_evidence.rationale": "تعذّر تحديد القاعدة {rule_id}: {detail}",
        "task.experience_evidence.expected": ("إجمالي سنوات خبرة تكنولوجيا المعلومات المكتسبة بالفعل، مع الأدلة "
                                              "الحالية عليها، مقدَّمة حتى يتمكن المحرك من إعادة التحقق من القاعدة."),
        "task.experience_evidence.steps": [
            "حدّد أدوار تكنولوجيا المعلومات التي شغلتها بالفعل مع التواريخ والمهام، من السجلات الحالية.",
            "اجمع أدلة التوظيف الحالية لتلك الأدوار.",
            "قدّم إجمالي سنوات خبرة تكنولوجيا المعلومات في الخطة لإعادة التحقق.",
        ],
        "task.experience_evidence.prerequisites": [
            "سجلات التوظيف الحالية للأدوار التي شغلتها بالفعل",
        ],
        "task.experience_evidence.acceptance": [
            "تم تحديد أدوار تكنولوجيا المعلومات التي شغلتها بالفعل مع التواريخ",
            "تم تقديم إجمالي سنوات خبرة تكنولوجيا المعلومات لإعادة التحقق",
        ],
        "task.experience_evidence.alternatives": [
            "إذا لم تكن لديك خبرة في تكنولوجيا المعلومات، فلا يمكن استيفاء القاعدة الأكاديمية عبر هذا المسار؛ راجع الصفحة الرسمية للاطلاع على المسارات الأخرى المذكورة.",
        ],
        "task.experience_evidence.uncertainty": ("يمكن تسجيل الخبرة المكتسبة بالفعل فقط؛ هذه المهمة لا تُنشئ وظيفة "
                                                "جديدة. وستبقى القاعدة غير معروفة حتى يتم تقديم رقم الخبرة."),
        "task.strengthen_margin.title": "ابنِ هامشًا فوق الحد الأدنى المطلوب",
        "task.strengthen_margin.rationale": "فجوة تنافسية فقط: {detail} القاعدة مستوفاة بالفعل؛ هذه المهمة تضيف فقط هامشًا فوق الحد الأدنى.",
        "task.strengthen_margin.expected": ("درجة أو مبلغ ميزانية فوق الحد الأدنى المطلوب، حتى يكون للقاعدة "
                                           "هامش عند إعادة التحقق. استيفاء الحد الأدنى يفي بالقاعدة بالفعل."),
        "task.strengthen_margin.steps": [
            "قرر ما إذا كان الهامش الإضافي يستحق الوقت قبل الموعد النهائي.",
            "إذا كان الأمر كذلك، فتدرّب على المهارة ذات الصلة أو راجع الميزانية لمعرفة الهامش المتاح.",
            "قدّم الدرجة أو الرقم الجديد لإعادة التحقق.",
        ],
        "task.strengthen_margin.prerequisites": [],
        "task.strengthen_margin.acceptance": [
            "تم تسجيل القرار بشأن الهامش الإضافي",
            "تم تقديم درجة أو مبلغ ميزانية جديد لإعادة التحقق، إذا تم السعي لذلك",
        ],
        "task.strengthen_margin.alternatives": [
            "تخطَّ هذه المهمة: القاعدة مستوفاة بالفعل، لذا لا يلزم أي إجراء قبل الموعد النهائي.",
        ],
        "task.strengthen_margin.uncertainty": "الهامش الإضافي اختياري: القاعدة مستوفاة بالفعل. لا يُوعد بأي أثر على القبول.",
        "task.confirm_evidence.title": "قدّم الدليل المفقود للقاعدة {rule_id}",
        "task.confirm_evidence.rationale": "تعذّر تحديد القاعدة {rule_id}: {detail}",
        "task.confirm_evidence.expected": "الدرجة أو المستند أو التأكيد المفقود مقدَّم، حتى يتمكن المحرك من تحديد هذه القاعدة.",
        "task.confirm_evidence.steps": [
            "اقرأ تفاصيل القاعدة لمعرفة ما المفقود بالضبط.",
            "اجمع المستند أو الدرجة التي تطلبها صفحة البرنامج الرسمية.",
            "قدّم ذلك في الخطة حتى يتمكن المحرك من إعادة التحقق من القاعدة.",
        ],
        "task.confirm_evidence.prerequisites": [],
        "task.confirm_evidence.acceptance": [
            "تم تحديد العنصر المفقود من تفاصيل القاعدة",
            "تم تقديم الدرجة أو المستند أو التأكيد المفقود لإعادة التحقق",
        ],
        "task.confirm_evidence.alternatives": [
            "إذا تعذّر تقديم العنصر قبل الموعد النهائي، فسجّل ذلك وأبقِ القاعدة غير معروفة.",
        ],
        "task.confirm_evidence.uncertainty": "حتى يتم تقديم الدليل المفقود، ستبقى هذه القاعدة غير معروفة.",
        "task.academic_prep.title": "استعد للمتطلب الأكاديمي",
        "task.academic_prep.rationale": "القاعدة {rule_id} غير مستوفاة: {detail}",
        "task.academic_prep.expected": "دليل مؤهل جديد يستوفي المتطلب الأكاديمي المطلوب، مقدَّم حتى يتمكن المحرك من إعادة التحقق من القاعدة.",
        "task.academic_prep.steps": [
            "اقرأ المتطلب الأكاديمي على صفحة البرنامج الرسمية المرتبطة أدناه.",
            "حدّد الموضوعات أو الدرجات التي تذكرها الصفحة.",
            "ادرس الموضوعات المحددة وسجّل العمل المنجز.",
            "قدّم أي دليل مؤهل جديد لإعادة التحقق.",
        ],
        "task.academic_prep.prerequisites": [],
        "task.academic_prep.acceptance": [
            "تم تحديد المتطلب الأكاديمي المطلوب من الصفحة الرسمية",
            "اكتمل العمل التحضيري وتم تسجيله",
            "تم تقديم دليل مؤهل جديد لإعادة التحقق، إن وجد",
        ],
        "task.academic_prep.alternatives": [
            "إذا تعذّر استيفاء المتطلب الأكاديمي قبل الموعد النهائي، فتحقق من الصفحة الرسمية لمعرفة ما إذا كانت تذكر مسارًا بديلًا.",
        ],
        "task.academic_prep.uncertainty": "الإعداد وحده لا يغيّر القاعدة؛ فقط دليل مؤهل جديد يمكنه ذلك.",
        "assume.complete": "إكمال مهمة لا يغيّر الأهلية؛ يتغير وضع القاعدة فقط عند تأكيد درجات أو أدلة جديدة وإعادة حسابها بواسطة المحرك.",
        "assume.hours": "الساعات الأسبوعية لكل مهمة تناسب القدرة المذكورة؛ يتم جدولة المهام بحيث تبقى ساعات أي أسبوع ضمن تلك القدرة.",
        "assume.cost": "التكاليف صفر ما لم يذكر نطاق التكلفة خلاف ذلك؛ رسوم الاختبار غير موجودة في المصادر الموثقة، لذا فإن أي مهمة تتضمن اختبارًا تذكر تكلفتها على أنها غير معروفة.",
        "assume.no_provider": "لم يتم تكوين أي مزود ذكاء اصطناعي، لذا فإن هذه المهام قوالب حتمية مبنية على تقييم الفجوات وليست نصًا مولّدًا بواسطة نموذج.",
        "assume.provider_failed": "فشل الاتصال بمزود الذكاء الاصطناعي، لذا فإن هذه المهام قوالب حتمية مبنية على تقييم الفجوات.",
        "assume.validation_failed": "لم يجتز ناتج النموذج التحقق، لذا فإن هذه المهام قوالب حتمية مبنية على تقييم الفجوات.",
        "limit.based_only": "تعتمد هذه الخطة فقط على نتائج قواعد المحرك والمصادر الموثقة في كتالوج الأدلة؛ لا يُوعد بأي أثر على القبول ولا تُذكر أي نسبة تحسين.",
        "limit.urls": "تستخدم المهام فقط روابط من كتالوج الأدلة؛ وعند عدم وجود مورد موثق، تقدم المهمة معايير بحث بدلًا من رابط.",
        "limit.unknown": "تبقى القواعد غير المعروفة غير معروفة حتى يتم تقديم الدليل المفقود.",
        "reassess.empty_patch": "لا تغييرات: كان تحديث الملف فارغًا، لذا لم تتم إعادة تقييم أي شيء.",
        "reassess.no_change": "لا تغييرات: لم يغيّر التحديث أي وضع قاعدة أو أي فجوة.",
        "reassess.note": ("أعادت إعادة التقييم حساب {n_programs} من البرامج: تغيّرت {n_changes} "
                          "من القواعد، وبقيت {n_gaps} من الفجوات، منها {n_unknowns} للتأكيد. "
                          "إكمال المهام وحده لا يغيّر أي قاعدة أبدًا؛ فقط إعادة حساب المحرك "
                          "أعلاه هي ما يُحتسب."),
        "task.user_statement_note": "بيان المستخدم فقط. ليس دليلًا موثقًا ولا يغيّر أي وضع قاعدة؛ فقط إعادة التقييم التي يعيد المحرك حسابها يمكنها ذلك.",
    },
}


def _plan_strings(locale: str) -> dict:
    return _PLAN_STRINGS.get(locale) or _PLAN_STRINGS["en"]


def _plan_fill(template: str, **values) -> str:
    """Substitute {name} placeholders without str.format: a value (e.g. an
    engine detail) may itself contain braces."""
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", str(value))
    return out


def _plan_str(locale: str, key: str, **values) -> str:
    return _plan_fill(_plan_strings(locale)[key], **values)


def _plan_list(locale: str, key: str) -> list[str]:
    return list(_plan_strings(locale)[key])


def _plan_comp(locale: str, component: str) -> str:
    return _plan_strings(locale).get(f"comp.{component}", component)


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


def _barely_met(rule, locale: str = "en") -> str | None:
    """Why a MET rule is only barely met, or None if it is not barely met.

    Barely met = IELTS overall or a component exactly at the minimum, or
    a budget within 10% of the fee. The reason renders in ``locale``
    (Round 14); the numbers come from the engine unchanged.
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
                return _plan_str(locale, "barely.fee",
                                 obs=f"{obs:g}", fee=f"{fee_val:g}")
        return None
    # IELTS overall exactly at the minimum.
    obs = _num(observed)
    if obs is not None:
        for key in ("overall",):
            if key in threshold and obs == _num(threshold[key]):
                return _plan_str(locale, "barely.overall", obs=f"{obs:g}")
        return None
    # IELTS components: a component exactly at its minimum.
    if isinstance(observed, dict):
        each = _num(threshold.get("each_component"))
        if each is not None:
            at_min = [k for k, v in observed.items()
                      if _num(v) is not None and _num(v) == each]
            if at_min:
                return _plan_str(
                    locale, "barely.components",
                    comps=", ".join(_plan_comp(locale, k) for k in at_min),
                    each=f"{each:g}")
        for key, val in threshold.items():
            if key in observed and _num(observed[key]) == _num(val):
                return _plan_str(locale, "barely.component",
                                 comp=_plan_comp(locale, key), val=f"{_num(val):g}")
    return None


def diagnose_gaps(profile: StudentProfile, evaluations: list[Evaluation],
                  deadline: str | None = None,
                  weekly_hours: float | None = None,
                  budget: dict | None = None,
                  locale: str = "en") -> dict:
    """Deterministic gap diagnosis from engine evaluations.

    Every NOT_MET rule -> hard_requirement gap; every UNKNOWN rule ->
    to_confirm gap; a MET rule met only barely -> competitiveness gap,
    clearly labelled as such. The ``what_is_missing`` prose renders in
    ``locale`` (Round 14); ``current_state`` stays the engine's own
    rule detail text.
    """
    gaps: list[dict] = []
    for ev in evaluations:
        for rule in ev.results:
            if rule.status == "NOT_MET":
                evidence_class = "hard_requirement"
                missing = _plan_str(
                    locale, "gap.not_met",
                    thr=_fmt_threshold(rule.threshold),
                    obs=_fmt_observed(rule.observed))
            elif rule.status == "UNKNOWN":
                evidence_class = "to_confirm"
                missing = _plan_str(locale, "gap.unknown")
            elif rule.status == "MET":
                reason = _barely_met(rule, locale)
                if reason is None:
                    continue
                evidence_class = "competitiveness"
                missing = _plan_str(locale, "gap.competitiveness",
                                    reason=reason)
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


def _program_resource(program: dict | None, catalogue: list,
                      locale: str = "en") -> dict:
    if program is not None:
        for s in catalogue:
            if s.id.startswith(f"src:{program['id']}:") and s.url:
                return {"label": _plan_str(
                    locale, "res.program",
                    name=program.get("official_name") or program["id"]),
                    "url": s.url, "search_criteria": None}
    return {"label": _plan_str(locale, "res.program_fallback"),
            "url": None,
            "search_criteria": "official programme entry requirements"}


def _gaokao_resource(program: dict | None, catalogue: list,
                     locale: str = "en") -> dict:
    for s in catalogue:
        if s.id.startswith("gaokao-") and s.url:
            return {"label": _plan_str(locale, "res.gaokao", title=s.title),
                    "url": s.url, "search_criteria": None}
    name = (program or {}).get("institution") or "the university"
    return {"label": _plan_str(locale, "res.gaokao_fallback"),
            "url": None,
            "search_criteria": f"{name} Gaokao entry requirements official site"}


def _finish_note(duration_weeks: int, deadline: str | None,
                 alternatives: list[str], locale: str = "en") -> str:
    """Deadline feasibility note; also guarantees a short-term alternative."""
    weeks_left = _weeks_until(deadline)
    if deadline is None:
        return _plan_str(locale, "finish.none")
    if weeks_left is None:
        return ""
    if duration_weeks > weeks_left:
        return _plan_str(locale, "finish.too_long", dur=duration_weeks,
                         left=weeks_left, deadline=deadline)
    return _plan_str(locale, "finish.fits", left=weeks_left,
                     deadline=deadline, dur=duration_weeks)



# Per-kind template numbers (hours / cost / duration) and resource
# composition. The human-readable text comes from _PLAN_STRINGS;
# only the search criteria stay English (they are search queries).
_TEMPLATE_TASK_SPECS = {
    "ielts_writing": {"hours": 5, "cost": (0, None, None), "duration": 4,
                      "resources": ("program", "ielts_writing")},
    "ielts_general": {"hours": 6, "cost": (0, None, None), "duration": 6,
                      "resources": ("program", "ielts_general")},
    "budget": {"hours": 2, "cost": (0, 0, "currency"), "duration": 2,
               "resources": ("program", "funding")},
    "gaokao_route": {"hours": 2, "cost": (0, 0, "currency"), "duration": 2,
                     "resources": ("gaokao", "program")},
    "confirm_test": {"hours": 2, "cost": (0, None, None), "duration": 2,
                     "resources": ("program", "test_provider")},
    "experience_evidence": {"hours": 3, "cost": (0, 0, "currency"),
                            "duration": 4, "resources": ("program",)},
    "strengthen_margin": {"hours": 4, "cost": (0, None, None), "duration": 4,
                          "resources": ("program", "prep")},
    "confirm_evidence": {"hours": 2, "cost": (0, 0, "currency"), "duration": 2,
                         "resources": ("program",)},
    "academic_prep": {"hours": 6, "cost": (0, 0, "currency"), "duration": 6,
                      "resources": ("program",)},
}

# Search criteria for the non-URL resources (English search queries).
_TEMPLATE_SEARCH = {
    "ielts_writing": "IELTS official writing practice materials band descriptors",
    "ielts_general": "IELTS official practice test materials",
    "test_provider": "official admissions test registration requirements",
    "prep": "official preparation material for the stated minimum",
}


def _template_resource(kind: str, program: dict | None, catalogue: list,
                       locale: str, institution: str = "") -> dict:
    if kind == "program":
        return _program_resource(program, catalogue, locale)
    if kind == "gaokao":
        return _gaokao_resource(program, catalogue, locale)
    if kind == "funding":
        return {"label": _plan_str(locale, "res.funding"),
                "url": None,
                "search_criteria": (f"scholarships funding international students "
                                    f"{institution}").strip()}
    return {"label": _plan_str(locale, f"res.{kind}"),
            "url": None, "search_criteria": _TEMPLATE_SEARCH[kind]}


def _template_task(gap: dict, programs_by_id: dict, deadline: str | None,
                   weekly_hours: float | None, budget: dict | None,
                   catalogue: list, locale: str = "en") -> dict:
    """One deterministic template task for a gap. Never invents a URL,
    an activity, or an admission effect.

    The human-readable text comes from _PLAN_STRINGS and renders in
    ``locale`` (Round 14); the numbers below (hours / cost / duration)
    and the resource composition are the same in every locale. Search
    criteria stay English: they are search queries, not prose."""
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

    spec = _TEMPLATE_TASK_SPECS[kind]
    cost_min, cost_max, cost_ccy = spec["cost"]
    institution = (program or {}).get("institution") or ""
    task = {
        "task_id": f"task-{gap['gap_id']}",
        "gap_id": gap["gap_id"],
        "category": category,
        "target_program_ids": [gap["program_id"]] if gap.get("program_id") else [],
        "current_state": detail,
        "deadline": deadline,
        "title": _plan_str(locale, f"task.{kind}.title", rule_id=rule_id),
        "rationale": _plan_str(locale, f"task.{kind}.rationale",
                               rule_id=rule_id, detail=detail),
        "expected_outcome": _plan_str(locale, f"task.{kind}.expected"),
        "steps": _plan_list(locale, f"task.{kind}.steps"),
        "resources": [_template_resource(kind_name, program, catalogue,
                                         locale, institution)
                      for kind_name in spec["resources"]],
        "weekly_hours": _hours(spec["hours"], weekly_hours),
        "cost_range": {"min": cost_min, "max": cost_max,
                       "currency": currency if cost_ccy == "currency" else None},
        "duration_weeks": spec["duration"],
        "prerequisites": _plan_list(locale, f"task.{kind}.prerequisites"),
        "acceptance_checklist": _plan_list(locale, f"task.{kind}.acceptance"),
        "alternatives": _plan_list(locale, f"task.{kind}.alternatives"),
        "uncertainty": _plan_str(locale, f"task.{kind}.uncertainty"),
    }
    note = _finish_note(task["duration_weeks"], deadline,
                        task["alternatives"], locale)
    task["uncertainty"] = f"{task['uncertainty']} {note}".strip()
    task["status"] = "todo"
    return task


def _template_tasks(gap_assessment: dict, programs_by_id: dict,
                    deadline: str | None, weekly_hours: float | None,
                    budget: dict | None, catalogue: list,
                    locale: str = "en") -> list[dict]:
    return [_template_task(gap, programs_by_id, deadline, weekly_hours,
                           budget, catalogue, locale)
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
    replacement keeps every gap covered.

    Round 13 fail-fast: ONE attempt with a 15 s budget, no repair
    retry. The old 12 s attempt + 12 s repair stacked to ~24 s of
    synchronous blocking, sitting exactly on the frontend's 25 s
    attempt-abort boundary — and the repair could only return after
    the caller had given up. A provider failure returns (None, False)
    so the caller falls back to templates; a validation failure
    returns the template tasks directly (model_used=False), keeping
    the caller's "did not pass validation" wording.
    """
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
                                   timeout_s=15.0)
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
        # Validation failure: no repair retry (Round 13) — the
        # template tasks cover every gap instead.
        return _template_tasks(gap_assessment, programs_by_id, deadline,
                               weekly_hours, budget, catalogue, locale), False

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
                                       weekly_hours, budget, catalogue, locale))
    return kept, model_used


def build_tasks_with_status(gap_assessment: dict,
                            evaluations: list[Evaluation],
                            programs: list[dict],
                            deadline: str | None,
                            weekly_hours: float | None,
                            budget: dict | None,
                            locale: str,
                            provider: ProviderAdapter | None) -> tuple[list[dict], str, list[str], list[str]]:
    """Returns (tasks, ai_status, assumptions, limitations).

    Template tasks and the assumptions / limitations render in
    ``locale`` (Round 14); the model path already answers in the
    requested locale via plan_system(locale).
    """
    program_ids = [p["id"] for p in programs]
    programs_by_id = {p["id"]: p for p in programs}
    catalogue = _evidence_catalog(program_ids)
    assumptions = [
        _plan_str(locale, "assume.complete"),
        _plan_str(locale, "assume.hours"),
        _plan_str(locale, "assume.cost"),
    ]
    limitations = [
        _plan_str(locale, "limit.based_only"),
        _plan_str(locale, "limit.urls"),
        _plan_str(locale, "limit.unknown"),
    ]
    if provider is None or not provider.available:
        tasks = _template_tasks(gap_assessment, programs_by_id, deadline,
                                weekly_hours, budget, catalogue, locale)
        assumptions.insert(0, _plan_str(locale, "assume.no_provider"))
        return tasks, "unavailable", assumptions, limitations
    tasks, model_used = _model_tasks(
        gap_assessment, evaluations, programs, deadline, weekly_hours,
        budget, locale, provider, catalogue)
    if tasks is None:
        tasks = _template_tasks(gap_assessment, programs_by_id, deadline,
                                weekly_hours, budget, catalogue, locale)
        assumptions.insert(0, _plan_str(locale, "assume.provider_failed"))
        return tasks, "unavailable", assumptions, limitations
    if not model_used:
        assumptions.insert(0, _plan_str(locale, "assume.validation_failed"))
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
    verdict). v2 programmes use their hand-written evaluator; matchable
    expansion programmes use the generic expansion evaluator. A
    display-only programme raises ProgramNotEvaluable and an unknown id
    raises a PROGRAM_NOT_FOUND PlanError — never a silent empty plan."""
    evaluations = []
    for pid in program_ids:
        program = resolve_program(pid)
        if program is None:
            if program_is_display_only(pid):
                raise ProgramNotEvaluable(pid)
            raise PlanError(f"No program with id '{pid}'.",
                            code="PROGRAM_NOT_FOUND", status=404)
        if pid in PROGRAMS:
            results = evaluate(profile, program)
        else:
            results = evaluate_expansion(profile, program)
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
                                   weekly_hours, budget, locale)
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
            "note": _plan_str(plan.get("locale") or "en",
                              "task.user_statement_note"),
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
    # Reassessment text renders in the plan's own locale (Round 14).
    locale = plan.get("locale") or "en"
    current_version = plan["versions"][-1]["version"]
    current_gaps = plan["gap_assessment"].get("gaps", [])
    unknowns = [g["gap_id"] for g in current_gaps
                if g.get("evidence_class") == "to_confirm"]

    def _no_change(note: str, changes: list | None = None) -> dict:
        return {"plan_id": plan_id, "new_version": current_version,
                "changes": changes or [], "remaining_gaps": copy.deepcopy(current_gaps),
                "unknowns": unknowns, "note": note}

    if not profile_patch:
        return _no_change(_plan_str(locale, "reassess.empty_patch"))
    _validate_patch_keys(profile_patch)
    merged = copy.deepcopy(plan["profile"])
    _deep_merge(merged, profile_patch)
    try:
        profile = StudentProfile(**merged)
    except Exception as exc:
        raise InvalidPatch(f"Patched profile is invalid: {exc}")
    programs = [resolve_program(pid) for pid in plan["program_ids"]]
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
        plan.get("budget"), locale)
    new_gaps = new_gap_assessment.get("gaps", [])
    gaps_same = ([(g["gap_id"], g["evidence_class"]) for g in new_gaps]
                 == [(g["gap_id"], g["evidence_class"]) for g in current_gaps])
    if not changes and gaps_same:
        return _no_change(_plan_str(locale, "reassess.no_change"),
                          changes=[])
    # New version: template tasks for the new gaps, preserving the status
    # of tasks that survive (same task_id) from the previous version.
    old_tasks = {t["task_id"]: t for t in plan["tasks"]}
    catalogue = _evidence_catalog(plan["program_ids"])
    programs_by_id = {p["id"]: p for p in programs}
    new_tasks = _template_tasks(new_gap_assessment, programs_by_id,
                                plan.get("deadline"), plan.get("weekly_hours"),
                                plan.get("budget"), catalogue, locale)
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
    note = _plan_str(locale, "reassess.note",
                     n_programs=len(plan["program_ids"]),
                     n_changes=len(changes), n_gaps=len(new_gaps),
                     n_unknowns=len(new_unknowns))
    return {"plan_id": plan_id, "new_version": new_version,
            "changes": changes,
            "remaining_gaps": copy.deepcopy(new_gaps),
            "unknowns": new_unknowns, "note": note}

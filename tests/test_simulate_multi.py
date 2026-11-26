"""Multi-change what-if simulation + highest-leverage diagnosis.

Covers the /simulate flat contract extension (scenarios + leverage +
explanation), backward compatibility of the old single-patch and nested
contracts, and the citation-check failure -> template fallback of the
delta explanation. Runs without an AI key (template mode).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from ai.grounding import programme_sources
from ai.simulate_explain import explain_simulation, leverage_candidates
from app.data import EXPANSION_MATCHABLE
from app.main import app

client = TestClient(app)

# Undergraduate, A-levels, IELTS writing 5.5 (below UCL's 6.0 component
# minimum), budget GBP 50,000 (above UCL's GBP 48,600 overseas fee).
UG_FLAT = {
    "track": "undergraduate", "targetProgramIds": ["ucl-cs-bsc-2026"],
    "alevels": "A*A*A", "mathsGrade": "A*",
    "ieltsOverall": 7.0, "ieltsListening": 6.5, "ieltsReading": 6.5,
    "ieltsWriting": 5.5, "ieltsSpeaking": 6.5,
    "budget": 50000, "budgetCurrency": "GBP",
}

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


def _ug_ids() -> list[str]:
    return ["ucl-cs-bsc-2026", "imperial-comp-beng-2027",
            "nus-bcomp-cs-2027", "ntu-bcomp-cs-2027"] + [
        pid for pid, p in EXPANSION_MATCHABLE.items()
        if p.get("degree_level") == "undergraduate"]


# --- Multi-scenario ---------------------------------------------------------

def test_multi_scenarios_delta_correctness():
    r = client.post("/api/v1/simulate", json={
        "baseline_profile": UG_FLAT,
        "scenarios": [{"name": "writing", "patch": {"ieltsWriting": 6.5}},
                      {"name": "overall", "patch": {"ieltsOverall": 8.0}}],
        "program_ids": ["ucl-cs-bsc-2026"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["scenarios"]) == 2
    writing, overall = body["scenarios"]
    # Writing 5.5 -> 6.5 flips the component rule; overall alone does not.
    assert {"program_id": "ucl-cs-bsc-2026", "rule_id": "ucl-ielts-components",
            "baseline_status": "NOT_MET", "scenario_status": "MET"} in writing["delta"]
    assert writing["rule_flip_count"] == 1
    assert writing["flipped_program_ids"] == ["ucl-cs-bsc-2026"]
    assert overall["delta"] == []
    assert overall["rule_flip_count"] == 0
    assert overall["flipped_program_ids"] == []
    # Backward-compat keys carry the first scenario.
    assert body["scenario"] == writing["scenario"]
    assert body["delta"] == writing["delta"]
    base = {x["ruleId"]: x for x in body["baseline"]["results"][0]["ruleResults"]}
    assert base["ucl-ielts-components"]["status"] == "NOT_MET"

def test_multi_scenarios_programme_flip_summary():
    r = client.post("/api/v1/simulate", json={
        "baseline_profile": UG_FLAT,
        "scenarios": [{"name": "writing", "patch": {"ieltsWriting": 6.5}}],
        "program_ids": ["ucl-cs-bsc-2026"]})
    assert r.status_code == 200, r.text
    scen = r.json()["scenarios"][0]
    assert scen["programme_flips"] == [
        {"program_id": "ucl-cs-bsc-2026",
         "baseline_summary": "NOT_MET", "scenario_summary": "PARTIAL_UNKNOWN"}]
    assert r.json()["baseline"]["results"][0]["eligibilitySummary"] == "NOT_MET"
    # All known minimums are met after the fix; only TARA stays UNKNOWN,
    # so the summary is PARTIAL_UNKNOWN, never fully MET.
    assert scen["scenario"]["results"][0]["eligibilitySummary"] == "PARTIAL_UNKNOWN"
    assert scen["flipped_to_met_ids"] == []


def test_multi_scenarios_bad_shape_422():
    # A non-object patch, and an empty scenarios list, are validation
    # errors, not a 500. A scenario with no patch at all is leniently
    # treated as an empty patch.
    r = client.post("/api/v1/simulate", json={
        "baseline_profile": UG_FLAT,
        "scenarios": [{"name": "x", "patch": "not-a-dict"}],
        "program_ids": ["ucl-cs-bsc-2026"]})
    assert r.status_code == 422, r.text
    r = client.post("/api/v1/simulate", json={
        "baseline_profile": UG_FLAT, "scenarios": [],
        "program_ids": ["ucl-cs-bsc-2026"]})
    assert r.status_code == 422, r.text


# --- Leverage ---------------------------------------------------------------

def test_leverage_candidates_only_evaluable_fields():
    cands = leverage_candidates(AUDIT_FLAT)
    assert [c["id"] for c in cands] == [
        "ielts-overall-plus-0.5", "ielts-writing-plus-0.5",
        "budget-plus-10000", "budget-plus-5000"]
    # No Gaokao candidate: no published equivalence, academic stays UNKNOWN.
    assert not any("gaokao" in c["id"] for c in cands)
    assert cands[0]["change"] == {"field": "ieltsOverall", "from": 7.0, "to": 7.5}
    assert cands[2]["change"] == {"field": "budget", "from": 50000, "to": 60000}
    # Missing baseline values offer no candidate.
    assert leverage_candidates({"track": "undergraduate", "budget": 1000}) == [
        {"id": "budget-plus-10000", "patch": {"budget": 11000},
         "change": {"field": "budget", "from": 1000, "to": 11000}},
        {"id": "budget-plus-5000", "patch": {"budget": 6000},
         "change": {"field": "budget", "from": 1000, "to": 6000}}]


def test_leverage_ranking_writing_is_top():
    r = client.post("/api/v1/simulate", json={
        "baseline_profile": UG_FLAT,
        "scenarios": [{"name": "writing", "patch": {"ieltsWriting": 6.5}}],
        "program_ids": ["ucl-cs-bsc-2026"]})
    assert r.status_code == 200, r.text
    lev = r.json()["leverage"]
    assert [c["id"] for c in lev["all"]] == [
        "ielts-overall-plus-0.5", "ielts-writing-plus-0.5",
        "budget-plus-10000", "budget-plus-5000"]
    by_id = {c["id"]: c for c in lev["all"]}
    # Writing +0.5 unblocks the programme (all known minimums met; TARA
    # stays UNKNOWN so it is PARTIAL_UNKNOWN, not fully MET).
    assert by_id["ielts-writing-plus-0.5"]["flips"] == 1
    assert by_id["ielts-writing-plus-0.5"]["flipped_program_ids"] == ["ucl-cs-bsc-2026"]
    assert by_id["ielts-writing-plus-0.5"]["flips_to_met"] == 0
    assert by_id["ielts-overall-plus-0.5"]["flips"] == 0
    assert by_id["budget-plus-10000"]["flips"] == 0
    assert by_id["budget-plus-5000"]["flips"] == 0
    assert lev["top"]["id"] == "ielts-writing-plus-0.5"
    assert r.json()["explanation"]["top_change"] == "ielts-writing-plus-0.5"


def test_leverage_budget_rule_flips_without_programme_flip():
    low_budget = {**UG_FLAT, "budget": 40000}
    r = client.post("/api/v1/simulate", json={
        "baseline_profile": low_budget,
        "scenarios": [{"name": "none", "patch": {}}],
        "program_ids": ["ucl-cs-bsc-2026"]})
    assert r.status_code == 200, r.text
    by_id = {c["id"]: c for c in r.json()["leverage"]["all"]}
    # Budget +10k flips the fee rule, but writing still blocks the programme.
    assert by_id["budget-plus-10000"]["rule_flips"] == 1
    assert by_id["budget-plus-10000"]["flips"] == 0
    assert by_id["budget-plus-5000"]["rule_flips"] == 0  # 45,000 < 48,600
    # Writing +0.5 flips exactly one rule too, so the two levers tie and
    # the spec-order tie-break picks writing.
    assert by_id["ielts-writing-plus-0.5"]["rule_flips"] == 1
    assert r.json()["leverage"]["top"]["id"] == "ielts-writing-plus-0.5"


def test_leverage_top_is_none_when_nothing_flips():
    rich = {**UG_FLAT, "ieltsWriting": 7.0, "budget": 90000}
    r = client.post("/api/v1/simulate", json={
        "baseline_profile": rich,
        "scenarios": [{"name": "none", "patch": {}}],
        "program_ids": ["ucl-cs-bsc-2026"]})
    assert r.status_code == 200, r.text
    lev = r.json()["leverage"]
    assert all(c["flips"] == 0 and c["rule_flips"] == 0 for c in lev["all"])
    assert lev["top"] is None
    assert r.json()["explanation"]["top_change"] is None


# --- Audit profile ----------------------------------------------------------

def test_audit_profile_leverage_no_programme_flip():
    """Gaokao audit profile, all 369 UG programmes: academic stays
    UNKNOWN everywhere (no published Gaokao equivalence), so no candidate
    flips any programme to fully MET (flips_to_met is 0 throughout) —
    but budget +10k unblocks the most programmes (fees) and flips the
    most rules, so it is the top lever."""
    r = client.post("/api/v1/simulate", json={
        "baseline_profile": AUDIT_FLAT,
        "scenarios": [{"name": "budget10k", "patch": {"budget": 60000}}],
        "program_ids": _ug_ids()})
    assert r.status_code == 200, r.text
    body = r.json()
    lev = body["leverage"]
    assert all(c["flips_to_met"] == 0 for c in lev["all"])
    by_id = {c["id"]: c for c in lev["all"]}
    assert by_id["budget-plus-10000"]["flips"] > by_id["budget-plus-5000"]["flips"] > 0
    assert by_id["budget-plus-10000"]["rule_flips"] > by_id["budget-plus-5000"]["rule_flips"] > 0
    assert lev["top"]["id"] == "budget-plus-10000"
    # The explanation says plainly why nothing becomes fully met.
    assert "UNKNOWN" in body["explanation"]["text"]
    assert body["explanation"]["ai_status"] == "unavailable"
    assert body["explanation"]["source"] == "template"


# --- Backward compatibility -------------------------------------------------

def test_backward_compat_single_patch():
    r = client.post("/api/v1/simulate", json={
        "baseline_profile": UG_FLAT, "patch": {"ieltsWriting": 6.5},
        "program_ids": ["ucl-cs-bsc-2026"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert {"program_id": "ucl-cs-bsc-2026", "rule_id": "ucl-ielts-components",
            "baseline_status": "NOT_MET", "scenario_status": "MET"} in body["delta"]
    # All known minimums met; TARA stays UNKNOWN so the summary is
    # PARTIAL_UNKNOWN, not fully MET.
    assert body["scenario"]["results"][0]["eligibilitySummary"] == "PARTIAL_UNKNOWN"
    # New keys are additive only.
    assert "leverage" in body and "explanation" in body and "scenarios" in body


def test_backward_compat_nested_contract():
    base = {
        "application_track": "undergraduate",
        "undergrad_profile": {
            "qualification_type": "a_level",
            "a_level_grades": ["A*", "A*", "A"],
            "a_level_maths_grade": "A*", "tara_taken": True},
        "language": {"exam": "ielts", "overall": 7.0, "listening": 6.5,
                     "reading": 6.5, "writing": 6.5, "speaking": 6.5},
        "budget": {"amount": 50000, "currency": "GBP", "period": "per_year"},
    }
    r = client.post("/api/v1/simulate", json={
        "profile": base, "program_id": "ucl-cs-bsc-2026",
        "patch": {"language": {"overall": 6.0}}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["program_id"] == "ucl-cs-bsc-2026"
    assert body["patched"]["overall_status"] == "NOT_MET"


# --- Explanation: model path + citation-check fallback ----------------------

def _scenarios_fixture() -> list[dict]:
    return [{"name": "writing", "patch": {"ieltsWriting": 6.5},
             "delta": [{"program_id": "ucl-cs-bsc-2026",
                        "rule_id": "ucl-ielts-components",
                        "baseline_status": "NOT_MET",
                        "scenario_status": "MET"}],
             "programme_flips": [{"program_id": "ucl-cs-bsc-2026",
                                  "baseline_summary": "NOT_MET",
                                  "scenario_summary": "MET"}],
             "flipped_program_ids": ["ucl-cs-bsc-2026"],
             "rule_flip_count": 1}]


def _leverage_fixture() -> dict:
    cand = {"id": "ielts-writing-plus-0.5",
            "patch": {"ieltsWriting": 6.5},
            "change": {"field": "ieltsWriting", "from": 5.5, "to": 6.5},
            "flips": 1, "flipped_program_ids": ["ucl-cs-bsc-2026"],
            "rule_flips": 1, "flipped_rules": []}
    return {"top": cand, "all": [cand]}


class _FakeProvider:
    """Duck-typed provider: returns the same canned text every call."""
    def __init__(self, text: str):
        self.text = text
        self.available = True
        self.calls = 0

    def chat(self, messages, system=None, timeout_s=None):
        self.calls += 1
        return SimpleNamespace(text=self.text)


def test_explain_template_fallback_on_citation_failure():
    # Model output with a forbidden admission-guarantee phrase fails the
    # citation check (twice: first attempt + repair) -> template.
    bad = json.dumps({"summary": "You are guaranteed admission.",
                      "claims": [{"text": "You are guaranteed admission.",
                                  "kind": "fact", "rule_ids": [],
                                  "evidence_ids": []}]})
    structured, text, status = explain_simulation(
        scenarios=_scenarios_fixture(), leverage=_leverage_fixture(),
        baseline_unknown_academic=False, provider=_FakeProvider(bad))
    assert status == "unavailable"
    assert "rules/template summary" in text
    assert structured["claims"][0]["text"].startswith("Scenario writing:")
    assert "guaranteed" not in text


def test_explain_model_valid_output_used():
    src_id = programme_sources("ucl-cs-bsc-2026")[0].id
    good = json.dumps({
        "summary": "Raising Writing may matter most for this programme.",
        "claims": [{"text": "Raising Writing may flip the component rule to met.",
                    "kind": "inference",
                    "rule_ids": ["ucl-ielts-components"],
                    "evidence_ids": [src_id]}],
        "unknowns": [], "actions": [], "limitations": []})
    provider = _FakeProvider(good)
    structured, text, status = explain_simulation(
        scenarios=_scenarios_fixture(), leverage=_leverage_fixture(),
        baseline_unknown_academic=False, provider=provider)
    assert status == "available", text
    assert "may matter most" in text
    assert provider.calls == 1


def test_explain_template_when_no_provider():
    structured, text, status = explain_simulation(
        scenarios=_scenarios_fixture(), leverage=_leverage_fixture(),
        baseline_unknown_academic=True, provider=None)
    assert status == "unavailable"
    assert "UNKNOWN" in text
    assert structured["unknowns"] and structured["unknowns"][0]["field"] == "academic"


# --- Round 14: leverage scoped to requested scenarios -----------------------

def test_leverage_scoped_to_requested_scenarios_only():
    """Round 14 (re-test task 8): unchecking the IELTS options still
    showed all 4 leverage rows and a top change naming an unchecked
    change. The response's leverage stays the global diagnosis (the
    frontend filters its display to the checked scenarios), but the
    explanation must only name changes actually requested: requesting
    only the budget scenario yields a template summary naming the
    budget change — in the requested locale — and top_change scoped to
    the budget lever. The scenario name is a localised label, so the
    scope keys on the patched field, not the name."""
    r = client.post("/api/v1/simulate", json={
        "baseline_profile": AUDIT_FLAT,
        "scenarios": [{"name": "预算 +£10,000", "patch": {"budget": 60000}}],
        "program_ids": ["mit-cs-sb-2027", "ucl-cs-bsc-2026"],
        "locale": "zh-CN"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["scenarios"]) == 1
    leverage = body["leverage"]
    assert leverage["top"]["id"] == "budget-plus-10000"
    assert leverage["top"]["flips"] == 1  # MIT fee rule flips to MET
    assert body["explanation"]["top_change"] == "budget-plus-10000"
    summary = body["explanation"]["text"]
    assert "预算" in summary
    assert "雅思" not in summary
    assert "mattered most" not in summary


# --- Round 14: simulate template localisation --------------------------------

_ENGLISH_BODY = ["mattered most", "stop being blocked", "Suggestion, not a fact",
                 "No university publishes", "rules/template summary",
                 "No single change", "No change in this simulation"]


def test_simulate_template_renders_zh_cn():
    """Round 14 (re-test task 8): the simulate template rendered in
    English on the Chinese UI. The template explanation and its top
    line now render in the requested locale, with engine numbers
    intact."""
    structured, text, status = explain_simulation(
        scenarios=_scenarios_fixture(), leverage=_leverage_fixture(),
        baseline_unknown_academic=True, locale="zh-CN", provider=None)
    assert status == "unavailable"
    assert "雅思写作" in text  # top change field label, localised
    assert "不再被卡住" in text
    assert "高考" in text
    assert "建议，并非事实" in text
    for phrase in _ENGLISH_BODY:
        assert phrase not in text, phrase
    # Engine numbers survive: the 5.5 -> 6.5 writing step and the flip counts.
    assert "5.5" in text and "6.5" in text
    assert structured["claims"][0]["text"].startswith("方案writing：")


def test_simulate_template_en_default_unchanged():
    """The English template is byte-identical to the pre-Round-14
    hardcoded text (pinned by the Round 12 tests)."""
    structured, text, status = explain_simulation(
        scenarios=_scenarios_fixture(), leverage=_leverage_fixture(),
        baseline_unknown_academic=True, provider=None)
    assert status == "unavailable"
    assert "ieltsWriting 5.5 -> 6.5 mattered most" in text
    assert structured["claims"][0]["text"].startswith("Scenario writing:")
    assert "rules/template summary" in text


def test_simulate_template_all_locales_no_english_body():
    """Every non-English locale renders the template without English
    body prose (status token MET and programme ids stay as-is)."""
    for locale in ("es", "fr", "pt-BR", "ar"):
        _s, text, _st = explain_simulation(
            scenarios=_scenarios_fixture(), leverage=_leverage_fixture(),
            baseline_unknown_academic=True, locale=locale, provider=None)
        for phrase in _ENGLISH_BODY:
            assert phrase not in text, (locale, phrase)
        assert "5.5" in text and "6.5" in text


def test_whynot_endpoint_serves_locale():
    """Round 14: /whynot computed the locale but never passed it to
    compute_whynot, so the endpoint served English regardless."""
    r = client.post("/api/v1/whynot", json={
        "profile": UG_FLAT, "program_ids": ["ucl-cs-bsc-2026"],
        "locale": "zh-CN"})
    assert r.status_code == 200, r.text
    whynot = r.json()["results"][0]["whynot"]
    assert whynot is not None
    assert "未达标" in whynot["template_text"]
    assert "Why ucl-cs-bsc-2026 is not met" not in whynot["template_text"]

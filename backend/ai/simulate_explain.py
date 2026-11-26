"""Multi-change what-if simulation: leverage candidates + delta explanation.

Leverage diagnosis (Day 3): given a flat baseline profile, the only
candidate single-field changes offered are ones the engine actually
evaluates — IELTS overall +0.5, IELTS writing +0.5, budget +GBP 10,000,
budget +GBP 5,000. A candidate is offered only when the baseline value
it changes is present and numeric. Gaokao score changes are NEVER
offered: no university publishes a Gaokao equivalence, so the academic
rule stays UNKNOWN whatever the score, and offering it would pretend
the engine can evaluate it. (The same honesty rule as GaokaoPanel:
no Gaokao % -> A-level conversion exists anywhere.)

Delta explanation: one model call at most, explaining which change
mattered most, grounded on the engine-computed delta via the existing
citation checker (ai.grounding.check_model_output, same chain as
ai/explain.py). Bad model output -> the deterministic template built
from engine numbers. No new endpoint may emit a number, date or
currency the engine did not compute or verify; no admission
probabilities anywhere. The model is explicitly told NOT to put any
number in its text — the server displays the engine-computed numbers
beside the model words, so the user can check them. (A number-bearing
fact claim would fail the numeric cross-check against the cited
evidence anyway, since profile scores/budgets are not in the
programme evidence text.)
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from ai.grounding import (check_model_output, programme_fact_texts,
                          programme_sources, render_structured_explanation)
from ai.prompts import PROMPT_VERSION, explain_system
from ai.provider import ProviderAdapter, ProviderError

# Candidate specs, in display order. ``field`` is the flat-profile key,
# ``delta`` the step. The label lives in the frontend locale files
# (sim.candidateOverall / sim.candidateWriting / sim.candidateBudget10k /
# sim.candidateBudget5k); the id is the stable contract between the
# backend leverage response and the frontend panel.
CANDIDATE_SPECS = (
    {"id": "ielts-overall-plus-0.5", "field": "ieltsOverall", "delta": 0.5},
    {"id": "ielts-writing-plus-0.5", "field": "ieltsWriting", "delta": 0.5},
    {"id": "budget-plus-10000", "field": "budget", "delta": 10000},
    {"id": "budget-plus-5000", "field": "budget", "delta": 5000},
)

# No candidate for Gaokao (see module docstring): a Gaokao change has no
# evaluable rule, so it must never appear as a lever.
_UNEVALUABLE_FIELDS = ("gaokaoScore", "gaokaoTotal", "gaokaoMaths")


def _num(value) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def leverage_candidates(baseline_flat: dict) -> list[dict]:
    """Candidate single-field changes for a flat baseline profile.

    Each candidate is {"id", "patch", "change": {"field", "from", "to"}}.
    Skipped when the baseline value is missing / blank / non-numeric.
    IELTS steps stay on the 0.5 grid; budget steps are whole pounds.
    """
    out: list[dict] = []
    for spec in CANDIDATE_SPECS:
        field = spec["field"]
        if field in _UNEVALUABLE_FIELDS:
            continue
        base = _num((baseline_flat or {}).get(field))
        if base is None:
            continue
        new = base + spec["delta"]
        if field.startswith("ielts"):
            new = round(new * 2) / 2
            if new > 9.0:
                continue
        else:
            new = int(new)
        out.append({"id": spec["id"], "patch": {field: new},
                    "change": {"field": field, "from": base, "to": new}})
    return out


def _fmt_change(change: dict) -> str:
    field, frm, to = change["field"], change["from"], change["to"]
    if field == "budget":
        return f"budget GBP {frm:,} -> GBP {to:,}"
    return f"{field} {frm} -> {to}"


def _top_line(scenarios: list[dict], leverage: dict | None) -> str:
    """One-sentence template summary, from engine numbers only."""
    top = (leverage or {}).get("top") or {}
    if not top:
        if scenarios:
            best = max(scenarios, key=lambda s: (len(s.get("flipped_program_ids") or []),
                                                 s.get("rule_flip_count", 0)))
            if (best.get("rule_flip_count", 0) or 0) == 0 and not best.get("flipped_program_ids"):
                return ("No change in this simulation flips any rule or programme: "
                        "every programme that is not met stays not met, and the "
                        "academic rule stays UNKNOWN where no equivalence is published.")
        return ("No single change in this simulation flips any programme to "
                "fully met.")
    flips = top.get("flips", 0)
    rule_flips = top.get("rule_flips", 0)
    strict_met = top.get("flips_to_met", 0)
    line = (f"{_fmt_change(top['change'])} mattered most: it flips "
            f"{rule_flips} rule(s) to MET and {flips} programme(s) stop "
            f"being blocked (all known minimums met")
    if strict_met:
        line += f", of which {strict_met} become fully MET"
    else:
        line += (", but none becomes fully MET, because an academic or "
                 "admissions-test rule stays UNKNOWN where no equivalence "
                 "or threshold is published")
    return line + ")."


def template_simulate_structured(*, scenarios: list[dict],
                                 leverage: dict | None,
                                 baseline_unknown_academic: bool,
                                 locale: str = "en") -> dict:
    """Deterministic structured explanation, built only from engine numbers.

    ``scenarios`` entries carry name/patch/delta/programme_flips/
    flipped_program_ids/rule_flip_count (the handler's computed delta).
    Claims cite the flipped programmes' first official source id, so a
    reader can follow each claim to a verified page; numbers in the text
    are engine-computed counts and profile deltas, never model output.
    """
    claims: list[dict] = []
    for scen in scenarios:
        name = scen.get("name") or "scenario"
        prog_flips = scen.get("flipped_program_ids") or []
        rule_flips = scen.get("rule_flip_count", 0)
        rule_ids = sorted({d["rule_id"] for d in (scen.get("delta") or [])
                           if d.get("scenario_status") == "MET"
                           and d.get("baseline_status") == "NOT_MET"})
        evidence = []
        for pid in prog_flips[:5]:
            sources = programme_sources(pid)
            if sources:
                evidence.append(sources[0].id)
        text = (f"Scenario {name}: {len(prog_flips)} programme(s) stop being "
                f"blocked (all known minimums met) and {rule_flips} rule(s) "
                f"flip to MET.")
        claims.append({"text": text, "kind": "fact",
                       "rule_ids": rule_ids[:10], "evidence_ids": evidence})
        if len(claims) >= 20:
            break
    unknowns: list[dict] = []
    if baseline_unknown_academic:
        unknowns.append({
            "field": "academic",
            "reason": ("No university publishes a Gaokao equivalence, so the "
                       "academic rule stays UNKNOWN whatever the Gaokao score."),
            "question": "Which foundation or alternative route does each "
                        "university publish for Gaokao applicants?"})
    actions: list[dict] = []
    top = (leverage or {}).get("top") or {}
    if top:
        actions.append({
            "explanation": (f"Suggestion, not a fact: consider "
                            f"{_fmt_change(top['change'])} first — it flips "
                            f"{top.get('rule_flips', 0)} rule(s) to MET."),
            "evidence_ids": []})
    limitations = [
        "This is a rules/template summary from the engine's own numbers, "
        "not model-generated text. No admission probabilities are given; "
        "unknown stays unknown.",
    ]
    return {"summary": _top_line(scenarios, leverage), "claims": claims,
            "unknowns": unknowns, "actions": actions,
            "limitations": limitations}


def template_simulate_text(structured: dict) -> str:
    lines = [structured.get("summary", "")]
    for claim in structured.get("claims", []):
        lines.append(f"- {claim.get('text', '')}")
    for u in structured.get("unknowns", []):
        lines.append(f"- Unknown: {u.get('field', '')} — {u.get('reason', '')}")
    for a in structured.get("actions", []):
        lines.append(f"- Next: {a.get('explanation', '')}")
    for lim in structured.get("limitations", []):
        lines.append(f"- Limitation: {lim}")
    return "\n".join(line for line in lines if line.strip())


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


def _model_explain_simulation(*, scenarios, leverage,
                              baseline_unknown_academic, locale,
                              provider) -> dict | None:
    """One model attempt + one repair attempt; validated output or None."""
    involved: list[str] = []
    for scen in scenarios:
        involved.extend(scen.get("flipped_program_ids") or [])
    top = (leverage or {}).get("top") or {}
    for cand in (leverage or {}).get("all") or []:
        involved.extend(cand.get("flipped_program_ids") or [])
    involved = list(dict.fromkeys(involved))[:10]
    sources = []
    for pid in involved:
        sources.extend(programme_sources(pid))
    allowed_evidence = {s.id for s in sources}
    evidence_texts: dict[str, str] = {}
    allowed_rules: set[str] = set()
    rule_status: dict[str, str] = {}
    for scen in scenarios:
        for d in scen.get("delta") or []:
            allowed_rules.add(d["rule_id"])
            rule_status[d["rule_id"]] = d["scenario_status"]
    for pid in involved:
        evidence_texts.update(programme_fact_texts(pid))
        for s in programme_sources(pid):
            allowed_evidence.add(s.id)
            evidence_texts.setdefault(s.id, s.excerpt)
    envelope = {
        "task": "simulate_explain",
        "prompt_version": PROMPT_VERSION,
        "locale": locale,
        "scenarios": [
            {"name": s.get("name"),
             "patch": s.get("patch"),
             "programmes_flipped_to_met": len(s.get("flipped_program_ids") or []),
             "rules_flipped_to_met": s.get("rule_flip_count", 0),
             "flipped_program_ids": s.get("flipped_program_ids") or []}
            for s in scenarios],
        "leverage": {
            "top_change": top.get("id"),
            "top_change_description": (_fmt_change(top["change"]) if top else None),
            "all": [{"id": c["id"], "flips": c.get("flips", 0),
                     "rule_flips": c.get("rule_flips", 0)}
                    for c in (leverage or {}).get("all") or []]},
        "baseline_academic_unknown": baseline_unknown_academic,
        "evidence_catalog": [
            {"id": s.id, "url": s.url, "title": s.title, "excerpt": s.excerpt}
            for s in sources],
        "rules": ("Do not include any numbers (scores, budgets, counts, "
                  "fees, years, percentages) in the summary or in any claim "
                  "text: describe each change by name only. The server "
                  "displays the engine-computed numbers beside your words, "
                  "so the reader can check them. One-sentence summary, at "
                  "most 3 claims. A claim about a rule must list that "
                  "rule_id and cite an evidence_id from the catalog."),
    }
    messages = [{"role": "user", "content": json.dumps(envelope, ensure_ascii=False)}]

    def _attempt(msgs, timeout_s: float) -> dict | None:
        try:
            result = provider.chat(msgs, system=explain_system(locale),
                                   timeout_s=timeout_s)
        except ProviderError:
            return None
        parsed = _parse_model_json(result.text)
        if parsed is None:
            return None
        check = check_model_output(
            parsed, allowed_evidence_ids=allowed_evidence,
            allowed_rule_ids=allowed_rules, rule_status=rule_status,
            evidence_texts=evidence_texts, locale=locale)
        if check.valid:
            return parsed
        return {"_check_error": check.error_text(),
                "_raw": result.text[:4000]}

    first = _attempt(messages, 30.0)
    if first is not None and "_check_error" not in first:
        return first
    if first is None:
        return None
    repair = ("Your previous output failed validation. Fix ONLY these "
              f"problems and output JSON only: {first['_check_error']}\n\n"
              f"Previous output:\n{first['_raw']}")
    second = _attempt(messages + [{"role": "user", "content": repair}], 20.0)
    if second is not None and "_check_error" not in second:
        return second
    return None


def explain_simulation(*, scenarios: list[dict], leverage: dict | None,
                       baseline_unknown_academic: bool, locale: str = "en",
                       provider: ProviderAdapter | None = None
                       ) -> tuple[dict, str, str]:
    """Returns (structured, text, ai_status).

    ``ai_status`` is "available" only when a validated model output was
    actually used; otherwise the text is the deterministic template and
    ai_status is "unavailable". ``provider`` is None for template mode
    (no model call is made); pass a ProviderAdapter to attempt one model
    call, or an injected adapter in tests.
    """
    template = template_simulate_structured(
        scenarios=scenarios, leverage=leverage,
        baseline_unknown_academic=baseline_unknown_academic, locale=locale)
    if provider is None:
        return template, template_simulate_text(template), "unavailable"
    if not provider.available:
        return template, template_simulate_text(template), "unavailable"
    structured = _model_explain_simulation(
        scenarios=scenarios, leverage=leverage,
        baseline_unknown_academic=baseline_unknown_academic,
        locale=locale, provider=provider)
    if structured is None:
        return template, template_simulate_text(template), "unavailable"
    sources = []
    for scen in scenarios:
        for pid in scen.get("flipped_program_ids") or []:
            sources.extend(programme_sources(pid))
    return (structured,
            render_structured_explanation(structured, sources), "available")

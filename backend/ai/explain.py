"""Explanation: template (always) + model-written (when a provider is
configured), both citation-checked (Day 3, spec Ch13).

Every claim references a real evidence_id / rule_id from the evaluation;
a claim with no matching evidence is dropped, never invented.
Model path: the model only sees the server-side recomputed evaluation
plus the programme's verified sources; its structured JSON output is
validated by ai.grounding.check_model_output (schema, id whitelist,
rule-status immutability, numeric cross-check, no probabilities or
guarantees, no raw URLs). One repair retry on validation failure, then
the deterministic template. Model timeout/failure -> template fallback,
never invented text. ai_status is "available" only when a validated
model output was actually used.
"""
from __future__ import annotations

import copy
import json

from ai.grounding import (check_model_output, programme_fact_texts,
                          programme_sources, render_structured_explanation)
from ai.prompts import PROMPT_VERSION, explain_system
from ai.provider import ProviderAdapter, ProviderError
from app.schemas import Evaluation, StudentProfile

_STATUS_WORDS = {
    "MET": "meets the stated minimum",
    "NOT_MET": "does not meet the stated minimum",
    "UNKNOWN": "cannot be decided from the supplied evidence",
    "NOT_APPLICABLE": "does not apply",
}


def template_explanation(evaluation: Evaluation) -> str:
    lines = [f"Evaluation for {evaluation.program_id} (data version {evaluation.data_version}): "
             f"overall status {evaluation.overall_status}."]
    for r in evaluation.results:
        # Citation check: only include claims whose evidence_ids are real
        # (non-empty, or the rule is explicitly NOT_APPLICABLE).
        if not r.evidence_ids and r.status != "NOT_APPLICABLE":
            continue
        word = _STATUS_WORDS.get(r.status, r.status)
        cite = f" [evidence: {', '.join(r.evidence_ids)}]" if r.evidence_ids else ""
        lines.append(f"- {r.rule_id}: {word}. {r.detail}{cite}")
    if evaluation.ai_status == "unavailable":
        lines.append("Note: no AI provider is configured, so this explanation is a rules/template summary, not model-generated text.")
    return "\n".join(lines)


def _parse_model_json(text: str) -> dict | None:
    """Parse a model reply as JSON, tolerating ```json fences."""
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


def _model_explain(evaluation: Evaluation, locale: str,
                   provider: ProviderAdapter) -> dict | None:
    """One model attempt + one repair attempt. Returns the validated
    structured output, or None (caller falls back to the template)."""
    sources = programme_sources(evaluation.program_id)
    allowed_evidence = {s.id for s in sources}
    evidence_texts = programme_fact_texts(evaluation.program_id)
    for s in sources:
        evidence_texts.setdefault(s.id, s.excerpt)
        allowed_evidence.add(s.id)
    rule_status = {r.rule_id: r.status for r in evaluation.results}
    allowed_rules = set(rule_status)
    for r in evaluation.results:
        for eid in r.evidence_ids:
            allowed_evidence.add(eid)
            evidence_texts.setdefault(eid, r.detail)
    envelope = {
        "task": "explain",
        "prompt_version": PROMPT_VERSION,
        "locale": locale,
        "program_id": evaluation.program_id,
        "data_version": evaluation.data_version,
        "overall_status": evaluation.overall_status,
        "rule_results": [
            {"rule_id": r.rule_id, "status": r.status, "detail": r.detail,
             "evidence_ids": list(r.evidence_ids)} for r in evaluation.results],
        "evidence_catalog": [
            {"id": s.id, "url": s.url, "title": s.title, "excerpt": s.excerpt}
            for s in sources],
    }
    messages = [{"role": "user", "content": json.dumps(envelope, ensure_ascii=False)}]
    # Timeouts (round 8, same fix round 7 made for pref-chat/chat): live
    # gateway calls take ~9-12 s each, so the old 12 s / 8 s budgets
    # were marginal — the 8 s repair budget was shorter than one call,
    # so any first-attempt validation failure fell back to the template
    # even though the provider was fine. 30 s first call, 20 s repair;
    # the provider default cap (60 s) is unchanged.
    try:
        result = provider.chat(messages, system=explain_system(locale),
                               timeout_s=30.0)
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
    # One repair attempt, within the total budget (spec Ch13).
    repair = ("Your previous output failed validation. Fix ONLY these "
              f"problems and output JSON only: {check.error_text()}\n\n"
              f"Previous output:\n{result.text[:4000]}")
    try:
        retry = provider.chat(messages + [{"role": "user", "content": repair}],
                              system=explain_system(locale), timeout_s=20.0)
    except ProviderError:
        return None
    parsed2 = _parse_model_json(retry.text)
    if parsed2 is None:
        return None
    check2 = check_model_output(
        parsed2, allowed_evidence_ids=allowed_evidence,
        allowed_rule_ids=allowed_rules, rule_status=rule_status,
        evidence_texts=evidence_texts, locale=locale)
    return parsed2 if check2.valid else None


def explain_structured_with_status(
        evaluation: Evaluation, locale: str = "en",
        provider: ProviderAdapter | None = None
) -> tuple[dict | None, str, str]:
    """Returns (structured_model_output_or_None, text, ai_status).

    ``structured`` is present only when a validated model output was used;
    otherwise text is the template explanation and ai_status is
    "unavailable". The rule results are always kept (spec FR06/NFR02:
    model failure never loses the rules).
    """
    provider = provider or ProviderAdapter()
    if not provider.available:
        return None, template_explanation(evaluation), "unavailable"
    structured = _model_explain(evaluation, locale, provider)
    if structured is None:
        return None, template_explanation(evaluation), "unavailable"
    sources = programme_sources(evaluation.program_id)
    return structured, render_structured_explanation(structured, sources), "available"


def explain(evaluation: Evaluation, provider: ProviderAdapter | None = None) -> str:
    text, _status = explain_with_status(evaluation, provider)
    return text


def explain_with_status(evaluation: Evaluation,
                         provider: ProviderAdapter | None = None) -> tuple[str, str]:
    """Template explanation plus the honest ai_status.

    If no provider is configured, or a configured provider fails/times out,
    or its output fails citation validation, the result is the template
    text with ai_status="unavailable" — the rule results are always kept
    (spec FR06/NFR02: model failure never loses the rules). Callers must
    use this, not explain(), when they report ai_status.
    """
    _structured, text, status = explain_structured_with_status(
        evaluation, "en", provider)
    return text, status


# ---------------------------------------------------------------------------
# Why-not explanations (Day 3, W2 build round)
#
# Pure template first: every gap is read off the engine's own
# RuleResult.threshold / observed values — nothing is computed from a
# fresh guess and no fix is ever invented. A candidate "cheapest fix"
# is a single change (one IELTS component / overall / TOEFL score, one
# budget increase, or one IELTS retake raising every failing
# component) ranked by how many NOT_MET rules it clears, then by
# change kind (a language step before a budget increase), then by the
# smallest numeric step. When a profile is supplied the candidates
# are verified by actually re-running the engine on the patched
# profile; a candidate the engine does not flip is dropped, never
# reported as a fix. A Gaokao academic UNKNOWN is never "fixed" by a
# score change: no university publishes a Gaokao equivalence, so the
# cheapest fix is None and the template says so, pointing at the
# Gaokao route panel instead.
# ---------------------------------------------------------------------------

_COMPONENTS = ("listening", "reading", "writing", "speaking")

_FAMILY_ORDER = ("academic", "language", "language-components", "toefl",
                 "gcse", "test", "gre", "fee", "other")

# Tie-break order for cheapest-fix candidates with the same number of
# resolved rules: a single language step is a smaller single change
# than a budget increase; a combined retake (several components at
# once) comes last.
_KIND_ORDER = {"ielts_component": 0, "ielts_overall": 1, "toefl": 2,
               "budget": 3, "ielts_components": 4}


def rule_family(rule_id: str) -> str:
    """Rule family for comparison alignment: programmes name the same
    requirement differently (ucl-ielts-overall vs imp-beng-language),
    so the comparison view aligns by family, never by raw rule id."""
    if rule_id.endswith("-academic"):
        return "academic"
    if rule_id.endswith("-fee"):
        return "fee"
    if rule_id.endswith("-toefl"):
        return "toefl"
    if (rule_id.endswith("-language-components")
            or rule_id.endswith("-ielts-components")):
        return "language-components"
    if rule_id.endswith("-language") or rule_id.endswith("-ielts-overall"):
        return "language"
    if rule_id == "ucl-gcse":
        return "gcse"
    if rule_id.endswith("-tmua") or rule_id == "ucl-tara" or rule_id.endswith("-test"):
        return "test"
    if rule_id.endswith("-gre") or rule_id.endswith("-gre-gmat"):
        return "gre"
    return "other"


def _num(value) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def _fmt_num(value) -> str:
    """Engine number as the user sees it: an IELTS band stays '6.0',
    a fee becomes '48,600' (money)."""
    if isinstance(value, float):
        if value == int(value):
            return f"{value:,.0f}" if abs(value) >= 1000 else f"{value:.1f}"
        return f"{value:g}"
    if isinstance(value, int):
        return f"{value:,}" if abs(value) >= 1000 else str(value)
    return str(value)


def _round_half_up(value: float) -> float:
    """Next IELTS band on the 0.5 grid at or above ``value``."""
    import math
    return math.ceil(value * 2 - 1e-9) / 2


def _component_required(threshold: dict | None, component: str) -> float | None:
    if not isinstance(threshold, dict):
        return None
    direct = _num(threshold.get(component))
    if direct is not None:
        return direct
    return _num(threshold.get("each_component"))


def _gaps_for_rule(rule, budget_currency: str | None = None,
                   fee_currency: str | None = None) -> list[dict]:
    """Exact gaps for one NOT_MET rule, from threshold vs observed.

    A gap is {"kind", "label", "required", "observed", "gap", ...}.
    When no numeric threshold can be read off the rule (e.g. an
    academic NOT_MET on A-level grades, a GCSE fail), the gap is a
    "detail" gap carrying the engine's own detail text — never an
    invented number. A fee shortfall is claimed only when the fee
    was compared in the budget currency (approx_converted) or the
    budget and fee currencies are known to be the same; otherwise
    the gap carries no shortfall rather than a cross-currency guess."""
    family = rule_family(rule.rule_id)
    thr = rule.threshold if isinstance(rule.threshold, dict) else None
    obs = rule.observed
    gaps: list[dict] = []
    if family == "language-components":
        observed = obs if isinstance(obs, dict) else {}
        three = _num(thr.get("__three__")) if thr else None
        remaining = _num(thr.get("__remaining__")) if thr else None
        if three is not None and remaining is not None:
            at_three = 0
            for comp in _COMPONENTS:
                score = _num(observed.get(comp))
                if score is None:
                    continue
                if score >= three:
                    at_three += 1
                if score < remaining:
                    gaps.append({"kind": "component", "label": comp,
                                 "required": remaining, "observed": score,
                                 "gap": round(remaining - score, 2)})
            if at_three < 3:
                gaps.append({"kind": "three_components",
                             "label": "three_components",
                             "required": three, "observed": at_three,
                             "gap": 3 - at_three})
            return gaps
        for comp in _COMPONENTS:
            required = _component_required(thr, comp)
            score = _num(observed.get(comp))
            if required is None or score is None:
                continue
            if score < required:
                gaps.append({"kind": "component", "label": comp,
                             "required": required, "observed": score,
                             "gap": round(required - score, 2)})
        return gaps
    if family == "language":
        if isinstance(obs, (int, float)) and not isinstance(obs, bool):
            required = _num(thr.get("overall")) if thr else None
            if required is not None and obs < required:
                gaps.append({"kind": "overall", "label": "overall",
                             "required": required, "observed": obs,
                             "gap": round(required - obs, 2)})
            return gaps
        if isinstance(obs, dict):
            for exam, key in (("ielts", "ielts_overall"),
                              ("toefl", "toefl_overall")):
                required_raw = thr.get(key) if thr else None
                if isinstance(required_raw, list):
                    nums = [_num(v) for v in required_raw]
                    nums = [v for v in nums if v is not None]
                    required = min(nums) if nums else None
                else:
                    required = _num(required_raw)
                score = _num(obs.get(key))
                if required is not None and score is not None and score < required:
                    gaps.append({"kind": "overall", "label": exam,
                                 "required": required, "observed": score,
                                 "gap": round(required - score, 2)})
            return gaps
        return gaps
    if family == "toefl":
        required = _num(thr.get("overall")) if thr else None
        score = _num(obs.get("overall")) if isinstance(obs, dict) else _num(obs)
        if required is not None and score is not None and score < required:
            gaps.append({"kind": "toefl", "label": "toefl",
                         "required": required, "observed": score,
                         "gap": round(required - score, 2)})
        return gaps
    if family == "fee":
        fallback_ccy = fee_currency  # programme's fee currency, for bare 'amount' thresholds
        fee_amount = None
        fee_currency = None
        if thr:
            for key, currency in (("gbp_per_year", "GBP"),
                                  ("sgd_total", "SGD")):
                if _num(thr.get(key)) is not None:
                    fee_amount, fee_currency = _num(thr.get(key)), currency
                    break
            if fee_amount is None:
                fee_amount = _num(thr.get("amount"))
                fee_currency = (thr.get("currency")
                                if isinstance(thr.get("currency"), str) else None)
        if fee_currency is None:
            fee_currency = fallback_ccy
        budget = _num(obs.get("amount")) if isinstance(obs, dict) else _num(obs)
        approx = thr.get("approx_converted") if thr else None
        approx = approx if isinstance(approx, dict) else None
        if fee_amount is not None and budget is not None:
            if fee_currency is None and thr:
                fee_currency = (thr.get("currency")
                                if isinstance(thr.get("currency"), str) else None)
            gap: dict = {"kind": "fee", "label": "fee",
                         "required": fee_amount, "observed": budget,
                         "fee_currency": fee_currency,
                         "fee_amount": fee_amount}
            if approx is not None:
                approx_amount = _num(approx.get("amount"))
                approx_currency = approx.get("currency")
                if approx_amount is not None and isinstance(approx_currency, str):
                    gap["converted_fee"] = approx_amount
                    gap["converted_currency"] = approx_currency
                    gap["gap"] = round(approx_amount - budget, 2)
                    gap["as_of"] = approx.get("as_of")
            elif (budget_currency is not None and fee_currency is not None
                    and budget_currency == fee_currency):
                gap["gap"] = round(fee_amount - budget, 2)
                gap["currency"] = fee_currency
            gaps.append(gap)
        return gaps
    return gaps


def _candidates_for_rule(rule, gaps: list[dict]) -> list[dict]:
    """Single-change candidates for one failing rule, with the rules
    each would clear judged structurally (a component raise clears
    its components rule only when it is the sole failing component;
    a combined retake clears it by raising every failing component).
    Engine verification (when a profile is supplied) re-checks this
    and drops any candidate the engine does not flip."""
    family = rule_family(rule.rule_id)
    out: list[dict] = []
    if family == "language-components":
        comp_gaps = [g for g in gaps if g["kind"] == "component"]
        three_gap = next((g for g in gaps if g["kind"] == "three_components"), None)
        for g in comp_gaps:
            target = _round_half_up(float(g["required"]))
            out.append({
                "id": f"ielts-{g['label']}-to-{target:g}",
                "kind": "ielts_component", "field": f"ielts{g['label'].capitalize()}",
                "component": g["label"], "from": g["observed"], "to": target,
                "resolves_rule_ids": ([rule.rule_id] if len(comp_gaps) == 1
                                      and three_gap is None else []),
                "label": f"Raise IELTS {g['label'].capitalize()} from "
                         f"{_fmt_num(g['observed'])} to {_fmt_num(target)}",
            })
        if len(comp_gaps) > 1 or three_gap is not None:
            changes = {g["label"]: _round_half_up(float(g["required"]))
                       for g in comp_gaps}
            if three_gap is not None:
                target3 = _round_half_up(float(three_gap["required"]))
                for comp in _COMPONENTS:
                    changes.setdefault(comp, target3)
            parts = ", ".join(f"{c} to {_fmt_num(v)}"
                              for c, v in sorted(changes.items()))
            out.append({
                "id": "ielts-components-retake",
                "kind": "ielts_components", "field": "ieltsComponents",
                "component": None, "from": None, "to": changes,
                "resolves_rule_ids": [rule.rule_id],
                "label": f"Retake IELTS and raise {parts}",
            })
        return out
    if family == "language":
        for g in gaps:
            if g["kind"] != "overall":
                continue
            target = _round_half_up(float(g["required"]))
            if g["label"] == "toefl":
                out.append({
                    "id": f"toefl-to-{target:g}", "kind": "toefl",
                    "field": "toefl", "component": None,
                    "from": g["observed"], "to": target,
                    "resolves_rule_ids": [rule.rule_id],
                    "label": f"Raise TOEFL from {_fmt_num(g['observed'])} "
                             f"to {_fmt_num(target)}",
                })
            else:
                out.append({
                    "id": f"ielts-overall-to-{target:g}", "kind": "ielts_overall",
                    "field": "ieltsOverall", "component": None,
                    "from": g["observed"], "to": target,
                    "resolves_rule_ids": [rule.rule_id],
                    "label": f"Raise IELTS overall from {_fmt_num(g['observed'])} "
                             f"to {_fmt_num(target)}",
                })
        return out
    if family == "toefl":
        for g in gaps:
            target = g["required"]
            out.append({
                "id": f"toefl-to-{target:g}", "kind": "toefl",
                "field": "toefl", "component": None,
                "from": g["observed"], "to": target,
                "resolves_rule_ids": [rule.rule_id],
                "label": f"Raise TOEFL from {_fmt_num(g['observed'])} "
                         f"to {_fmt_num(target)}",
            })
        return out
    if family == "fee":
        for g in gaps:
            shortfall = g.get("gap")
            if shortfall is None or shortfall <= 0:
                continue
            currency = g.get("converted_currency") or g.get("fee_currency")
            if g.get("converted_fee") is not None:
                # The converted figure is approximate and rounded to
                # whole pounds: the true fee can sit up to a pound
                # above it, so the fix target is one whole unit above
                # the rounded figure — otherwise the patched budget
                # can sit a fraction below the true converted fee and
                # fail engine verification.
                import math
                target = math.floor(float(g["converted_fee"])) + 1
            else:
                target = g.get("fee_amount")
            out.append({
                "id": "budget-to-fee", "kind": "budget", "field": "budget",
                "component": None, "from": g["observed"], "to": target,
                "currency": currency,
                "resolves_rule_ids": [rule.rule_id],
                "label": (f"Raise your budget to {_fmt_num(target)} {currency}"
                          if currency else
                          f"Raise your budget to {_fmt_num(target)}"),
            })
        return out
    return out


def _candidate_step(candidate: dict) -> float:
    """Numeric size of a candidate's change, for tie-breaking: the
    smallest step wins among candidates clearing the same rules."""
    if candidate["kind"] == "budget":
        try:
            return float(candidate["to"]) - float(candidate["from"])
        except (TypeError, ValueError):
            return float("inf")
    if candidate["kind"] == "ielts_components":
        to = candidate.get("to") or {}
        return sum(float(v) for v in to.values()) if isinstance(to, dict) else float("inf")
    try:
        return float(candidate["to"]) - float(candidate["from"])
    except (TypeError, ValueError):
        return float("inf")


def _rank_candidates(candidates: list[dict]) -> list[dict]:
    def key(c: dict):
        return (-len(c.get("resolves_rule_ids") or []),
                _KIND_ORDER.get(c.get("kind", ""), 99),
                _candidate_step(c))
    return sorted(candidates, key=key)


def _verify_candidates(candidates: list[dict], evaluation: Evaluation,
                       profile: StudentProfile) -> list[dict]:
    """Re-run the engine once per candidate on the patched profile and
    keep only the flips the engine actually produces. A candidate
    whose patch flips no rule is dropped from the ranking (its
    resolves list becomes empty); the ranking is then recomputed on
    verified flips. No profile -> no verification (verified=False)."""
    from app.data import EXPANSION_MATCHABLE, PROGRAMS
    from domain.eligibility import evaluate
    from domain.expansion_eval import evaluate_expansion

    program = PROGRAMS.get(evaluation.program_id)
    is_expansion = program is None
    if is_expansion:
        program = EXPANSION_MATCHABLE.get(evaluation.program_id)
    if program is None:
        return candidates
    baseline = {r.rule_id: r.status for r in evaluation.results}
    verified: list[dict] = []
    for cand in candidates:
        patched = copy.deepcopy(profile.model_dump(mode="json"))
        lang = patched.setdefault("language", {}) or {}
        if cand["kind"] == "ielts_component":
            lang[cand["component"]] = cand["to"]
        elif cand["kind"] == "ielts_components":
            for comp, value in (cand.get("to") or {}).items():
                lang[comp] = value
        elif cand["kind"] == "ielts_overall":
            lang["overall"] = cand["to"]
        elif cand["kind"] == "toefl":
            lang["toefl_overall"] = cand["to"]
            if (lang.get("exam") == "toefl"):
                lang["overall"] = cand["to"]
        elif cand["kind"] == "budget":
            budget = patched.setdefault("budget", {}) or {}
            budget["amount"] = cand["to"]
        try:
            new_profile = StudentProfile(**patched)
        except Exception:
            continue
        try:
            results = (evaluate_expansion(new_profile, program) if is_expansion
                       else evaluate(new_profile, program))
        except Exception:
            continue
        flips = [r.rule_id for r in results
                 if baseline.get(r.rule_id) == "NOT_MET" and r.status == "MET"]
        cand = dict(cand)
        cand["resolves_rule_ids"] = flips
        cand["verified"] = True
        verified.append(cand)
    return verified


def _gap_line(rule_id: str, gap: dict) -> str:
    if gap["kind"] == "component":
        return (f"IELTS {gap['label'].capitalize()}: required "
                f"{_fmt_num(gap['required'])}, you have "
                f"{_fmt_num(gap['observed'])} "
                f"(short by {_fmt_num(gap['gap'])}).")
    if gap["kind"] == "three_components":
        return (f"IELTS: at least three components at "
                f"{_fmt_num(gap['required'])}, you have "
                f"{gap['observed']} component(s) at that level.")
    if gap["kind"] == "overall":
        exam = "TOEFL" if gap["label"] == "toefl" else "IELTS overall"
        return (f"{exam}: required {_fmt_num(gap['required'])}, you have "
                f"{_fmt_num(gap['observed'])} "
                f"(short by {_fmt_num(gap['gap'])}).")
    if gap["kind"] == "toefl":
        return (f"TOEFL: required {_fmt_num(gap['required'])}, you have "
                f"{_fmt_num(gap['observed'])} "
                f"(short by {_fmt_num(gap['gap'])}).")
    if gap["kind"] == "fee":
        fee = gap.get("fee_amount")
        fee_ccy = gap.get("fee_currency") or ""
        base = (f"Tuition fee: {fee_ccy} {_fmt_num(fee)}"
                if fee is not None else "Tuition fee")
        if gap.get("converted_fee") is not None:
            base += (f" (about {gap.get('converted_currency')} "
                     f"{_fmt_num(gap['converted_fee'])}"
                     + (f", rates {gap['as_of']}" if gap.get("as_of") else "")
                     + ")")
        shortfall = gap.get("gap")
        if shortfall is not None and shortfall > 0:
            ccy = gap.get("converted_currency") or fee_ccy
            base += (f"; your budget {_fmt_num(gap['observed'])} — short by "
                     f"about {ccy} {_fmt_num(shortfall)}.")
        else:
            base += (f"; your budget {_fmt_num(gap['observed'])} is in a "
                     f"different currency and no converted figure is "
                     f"available, so no shortfall is claimed.")
        return base
    return ""


def compute_whynot(evaluation: Evaluation,
                   profile: StudentProfile | None = None,
                   budget_currency: str | None = None,
                   fee_currency: str | None = None) -> dict:
    """Why-not explanation for one evaluation, from engine data only.

    Returns the explanation contract the frontend renders and the
    /whynot endpoint returns: failing rules with exact gaps,
    unknown rules, the academic-unknown / Gaokao flags, and the
    cheapest fix (or None, with ``no_single_fix`` when failing rules
    exist but no single change clears one). ``budget_currency`` is
    the applicant's own budget currency and ``fee_currency`` the
    programme's fee currency (for bare 'amount' thresholds);
    without them a cross-currency fee gap reports no shortfall
    rather than guessing one.
    """
    failing: list[dict] = []
    unknown_ids: list[str] = []
    academic_unknown = False
    gaokao_route = False
    all_candidates: list[dict] = []
    for r in evaluation.results:
        if r.status == "UNKNOWN":
            unknown_ids.append(r.rule_id)
            if rule_family(r.rule_id) == "academic":
                academic_unknown = True
                obs = r.observed if isinstance(r.observed, dict) else {}
                if obs.get("curriculum") == "cn_gaokao":
                    gaokao_route = True
        if r.status != "NOT_MET":
            continue
        gaps = _gaps_for_rule(r, budget_currency=budget_currency,
                              fee_currency=fee_currency)
        if not gaps:
            gaps = [{"kind": "detail", "label": rule_family(r.rule_id),
                     "required": None, "observed": None, "gap": None,
                     "text": r.detail}]
        failing.append({
            "rule_id": r.rule_id,
            "status": r.status,
            "family": rule_family(r.rule_id),
            "detail": r.detail,
            "evidence_ids": list(r.evidence_ids),
            "gaps": gaps,
        })
        all_candidates.extend(_candidates_for_rule(r, gaps))
    if profile is not None:
        all_candidates = _verify_candidates(all_candidates, evaluation, profile)
    else:
        for cand in all_candidates:
            cand["verified"] = False
    ranked = _rank_candidates(all_candidates)
    cheapest = None
    for cand in ranked:
        if cand.get("resolves_rule_ids"):
            cheapest = dict(cand)
            cheapest["rules_resolved"] = len(cand["resolves_rule_ids"])
            break
    no_single_fix = bool(failing) and cheapest is None
    lines = []
    if failing:
        lines.append(
            f"Why {evaluation.program_id} is not met: "
            f"{len(failing)} rule(s) below the stated minimum.")
        for fr in failing:
            for gap in fr["gaps"]:
                line = _gap_line(fr["rule_id"], gap)
                if line:
                    lines.append(f"- {fr['rule_id']}: {line}")
                else:
                    lines.append(f"- {fr['rule_id']}: {gap.get('text', fr['detail'])}")
    else:
        lines.append(f"No rule is failed for {evaluation.program_id}.")
    if academic_unknown:
        if gaokao_route:
            lines.append(
                "Academic: cannot be decided from the published evidence. "
                "No university publishes a Gaokao equivalence, so a higher "
                "Gaokao score would not change this — see the official "
                "Gaokao routes, not a score fix.")
        else:
            lines.append(
                "Academic: cannot be decided from the published evidence.")
    if cheapest is not None:
        lines.append(
            "Cheapest fix (suggestion, not a fact): "
            f"{cheapest['label']} — clears {cheapest['rules_resolved']} "
            f"rule(s) ({', '.join(cheapest['resolves_rule_ids'])}).")
    elif no_single_fix:
        lines.append(
            "No single change on its own clears a failed rule — each gap "
            "above would need its own change.")
    return {
        "program_id": evaluation.program_id,
        "overall_status": evaluation.overall_status,
        "failing_rules": failing,
        "unknown_rules": unknown_ids,
        "academic_unknown": academic_unknown,
        "gaokao_route": gaokao_route,
        "cheapest_fix": cheapest,
        "no_single_fix": no_single_fix,
        "template_text": "\n".join(lines),
    }


def whynot_template_text(whynot: dict) -> str:
    """The deterministic template text for a compute_whynot() result."""
    return whynot.get("template_text", "")


def whynot_with_model(evaluation: Evaluation, locale: str = "en",
                      provider: ProviderAdapter | None = None,
                      profile: StudentProfile | None = None,
                      budget_currency: str | None = None,
                      fee_currency: str | None = None
                      ) -> tuple[dict, str | None, str]:
    """(whynot, model_note_or_None, ai_status).

    The template whynot is always present. Model polish goes through
    the existing /explain citation-checked path
    (explain_structured_with_status): the model only ever sees the
    server-side recomputed evaluation plus verified sources, its
    output is validated (evidence/rule whitelist, rule-status
    immutability, numeric cross-check, no probabilities, no raw
    URLs), and any failure degrades to template-only with
    ai_status="unavailable" — the model note is None, never invented
    text. ai_status is "available" only when a validated model
    output was actually used.
    """
    whynot = compute_whynot(evaluation, profile=profile,
                            budget_currency=budget_currency,
                            fee_currency=fee_currency)
    structured, _text, status = explain_structured_with_status(
        evaluation, locale, provider)
    if structured is None:
        return whynot, None, "unavailable"
    sources = programme_sources(evaluation.program_id)
    return whynot, render_structured_explanation(structured, sources), status


def build_comparison(evaluations: list[Evaluation]) -> dict:
    """Rule-by-rule comparison shape for 2–3 evaluations.

    Rows are rule families (academic / language / language-components
    / toefl / gcse / test / gre / fee), in fixed order, so programmes
    that name the same requirement differently still line up side by
    side. A family's cell status is the worst of its rules
    (NOT_MET > UNKNOWN > MET > NOT_APPLICABLE); a programme with no
    rule in a family has no cell there.
    """
    families: list[str] = []
    columns: list[dict] = []
    for ev in evaluations:
        whynot = compute_whynot(ev)
        by_family: dict[str, dict] = {}
        for r in ev.results:
            fam = rule_family(r.rule_id)
            if fam not in families:
                families.append(fam)
            cell = by_family.setdefault(
                fam, {"rule_ids": [], "status": "NOT_APPLICABLE",
                      "gaps": []})
            cell["rule_ids"].append(r.rule_id)
            rank = {"NOT_MET": 0, "UNKNOWN": 1, "MET": 2,
                    "NOT_APPLICABLE": 3}
            if rank.get(r.status, 3) < rank.get(cell["status"], 3):
                cell["status"] = r.status
            if r.status == "NOT_MET":
                fr = next((f for f in whynot["failing_rules"]
                           if f["rule_id"] == r.rule_id), None)
                if fr:
                    cell["gaps"].extend(fr["gaps"])
        columns.append({
            "program_id": ev.program_id,
            "overall_status": ev.overall_status,
            "families": by_family,
            "cheapest_fix": whynot["cheapest_fix"],
            "academic_unknown": whynot["academic_unknown"],
            "gaokao_route": whynot["gaokao_route"],
        })
    families.sort(key=lambda f: _FAMILY_ORDER.index(f)
                  if f in _FAMILY_ORDER else len(_FAMILY_ORDER))
    return {"rule_families": families, "columns": columns}

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

import json

from ai.grounding import (check_model_output, programme_fact_texts,
                          programme_sources, render_structured_explanation)
from ai.prompts import PROMPT_VERSION, explain_system
from ai.provider import ProviderAdapter, ProviderError
from app.schemas import Evaluation

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

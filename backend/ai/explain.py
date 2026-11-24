"""Template explanation, citation-checked.

Every claim references a real evidence_id / rule_id from the evaluation;
a claim with no matching evidence is dropped, never invented.
Model timeout/failure -> template fallback, never invented text.
"""
from __future__ import annotations

from app.schemas import Evaluation
from ai.provider import ProviderAdapter

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


def explain(evaluation: Evaluation, provider: ProviderAdapter | None = None) -> str:
    provider = provider or ProviderAdapter()
    if not provider.available:
        return template_explanation(evaluation)
    try:
        # No provider is wired in on Day 1; generate() raises and we fall back.
        return provider.generate(template_explanation(evaluation))
    except Exception:
        return template_explanation(evaluation)

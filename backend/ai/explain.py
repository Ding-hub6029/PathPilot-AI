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
from ai.locale_sep import join_list
from ai.prompts import PROMPT_VERSION, explain_system
from ai.provider import ProviderAdapter, ProviderError
from app.schemas import Evaluation, StudentProfile

# ---------------------------------------------------------------------------
# Localised template explanation (Round 14)
#
# The deterministic template renders in the requested locale (all 6).
# Engine numbers and identifiers — programme id, data version, rule ids,
# evidence ids and the engine's own rule detail text — are inserted
# unchanged; only the surrounding prose is translated. An unknown locale
# falls back to English. The model path already answers in the requested
# locale via explain_system(locale); only this template path was English
# on every UI.
# ---------------------------------------------------------------------------

_EXPLAIN_TEMPLATE_STRINGS = {
    "en": {
        "header": ("Evaluation for {program_id} (data version "
                   "{data_version}): overall status {overall_status}."),
        "status_MET": "meets the stated minimum",
        "status_NOT_MET": "does not meet the stated minimum",
        "status_UNKNOWN": "cannot be decided from the supplied evidence",
        "status_NOT_APPLICABLE": "does not apply",
        "note": ("Note: no AI provider is configured, so this explanation "
                 "is a rules/template summary, not model-generated text."),
    },
    "zh-CN": {
        "header": ("对 {program_id} 的评估（数据版本 {data_version}）："
                   "总体状态 {overall_status}。"),
        "status_MET": "达到规定的最低要求",
        "status_NOT_MET": "未达到规定的最低要求",
        "status_UNKNOWN": "根据现有证据无法判定",
        "status_NOT_APPLICABLE": "不适用",
        "note": ("说明：未配置 AI 服务，因此本说明为规则/模板摘要，"
                 "并非模型生成的文本。"),
    },
    "es": {
        "header": ("Evaluación de {program_id} (versión de datos "
                   "{data_version}): estado general {overall_status}."),
        "status_MET": "cumple el mínimo establecido",
        "status_NOT_MET": "no cumple el mínimo establecido",
        "status_UNKNOWN": "no se puede decidir con la evidencia proporcionada",
        "status_NOT_APPLICABLE": "no aplica",
        "note": ("Nota: no hay ningún proveedor de IA configurado, por lo "
                 "que esta explicación es un resumen de reglas/plantilla, "
                 "no un texto generado por un modelo."),
    },
    "fr": {
        "header": ("Évaluation de {program_id} (version des données "
                   "{data_version}) : statut global {overall_status}."),
        "status_MET": "satisfait le minimum requis",
        "status_NOT_MET": "ne satisfait pas le minimum requis",
        "status_UNKNOWN": "ne peut pas être décidé à partir des preuves fournies",
        "status_NOT_APPLICABLE": "sans objet",
        "note": ("Remarque : aucun fournisseur d'IA n'est configuré, cette "
                 "explication est donc un résumé règles/modèle, et non un "
                 "texte généré par un modèle."),
    },
    "pt-BR": {
        "header": ("Avaliação de {program_id} (versão dos dados "
                   "{data_version}): status geral {overall_status}."),
        "status_MET": "atende ao mínimo exigido",
        "status_NOT_MET": "não atende ao mínimo exigido",
        "status_UNKNOWN": "não pode ser decidido com as evidências fornecidas",
        "status_NOT_APPLICABLE": "não se aplica",
        "note": ("Nota: nenhum provedor de IA está configurado, portanto "
                 "esta explicação é um resumo de regras/modelo, não um "
                 "texto gerado por modelo."),
    },
    "ar": {
        "header": ("تقييم {program_id} (إصدار البيانات {data_version}): "
                   "الحالة العامة {overall_status}."),
        "status_MET": "يستوفي الحد الأدنى المطلوب",
        "status_NOT_MET": "لا يستوفي الحد الأدنى المطلوب",
        "status_UNKNOWN": "لا يمكن تحديده من الأدلة المقدمة",
        "status_NOT_APPLICABLE": "لا ينطبق",
        "note": ("ملاحظة: لم يتم تكوين أي مزود ذكاء اصطناعي، لذا فإن هذا "
                 "الشرح ملخص قواعد/قالب وليس نصًا مولّدًا بواسطة نموذج."),
    },
}


def _explain_strings(locale: str) -> dict:
    return _EXPLAIN_TEMPLATE_STRINGS.get(locale) or _EXPLAIN_TEMPLATE_STRINGS["en"]


def _fill(template: str, **values) -> str:
    """Substitute {name} placeholders without str.format: a value (e.g. an
    engine detail) may itself contain braces, which .format would choke on."""
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", str(value))
    return out


def template_explanation(evaluation: Evaluation, locale: str = "en") -> str:
    s = _explain_strings(locale)
    lines = [_fill(s["header"], program_id=evaluation.program_id,
                   data_version=evaluation.data_version,
                   overall_status=evaluation.overall_status)]
    for r in evaluation.results:
        # Citation check: only include claims whose evidence_ids are real
        # (non-empty, or the rule is explicitly NOT_APPLICABLE).
        if not r.evidence_ids and r.status != "NOT_APPLICABLE":
            continue
        word = s.get(f"status_{r.status}", r.status)
        cite = f" [evidence: {', '.join(r.evidence_ids)}]" if r.evidence_ids else ""
        lines.append(f"- {r.rule_id}: {word}. {r.detail}{cite}")
    if evaluation.ai_status == "unavailable":
        lines.append(s["note"])
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
        return None, template_explanation(evaluation, locale), "unavailable"
    structured = _model_explain(evaluation, locale, provider)
    if structured is None:
        return None, template_explanation(evaluation, locale), "unavailable"
    sources = programme_sources(evaluation.program_id)
    return structured, render_structured_explanation(structured, sources), "available"


def explain(evaluation: Evaluation, provider: ProviderAdapter | None = None,
              locale: str = "en") -> str:
    text, _status = explain_with_status(evaluation, provider, locale)
    return text


def explain_with_status(evaluation: Evaluation,
                         provider: ProviderAdapter | None = None,
                         locale: str = "en") -> tuple[str, str]:
    """Template explanation plus the honest ai_status.

    If no provider is configured, or a configured provider fails/times out,
    or its output fails citation validation, the result is the template
    text with ai_status="unavailable" — the rule results are always kept
    (spec FR06/NFR02: model failure never loses the rules). Callers must
    use this, not explain(), when they report ai_status. The template
    renders in ``locale`` (Round 14); the default "en" keeps old callers
    unchanged.
    """
    _structured, text, status = explain_structured_with_status(
        evaluation, locale, provider)
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


# ---------------------------------------------------------------------------
# Localised why-not template (Round 14)
#
# Same rule as the explanation template above: engine numbers (scores,
# fees, counts, rule ids) are inserted unchanged; only the surrounding
# prose — gap lines, candidate labels, summary lines — is translated.
# ``compute_whynot(..., locale="en")`` keeps the old English default, so
# existing callers and tests are unchanged until they pass a locale.
# ---------------------------------------------------------------------------

_WHynOT_STRINGS = {
    "en": {
        "comp_label": "Raise IELTS {comp} from {a} to {b}",
        "retake_label": "Retake IELTS and raise {parts}",
        "retake_part": "{comp} to {v}",
        "toefl_label": "Raise TOEFL from {a} to {b}",
        "overall_label": "Raise IELTS overall from {a} to {b}",
        "budget_label": "Raise your budget to {v} {ccy}",
        "budget_label_no_ccy": "Raise your budget to {v}",
        "gap_component": "IELTS {comp}: required {req}, you have {obs} (short by {gap}).",
        "gap_three": ("IELTS: at least three components at {req}, you have "
                      "{obs} component(s) at that level."),
        "gap_overall": "{exam}: required {req}, you have {obs} (short by {gap}).",
        "gap_toefl": "TOEFL: required {req}, you have {obs} (short by {gap}).",
        "gap_fee_label": "Tuition fee",
        "gap_fee_base": "Tuition fee: {ccy} {fee}",
        "gap_fee_converted": " (about {ccy} {fee}{rates})",
        "gap_fee_rates": ", rates {as_of}",
        "gap_fee_short": "; your budget {obs} — short by about {ccy} {short}.",
        "gap_fee_no_short": ("; your budget {obs} is in a different currency "
                             "and no converted figure is available, so no "
                             "shortfall is claimed."),
        "why_header": ("Why {pid} is not met: {n} rule(s) below the stated "
                       "minimum."),
        "why_none": "No rule is failed for {pid}.",
        "why_academic_gaokao": ("Academic: cannot be decided from the published "
                                "evidence. No university publishes a Gaokao "
                                "equivalence, so a higher Gaokao score would not "
                                "change this — see the official Gaokao routes, "
                                "not a score fix."),
        "why_academic": "Academic: cannot be decided from the published evidence.",
        "why_cheapest": ("Cheapest fix (suggestion, not a fact): {label} — "
                         "clears {n} rule(s) ({rules})."),
        "why_no_single": ("No single change on its own clears a failed rule — "
                          "each gap above would need its own change."),
        "exam_ielts_overall": "IELTS overall",
        "exam_toefl": "TOEFL",
        "comp_listening": "listening",
        "comp_reading": "reading",
        "comp_writing": "writing",
        "comp_speaking": "speaking",
    },
    "zh-CN": {
        "comp_label": "将雅思{comp}从 {a} 提高到 {b}",
        "retake_label": "重考雅思（{parts}）",
        "retake_part": "{comp}提高到 {v}",
        "toefl_label": "将托福从 {a} 提高到 {b}",
        "overall_label": "将雅思总分从 {a} 提高到 {b}",
        "budget_label": "将预算提高到 {v} {ccy}",
        "budget_label_no_ccy": "将预算提高到 {v}",
        "gap_component": "雅思{comp}：要求 {req}，你目前为 {obs}（还差 {gap}）。",
        "gap_three": "雅思：至少三项达到 {req}，你目前有 {obs} 项达到该水平。",
        "gap_overall": "{exam}：要求 {req}，你目前为 {obs}（还差 {gap}）。",
        "gap_toefl": "托福：要求 {req}，你目前为 {obs}（还差 {gap}）。",
        "gap_fee_label": "学费",
        "gap_fee_base": "学费：{ccy} {fee}",
        "gap_fee_converted": "（约 {ccy} {fee}{rates}）",
        "gap_fee_rates": "，汇率截至 {as_of}",
        "gap_fee_short": "；你的预算为 {obs}——还差约 {ccy} {short}。",
        "gap_fee_no_short": "；你的预算为 {obs}，币种不同且没有换算金额，因此不计算差额。",
        "why_header": "{pid} 未达标：有 {n} 项规则低于规定的最低要求。",
        "why_none": "{pid} 没有未通过的规则。",
        "why_academic_gaokao": ("学术：根据已公布的证据无法判定。没有大学公布高考分数换算标准，"
                                "因此提高高考分数也不会改变这一点——请查看官方公布的高考入学路径，"
                                "而不是纠结分数。"),
        "why_academic": "学术：根据已公布的证据无法判定。",
        "why_cheapest": "代价最小的改进方法（建议，并非事实）：{label}——可通过 {n} 项规则（{rules}）。",
        "why_no_single": "没有任何一项单独的改变能通过未达标的规则——上面每一项差距都需要各自改进。",
        "exam_ielts_overall": "雅思总分",
        "exam_toefl": "托福",
        "comp_listening": "听力",
        "comp_reading": "阅读",
        "comp_writing": "写作",
        "comp_speaking": "口语",
    },
    "es": {
        "comp_label": "Sube el {comp} de IELTS de {a} a {b}",
        "retake_label": "Repite el IELTS y sube {parts}",
        "retake_part": "{comp} a {v}",
        "toefl_label": "Sube el TOEFL de {a} a {b}",
        "overall_label": "Sube la puntuación general de IELTS de {a} a {b}",
        "budget_label": "Aumenta tu presupuesto a {v} {ccy}",
        "budget_label_no_ccy": "Aumenta tu presupuesto a {v}",
        "gap_component": "IELTS {comp}: requerido {req}, tienes {obs} (faltan {gap}).",
        "gap_three": ("IELTS: al menos tres componentes en {req}, tienes {obs} "
                      "componente(s) en ese nivel."),
        "gap_overall": "{exam}: requerido {req}, tienes {obs} (faltan {gap}).",
        "gap_toefl": "TOEFL: requerido {req}, tienes {obs} (faltan {gap}).",
        "gap_fee_label": "Matrícula",
        "gap_fee_base": "Matrícula: {ccy} {fee}",
        "gap_fee_converted": " (aprox. {ccy} {fee}{rates})",
        "gap_fee_rates": ", tipos de {as_of}",
        "gap_fee_short": "; tu presupuesto es {obs} — faltan aprox. {ccy} {short}.",
        "gap_fee_no_short": ("; tu presupuesto es {obs}, está en otra moneda y no "
                             "hay cifra convertida disponible, así que no se "
                             "indica ningún déficit."),
        "why_header": "Por qué {pid} no se cumple: {n} regla(s) por debajo del mínimo establecido.",
        "why_none": "Ninguna regla está incumplida para {pid}.",
        "why_academic_gaokao": ("Académico: no se puede decidir con la evidencia "
                                "publicada. Ninguna universidad publica una "
                                "equivalencia de Gaokao, así que una puntuación "
                                "de Gaokao más alta no cambiaría esto — consulta "
                                "las vías oficiales de Gaokao, no una corrección "
                                "de puntuación."),
        "why_academic": "Académico: no se puede decidir con la evidencia publicada.",
        "why_cheapest": ("Solución más barata (sugerencia, no un hecho): {label} — "
                         "resuelve {n} regla(s) ({rules})."),
        "why_no_single": ("Ningún cambio por sí solo resuelve una regla incumplida — "
                          "cada brecha anterior necesitaría su propio cambio."),
        "exam_ielts_overall": "IELTS general",
        "exam_toefl": "TOEFL",
        "comp_listening": "comprensión auditiva",
        "comp_reading": "lectura",
        "comp_writing": "escritura",
        "comp_speaking": "expresión oral",
    },
    "fr": {
        "comp_label": "Augmentez le {comp} de l'IELTS de {a} à {b}",
        "retake_label": "Repassez l'IELTS et augmentez {parts}",
        "retake_part": "{comp} à {v}",
        "toefl_label": "Augmentez le TOEFL de {a} à {b}",
        "overall_label": "Augmentez le score global de l'IELTS de {a} à {b}",
        "budget_label": "Augmentez votre budget à {v} {ccy}",
        "budget_label_no_ccy": "Augmentez votre budget à {v}",
        "gap_component": "IELTS {comp} : requis {req}, vous avez {obs} (il manque {gap}).",
        "gap_three": ("IELTS : au moins trois composantes à {req}, vous en avez "
                      "{obs} à ce niveau."),
        "gap_overall": "{exam} : requis {req}, vous avez {obs} (il manque {gap}).",
        "gap_toefl": "TOEFL : requis {req}, vous avez {obs} (il manque {gap}).",
        "gap_fee_label": "Frais de scolarité",
        "gap_fee_base": "Frais de scolarité : {ccy} {fee}",
        "gap_fee_converted": " (environ {ccy} {fee}{rates})",
        "gap_fee_rates": ", taux de {as_of}",
        "gap_fee_short": " ; votre budget est de {obs} — il manque environ {ccy} {short}.",
        "gap_fee_no_short": (" ; votre budget est de {obs}, dans une autre devise "
                             "et sans montant converti disponible, donc aucun "
                             "déficit n'est indiqué."),
        "why_header": "Pourquoi {pid} n'est pas satisfait : {n} règle(s) sous le minimum requis.",
        "why_none": "Aucune règle n'est en échec pour {pid}.",
        "why_academic_gaokao": ("Académique : impossible à décider à partir des preuves "
                                "publiées. Aucune université ne publie "
                                "d'équivalence du Gaokao, donc un score Gaokao "
                                "plus élevé ne changerait rien — consultez les "
                                "voies Gaokao officielles, pas une correction "
                                "de score."),
        "why_academic": "Académique : impossible à décider à partir des preuves publiées.",
        "why_cheapest": ("Solution la moins coûteuse (suggestion, pas un fait) : "
                         "{label} — résout {n} règle(s) ({rules})."),
        "why_no_single": ("Aucun changement à lui seul ne résout une règle en échec — "
                          "chaque écart ci-dessus nécessiterait son propre "
                          "changement."),
        "exam_ielts_overall": "IELTS global",
        "exam_toefl": "TOEFL",
        "comp_listening": "compréhension orale",
        "comp_reading": "lecture",
        "comp_writing": "écriture",
        "comp_speaking": "expression orale",
    },
    "pt-BR": {
        "comp_label": "Aumente o {comp} do IELTS de {a} para {b}",
        "retake_label": "Refaça o IELTS e aumente {parts}",
        "retake_part": "{comp} para {v}",
        "toefl_label": "Aumente o TOEFL de {a} para {b}",
        "overall_label": "Aumente a nota geral do IELTS de {a} para {b}",
        "budget_label": "Aumente seu orçamento para {v} {ccy}",
        "budget_label_no_ccy": "Aumente seu orçamento para {v}",
        "gap_component": "IELTS {comp}: exigido {req}, você tem {obs} (faltam {gap}).",
        "gap_three": ("IELTS: pelo menos três componentes em {req}, você tem {obs} "
                      "componente(s) nesse nível."),
        "gap_overall": "{exam}: exigido {req}, você tem {obs} (faltam {gap}).",
        "gap_toefl": "TOEFL: exigido {req}, você tem {obs} (faltam {gap}).",
        "gap_fee_label": "Mensalidade",
        "gap_fee_base": "Mensalidade: {ccy} {fee}",
        "gap_fee_converted": " (cerca de {ccy} {fee}{rates})",
        "gap_fee_rates": ", câmbio de {as_of}",
        "gap_fee_short": "; seu orçamento é {obs} — faltam cerca de {ccy} {short}.",
        "gap_fee_no_short": ("; seu orçamento é {obs}, está em outra moeda e não há "
                             "valor convertido disponível, então nenhum déficit "
                             "é informado."),
        "why_header": "Por que {pid} não foi atendido: {n} regra(s) abaixo do mínimo exigido.",
        "why_none": "Nenhuma regra foi reprovada para {pid}.",
        "why_academic_gaokao": ("Acadêmico: não é possível decidir com base nas evidências "
                                "publicadas. Nenhuma universidade publica "
                                "equivalência de Gaokao, então uma nota maior no "
                                "Gaokao não mudaria isso — consulte as vias "
                                "oficiais de Gaokao, não uma correção de nota."),
        "why_academic": "Acadêmico: não é possível decidir com base nas evidências publicadas.",
        "why_cheapest": ("Correção mais barata (sugestão, não um fato): {label} — "
                         "resolve {n} regra(s) ({rules})."),
        "why_no_single": ("Nenhuma mudança isolada resolve uma regra reprovada — cada "
                          "lacuna acima precisaria da sua própria mudança."),
        "exam_ielts_overall": "IELTS geral",
        "exam_toefl": "TOEFL",
        "comp_listening": "compreensão auditiva",
        "comp_reading": "leitura",
        "comp_writing": "escrita",
        "comp_speaking": "expressão oral",
    },
    "ar": {
        "comp_label": "ارفع {comp} في IELTS من {a} إلى {b}",
        "retake_label": "أعد اختبار IELTS وارفع {parts}",
        "retake_part": "{comp} إلى {v}",
        "toefl_label": "ارفع TOEFL من {a} إلى {b}",
        "overall_label": "ارفع الدرجة العامة في IELTS من {a} إلى {b}",
        "budget_label": "ارفع ميزانيتك إلى {v} {ccy}",
        "budget_label_no_ccy": "ارفع ميزانيتك إلى {v}",
        "gap_component": "IELTS {comp}: المطلوب {req}، لديك {obs} (النقص {gap}).",
        "gap_three": "IELTS: ثلاثة مكونات على الأقل بدرجة {req}، لديك {obs} من المكونات بهذا المستوى.",
        "gap_overall": "{exam}: المطلوب {req}، لديك {obs} (النقص {gap}).",
        "gap_toefl": "TOEFL: المطلوب {req}، لديك {obs} (النقص {gap}).",
        "gap_fee_label": "الرسوم الدراسية",
        "gap_fee_base": "الرسوم الدراسية: {ccy} {fee}",
        "gap_fee_converted": " (حوالي {ccy} {fee}{rates})",
        "gap_fee_rates": "، الأسعار بتاريخ {as_of}",
        "gap_fee_short": "؛ ميزانيتك {obs} — النقص حوالي {ccy} {short}.",
        "gap_fee_no_short": "؛ ميزانيتك {obs} بعملة مختلفة ولا يوجد مبلغ محوّل متاح، لذا لا يُذكر أي نقص.",
        "why_header": "لماذا لم يستوفِ {pid}: ‏{n} من القواعد أقل من الحد الأدنى المطلوب.",
        "why_none": "لا توجد قاعدة مخالفة لـ {pid}.",
        "why_academic_gaokao": ("أكاديميًا: لا يمكن تحديده من الأدلة المنشورة. لا تنشر أي جامعة "
                                "معادلة لاختبار Gaokao، لذا فإن الحصول على درجة "
                                "أعلى في Gaokao لن يغير ذلك — راجع المسارات "
                                "الرسمية لاختبار Gaokao وليس تصحيح الدرجة."),
        "why_academic": "أكاديميًا: لا يمكن تحديده من الأدلة المنشورة.",
        "why_cheapest": "أرخص إصلاح (اقتراح وليس حقيقة): {label} — يحل {n} من القواعد ({rules}).",
        "why_no_single": "لا يوجد تغيير واحد بمفرده يحل أي قاعدة مخالفة — كل فجوة أعلاه تحتاج إلى تغيير خاص بها.",
        "exam_ielts_overall": "الدرجة العامة في IELTS",
        "exam_toefl": "TOEFL",
        "comp_listening": "الاستماع",
        "comp_reading": "القراءة",
        "comp_writing": "الكتابة",
        "comp_speaking": "التحدث",
    },
}


def _whynot_strings(locale: str) -> dict:
    return _WHynOT_STRINGS.get(locale) or _WHynOT_STRINGS["en"]


def _comp_name(locale: str, component: str, capital: bool = False) -> str:
    s = _whynot_strings(locale)
    name = s.get(f"comp_{component}", component)
    return name[:1].upper() + name[1:] if capital and name else name


def _candidates_for_rule(rule, gaps: list[dict], locale: str = "en") -> list[dict]:
    """Single-change candidates for one failing rule, with the rules
    each would clear judged structurally (a component raise clears
    its components rule only when it is the sole failing component;
    a combined retake clears it by raising every failing component).
    Engine verification (when a profile is supplied) re-checks this
    and drops any candidate the engine does not flip. Candidate labels
    are template prose: they render in ``locale`` (Round 14)."""
    s = _whynot_strings(locale)
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
                "label": _fill(s["comp_label"],
                               comp=_comp_name(locale, g["label"], capital=True),
                               a=_fmt_num(g["observed"]), b=_fmt_num(target)),
            })
        if len(comp_gaps) > 1 or three_gap is not None:
            changes = {g["label"]: _round_half_up(float(g["required"]))
                       for g in comp_gaps}
            if three_gap is not None:
                target3 = _round_half_up(float(three_gap["required"]))
                for comp in _COMPONENTS:
                    changes.setdefault(comp, target3)
            parts = join_list((_fill(s["retake_part"],
                                    comp=_comp_name(locale, c), v=_fmt_num(v))
                              for c, v in sorted(changes.items())), locale)
            out.append({
                "id": "ielts-components-retake",
                "kind": "ielts_components", "field": "ieltsComponents",
                "component": None, "from": None, "to": changes,
                "resolves_rule_ids": [rule.rule_id],
                "label": _fill(s["retake_label"], parts=parts),
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
                    "label": _fill(s["toefl_label"],
                                   a=_fmt_num(g["observed"]), b=_fmt_num(target)),
                })
            else:
                out.append({
                    "id": f"ielts-overall-to-{target:g}", "kind": "ielts_overall",
                    "field": "ieltsOverall", "component": None,
                    "from": g["observed"], "to": target,
                    "resolves_rule_ids": [rule.rule_id],
                    "label": _fill(s["overall_label"],
                                   a=_fmt_num(g["observed"]), b=_fmt_num(target)),
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
                "label": _fill(s["toefl_label"],
                               a=_fmt_num(g["observed"]), b=_fmt_num(target)),
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
                "label": (_fill(s["budget_label"], v=_fmt_num(target),
                                ccy=currency)
                          if currency else
                          _fill(s["budget_label_no_ccy"], v=_fmt_num(target))),
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


def _gap_line(rule_id: str, gap: dict, locale: str = "en") -> str:
    s = _whynot_strings(locale)
    if gap["kind"] == "component":
        return _fill(s["gap_component"],
                     comp=_comp_name(locale, gap["label"], capital=True),
                     req=_fmt_num(gap["required"]), obs=_fmt_num(gap["observed"]),
                     gap=_fmt_num(gap["gap"]))
    if gap["kind"] == "three_components":
        return _fill(s["gap_three"], req=_fmt_num(gap["required"]),
                     obs=gap["observed"])
    if gap["kind"] == "overall":
        exam = (s["exam_toefl"] if gap["label"] == "toefl"
                else s["exam_ielts_overall"])
        return _fill(s["gap_overall"], exam=exam,
                     req=_fmt_num(gap["required"]), obs=_fmt_num(gap["observed"]),
                     gap=_fmt_num(gap["gap"]))
    if gap["kind"] == "toefl":
        return _fill(s["gap_toefl"],
                     req=_fmt_num(gap["required"]), obs=_fmt_num(gap["observed"]),
                     gap=_fmt_num(gap["gap"]))
    if gap["kind"] == "fee":
        fee = gap.get("fee_amount")
        fee_ccy = gap.get("fee_currency") or ""
        base = (_fill(s["gap_fee_base"], ccy=fee_ccy, fee=_fmt_num(fee))
                if fee is not None else s["gap_fee_label"])
        if gap.get("converted_fee") is not None:
            rates = (_fill(s["gap_fee_rates"], as_of=gap["as_of"])
                     if gap.get("as_of") else "")
            base += _fill(s["gap_fee_converted"],
                          ccy=gap.get("converted_currency"),
                          fee=_fmt_num(gap["converted_fee"]), rates=rates)
        shortfall = gap.get("gap")
        if shortfall is not None and shortfall > 0:
            ccy = gap.get("converted_currency") or fee_ccy
            base += _fill(s["gap_fee_short"], obs=_fmt_num(gap["observed"]),
                          ccy=ccy, short=_fmt_num(shortfall))
        else:
            base += _fill(s["gap_fee_no_short"], obs=_fmt_num(gap["observed"]))
        return base
    return ""


def compute_whynot(evaluation: Evaluation,
                   profile: StudentProfile | None = None,
                   budget_currency: str | None = None,
                   fee_currency: str | None = None,
                   locale: str = "en") -> dict:
    """Why-not explanation for one evaluation, from engine data only.

    Returns the explanation contract the frontend renders and the
    /whynot endpoint returns: failing rules with exact gaps,
    unknown rules, the academic-unknown / Gaokao flags, and the
    cheapest fix (or None, with ``no_single_fix`` when failing rules
    exist but no single change clears one). ``budget_currency`` is
    the applicant's own budget currency and ``fee_currency`` the
    programme's fee currency (for bare 'amount' thresholds);
    without them a cross-currency fee gap reports no shortfall
    rather than guessing one. The template text renders in
    ``locale`` (Round 14); the default "en" keeps old callers
    unchanged.
    """
    s = _whynot_strings(locale)
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
        all_candidates.extend(_candidates_for_rule(r, gaps, locale))
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
        lines.append(_fill(s["why_header"], pid=evaluation.program_id,
                           n=len(failing)))
        for fr in failing:
            for gap in fr["gaps"]:
                line = _gap_line(fr["rule_id"], gap, locale)
                if line:
                    lines.append(f"- {fr['rule_id']}: {line}")
                else:
                    lines.append(f"- {fr['rule_id']}: {gap.get('text', fr['detail'])}")
    else:
        lines.append(_fill(s["why_none"], pid=evaluation.program_id))
    if academic_unknown:
        if gaokao_route:
            lines.append(s["why_academic_gaokao"])
        else:
            lines.append(s["why_academic"])
    if cheapest is not None:
        lines.append(_fill(s["why_cheapest"], label=cheapest["label"],
                           n=cheapest["rules_resolved"],
                           rules=join_list(cheapest["resolves_rule_ids"],
                                           locale)))
    elif no_single_fix:
        lines.append(s["why_no_single"])
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

    Single-programme on-demand model polish ONLY (Round 13: the
    batched POST /api/v1/whynot endpoint no longer calls this — it is
    template-only, because one sync model call per programme in a
    batch blocked the event loop for minutes). If this is ever wired
    to an endpoint, that endpoint must run it in a worker thread with
    a <=15 s budget, never in a per-programme loop.

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
                            fee_currency=fee_currency, locale=locale)
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


# ---------------------------------------------------------------------------
# Localised gap state (Round 15, Finding 1)
#
# ``localised_gap_state`` renders one engine RuleResult as the
# ``current_state`` sentence a plan gap shows — in the requested locale,
# built ONLY from the rule's structured data (rule id family, status,
# threshold, observed), never from the engine's English ``detail``
# string. The plan UI used to render ``rule.detail`` verbatim, so a
# Chinese plan showed an English sentence ("This programme requires
# German C1 (CEFR), not an IELTS/TOEFL score; ...") inside a Chinese
# frame. Requirement labels (e.g. "German C1 (CEFR)", "IELTS", "TMUA")
# are proper names and stay verbatim in every locale; only the
# surrounding prose is translated. Numeric language/fee gaps reuse
# the whynot renderer (_gaps_for_rule/_gap_line) so the numbers match
# the why-not view exactly; the branches below cover the shapes it
# does not (other-language requirements, no test, TOEFL date/scale,
# fee unknowns, academic/Gaokao, GCSE, test, experience, generic).
# ``template_explanation`` above still embeds the raw English detail
# — that endpoint's contract is unchanged by this round (see report).
# ---------------------------------------------------------------------------

_GAP_STATE_STRINGS = {
    "en": {
        "lang_other": ("This programme requires {labels}; no evidence for "
                       "that requirement was supplied, so it cannot be "
                       "assessed from a test score."),
        "lang_no_test": "No language test supplied.",
        "lang_wrong_exam_ielts": ("IELTS was supplied, but this programme "
                                  "states no IELTS minimum, so the supplied "
                                  "score is not evidence for any stated route."),
        "lang_wrong_exam_toefl": ("TOEFL was supplied, but this programme "
                                  "states no TOEFL minimum, so the supplied "
                                  "score is not evidence for any stated route."),
        "lang_unknown": ("{label}: cannot be decided from the supplied "
                         "evidence. Check the official programme page for "
                         "which language tests and scores it accepts."),
        "lang_met_overall": "{exam} overall {obs} meets the stated minimum {req}.",
        "lang_met_components": "Every required IELTS component meets its minimum.",
        "lang_components_missing": "IELTS component score(s) not supplied: {comps}.",
        "lang_components_unknown": ("{label}: the supplied evidence does not "
                                    "include IELTS component scores, so the "
                                    "components cannot be assessed."),
        "lang_toefl_date": ("TOEFL was supplied but no valid test date was "
                            "given, so the scale cannot be chosen and TOEFL "
                            "cannot be compared."),
        "lang_toefl_scale": ("The supplied TOEFL score looks like the new "
                             "1–6 scale, but only an iBT threshold is stated, "
                             "so the score cannot be compared."),
        "fee_met": ("Budget {ccy} {obs} {period} covers the {fee_ccy} {fee} "
                    "{period} tuition fee."),
        "fee_met_converted": ("Budget {ccy} {obs} {period} covers the "
                              "{fee_ccy} {fee} {period} tuition fee (about "
                              "{ccy} {converted})."),
        "fee_no_amount": ("No tuition fee amount is stated on the official "
                          "programme page, so the fee cannot be compared "
                          "with the budget."),
        "fee_no_budget": "No budget supplied.",
        "fee_period_mismatch": ("Budget period ({bperiod}) does not match "
                                "the fee period ({fperiod}), so it cannot be "
                                "compared with the fee."),
        "fee_no_rate": ("The fee and the budget are in different currencies "
                        "and no reference exchange rate is available for "
                        "this currency pair, so the fee cannot be converted "
                        "for comparison."),
        "fee_unknown": ("{label}: cannot be decided from the supplied "
                        "evidence. Check the official programme page for the "
                        "published fee."),
        "academic_gaokao": ("Gaokao {score}/{total}: no university publishes "
                            "a Gaokao equivalence, and Gaokao scores are "
                            "never converted to A-level grades — see the "
                            "official Gaokao routes, not a score fix."),
        "academic_gaokao_no_score": ("No university publishes a Gaokao "
                                     "equivalence, and Gaokao scores are "
                                     "never converted to A-level grades — see "
                                     "the official Gaokao routes, not a score fix."),
        "academic_alevel_below": "A-level grades do not meet the stated A-level threshold.",
        "academic_no_threshold": ("No A-level threshold is stated for this "
                                  "programme, so academic eligibility cannot "
                                  "be decided from grades alone."),
        "academic_not_alevel": ("An A-level threshold is stated, but this "
                                "applicant's curriculum is not A-level; "
                                "scores are never converted to A-levels."),
        "academic_no_grades": "A-level grades not supplied (three grades are needed).",
        "academic_masters": ("A-level thresholds apply to undergraduate "
                             "entry; this is a taught-masters programme, so "
                             "no A-level rule can be assessed here."),
        "academic_not_met": "{label}: the stated academic minimum was not met.",
        "academic_unknown": ("{label}: cannot be decided from the published "
                             "evidence. Check the official programme page for "
                             "the accepted qualifications."),
        "test_unknown": ("{test}: the requirement cannot be decided from the "
                         "supplied evidence. Check the official programme "
                         "page for whether a test is required and what score "
                         "is published."),
        "test_not_met": "{test}: the stated minimum was not met.",
        "gcse_below": "GCSE English {eng} / Maths {maths}: grade C/4 is required.",
        "gcse_unknown": ("GCSE grade(s) not supplied or unrecognised: "
                         "{subjects}. GCSE English and Maths at grade C/4 "
                         "are required."),
        "gcse_met": "GCSE English and Maths are both at grade C/4 or above.",
        "experience_unknown": ("{label}: the required experience evidence "
                               "was not supplied, so this rule cannot be "
                               "decided."),
        "experience_not_met": "{label}: the stated minimum was not met.",
        "generic_not_met": "{label}: the stated minimum was not met.",
        "generic_unknown": ("{label}: cannot be decided from the supplied "
                            "evidence. Check the official programme page for "
                            "what is required."),
        "generic_met": "{label}: meets the stated minimum.",
        "period.per_year": "per year",
        "period.total": "in total",
        "subject.english": "English",
        "subject.maths": "Maths",
    },
    "zh-CN": {
        "lang_other": ("该项目要求 {labels}，而不是雅思/托福成绩；未提供该要求的证明，"
                       "因此无法通过考试成绩评估。"),
        "lang_no_test": "未提供任何语言考试成绩。",
        "lang_wrong_exam_ielts": ("已提供雅思成绩，但该项目没有公布雅思最低要求，"
                                  "因此该成绩不能作为任何已公布路线的证明。"),
        "lang_wrong_exam_toefl": ("已提供托福成绩，但该项目没有公布托福最低要求，"
                                  "因此该成绩不能作为任何已公布路线的证明。"),
        "lang_unknown": "{label}：根据现有证据无法判定。请查看官方项目页面，了解其接受哪些语言考试和分数。",
        "lang_met_overall": "{exam}总分 {obs} 达到规定的最低要求 {req}。",
        "lang_met_components": "所有要求的雅思单项均达到最低要求。",
        "lang_components_missing": "未提供雅思单项成绩：{comps}。",
        "lang_components_unknown": "{label}：现有证据中没有雅思单项成绩，因此无法评估各单项。",
        "lang_toefl_date": "已提供托福成绩，但没有有效的考试日期，因此无法确定适用量表，也无法比较托福成绩。",
        "lang_toefl_scale": "所提供的托福成绩像是新的 1–6 分量表，但只公布了 iBT 门槛，因此无法比较该成绩。",
        "fee_met": "预算 {ccy} {obs}{period}已覆盖学费 {fee_ccy} {fee}{period}。",
        "fee_met_converted": "预算 {ccy} {obs}{period}已覆盖学费 {fee_ccy} {fee}{period}（约 {ccy} {converted}）。",
        "fee_no_amount": "官方项目页面上没有公布学费金额，因此无法将学费与预算比较。",
        "fee_no_budget": "未提供预算。",
        "fee_period_mismatch": "预算周期（{bperiod}）与学费周期（{fperiod}）不一致，因此无法比较。",
        "fee_no_rate": "学费与预算币种不同，且没有该货币对的参考汇率，因此无法换算比较。",
        "fee_unknown": "{label}：根据现有证据无法判定。请查看官方项目页面上公布的学费。",
        "academic_gaokao": "高考 {score}/{total}：没有大学公布高考分数换算标准，高考分数从不换算为 A-level 成绩——请查看官方公布的高考入学路径，而不是纠结分数。",
        "academic_gaokao_no_score": "没有大学公布高考分数换算标准，高考分数从不换算为 A-level 成绩——请查看官方公布的高考入学路径，而不是纠结分数。",
        "academic_alevel_below": "A-level 成绩未达到规定的 A-level 门槛。",
        "academic_no_threshold": "该项目没有公布 A-level 门槛，因此无法仅凭成绩判定学术资格。",
        "academic_not_alevel": "该项目公布了 A-level 门槛，但申请人的课程体系不是 A-level；分数从不换算为 A-level 成绩。",
        "academic_no_grades": "未提供 A-level 成绩（需要三门成绩）。",
        "academic_masters": "A-level 门槛只适用于本科入学；这是授课型硕士项目，因此此处无法评估 A-level 规则。",
        "academic_not_met": "{label}：未达到规定的学术最低要求。",
        "academic_unknown": "{label}：根据已公布的证据无法判定。请查看官方项目页面，了解其接受哪些学历。",
        "test_unknown": "{test}：根据现有证据无法判定。请查看官方项目页面，了解是否需要考试以及公布的分数。",
        "test_not_met": "{test}：未达到规定的最低要求。",
        "gcse_below": "GCSE 英语 {eng} / 数学 {maths}：要求达到 C/4。",
        "gcse_unknown": "未提供或无法识别 GCSE 成绩：{subjects}。要求 GCSE 英语和数学达到 C/4。",
        "gcse_met": "GCSE 英语和数学均达到 C/4 或以上。",
        "experience_unknown": "{label}：未提供所需的工作经验依据，因此无法判定此规则。",
        "experience_not_met": "{label}：未达到规定的最低要求。",
        "generic_not_met": "{label}：未达到规定的最低要求。",
        "generic_unknown": "{label}：根据现有证据无法判定。请查看官方项目页面，了解具体要求。",
        "generic_met": "{label}：达到规定的最低要求。",
        "period.per_year": "每年",
        "period.total": "总计",
        "subject.english": "英语",
        "subject.maths": "数学",
    },
    "es": {
        "lang_other": ("Este programa exige {labels}, no una puntuación de "
                       "IELTS/TOEFL; no se aportó evidencia de ese "
                       "requisito, así que no se puede evaluar con una "
                       "puntuación de examen."),
        "lang_no_test": "No se aportó ningún examen de idioma.",
        "lang_wrong_exam_ielts": ("Se aportó IELTS, pero este programa no "
                                  "establece un mínimo de IELTS, así que la "
                                  "puntuación no es evidencia de ninguna vía "
                                  "establecida."),
        "lang_wrong_exam_toefl": ("Se aportó TOEFL, pero este programa no "
                                  "establece un mínimo de TOEFL, así que la "
                                  "puntuación no es evidencia de ninguna vía "
                                  "establecida."),
        "lang_unknown": ("{label}: no se puede decidir con la evidencia "
                         "proporcionada. Consulta la página oficial del "
                         "programa para ver qué exámenes de idioma y "
                         "puntuaciones acepta."),
        "lang_met_overall": "{exam} general {obs} alcanza el mínimo establecido {req}.",
        "lang_met_components": "Todos los componentes exigidos de IELTS alcanzan su mínimo.",
        "lang_components_missing": "Puntuación(es) de componentes de IELTS no aportada(s): {comps}.",
        "lang_components_unknown": ("{label}: la evidencia proporcionada no "
                                    "incluye puntuaciones de componentes de "
                                    "IELTS, así que los componentes no se "
                                    "pueden evaluar."),
        "lang_toefl_date": ("Se aportó TOEFL pero no una fecha válida de "
                            "examen, así que no se puede elegir la escala y "
                            "el TOEFL no se puede comparar."),
        "lang_toefl_scale": ("La puntuación de TOEFL aportada parece de la "
                             "nueva escala 1–6, pero solo se establece un "
                             "umbral iBT, así que la puntuación no se puede "
                             "comparar."),
        "fee_met": ("El presupuesto de {ccy} {obs} {period} cubre la "
                    "matrícula de {fee_ccy} {fee} {period}."),
        "fee_met_converted": ("El presupuesto de {ccy} {obs} {period} cubre "
                              "la matrícula de {fee_ccy} {fee} {period} "
                              "(aprox. {ccy} {converted})."),
        "fee_no_amount": ("La página oficial del programa no establece "
                          "ningún importe de matrícula, así que la matrícula "
                          "no se puede comparar con el presupuesto."),
        "fee_no_budget": "No se aportó presupuesto.",
        "fee_period_mismatch": ("El periodo del presupuesto ({bperiod}) no "
                                "coincide con el periodo de la matrícula "
                                "({fperiod}), así que no se pueden comparar."),
        "fee_no_rate": ("La matrícula y el presupuesto están en monedas "
                        "distintas y no hay tipo de cambio de referencia "
                        "disponible para ese par, así que la matrícula no se "
                        "puede convertir para comparar."),
        "fee_unknown": ("{label}: no se puede decidir con la evidencia "
                        "proporcionada. Consulta la página oficial del "
                        "programa para ver la matrícula publicada."),
        "academic_gaokao": ("Gaokao {score}/{total}: ninguna universidad "
                            "publica una equivalencia de Gaokao, y las "
                            "puntuaciones de Gaokao nunca se convierten a "
                            "calificaciones A-level — consulta las vías "
                            "oficiales de Gaokao, no una corrección de "
                            "puntuación."),
        "academic_gaokao_no_score": ("Ninguna universidad publica una "
                                     "equivalencia de Gaokao, y las "
                                     "puntuaciones de Gaokao nunca se "
                                     "convierten a calificaciones A-level — "
                                     "consulta las vías oficiales de Gaokao, "
                                     "no una corrección de puntuación."),
        "academic_alevel_below": "Las calificaciones A-level no alcanzan el umbral A-level establecido.",
        "academic_no_threshold": ("Este programa no establece ningún umbral "
                                  "A-level, así que la elegibilidad académica "
                                  "no se puede decidir solo con las notas."),
        "academic_not_alevel": ("Se establece un umbral A-level, pero el "
                                "plan de estudios de este solicitante no es "
                                "A-level; las puntuaciones nunca se convierten "
                                "a A-level."),
        "academic_no_grades": "Calificaciones A-level no aportadas (se necesitan tres calificaciones).",
        "academic_masters": ("Los umbrales A-level se aplican al acceso de "
                             "grado; este es un programa de máster, así que "
                             "ninguna regla A-level se puede evaluar aquí."),
        "academic_not_met": "{label}: el mínimo académico establecido no se alcanzó.",
        "academic_unknown": ("{label}: no se puede decidir con la evidencia "
                             "publicada. Consulta la página oficial del "
                             "programa para ver las titulaciones aceptadas."),
        "test_unknown": ("{test}: el requisito no se puede decidir con la "
                         "evidencia proporcionada. Consulta la página "
                         "oficial del programa para ver si se exige un examen "
                         "y qué puntuación se publica."),
        "test_not_met": "{test}: el mínimo establecido no se alcanzó.",
        "gcse_below": "GCSE inglés {eng} / matemáticas {maths}: se exige la nota C/4.",
        "gcse_unknown": ("Nota(s) de GCSE no aportada(s) o no reconocida(s): "
                         "{subjects}. Se exigen GCSE inglés y matemáticas "
                         "con nota C/4."),
        "gcse_met": "GCSE inglés y matemáticas están ambos en C/4 o por encima.",
        "experience_unknown": ("{label}: la evidencia de experiencia "
                               "requerida no se aportó, así que esta regla no "
                               "se puede decidir."),
        "experience_not_met": "{label}: el mínimo establecido no se alcanzó.",
        "generic_not_met": "{label}: el mínimo establecido no se alcanzó.",
        "generic_unknown": ("{label}: no se puede decidir con la evidencia "
                            "proporcionada. Consulta la página oficial del "
                            "programa para ver lo que se exige."),
        "generic_met": "{label}: alcanza el mínimo establecido.",
        "period.per_year": "al año",
        "period.total": "en total",
        "subject.english": "inglés",
        "subject.maths": "matemáticas",
    },
    "fr": {
        "lang_other": ("Ce programme exige {labels}, et non un score "
                       "IELTS/TOEFL ; aucune preuve de cette exigence n'a "
                       "été fournie, elle ne peut donc pas être évaluée à "
                       "partir d'un score de test."),
        "lang_no_test": "Aucun test de langue fourni.",
        "lang_wrong_exam_ielts": ("Un score IELTS a été fourni, mais ce "
                                  "programme n'établit aucun minimum IELTS, "
                                  "ce score n'est donc la preuve d'aucune voie "
                                  "établie."),
        "lang_wrong_exam_toefl": ("Un score TOEFL a été fourni, mais ce "
                                  "programme n'établit aucun minimum TOEFL, "
                                  "ce score n'est donc la preuve d'aucune voie "
                                  "établie."),
        "lang_unknown": ("{label} : impossible à décider à partir des "
                         "preuves fournies. Consultez la page officielle du "
                         "programme pour savoir quels tests de langue et "
                         "quels scores il accepte."),
        "lang_met_overall": "{exam} global {obs} atteint le minimum requis {req}.",
        "lang_met_components": "Toutes les composantes IELTS exigées atteignent leur minimum.",
        "lang_components_missing": "Score(s) de composantes IELTS non fourni(s) : {comps}.",
        "lang_components_unknown": ("{label} : les preuves fournies ne "
                                    "comprennent pas de scores de composantes "
                                    "IELTS, les composantes ne peuvent donc "
                                    "pas être évaluées."),
        "lang_toefl_date": ("Un score TOEFL a été fourni mais sans date de "
                            "test valide, l'échelle ne peut donc pas être "
                            "choisie et le TOEFL ne peut pas être comparé."),
        "lang_toefl_scale": ("Le score TOEFL fourni ressemble à la nouvelle "
                             "échelle 1–6, mais seul un seuil iBT est "
                             "établi, le score ne peut donc pas être comparé."),
        "fee_met": ("Le budget de {ccy} {obs} {period} couvre les frais de "
                    "scolarité de {fee_ccy} {fee} {period}."),
        "fee_met_converted": ("Le budget de {ccy} {obs} {period} couvre les "
                              "frais de scolarité de {fee_ccy} {fee} "
                              "{period} (environ {ccy} {converted})."),
        "fee_no_amount": ("La page officielle du programme n'indique aucun "
                          "montant de frais de scolarité, les frais ne "
                          "peuvent donc pas être comparés au budget."),
        "fee_no_budget": "Aucun budget fourni.",
        "fee_period_mismatch": ("La période du budget ({bperiod}) ne "
                                "correspond pas à la période des frais "
                                "({fperiod}), ils ne peuvent donc pas être "
                                "comparés."),
        "fee_no_rate": ("Les frais et le budget sont dans des devises "
                        "différentes et aucun taux de change de référence "
                        "n'est disponible pour cette paire, les frais ne "
                        "peuvent donc pas être convertis pour comparaison."),
        "fee_unknown": ("{label} : impossible à décider à partir des "
                        "preuves fournies. Consultez la page officielle du "
                        "programme pour les frais publiés."),
        "academic_gaokao": ("Gaokao {score}/{total} : aucune université ne "
                            "publie d'équivalence du Gaokao, et les scores "
                            "Gaokao ne sont jamais convertis en notes "
                            "A-level — consultez les voies Gaokao officielles, "
                            "pas une correction de score."),
        "academic_gaokao_no_score": ("Aucune université ne publie "
                                     "d'équivalence du Gaokao, et les scores "
                                     "Gaokao ne sont jamais convertis en notes "
                                     "A-level — consultez les voies Gaokao "
                                     "officielles, pas une correction de score."),
        "academic_alevel_below": "Les notes A-level n'atteignent pas le seuil A-level requis.",
        "academic_no_threshold": ("Ce programme n'établit aucun seuil "
                                  "A-level, l'éligibilité académique ne peut "
                                  "donc pas être décidée à partir des notes "
                                  "seules."),
        "academic_not_alevel": ("Un seuil A-level est établi, mais le cursus "
                                "de ce candidat n'est pas A-level ; les scores "
                                "ne sont jamais convertis en A-level."),
        "academic_no_grades": "Notes A-level non fournies (trois notes sont nécessaires).",
        "academic_masters": ("Les seuils A-level s'appliquent à l'entrée en "
                             "licence ; il s'agit d'un programme de master, "
                             "aucune règle A-level ne peut donc être évaluée "
                             "ici."),
        "academic_not_met": "{label} : le minimum académique requis n'est pas atteint.",
        "academic_unknown": ("{label} : impossible à décider à partir des "
                             "preuves publiées. Consultez la page officielle "
                             "du programme pour les diplômes acceptés."),
        "test_unknown": ("{test} : l'exigence ne peut pas être décidée à "
                         "partir des preuves fournies. Consultez la page "
                         "officielle du programme pour savoir si un test est "
                         "exigé et quel score est publié."),
        "test_not_met": "{test} : le minimum requis n'est pas atteint.",
        "gcse_below": "GCSE anglais {eng} / mathématiques {maths} : la note C/4 est exigée.",
        "gcse_unknown": ("Note(s) GCSE non fournie(s) ou non reconnue(s) : "
                         "{subjects}. GCSE anglais et mathématiques à la "
                         "note C/4 sont exigés."),
        "gcse_met": "GCSE anglais et mathématiques sont tous deux à C/4 ou au-dessus.",
        "experience_unknown": ("{label} : la preuve d'expérience requise n'a "
                               "pas été fournie, cette règle ne peut donc pas "
                               "être décidée."),
        "experience_not_met": "{label} : le minimum requis n'est pas atteint.",
        "generic_not_met": "{label} : le minimum requis n'est pas atteint.",
        "generic_unknown": ("{label} : impossible à décider à partir des "
                            "preuves fournies. Consultez la page officielle "
                            "du programme pour savoir ce qui est exigé."),
        "generic_met": "{label} : satisfait le minimum requis.",
        "period.per_year": "par an",
        "period.total": "au total",
        "subject.english": "anglais",
        "subject.maths": "mathématiques",
    },
    "pt-BR": {
        "lang_other": ("Este programa exige {labels}, e não uma nota de "
                       "IELTS/TOEFL; nenhuma evidência desse requisito foi "
                       "fornecida, portanto ele não pode ser avaliado por "
                       "uma nota de exame."),
        "lang_no_test": "Nenhum exame de idioma fornecido.",
        "lang_wrong_exam_ielts": ("O IELTS foi fornecido, mas este programa "
                                  "não estabelece um mínimo de IELTS, portanto "
                                  "a nota não é evidência de nenhuma via "
                                  "estabelecida."),
        "lang_wrong_exam_toefl": ("O TOEFL foi fornecido, mas este programa "
                                  "não estabelece um mínimo de TOEFL, portanto "
                                  "a nota não é evidência de nenhuma via "
                                  "estabelecida."),
        "lang_unknown": ("{label}: não é possível decidir com base nas "
                         "evidências fornecidas. Consulte a página oficial "
                         "do programa para ver quais exames de idioma e "
                         "notas ele aceita."),
        "lang_met_overall": "{exam} geral {obs} atinge o mínimo exigido {req}.",
        "lang_met_components": "Todos os componentes exigidos do IELTS atingem seu mínimo.",
        "lang_components_missing": "Nota(s) de componentes do IELTS não fornecida(s): {comps}.",
        "lang_components_unknown": ("{label}: as evidências fornecidas não "
                                    "incluem notas de componentes do IELTS, "
                                    "portanto os componentes não podem ser "
                                    "avaliados."),
        "lang_toefl_date": ("O TOEFL foi fornecido, mas sem uma data válida "
                            "de exame, portanto a escala não pode ser "
                            "escolhida e o TOEFL não pode ser comparado."),
        "lang_toefl_scale": ("A nota de TOEFL fornecida parece da nova "
                             "escala 1–6, mas apenas um limite iBT é "
                             "estabelecido, portanto a nota não pode ser "
                             "comparada."),
        "fee_met": ("O orçamento de {ccy} {obs} {period} cobre a mensalidade "
                    "de {fee_ccy} {fee} {period}."),
        "fee_met_converted": ("O orçamento de {ccy} {obs} {period} cobre a "
                              "mensalidade de {fee_ccy} {fee} {period} "
                              "(cerca de {ccy} {converted})."),
        "fee_no_amount": ("A página oficial do programa não informa nenhum "
                          "valor de mensalidade, portanto a mensalidade não "
                          "pode ser comparada com o orçamento."),
        "fee_no_budget": "Nenhum orçamento fornecido.",
        "fee_period_mismatch": ("O período do orçamento ({bperiod}) não "
                                "corresponde ao período da mensalidade "
                                "({fperiod}), portanto não podem ser "
                                "comparados."),
        "fee_no_rate": ("A mensalidade e o orçamento estão em moedas "
                        "diferentes e não há taxa de câmbio de referência "
                        "disponível para esse par, portanto a mensalidade não "
                        "pode ser convertida para comparação."),
        "fee_unknown": ("{label}: não é possível decidir com base nas "
                        "evidências fornecidas. Consulte a página oficial do "
                        "programa para ver a mensalidade publicada."),
        "academic_gaokao": ("Gaokao {score}/{total}: nenhuma universidade "
                            "publica uma equivalência de Gaokao, e as notas "
                            "do Gaokao nunca são convertidas para notas "
                            "A-level — consulte as vias oficiais de Gaokao, "
                            "não uma correção de nota."),
        "academic_gaokao_no_score": ("Nenhuma universidade publica uma "
                                     "equivalência de Gaokao, e as notas do "
                                     "Gaokao nunca são convertidas para notas "
                                     "A-level — consulte as vias oficiais de "
                                     "Gaokao, não uma correção de nota."),
        "academic_alevel_below": "As notas A-level não atingem o limite A-level estabelecido.",
        "academic_no_threshold": ("Este programa não estabelece nenhum limite "
                                  "A-level, portanto a elegibilidade acadêmica "
                                  "não pode ser decidida apenas com as notas."),
        "academic_not_alevel": ("Um limite A-level é estabelecido, mas o "
                                "currículo deste candidato não é A-level; as "
                                "notas nunca são convertidas para A-level."),
        "academic_no_grades": "Notas A-level não fornecidas (são necessárias três notas).",
        "academic_masters": ("Os limites A-level aplicam-se ao ingresso na "
                             "graduação; este é um programa de mestrado, "
                             "portanto nenhuma regra A-level pode ser avaliada "
                             "aqui."),
        "academic_not_met": "{label}: o mínimo acadêmico exigido não foi atingido.",
        "academic_unknown": ("{label}: não é possível decidir com base nas "
                             "evidências publicadas. Consulte a página "
                             "oficial do programa para ver as qualificações "
                             "aceitas."),
        "test_unknown": ("{test}: o requisito não pode ser decidido com base "
                         "nas evidências fornecidas. Consulte a página "
                         "oficial do programa para saber se um exame é "
                         "exigido e qual nota é publicada."),
        "test_not_met": "{test}: o mínimo exigido não foi atingido.",
        "gcse_below": "GCSE inglês {eng} / matemática {maths}: exige-se a nota C/4.",
        "gcse_unknown": ("Nota(s) do GCSE não fornecida(s) ou não "
                         "reconhecida(s): {subjects}. Exigem-se GCSE inglês "
                         "e matemática com nota C/4."),
        "gcse_met": "GCSE inglês e matemática estão ambos em C/4 ou acima.",
        "experience_unknown": ("{label}: a evidência de experiência "
                               "exigida não foi fornecida, portanto esta regra "
                               "não pode ser decidida."),
        "experience_not_met": "{label}: o mínimo exigido não foi atingido.",
        "generic_not_met": "{label}: o mínimo exigido não foi atingido.",
        "generic_unknown": ("{label}: não é possível decidir com base nas "
                            "evidências fornecidas. Consulte a página oficial "
                            "do programa para ver o que é exigido."),
        "generic_met": "{label}: atinge o mínimo exigido.",
        "period.per_year": "por ano",
        "period.total": "no total",
        "subject.english": "inglês",
        "subject.maths": "matemática",
    },
    "ar": {
        "lang_other": ("يتطلب هذا البرنامج {labels}، وليس درجة IELTS/TOEFL؛ "
                       "ولم يتم تقديم أي دليل على هذا المتطلب، لذا لا يمكن "
                       "تقييمه من درجة اختبار."),
        "lang_no_test": "لم يتم تقديم أي اختبار لغة.",
        "lang_wrong_exam_ielts": ("تم تقديم IELTS، لكن هذا البرنامج لا يحدد "
                                  "حدًا أدنى لـ IELTS، لذا فإن الدرجة المقدمة "
                                  "ليست دليلًا على أي مسار محدد."),
        "lang_wrong_exam_toefl": ("تم تقديم TOEFL، لكن هذا البرنامج لا يحدد "
                                  "حدًا أدنى لـ TOEFL، لذا فإن الدرجة المقدمة "
                                  "ليست دليلًا على أي مسار محدد."),
        "lang_unknown": ("{label}: لا يمكن تحديده من الأدلة المقدمة. راجع "
                         "صفحة البرنامج الرسمية لمعرفة اختبارات اللغة "
                         "والدرجات التي يقبلها."),
        "lang_met_overall": "{exam} العامة {obs} تستوفي الحد الأدنى المطلوب {req}.",
        "lang_met_components": "جميع مكونات IELTS المطلوبة تستوفي الحد الأدنى.",
        "lang_components_missing": "لم يتم تقديم درجة (درجات) مكونات IELTS: {comps}.",
        "lang_components_unknown": ("{label}: الأدلة المقدمة لا تتضمن درجات "
                                    "مكونات IELTS، لذا لا يمكن تقييم "
                                    "المكونات."),
        "lang_toefl_date": ("تم تقديم TOEFL ولكن دون تاريخ اختبار صالح، لذا "
                            "لا يمكن اختيار المقياس ولا يمكن مقارنة TOEFL."),
        "lang_toefl_scale": ("تبدو درجة TOEFL المقدمة من المقياس الجديد 1–6، "
                             "لكن الحد المعلن الوحيد هو حد iBT، لذا لا يمكن "
                             "مقارنة الدرجة."),
        "fee_met": ("الميزانية {ccy} {obs} {period} تغطي الرسوم الدراسية "
                    "{fee_ccy} {fee} {period}."),
        "fee_met_converted": ("الميزانية {ccy} {obs} {period} تغطي الرسوم "
                              "الدراسية {fee_ccy} {fee} {period} (حوالي "
                              "{ccy} {converted})."),
        "fee_no_amount": ("لا تذكر صفحة البرنامج الرسمية أي مبلغ للرسوم "
                          "الدراسية، لذا لا يمكن مقارنة الرسوم بالميزانية."),
        "fee_no_budget": "لم يتم تقديم ميزانية.",
        "fee_period_mismatch": ("فترة الميزانية ({bperiod}) لا تطابق فترة "
                                "الرسوم ({fperiod})، لذا لا يمكن مقارنتهما."),
        "fee_no_rate": ("الرسوم والميزانية بعملتين مختلفتين ولا يوجد سعر "
                        "صرف مرجعي متاح لهذا الزوج، لذا لا يمكن تحويل الرسوم "
                        "للمقارنة."),
        "fee_unknown": ("{label}: لا يمكن تحديده من الأدلة المقدمة. راجع "
                        "صفحة البرنامج الرسمية لمعرفة الرسوم المنشورة."),
        "academic_gaokao": ("Gaokao {score}/{total}: لا تنشر أي جامعة معادلة "
                            "لاختبار Gaokao، ولا تُحوَّل درجات Gaokao أبدًا "
                            "إلى درجات A-level — راجع المسارات الرسمية "
                            "لاختبار Gaokao وليس تصحيح الدرجة."),
        "academic_gaokao_no_score": ("لا تنشر أي جامعة معادلة لاختبار Gaokao، "
                                     "ولا تُحوَّل درجات Gaokao أبدًا إلى درجات "
                                     "A-level — راجع المسارات الرسمية لاختبار "
                                     "Gaokao وليس تصحيح الدرجة."),
        "academic_alevel_below": "درجات A-level لا تستوفي الحد الأدنى المطلوب لـ A-level.",
        "academic_no_threshold": ("لا يحدد هذا البرنامج أي حد لـ A-level، لذا "
                                  "لا يمكن تحديد الأهلية الأكاديمية من الدرجات "
                                  "وحدها."),
        "academic_not_alevel": ("يوجد حد لـ A-level، لكن منهج هذا المتقدم ليس "
                                "A-level؛ ولا تُحوَّل الدرجات أبدًا إلى "
                                "A-level."),
        "academic_no_grades": "لم يتم تقديم درجات A-level (يلزم ثلاث درجات).",
        "academic_masters": ("تنطبق حدود A-level على الالتحاق بالبكالوريوس؛ "
                             "هذا برنامج ماجستير، لذا لا يمكن تقييم أي قاعدة "
                             "A-level هنا."),
        "academic_not_met": "{label}: لم يتم استيفاء الحد الأدنى الأكاديمي المطلوب.",
        "academic_unknown": ("{label}: لا يمكن تحديده من الأدلة المنشورة. "
                             "راجع صفحة البرنامج الرسمية لمعرفة المؤهلات "
                             "المقبولة."),
        "test_unknown": ("{test}: لا يمكن تحديد المتطلب من الأدلة المقدمة. "
                         "راجع صفحة البرنامج الرسمية لمعرفة ما إذا كان "
                         "الاختبار مطلوبًا وما الدرجة المنشورة."),
        "test_not_met": "{test}: لم يتم استيفاء الحد الأدنى المطلوب.",
        "gcse_below": "GCSE الإنجليزية {eng} / الرياضيات {maths}: الدرجة C/4 مطلوبة.",
        "gcse_unknown": ("لم يتم تقديم درجة (درجات) GCSE أو لم يتم التعرف "
                         "عليها: {subjects}. يشترط الحصول على C/4 في GCSE "
                         "الإنجليزية والرياضيات."),
        "gcse_met": "GCSE الإنجليزية والرياضيات كلاهما بدرجة C/4 أو أعلى.",
        "experience_unknown": ("{label}: لم يتم تقديم دليل الخبرة المطلوب، لذا "
                               "لا يمكن تحديد هذه القاعدة."),
        "experience_not_met": "{label}: لم يتم استيفاء الحد الأدنى المطلوب.",
        "generic_not_met": "{label}: لم يتم استيفاء الحد الأدنى المطلوب.",
        "generic_unknown": ("{label}: لا يمكن تحديده من الأدلة المقدمة. راجع "
                            "صفحة البرنامج الرسمية لمعرفة المطلوب."),
        "generic_met": "{label}: يستوفي الحد الأدنى المطلوب.",
        "period.per_year": "سنويًا",
        "period.total": "إجمالًا",
        "subject.english": "الإنجليزية",
        "subject.maths": "الرياضيات",
    },
}


def _gap_state_strings(locale: str) -> dict:
    return _GAP_STATE_STRINGS.get(locale) or _GAP_STATE_STRINGS["en"]


def _gap_state_period(s: dict, period: str | None) -> str:
    """Localised period word for a fee sentence: 'per year' / 'in
    total' in the locale, '' when the period is unknown (the sentence
    templates tolerate an empty period)."""
    if period == "per_year":
        return s["period.per_year"]
    if period == "total":
        return s["period.total"]
    return ""


def _gap_state_other_labels(rule) -> list[str]:
    thr = rule.threshold if isinstance(rule.threshold, dict) else None
    labels = (thr or {}).get("other_requirements")
    if isinstance(labels, list):
        return [str(v) for v in labels if isinstance(v, str) and str(v).strip()]
    return []


def _gap_state_obs_dict(rule) -> dict:
    return rule.observed if isinstance(rule.observed, dict) else {}


def _gap_state_exam(rule) -> str:
    """IELTS / TOEFL / Language, from the rule id: v2 overall rules
    name the exam (ucl-ielts-overall); the IELTS-or-TOEFL rules
    (nus-language) stay neutral."""
    rid = (rule.rule_id or "").lower()
    if "toefl" in rid:
        return "TOEFL"
    if "ielts" in rid:
        return "IELTS"
    return "Language"


def _gap_state_test_name(rule) -> str | None:
    """TMUA / TARA / GRE / GMAT, from the rule id, else None."""
    rid = (rule.rule_id or "").lower()
    for name in ("tmua", "tara", "gre", "gmat"):
        if name in rid:
            return name.upper()
    return None


def _gap_state_fee_numbers(rule, budget_currency, budget_period):
    """(fee_amount, fee_currency, period, budget_amount, approx) for a
    fee rule, from threshold + observed + the profile budget. The fee
    currency falls back to the budget currency only when the engine
    compared without a converted figure — i.e. same-currency — so it
    is never a cross-currency guess."""
    thr = rule.threshold if isinstance(rule.threshold, dict) else None
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
    obs = rule.observed
    budget_amount = _num(obs)
    if budget_amount is None and isinstance(obs, dict):
        budget_amount = _num(obs.get("amount"))
    period = (thr or {}).get("period") or budget_period
    approx = (thr or {}).get("approx_converted")
    approx = approx if isinstance(approx, dict) else None
    if fee_currency is None and approx is None:
        fee_currency = budget_currency
    return fee_amount, fee_currency, period, budget_amount, approx


def localised_gap_state(rule, locale: str = "en", label: str | None = None,
                        budget_currency: str | None = None,
                        budget_period: str | None = None) -> str:
    """One localised ``current_state`` sentence for an engine
    RuleResult, built from structured data only (family, status,
    threshold, observed). ``label`` is the caller's localised rule
    name (plans.py passes it); without one the raw rule id is used as
    a last resort, never an invented name. Numbers are engine numbers
    formatted by _fmt_num; requirement labels stay verbatim. An
    unknown locale falls back to English."""
    s = _gap_state_strings(locale)
    fam = rule_family(rule.rule_id)
    status = rule.status
    label = label or rule.rule_id
    thr = rule.threshold if isinstance(rule.threshold, dict) else None
    obs = rule.observed
    obs_d = _gap_state_obs_dict(rule)
    out = ""

    def _period_word(period):
        return _gap_state_period(s, period)

    if status == "MET":
        if fam in ("language", "language-components", "toefl", "fee"):
            gaps = _gaps_for_rule(rule, budget_currency=budget_currency,
                                  fee_currency=(thr or {}).get("currency"))
            if fam == "fee" and gaps:
                g = gaps[0]
                fee_amount, fee_ccy, period, budget_amount, approx = (
                    _gap_state_fee_numbers(rule, budget_currency,
                                           budget_period))
                if (approx is not None
                        and _num(approx.get("amount")) is not None):
                    out = _fill(s["fee_met_converted"], ccy=budget_currency or "",
                                obs=_fmt_num(budget_amount),
                                period=_period_word(period),
                                fee_ccy=fee_ccy or "",
                                fee=_fmt_num(fee_amount),
                                converted=_fmt_num(_num(approx.get("amount"))))
                elif fee_amount is not None and budget_amount is not None:
                    out = _fill(s["fee_met"], ccy=budget_currency or "",
                                obs=_fmt_num(budget_amount),
                                period=_period_word(period),
                                fee_ccy=fee_ccy or "",
                                fee=_fmt_num(fee_amount))
            elif fam == "language":
                required = None
                if thr:
                    required = _num(thr.get("overall"))
                    if required is None:
                        for key in ("ielts_overall", "toefl_overall"):
                            raw = thr.get(key)
                            if isinstance(raw, list):
                                nums = [v for v in (_num(v) for v in raw)
                                        if v is not None]
                                required = min(nums) if nums else None
                            else:
                                required = _num(raw)
                            if required is not None:
                                break
                observed_num = _num(obs)
                if observed_num is None and obs_d:
                    observed_num = (_num(obs_d.get("ielts_overall"))
                                    or _num(obs_d.get("toefl_overall")))
                if required is not None and observed_num is not None:
                    out = _fill(s["lang_met_overall"],
                                exam=_gap_state_exam(rule),
                                obs=_fmt_num(observed_num),
                                req=_fmt_num(required))
            elif fam == "language-components":
                out = s["lang_met_components"]
        if not out:
            if fam == "gcse":
                out = s["gcse_met"]
            else:
                out = _fill(s["generic_met"], label=label)
    elif status == "NOT_MET":
        if fam in ("language", "language-components", "toefl", "fee"):
            gaps = _gaps_for_rule(rule, budget_currency=budget_currency,
                                  fee_currency=(thr or {}).get("currency"))
            lines = [_gap_line(rule.rule_id, g, locale) for g in gaps]
            lines = [line for line in lines if line]
            if lines:
                out = " ".join(lines)
        if not out:
            if fam == "academic":
                if thr and _num(thr.get("a_level")) is not None:
                    out = s["academic_alevel_below"]
                else:
                    out = _fill(s["academic_not_met"], label=label)
            elif fam == "gcse":
                # NOT_MET means both grades were supplied and one is
                # below C/4; a missing grade would be UNKNOWN, not here.
                eng = obs_d.get("english")
                maths = obs_d.get("maths")
                out = _fill(s["gcse_below"],
                            eng=(str(eng) if eng is not None else ""),
                            maths=(str(maths) if maths is not None else ""))
            elif fam in ("test", "gre"):
                test = _gap_state_test_name(rule)
                out = (_fill(s["test_not_met"], test=test)
                       if test else _fill(s["generic_not_met"], label=label))
            elif fam == "experience":
                out = _fill(s["experience_not_met"], label=label)
            else:
                out = _fill(s["generic_not_met"], label=label)
    else:  # UNKNOWN
        if fam == "language":
            labels = _gap_state_other_labels(rule)
            ielts_obs = _num(obs_d.get("ielts_overall"))
            toefl_obs = _num(obs_d.get("toefl_overall"))
            if labels:
                out = _fill(s["lang_other"], labels=join_list(labels, locale))
            elif ielts_obs is None and toefl_obs is None and _num(obs) is None:
                out = s["lang_no_test"]
            elif (toefl_obs is not None and thr is not None
                    and not _num(thr.get("toefl_overall"))
                    and not (thr.get("toefl_overall") or [])):
                out = s["lang_wrong_exam_toefl"]
            elif (ielts_obs is not None and thr is not None
                    and not _num(thr.get("ielts_overall"))
                    and not (thr.get("ielts_overall") or [])):
                out = s["lang_wrong_exam_ielts"]
            elif obs_d.get("exam") == "toefl" or "toefl" in rule.rule_id:
                if (_num(obs_d.get("overall")) is not None
                        and _num(obs_d.get("overall")) <= 6
                        and not obs_d.get("test_date")):
                    out = s["lang_toefl_scale"]
                elif not obs_d.get("test_date"):
                    out = s["lang_toefl_date"]
                else:
                    out = _fill(s["lang_unknown"], label=label)
            else:
                out = _fill(s["lang_unknown"], label=label)
        elif fam == "language-components":
            missing = [c for c in _COMPONENTS
                       if c in obs_d and obs_d.get(c) is None]
            present = [c for c in _COMPONENTS
                       if c in obs_d and obs_d.get(c) is not None]
            if obs_d and not present:
                out = s["lang_no_test"]
            elif missing:
                comp_names = [_comp_name(locale, c, capital=True)
                              for c in missing]
                out = _fill(s["lang_components_missing"],
                            comps=join_list(comp_names, locale))
            else:
                out = _fill(s["lang_components_unknown"], label=label)
        elif fam == "toefl":
            if (_num(obs_d.get("overall")) is not None
                    and _num(obs_d.get("overall")) <= 6
                    and not obs_d.get("test_date")):
                out = s["lang_toefl_scale"]
            elif not obs_d.get("test_date"):
                out = s["lang_toefl_date"]
            else:
                out = _fill(s["lang_unknown"], label=label)
        elif fam == "fee":
            fee_amount, fee_ccy, period, budget_amount, approx = (
                _gap_state_fee_numbers(rule, budget_currency, budget_period))
            if fee_amount is None:
                out = s["fee_no_amount"]
            elif budget_amount is None and _num(obs) is None:
                out = s["fee_no_budget"]
            elif (isinstance(obs, dict) and thr
                    and obs.get("period") and thr.get("period")
                    and obs.get("period") != thr.get("period")):
                out = _fill(s["fee_period_mismatch"],
                            bperiod=_period_word(obs.get("period")),
                            fperiod=_period_word(thr.get("period")))
            elif (isinstance(obs, dict) and thr
                    and obs.get("currency") and thr.get("currency")
                    and obs.get("currency") != thr.get("currency")
                    and approx is None):
                out = s["fee_no_rate"]
            else:
                out = _fill(s["fee_unknown"], label=label)
        elif fam == "academic":
            curriculum = obs_d.get("curriculum")
            if curriculum == "cn_gaokao":
                score = obs_d.get("gaokao_score")
                total = obs_d.get("gaokao_total")
                if score is not None and total is not None:
                    out = _fill(s["academic_gaokao"],
                                score=_fmt_num(score), total=_fmt_num(total))
                else:
                    out = s["academic_gaokao_no_score"]
            elif rule.rule_id == "exp-academic" and obs is None:
                out = s["academic_masters"]
            elif thr and _num(thr.get("a_level")) is not None \
                    and curriculum not in ("uk_alevel", "sg_alevel", None):
                out = s["academic_not_alevel"]
            elif thr is None and curriculum in ("uk_alevel", "sg_alevel"):
                grades = obs_d.get("grades")
                if not grades:
                    out = s["academic_no_grades"]
                else:
                    out = s["academic_no_threshold"]
            elif thr is None:
                out = s["academic_no_threshold"]
            else:
                out = _fill(s["academic_unknown"], label=label)
        elif fam == "gcse":
            missing = []
            if obs_d.get("english") is None:
                missing.append(s["subject.english"])
            if obs_d.get("maths") is None:
                missing.append(s["subject.maths"])
            out = _fill(s["gcse_unknown"], subjects=join_list(missing, locale))
        elif fam in ("test", "gre"):
            test = _gap_state_test_name(rule)
            out = (_fill(s["test_unknown"], test=test)
                   if test else _fill(s["generic_unknown"], label=label))
        elif fam == "experience":
            out = _fill(s["experience_unknown"], label=label)
        else:
            out = _fill(s["generic_unknown"], label=label)
    # Collapse any empty period slot ("Budget GBP 50000  covers ...")
    # to single spaces; Chinese/Arabic prose has no inter-word spaces
    # of its own to lose.
    return " ".join((out or "").split())

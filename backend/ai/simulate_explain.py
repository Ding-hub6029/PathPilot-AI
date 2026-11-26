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


# Round 14: the deterministic template is user-facing text, so it is
# localised like the explain.py template (same _STRINGS pattern; the
# "en" row is byte-identical to the old hardcoded English, which the
# Round 12 tests pin). Engine numbers, rule ids and evidence ids are
# inserted unchanged; MET stays the literal status token in every
# locale, as in the whynot template. Unknown locale -> "en".
_SIMULATE_TEMPLATE_STRINGS = {
    "en": {
        "field_budget": "budget",
        "field_ieltsOverall": "ieltsOverall",
        "field_ieltsWriting": "ieltsWriting",
        "top_with_strict": ("{change} mattered most: it flips {rule_flips} rule(s) "
                            "to MET and {flips} programme(s) stop being blocked "
                            "(all known minimums met, of which {strict_met} "
                            "become fully MET)."),
        "top_without_strict": ("{change} mattered most: it flips {rule_flips} rule(s) "
                               "to MET and {flips} programme(s) stop being blocked "
                               "(all known minimums met, but none becomes fully MET, "
                               "because an academic or admissions-test rule stays "
                               "UNKNOWN where no equivalence or threshold is "
                               "published)."),
        "no_flip_with_scenarios": ("No change in this simulation flips any rule or "
                                   "programme: every programme that is not met stays "
                                   "not met, and the academic rule stays UNKNOWN "
                                   "where no equivalence is published."),
        "no_flip": ("No single change in this simulation flips any programme "
                    "to fully met."),
        "claim": ("Scenario {name}: {prog_flips} programme(s) stop being blocked "
                  "(all known minimums met) and {rule_flips} rule(s) flip to MET."),
        "unknown_field_academic": "academic",
        "unknown_reason": ("No university publishes a Gaokao equivalence, so the "
                           "academic rule stays UNKNOWN whatever the Gaokao score."),
        "unknown_question": ("Which foundation or alternative route does each "
                             "university publish for Gaokao applicants?"),
        "action": ("Suggestion, not a fact: consider {change} first — it flips "
                   "{rule_flips} rule(s) to MET."),
        "limitation": ("This is a rules/template summary from the engine's own "
                       "numbers, not model-generated text. No admission "
                       "probabilities are given; unknown stays unknown."),
        "unknown_prefix": "Unknown: ",
        "next_prefix": "Next: ",
        "limitation_prefix": "Limitation: ",
    },
    "zh-CN": {
        "field_budget": "预算",
        "field_ieltsOverall": "雅思总分",
        "field_ieltsWriting": "雅思写作",
        "top_with_strict": ("{change}最关键：它使 {rule_flips} 条规则变为达标，{flips} 个课程"
                            "不再被卡住（所有已知最低要求均已满足，其中 {strict_met} 个完全达标）。"),
        "top_without_strict": ("{change}最关键：它使 {rule_flips} 条规则变为达标，{flips} 个课程"
                               "不再被卡住（所有已知最低要求均已满足，但没有一个完全达标，因为学术或"
                               "入学考试规则在没有公布等效标准或分数线的情况下仍为未知）。"),
        "no_flip_with_scenarios": ("本次推演中没有任何改变能使规则或课程翻转：未达标的课程仍然未达标，"
                                   "学术规则在没有公布等效标准的情况下仍为未知。"),
        "no_flip": "本次推演中没有任何单一改变能使课程完全达标。",
        "claim": ("方案{name}：{prog_flips} 个课程不再被卡住（所有已知最低要求均已满足），"
                  "{rule_flips} 条规则变为达标。"),
        "unknown_field_academic": "学业资格",
        "unknown_reason": "没有任何大学公布高考等效标准，因此无论高考分数如何，学术规则都仍为未知。",
        "unknown_question": "各大学为高考申请者公布了哪些预科或其他替代路径？",
        "action": "建议，并非事实：请优先考虑{change}——它使 {rule_flips} 条规则变为达标。",
        "limitation": ("这是根据引擎自身数字生成的规则/模板摘要，并非模型生成的文本。不提供录取概率；"
                       "未知仍为未知。"),
        "unknown_prefix": "未知：",
        "next_prefix": "下一步：",
        "limitation_prefix": "说明：",
    },
    "es": {
        "field_budget": "presupuesto",
        "field_ieltsOverall": "IELTS general",
        "field_ieltsWriting": "IELTS Writing",
        "top_with_strict": ("{change} es lo que más importa: cambia {rule_flips} regla(s) "
                            "a MET y {flips} programa(s) dejan de estar bloqueados (todos "
                            "los mínimos conocidos se cumplen, de los cuales {strict_met} "
                            "quedan totalmente cumplidos)."),
        "top_without_strict": ("{change} es lo que más importa: cambia {rule_flips} regla(s) "
                               "a MET y {flips} programa(s) dejan de estar bloqueados (todos "
                               "los mínimos conocidos se cumplen, pero ninguno queda totalmente "
                               "cumplido, porque una regla académica o de examen de admisión "
                               "sigue siendo UNKNOWN al no haberse publicado equivalencia "
                               "ni umbral)."),
        "no_flip_with_scenarios": ("Ningún cambio de esta simulación cambia ninguna regla ni "
                                   "ningún programa: cada programa no cumplido sigue sin "
                                   "cumplirse, y la regla académica sigue siendo UNKNOWN al no "
                                   "haberse publicado ninguna equivalencia."),
        "no_flip": ("Ningún cambio por sí solo en esta simulación hace que un programa "
                    "quede totalmente cumplido."),
        "claim": ("Escenario {name}: {prog_flips} programa(s) dejan de estar bloqueados "
                  "(todos los mínimos conocidos se cumplen) y {rule_flips} regla(s) "
                  "cambian a MET."),
        "unknown_field_academic": "académico",
        "unknown_reason": ("Ninguna universidad publica una equivalencia del Gaokao, por lo "
                           "que la regla académica sigue siendo UNKNOWN sea cual sea la nota "
                           "del Gaokao."),
        "unknown_question": ("¿Qué programa de foundation o ruta alternativa publica cada "
                             "universidad para los solicitantes del Gaokao?"),
        "action": ("Sugerencia, no un hecho: considera {change} primero — cambia "
                   "{rule_flips} regla(s) a MET."),
        "limitation": ("Esto es un resumen de reglas/plantilla a partir de los números del "
                       "propio motor, no un texto generado por un modelo. No se dan "
                       "probabilidades de admisión; lo desconocido sigue siendo "
                       "desconocido."),
        "unknown_prefix": "Desconocido: ",
        "next_prefix": "Siguiente: ",
        "limitation_prefix": "Limitación: ",
    },
    "fr": {
        "field_budget": "budget",
        "field_ieltsOverall": "IELTS global",
        "field_ieltsWriting": "IELTS Writing",
        "top_with_strict": ("{change} compte le plus : il fait passer {rule_flips} règle(s) "
                            "à MET et {flips} programme(s) ne sont plus bloqués (tous les "
                            "minimums connus sont satisfaits, dont {strict_met} deviennent "
                            "entièrement satisfaits)."),
        "top_without_strict": ("{change} compte le plus : il fait passer {rule_flips} règle(s) "
                               "à MET et {flips} programme(s) ne sont plus bloqués (tous les "
                               "minimums connus sont satisfaits, mais aucun ne devient "
                               "entièrement satisfait, car une règle académique ou d'examen "
                               "d'admission reste UNKNOWN faute d'équivalence ou de seuil "
                               "publié)."),
        "no_flip_with_scenarios": ("Aucun changement de cette simulation ne fait basculer une "
                                   "règle ou un programme : chaque programme non satisfait le "
                                   "reste, et la règle académique reste UNKNOWN faute "
                                   "d'équivalence publiée."),
        "no_flip": ("Aucun changement isolé de cette simulation ne rend un programme "
                    "entièrement satisfait."),
        "claim": ("Scénario {name} : {prog_flips} programme(s) ne sont plus bloqués "
                  "(tous les minimums connus sont satisfaits) et {rule_flips} règle(s) "
                  "passent à MET."),
        "unknown_field_academic": "académique",
        "unknown_reason": ("Aucune université ne publie d'équivalence du Gaokao, donc la "
                           "règle académique reste UNKNOWN quel que soit le score au Gaokao."),
        "unknown_question": ("Quelle année de foundation ou quelle autre voie chaque université "
                             "publie-t-elle pour les candidats du Gaokao ?"),
        "action": ("Suggestion, pas un fait : envisagez {change} d'abord — il fait "
                   "passer {rule_flips} règle(s) à MET."),
        "limitation": ("Ceci est un résumé règles/modèle à partir des chiffres du moteur "
                       "lui-même, et non un texte généré par un modèle. Aucune probabilité "
                       "d'admission n'est donnée ; l'inconnu reste inconnu."),
        "unknown_prefix": "Inconnu : ",
        "next_prefix": "Ensuite : ",
        "limitation_prefix": "Limite : ",
    },
    "pt-BR": {
        "field_budget": "orçamento",
        "field_ieltsOverall": "IELTS geral",
        "field_ieltsWriting": "IELTS Writing",
        "top_with_strict": ("{change} é o que mais importa: muda {rule_flips} regra(s) para "
                            "MET e {flips} programa(s) deixam de estar bloqueados (todos os "
                            "mínimos conhecidos são atendidos, dos quais {strict_met} ficam "
                            "totalmente atendidos)."),
        "top_without_strict": ("{change} é o que mais importa: muda {rule_flips} regra(s) para "
                               "MET e {flips} programa(s) deixam de estar bloqueados (todos os "
                               "mínimos conhecidos são atendidos, mas nenhum fica totalmente "
                               "atendido, porque uma regra acadêmica ou de exame de admissão "
                               "continua UNKNOWN sem equivalência ou limite publicado)."),
        "no_flip_with_scenarios": ("Nenhuma mudança desta simulação altera qualquer regra ou "
                                   "programa: cada programa não atendido continua não atendido, "
                                   "e a regra acadêmica continua UNKNOWN sem equivalência "
                                   "publicada."),
        "no_flip": ("Nenhuma mudança isolada desta simulação torna um programa totalmente "
                    "atendido."),
        "claim": ("Cenário {name}: {prog_flips} programa(s) deixam de estar bloqueados "
                  "(todos os mínimos conhecidos são atendidos) e {rule_flips} regra(s) "
                  "mudam para MET."),
        "unknown_field_academic": "acadêmico",
        "unknown_reason": ("Nenhuma universidade publica equivalência do Gaokao, portanto a "
                           "regra acadêmica continua UNKNOWN qualquer que seja a nota do Gaokao."),
        "unknown_question": ("Qual programa de foundation ou rota alternativa cada universidade "
                             "publica para candidatos do Gaokao?"),
        "action": ("Sugestão, não fato: considere {change} primeiro — muda {rule_flips} "
                   "regra(s) para MET."),
        "limitation": ("Isto é um resumo de regras/modelo a partir dos números do próprio "
                       "mecanismo, não um texto gerado por modelo. Nenhuma probabilidade de "
                       "admissão é dada; o desconhecido continua desconhecido."),
        "unknown_prefix": "Desconhecido: ",
        "next_prefix": "Próximo passo: ",
        "limitation_prefix": "Limitação: ",
    },
    "ar": {
        "field_budget": "الميزانية",
        "field_ieltsOverall": "IELTS العام",
        "field_ieltsWriting": "IELTS الكتابة",
        "top_with_strict": ("{change} هو الأهم: يغيّر {rule_flips} من القواعد إلى MET ويتوقف "
                            "{flips} من البرامج عن كونها محظورة (جميع الحدود الدنيا المعروفة "
                            "مستوفاة، ومنها {strict_met} تصبح مستوفاة بالكامل)."),
        "top_without_strict": ("{change} هو الأهم: يغيّر {rule_flips} من القواعد إلى MET ويتوقف "
                               "{flips} من البرامج عن كونها محظورة (جميع الحدود الدنيا المعروفة "
                               "مستوفاة، لكن لا يصبح أي منها مستوفًى بالكامل، لأن قاعدة أكاديمية "
                               "أو قاعدة اختبار قبول تبقى UNKNOWN حيث لا توجد معادلة أو حد منشور)."),
        "no_flip_with_scenarios": ("لا يوجد أي تغيير في هذه المحاكاة يقلب أي قاعدة أو برنامج: كل "
                                   "برنامج غير مستوفٍ يبقى غير مستوفٍ، وتبقى القاعدة الأكاديمية "
                                   "UNKNOWN حيث لا توجد معادلة منشورة."),
        "no_flip": "لا يوجد أي تغيير منفرد في هذه المحاكاة يجعل برنامجًا مستوفًى بالكامل.",
        "claim": ("السيناريو {name}: يتوقف {prog_flips} من البرامج عن كونها محظورة "
                  "(جميع الحدود الدنيا المعروفة مستوفاة) وتتغير {rule_flips} من القواعد "
                  "إلى MET."),
        "unknown_field_academic": "أكاديمي",
        "unknown_reason": ("لا تنشر أي جامعة معادلة لامتحان Gaokao، لذا تبقى القاعدة الأكاديمية "
                           "UNKNOWN مهما كانت نتيجة Gaokao."),
        "unknown_question": ("ما برنامج السنة التأسيسية أو المسار البديل الذي تنشره كل جامعة "
                             "لمتقدمي Gaokao؟"),
        "action": ("اقتراح وليس حقيقة: فكّر في {change} أولًا — فهو يغيّر {rule_flips} "
                   "من القواعد إلى MET."),
        "limitation": ("هذا ملخص قواعد/قالب من أرقام المحرك نفسه، وليس نصًا مولّدًا بواسطة "
                       "نموذج. لا تُقدَّم أي احتمالات قبول؛ والمجهول يبقى مجهولًا."),
        "unknown_prefix": "غير معروف: ",
        "next_prefix": "التالي: ",
        "limitation_prefix": "القيد: ",
    },
}


def _simulate_strings(locale: str) -> dict:
    return _SIMULATE_TEMPLATE_STRINGS.get(locale) or _SIMULATE_TEMPLATE_STRINGS["en"]


def _sim_fill(template: str, **values) -> str:
    """Substitute {name} placeholders without str.format (same reason as
    ai.explain._fill: a value may itself contain braces)."""
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", str(value))
    return out


def _fmt_change(change: dict, locale: str = "en") -> str:
    s = _simulate_strings(locale)
    field, frm, to = change["field"], change["from"], change["to"]
    label = s.get(f"field_{field}", field)
    if field == "budget":
        return _sim_fill("{label} GBP {frm} -> GBP {to}", label=label,
                         frm=f"{frm:,}", to=f"{to:,}")
    return _sim_fill("{label} {frm} -> {to}", label=label, frm=frm, to=to)


def _top_line(scenarios: list[dict], leverage: dict | None,
              locale: str = "en") -> str:
    """One-sentence template summary, from engine numbers only."""
    s = _simulate_strings(locale)
    top = (leverage or {}).get("top") or {}
    if not top:
        if scenarios:
            best = max(scenarios, key=lambda s: (len(s.get("flipped_program_ids") or []),
                                                 s.get("rule_flip_count", 0)))
            if (best.get("rule_flip_count", 0) or 0) == 0 and not best.get("flipped_program_ids"):
                return s["no_flip_with_scenarios"]
        return s["no_flip"]
    flips = top.get("flips", 0)
    rule_flips = top.get("rule_flips", 0)
    strict_met = top.get("flips_to_met", 0)
    change = _fmt_change(top["change"], locale)
    if strict_met:
        return _sim_fill(s["top_with_strict"], change=change,
                         rule_flips=rule_flips, flips=flips,
                         strict_met=strict_met)
    return _sim_fill(s["top_without_strict"], change=change,
                     rule_flips=rule_flips, flips=flips)


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
    s = _simulate_strings(locale)
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
        text = _sim_fill(s["claim"], name=name, prog_flips=len(prog_flips),
                         rule_flips=rule_flips)
        claims.append({"text": text, "kind": "fact",
                       "rule_ids": rule_ids[:10], "evidence_ids": evidence})
        if len(claims) >= 20:
            break
    unknowns: list[dict] = []
    if baseline_unknown_academic:
        unknowns.append({
            "field": s["unknown_field_academic"],
            "reason": s["unknown_reason"],
            "question": s["unknown_question"]})
    actions: list[dict] = []
    top = (leverage or {}).get("top") or {}
    if top:
        actions.append({
            "explanation": _sim_fill(
                s["action"], change=_fmt_change(top["change"], locale),
                rule_flips=top.get("rule_flips", 0)),
            "evidence_ids": []})
    limitations = [s["limitation"]]
    return {"summary": _top_line(scenarios, leverage, locale), "claims": claims,
            "unknowns": unknowns, "actions": actions,
            "limitations": limitations}


def template_simulate_text(structured: dict, locale: str = "en") -> str:
    s = _simulate_strings(locale)
    lines = [structured.get("summary", "")]
    for claim in structured.get("claims", []):
        lines.append(f"- {claim.get('text', '')}")
    for u in structured.get("unknowns", []):
        lines.append(f"- {s['unknown_prefix']}{u.get('field', '')} — {u.get('reason', '')}")
    for a in structured.get("actions", []):
        lines.append(f"- {s['next_prefix']}{a.get('explanation', '')}")
    for lim in structured.get("limitations", []):
        lines.append(f"- {s['limitation_prefix']}{lim}")
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
    """One model attempt, no repair; validated output or None.

    Round 13 fail-fast: a single attempt with a 15 s budget. The old
    30 s first attempt + 20 s repair could block for up to 50 s, and
    the frontend aborts a simulate attempt at 25 s (40 s in the
    Round 13 frontend fail-fast) — a repair retry can only ever
    return after the caller has given up, so it is dropped entirely.
    A validation failure or a provider failure both fall back to the
    deterministic template (the caller never sees an exception).
    """
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
            "top_change_description": (_fmt_change(top["change"], locale) if top else None),
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

    first = _attempt(messages, 15.0)
    if first is not None and "_check_error" not in first:
        return first
    # No repair retry (Round 13): a failed first attempt — timeout,
    # transport error, bad JSON or a citation-check failure — falls
    # back to the template immediately. The caller budgeted 15 s for
    # the model; a second attempt cannot fit it.
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
        return template, template_simulate_text(template, locale), "unavailable"
    if not provider.available:
        return template, template_simulate_text(template, locale), "unavailable"
    try:
        structured = _model_explain_simulation(
            scenarios=scenarios, leverage=leverage,
            baseline_unknown_academic=baseline_unknown_academic,
            locale=locale, provider=provider)
    except Exception:
        # Round 13: a model failure must never raise/500 — any
        # unexpected error in the model path falls back to the
        # template (the engine numbers are already computed).
        return template, template_simulate_text(template, locale), "unavailable"
    if structured is None:
        return template, template_simulate_text(template, locale), "unavailable"
    sources = []
    for scen in scenarios:
        for pid in scen.get("flipped_program_ids") or []:
            sources.extend(programme_sources(pid))
    return (structured,
            render_structured_explanation(structured, sources), "available")

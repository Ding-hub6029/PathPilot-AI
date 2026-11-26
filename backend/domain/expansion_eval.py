"""Generic rule evaluator for expansion (v3) programmes.

The 8 v2 programmes keep their own hand-written evaluators in
domain/eligibility.py (byte-identical behaviour, untouched). Expansion
programmes have no hand-written rules: this module evaluates ONLY the
verified structured data in data/expansions/expansion.json —

- fee: fees.amount + currency + period, compared against the profile
  budget. Same currency + period compares exactly, as v2 does.
  Different currencies are compared with the dated, approximate FX
  reference table in data/expansions/fx_rates.json (round 9, R2):
  the fee is converted into the budget currency via GBP and the
  converted figure is always labelled approximate. A currency with no
  reference rate, a period mismatch, or a per-credit fee is UNKNOWN
  ("cannot be converted for comparison") — never a false mismatch.
  Per-credit fees are UNKNOWN because the profile has no credit count;
- language: structured IELTS / TOEFL thresholds. Language
  requirements on one programme are ALTERNATIVE routes (an IELTS
  requirement, a TOEFL requirement and a Duolingo requirement are
  separate entries for the same programme), so the overall rule is MET
  when any route the applicant evidenced is met. Thresholds that are
  only Duolingo / PTE / HSK / CEFR are UNKNOWN — the profile has no
  such scores. TOEFL follows the v2 Jan 2026 scale split (an old-scale
  iBT threshold cannot be compared with a new-scale-looking score, and
  a new-scale threshold needs a test date on/after the cutoff);
- academic: A-level thresholds only, and only for the uk_alevel /
  sg_alevel curricula. Gaokao / SAT / IB scores are never converted
  to A-levels. Two structured shapes exist in the data: the string
  form {"a_level": "A*AA"} (ranges such as "A*A*A*-AAB" and
  alternatives such as "A*A*A or A*AAA" are read at their published
  minimum) and the grades form {"grades": ["A*", "A", "A"],
  "maths_grade": "A*"}. Any other academic threshold (GPA, IB total,
  degree class, ATAR, ...) is UNKNOWN.

Everything else is UNKNOWN, never MET on missing data. Rule ids are
exp-fee / exp-language / exp-language-components / exp-academic.
Overall status reuses the existing semantics (any NOT_MET -> NOT_MET;
any UNKNOWN -> PARTIAL_UNKNOWN; else MET) via overall_status().

Placeholder rule (round 8): a requirement with no parseable numeric
threshold — threshold missing, a string, or a dict of non-numeric
values, e.g. "IELTS / TOEFL minimum as stated on the official
programme page" — can NEVER yield NOT_MET. It yields UNKNOWN. The
sub-evaluators below already only fail a rule against a numeric
threshold they actually compared, and evaluate_expansion() enforces
the invariant structurally with _has_numeric_threshold(): any NOT_MET
without a numeric threshold behind it is downgraded to UNKNOWN, so a
future sub-evaluator change cannot reintroduce a placeholder failure.
The frontend offline mirror (frontend/src/lib/api.ts,
evaluateExpansionLocal) implements the same rule.

Promotion (see app/data.py): a programme is matchable only when it
has at least one evaluable rule (fee amount known, or a structured
IELTS/TOEFL language threshold, or an A-level threshold) AND its
degree_level is undergraduate / taught_masters (the wizard has no
track for foundation / joint_honours).
"""
from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.schemas import Language, RuleResult, StudentProfile, UndergradProfile
from domain.eligibility import (
    TOEFL_SCALE_CUTOFF,
    _alevel_top3,
    _dec,
    _parse_test_date,
    _plain_number,
    _r,
    _toefl_score,
    effective_curriculum,
)

# --- FX reference table (round 9, R2) ---------------------------------------
# data/expansions/fx_rates.json: dated, approximate mid-market rates
# (units per 1 GBP, three significant figures) for cross-currency fee
# comparison. A missing/unreadable file means "no rates": every
# cross-currency comparison is UNKNOWN, never a mismatch, never a
# crash. See docs/FX_RATES.md.
_FX_PATH = Path(__file__).resolve().parents[2] / "data" / "expansions" / "fx_rates.json"


def _load_fx_table() -> tuple[dict[str, Decimal], str | None]:
    try:
        with open(_FX_PATH, encoding="utf-8") as f:
            data = json.load(f)
        rates: dict[str, Decimal] = {}
        for code, value in (data.get("rates_per_gbp") or {}).items():
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
                rates[str(code).upper()] = Decimal(str(value))
        return rates, str(data.get("as_of") or "") or None
    except Exception:
        return {}, None


FX_RATES, FX_AS_OF = _load_fx_table()


def _convert_fee(amount: Decimal, from_currency: str,
                 to_currency: str) -> Decimal | None:
    """Convert a fee amount from one currency to another via GBP.

    Returns None when either currency has no reference rate (the
    caller must then return UNKNOWN, never a mismatch). Same currency
    returns the amount unchanged.
    """
    from_currency = (from_currency or "").upper()
    to_currency = (to_currency or "").upper()
    if from_currency == to_currency:
        return amount
    from_rate = FX_RATES.get(from_currency)
    to_rate = FX_RATES.get(to_currency)
    if from_rate is None or to_rate is None:
        return None
    return amount / from_rate * to_rate


def _fx_note(from_currency: str, to_currency: str) -> str:
    """Rate provenance suffix for a converted-fee detail, e.g.
    " (reference rate 1 GBP = 1.09 CHF, 26 Nov 2026 — approximate)".
    The rate shown is for the non-GBP side(s) of the conversion —
    showing the GBP side's own rate (1) would read "1 GBP = 1 GBP"."""
    parts: list[str] = []
    for ccy in ((from_currency or "").upper(), (to_currency or "").upper()):
        if ccy and ccy != "GBP":
            rate = FX_RATES.get(ccy)
            if rate is not None:
                part = f"1 GBP = {rate:g} {ccy}"
                if part not in parts:
                    parts.append(part)
    if not parts:
        return ""
    return (f" (reference rate {', '.join(parts)}, "
            f"{FX_AS_OF or 'undated'} — approximate)")

_GRADE_RANK = {"A*": 5, "A": 4, "B": 3, "C": 2, "D": 1, "E": 0}

_IELTS_COMPONENT_KEYS = ("ielts_listening", "ielts_reading",
                         "ielts_writing", "ielts_speaking")
_BARE_COMPONENT_KEYS = ("listening", "reading", "writing", "speaking")


def _num(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def _classify_language_requirement(req: dict) -> str | None:
    """'ielts' | 'toefl' | 'duolingo' | 'pte' | 'hsk' | 'cefr' | 'other'.

    None when the requirement carries no structured threshold at all.
    Classification uses explicit threshold keys first — including
    the non-IELTS/TOEFL keys (cefr_level, duolingo_overall, pte_overall,
    hsk_level), so a CEFR requirement is classified 'cefr' even when
    its id/description never spells the word out (round 9, R13: the
    Swiss German C1 / French B2 requirements were read as 'other') —
    then the requirement id / description prefix (e.g. "...-ielts",
    "TOEFL iBT 90 ..."). The bare "overall" key is meaningless on its
    own — a TOEFL requirement's overall is an iBT score, a Duolingo
    requirement's overall is a Duolingo score — so an unclassified
    requirement is never treated as an IELTS threshold.
    """
    th = req.get("threshold")
    if not isinstance(th, dict):
        return None
    if "ielts_overall" in th or "ielts" in th:
        return "ielts"
    if "toefl_ibt" in th or "toefl_ibt_overall" in th or "toefl_overall" in th:
        return "toefl"
    if "cefr_level" in th:
        return "cefr"
    if "duolingo_overall" in th or "duolingo" in th:
        return "duolingo"
    if "pte_overall" in th:
        return "pte"
    if "hsk_level" in th:
        return "hsk"
    rid = str(req.get("id", "")).lower()
    desc = str(req.get("description", ""))[:40].lower()
    for key in ("ielts", "toefl", "duolingo", "pte", "hsk", "cefr"):
        if key in rid or key in desc:
            return key
    return "other"


def _ielts_overall_of(th: dict, kind: str) -> float | int | None:
    if kind != "ielts":
        return None
    for key in ("ielts_overall", "ielts", "overall"):
        v = _num(th.get(key))
        if v is not None:
            return v
    return None


def _toefl_overall_of(th: dict, kind: str) -> float | int | None:
    if kind != "toefl":
        return None
    # Round 9, R13: the bare "toefl_overall" key (UCLA CS BS / CSE BS,
    # TOEFL 100) was not read, so a real stated threshold was dropped.
    for key in ("toefl_ibt_overall", "toefl_ibt", "toefl_overall", "overall"):
        v = _num(th.get(key))
        if v is not None:
            return v
    return None


def _ielts_component_sets(th: dict, kind: str) -> list[dict[str, float]]:
    """Component-minimum sets for one IELTS-classified threshold.

    Each set is one alternative way to satisfy the components: a plain
    each-component minimum gives one set; a three-components + remaining
    minimum (Edinburgh DS MSc) gives one set with a special marker.
    Bare listening/reading/writing/speaking keys with values <= 9 are
    IELTS components; values > 9 are TOEFL section scores (not
    evaluable — the profile has no TOEFL component scores).
    Returns [] when the threshold states no IELTS component minimum.
    """
    if kind != "ielts":
        return []
    sets: list[dict[str, float]] = []
    each = (_num(th.get("each_component")) or _num(th.get("ielts_min_each"))
            or _num(th.get("min_section")))
    if each is not None:
        sets.append({k: each for k in
                     ("listening", "reading", "writing", "speaking")})
    three = _num(th.get("ielts_min_three_components"))
    remaining = _num(th.get("ielts_min_remaining"))
    if three is not None and remaining is not None:
        sets.append({"__three__": three, "__remaining__": remaining})
    per: dict[str, float] = {}
    for key in _IELTS_COMPONENT_KEYS:
        v = _num(th.get(key))
        if v is not None and v <= 9:
            per[key[len("ielts_"):]] = v
    for key in _BARE_COMPONENT_KEYS:
        v = _num(th.get(key))
        if v is not None and v <= 9:
            per.setdefault(key, v)
    if per:
        sets.append(per)
    return sets


def _has_toefl_section_minima(th: dict, kind: str) -> bool:
    if kind != "toefl":
        return False
    if any(k in th for k in ("toefl_ibt_min_each", "toefl_ibt_min_other",
                             "toefl_ibt_writing")):
        return True
    return any(_num(th.get(k)) is not None and _num(th.get(k)) > 9  # type: ignore[operator]
               for k in _BARE_COMPONENT_KEYS)


def _other_language_label(req: dict, kind: str | None) -> str | None:
    """Human label for a structured non-IELTS/TOEFL language
    requirement, e.g. "German C1 (CEFR)", "French B2 (CEFR)",
    "HSK 6", "Duolingo 130", "PTE 65". Round 9, R13: the Swiss
    programmes state a real CEFR requirement, and the card must name
    it instead of claiming an IELTS/TOEFL minimum. None when the
    requirement carries no such structured threshold."""
    th = req.get("threshold")
    if not isinstance(th, dict):
        return None
    if kind == "cefr":
        level = th.get("cefr_level")
        lang = th.get("language")
        if isinstance(level, str) and level.strip():
            return f"{lang} {level} (CEFR)".strip() if isinstance(lang, str) and lang.strip() else f"CEFR {level}"
        return None
    if kind == "hsk":
        level = _num(th.get("hsk_level"))
        return f"HSK {level:g}" if level is not None else None
    if kind == "duolingo":
        score = _num(th.get("duolingo_overall")) or _num(th.get("duolingo"))
        return f"Duolingo {score:g}" if score is not None else None
    if kind == "pte":
        score = _num(th.get("pte_overall"))
        return f"PTE {score:g}" if score is not None else None
    return None


def _language_thresholds(program: dict) -> dict[str, Any]:
    """Collect the evaluable language thresholds of one programme."""
    ielts_overalls: list[float] = []
    toefl_overalls: list[float] = []
    component_sets: list[dict[str, float]] = []
    has_toefl_sections = False
    has_any_language_req = False
    has_unassessable_only = False
    other_labels: list[str] = []
    for req in program.get("requirements", []):
        if req.get("category") != "language":
            continue
        has_any_language_req = True
        th = req.get("threshold")
        if not isinstance(th, dict):
            continue
        kind = _classify_language_requirement(req)
        label = _other_language_label(req, kind)
        if label is not None and label not in other_labels:
            other_labels.append(label)
        if kind in ("duolingo", "pte", "hsk", "cefr", "other"):
            has_unassessable_only = True
            continue
        io = _ielts_overall_of(th, kind or "")
        if io is not None:
            ielts_overalls.append(float(io))
        to = _toefl_overall_of(th, kind or "")
        if to is not None:
            toefl_overalls.append(float(to))
        component_sets.extend(_ielts_component_sets(th, kind or ""))
        if _has_toefl_section_minima(th, kind or ""):
            has_toefl_sections = True
    return {"ielts_overalls": ielts_overalls,
            "toefl_overalls": toefl_overalls,
            "component_sets": component_sets,
            "has_toefl_sections": has_toefl_sections,
            "has_any_language_req": has_any_language_req,
            "has_unassessable_only": has_unassessable_only,
            "other_labels": other_labels}


def _toefl_route(score: float, threshold: float,
                 test_date: Any) -> str:
    """'met' | 'below' | 'unknown' for one TOEFL threshold.

    Thresholds <= 6 are new-scale (1-6) thresholds: they can only be
    compared when the test date is on/after the Jan 2026 cutoff.
    Thresholds > 6 are old-scale iBT thresholds: a new-scale-looking
    score (<= 6) cannot be compared with them.
    """
    if threshold <= 6:
        if test_date is None or test_date < TOEFL_SCALE_CUTOFF:
            return "unknown"
        return "met" if score >= threshold else "below"
    if score <= 6:
        return "unknown"
    return "met" if score >= threshold else "below"


def _parse_alevel_triples(text: str) -> list[list[int]]:
    """All grade triples stated in an A-level requirement string.

    "A*AA" -> [[5,4,4]]; "A*A*A or A*AAA" -> [[5,5,5],[5,4,4]];
    "A*A*A*-AAB" -> [[5,5,5],[4,4,3]] (a range: both ends listed).
    The published minimum is min() of the triples.
    """
    found = re.findall(r"A\*|[A-E]", text.upper())
    triples: list[list[int]] = []
    for i in range(0, len(found) - 2, 3):
        ranks = sorted((_GRADE_RANK[g] for g in found[i:i + 3]), reverse=True)
        triples.append(ranks)
    return triples


def _alevel_requirements(program: dict) -> list[dict[str, Any]]:
    """Structured A-level requirements: string form and grades form."""
    out: list[dict[str, Any]] = []
    for req in program.get("requirements", []):
        if req.get("category") != "academic":
            continue
        th = req.get("threshold")
        if not isinstance(th, dict):
            continue
        if isinstance(th.get("a_level"), str) and th["a_level"].strip():
            triples = _parse_alevel_triples(th["a_level"])
            if triples:
                out.append({"kind": "string", "minimum": min(triples),
                            "source_ids": list(req.get("source_ids") or []),
                            "req_id": req.get("id")})
        grades = th.get("grades")
        if isinstance(grades, list) and len(grades) >= 3 and all(
                isinstance(g, str) and g.upper() in _GRADE_RANK for g in grades):
            ranks = sorted((_GRADE_RANK[g.upper()] for g in grades),
                           reverse=True)[:3]
            maths = th.get("maths_grade")
            maths_rank = _GRADE_RANK.get(str(maths).upper()) \
                if isinstance(maths, str) else None
            out.append({"kind": "grades", "minimum": ranks,
                        "maths_rank": maths_rank,
                        "source_ids": list(req.get("source_ids") or []),
                        "req_id": req.get("id")})
    return out


def evaluable_rules(program: dict) -> dict[str, bool]:
    """Which generic rules can be evaluated for this programme."""
    fees = program.get("fees") or {}
    amount = fees.get("amount")
    fee = (isinstance(amount, (int, float)) and not isinstance(amount, bool)
           and fees.get("period") in ("per_year", "total"))
    lang = _language_thresholds(program)
    language = bool(lang["ielts_overalls"] or lang["toefl_overalls"]
                    or lang["component_sets"])
    academic = bool(_alevel_requirements(program))
    return {"fee": fee, "language": language, "academic": academic}


def _fee_rule(profile: StudentProfile, program: dict) -> RuleResult:
    fees = program.get("fees") or {}
    amount = fees.get("amount")
    currency = fees.get("currency") or ""
    period = fees.get("period") or ""
    fee_reqs = [r for r in program.get("requirements", [])
                if r.get("category") == "fee"]
    evidence = [s for r in fee_reqs for s in (r.get("source_ids") or [])]
    threshold = ({"amount": _plain_number(amount), "currency": currency,
                  "period": period}
                 if isinstance(amount, (int, float)) else None)
    if not isinstance(amount, (int, float)) or isinstance(amount, bool):
        return _r("exp-fee", "UNKNOWN",
                  "No tuition fee amount is stated on the official programme page, so the fee cannot be compared with the budget.",
                  evidence, threshold=threshold)
    if period == "per_credit":
        return _r("exp-fee", "UNKNOWN",
                  f"Tuition is {currency} {amount:g} per credit; the profile has no credit count, so a per-credit fee cannot be compared with the budget.",
                  evidence, threshold=threshold)
    budget = profile.budget
    if budget is None or budget.amount is None:
        return _r("exp-fee", "UNKNOWN", "No budget supplied.", evidence,
                  threshold=threshold)
    if budget.period != period:
        return _r("exp-fee", "UNKNOWN",
                  f"Budget period ({budget.period}) does not match the fee period ({period}), so it cannot be compared with the fee.",
                  evidence,
                  observed={"amount": _plain_number(budget.amount),
                            "currency": budget.currency,
                            "period": budget.period},
                  threshold=threshold)
    fee = _dec(amount)
    got = _dec(budget.amount)
    if budget.currency == currency:
        if got >= fee:
            return _r("exp-fee", "MET",
                      f"Budget {currency} {got:g} {period} meets the {currency} {fee:g} {period} tuition fee.",
                      evidence, observed=_plain_number(got), threshold=threshold)
        return _r("exp-fee", "NOT_MET",
                  f"Budget {currency} {got:g} {period} is below the {currency} {fee:g} {period} tuition fee.",
                  evidence, observed=_plain_number(got), threshold=threshold)
    # Round 9, R2: cross-currency comparison with the dated,
    # approximate FX reference table (docs/FX_RATES.md). The converted
    # figure is always labelled approximate; a currency with no
    # reference rate is UNKNOWN ("cannot be converted"), never a
    # false "budget does not match" verdict.
    converted = _convert_fee(fee, currency, budget.currency or "")
    if converted is None:
        return _r("exp-fee", "UNKNOWN",
                  f"The fee is {currency} {fee:g} {period} and the budget is in {budget.currency}; no reference exchange rate is available for this currency pair, so the fee cannot be converted for comparison.",
                  evidence,
                  observed={"amount": _plain_number(budget.amount),
                            "currency": budget.currency,
                            "period": budget.period},
                  threshold=threshold)
    converted_note = (f"(about {budget.currency} {converted:,.0f}"
                      f"{_fx_note(currency, budget.currency or '')})")
    # Round 9 integration: carry the converted figure in the threshold
    # payload so renderers (adapter _exp_expected, frontend
    # ruleExpected) can show it without re-parsing the detail string.
    # Whole units only — the figure is approximate, matching the
    # detail's "(about GBP 4,018 ...)" and the mirror's Math.round.
    threshold = {**threshold,
                 "approx_converted": {"amount": round(float(converted)),
                                      "currency": budget.currency or "",
                                      "as_of": FX_AS_OF}}
    if got >= converted:
        return _r("exp-fee", "MET",
                  f"Budget {budget.currency} {got:g} {period} covers the {currency} {fee:g} {period} tuition fee {converted_note}.",
                  evidence, observed=_plain_number(got), threshold=threshold)
    return _r("exp-fee", "NOT_MET",
              f"Budget {budget.currency} {got:g} {period} is below the {currency} {fee:g} {period} tuition fee {converted_note}.",
              evidence, observed=_plain_number(got), threshold=threshold)


def _language_rules(profile: StudentProfile, program: dict,
                    thresholds: dict[str, Any]) -> list[RuleResult]:
    results: list[RuleResult] = []
    lang = profile.language
    evidence: list[str] = []
    for req in program.get("requirements", []):
        if req.get("category") == "language":
            evidence.extend(s for s in (req.get("source_ids") or [])
                            if s not in evidence)
    ielts_overalls: list[float] = thresholds["ielts_overalls"]
    toefl_overalls: list[float] = thresholds["toefl_overalls"]
    # --- Overall: MET when any evidenced route is met. ---
    ielts_score = (lang.overall if lang is not None
                   and lang.exam == "ielts" else None)
    toefl_score = _toefl_score(lang)
    test_date = _parse_test_date(lang.test_date if lang else None)
    met = False
    assessable_failed = False
    relevant_supplied = False
    if ielts_score is not None:
        if ielts_overalls:
            relevant_supplied = True
            if any(ielts_score >= t for t in ielts_overalls):
                met = True
            else:
                assessable_failed = True
    if toefl_score is not None and not met:
        if toefl_overalls:
            relevant_supplied = True
            verdicts = [_toefl_route(toefl_score, t, test_date)
                        for t in toefl_overalls]
            if "met" in verdicts:
                met = True
            elif "below" in verdicts:
                assessable_failed = True
            # "unknown" verdicts (scale/date) leave the route undecided.
    # Threshold payload. "other_requirements" carries the real
    # non-IELTS/TOEFL requirement labels (CEFR / HSK / Duolingo /
    # PTE) so the renderer can name them instead of showing a generic
    # placeholder — round 9, R13 (the adapter's _exp_expected reads
    # this dict for the live path).
    threshold = {"ielts_overall": ielts_overalls or None,
                 "toefl_overall": toefl_overalls or None,
                 "other_requirements": thresholds.get("other_labels") or None}
    if met:
        detail = ("Language requirement met by a supplied test score "
                  "(IELTS or TOEFL route).")
        results.append(_r("exp-language", "MET", detail, evidence,
                          observed={"ielts_overall": ielts_score,
                                    "toefl_overall": toefl_score},
                          threshold=threshold))
    elif assessable_failed:
        results.append(_r("exp-language", "NOT_MET",
                          "A supplied test score is below the stated IELTS/TOEFL minimum for this programme.",
                          evidence,
                          observed={"ielts_overall": ielts_score,
                                    "toefl_overall": toefl_score},
                          threshold=threshold))
    elif not relevant_supplied:
        if thresholds.get("other_labels"):
            # Round 9, R13: the programme states a real requirement in
            # another system (CEFR / HSK / Duolingo / PTE) — name it.
            # The old wording claimed "no IELTS/TOEFL score is stated",
            # which is false for e.g. the Swiss German C1 / French B2
            # requirements. (Detail wording avoids the adapter's
            # reason-key trigger phrases, so this maps to
            # 'missing-info', not a false 'no-threshold'.)
            labels = ", ".join(thresholds["other_labels"])
            reason = (f"This programme requires {labels}, not an "
                      "IELTS/TOEFL score; the profile has no evidence "
                      "for that requirement, so it cannot be assessed "
                      "from a test score.")
        elif not ielts_overalls and not toefl_overalls \
                and not thresholds["component_sets"]:
            reason = ("This programme states a language requirement, but no "
                      "IELTS/TOEFL score is stated on the official page, so "
                      "it cannot be assessed from a test score.")
        elif toefl_score is not None and toefl_overalls:
            reason = ("TOEFL supplied but no valid test date. The Jan 2026 "
                      "scale split cannot be applied, so TOEFL is UNKNOWN, "
                      "never converted.")
        elif lang is None or lang.exam in (None, "none"):
            reason = "No language test supplied."
        elif ielts_score is not None:
            reason = ("IELTS supplied, but this programme states no IELTS "
                      "minimum (only TOEFL / Duolingo / other routes), so "
                      "the supplied score is not evidence for any stated route.")
        elif toefl_score is not None:
            reason = ("TOEFL supplied, but this programme states no TOEFL "
                      "minimum, so the supplied score is not evidence for "
                      "any stated route.")
        else:
            reason = ("No IELTS/TOEFL score supplied that matches a stated "
                      "route (Duolingo / PTE / HSK / CEFR routes cannot be "
                      "assessed from this profile).")
        results.append(_r("exp-language", "UNKNOWN", reason, evidence,
                          observed={"ielts_overall": ielts_score,
                                    "toefl_overall": toefl_score},
                          threshold=threshold))
    else:
        # A relevant test was supplied but its route could not be
        # assessed (TOEFL scale/date): UNKNOWN, never a failure.
        if toefl_score is not None and toefl_score <= 6:
            reason = ("The supplied TOEFL score is 6 or below, so it "
                      "cannot be placed on the pre/post-Jan-2026 scale "
                      "against the stated iBT minimum; TOEFL is UNKNOWN, "
                      "never converted.")
        else:
            reason = ("TOEFL supplied but no valid test date. The Jan 2026 "
                      "scale split cannot be applied, so TOEFL is UNKNOWN, "
                      "never converted.")
        results.append(_r("exp-language", "UNKNOWN", reason, evidence,
                          observed={"ielts_overall": ielts_score,
                                    "toefl_overall": toefl_score},
                          threshold=threshold))
    # --- Components: IELTS components only (the profile has no TOEFL
    # component scores). NOT_APPLICABLE when no component minimum is
    # stated at all and a test was supplied. ---
    sets: list[dict[str, float]] = thresholds["component_sets"]
    if not sets:
        if lang is None or lang.exam in (None, "none"):
            results.append(_r("exp-language-components", "UNKNOWN",
                              "No language test supplied.", evidence))
        elif thresholds["has_toefl_sections"]:
            results.append(_r("exp-language-components", "UNKNOWN",
                              "This programme states TOEFL section minimums only; the profile has no TOEFL component scores, so they cannot be assessed.",
                              evidence))
        else:
            results.append(_r("exp-language-components", "NOT_APPLICABLE",
                              "This programme states no IELTS/TOEFL component minimum (overall minimum only); there is no component requirement to check.",
                              evidence))
        return results
    if lang is None or lang.exam != "ielts":
        results.append(_r("exp-language-components", "UNKNOWN",
                          "TOEFL supplied; IELTS components do not apply. TOEFL is assessed under its own rule.",
                          evidence))
        return results
    comps = {"listening": lang.listening, "reading": lang.reading,
             "writing": lang.writing, "speaking": lang.speaking}
    missing = [k for k, v in comps.items() if v is None]
    if missing:
        results.append(_r("exp-language-components", "UNKNOWN",
                          f"Missing component score(s): {', '.join(missing)}.",
                          evidence, observed=comps))
        return results

    def _set_met(s: dict[str, float]) -> bool:
        if "__three__" in s:
            above = sum(1 for k in ("listening", "reading", "writing",
                                    "speaking")
                        if comps[k] >= s["__three__"])  # type: ignore[operator]
            return above >= 3 and all(comps[k] >= s["__remaining__"]
                                      for k in comps)  # type: ignore[operator]
        return all(comps[k] >= v for k, v in s.items())

    if any(_set_met(s) for s in sets):
        results.append(_r("exp-language-components", "MET",
                          "Every required IELTS component meets its minimum.",
                          evidence, observed=comps,
                          threshold=sets[0] if len(sets) == 1 else None))
    else:
        low = {k: v for k, v in comps.items()
               if any(k in s and v < s[k] for s in sets if "__three__" not in s)}
        results.append(_r("exp-language-components", "NOT_MET",
                          f"Component(s) below the minimum: {low}.",
                          evidence, observed=comps,
                          threshold=sets[0] if len(sets) == 1 else None))
    return results


def _ug_observed(ug: UndergradProfile) -> dict[str, Any]:
    """Branch-aware observed values for the academic rule.

    Round 9, R10: the frontend renders "你的情况" from observedRaw,
    and a Gaokao / IB / USA profile used to get no observed at all,
    so the card read "未提供" even though the score was supplied
    (e.g. Gaokao 680/750). Only the branch-relevant keys are kept —
    the frontend's localised renderer keys off `curriculum` — and
    None values are dropped so the English fallback string stays
    readable.
    """
    curriculum = effective_curriculum(ug)
    obs: dict[str, Any] = {"curriculum": curriculum}
    if curriculum == "cn_gaokao":
        obs.update({"gaokao_score": ug.gaokao_score,
                    "gaokao_total": ug.gaokao_total,
                    "gaokao_maths": ug.gaokao_maths})
    elif curriculum == "ib":
        obs.update({"total": ug.ib_total,
                    "hl_maths": ug.ib_hl_maths_grade,
                    "hl_total": ug.ib_hl_total})
    elif curriculum == "usa":
        obs.update({"sat_total": ug.sat_total,
                    "act_composite": ug.act_composite,
                    "ap_grades": ug.ap_grades})
    elif curriculum in ("uk_alevel", "sg_alevel"):
        obs.update({"grades": ug.a_level_grades,
                    "maths": ug.a_level_maths_grade})
    return {k: v for k, v in obs.items() if v is not None or k == "curriculum"}


def _academic_rule(profile: StudentProfile, program: dict,
                   alevels: list[dict[str, Any]]) -> RuleResult:
    evidence: list[str] = []
    for req in program.get("requirements", []):
        if req.get("category") == "academic":
            evidence.extend(s for s in (req.get("source_ids") or [])
                            if s not in evidence)
    if profile.application_track == "taught_masters":
        return _r("exp-academic", "UNKNOWN",
                  "A-level thresholds apply to undergraduate entry; this is a taught-masters programme, so no A-level rule can be assessed here.",
                  evidence)
    ug = profile.undergrad_profile or UndergradProfile()
    curriculum = effective_curriculum(ug)
    observed = _ug_observed(ug)
    if not alevels:
        return _r("exp-academic", "UNKNOWN",
                  "No A-level threshold is stated for this programme (the academic requirement uses GPA / IB / degree-class or free-text criteria), so academic eligibility cannot be decided from grades alone.",
                  evidence, observed=observed)
    if curriculum not in ("uk_alevel", "sg_alevel"):
        return _r("exp-academic", "UNKNOWN",
                  "An A-level threshold is stated, but this applicant's curriculum is not A-level; A-level thresholds are only assessed for UK / Singapore A-level applicants, and other scores are never converted to A-levels.",
                  evidence, observed=observed)
    top = _alevel_top3(ug.a_level_grades)
    if top is None:
        return _r("exp-academic", "UNKNOWN",
                  "A-level grades not supplied (three grades are needed).",
                  evidence, observed=observed)
    maths_rank = _GRADE_RANK.get((ug.a_level_maths_grade or "").upper())
    for req in alevels:
        if top < req["minimum"]:
            continue
        if req["kind"] == "grades":
            if req.get("maths_rank") is not None:
                if maths_rank is None:
                    return _r("exp-academic", "UNKNOWN",
                              "A-level grades meet the stated grades, but the required Mathematics grade cannot be checked (no A-level Maths grade supplied).",
                              evidence, observed=observed)
                if maths_rank < req["maths_rank"]:
                    continue
        return _r("exp-academic", "MET",
                  "A-level grades meet the stated A-level threshold.",
                  evidence, observed=observed,
                  threshold={"a_level": req["minimum"]})
    return _r("exp-academic", "NOT_MET",
              "A-level grades do not meet the stated A-level threshold.",
              evidence, observed=observed,
              threshold={"a_level": min(req["minimum"] for req in alevels)})


def _has_numeric_threshold(program: dict, rule_id: str) -> bool:
    """True when the programme states a parseable numeric threshold for
    this rule. A requirement whose threshold is missing, a string, or a
    dict of non-numeric values is a placeholder ("... as stated on the
    official programme page") — it carries no number to fail against,
    so it must never decide a NOT_MET. Unknown rule ids return True:
    the guard only ever downgrades the four generic rules.
    """
    if rule_id == "exp-fee":
        amount = (program.get("fees") or {}).get("amount")
        return isinstance(amount, (int, float)) and not isinstance(amount, bool)
    if rule_id in ("exp-language", "exp-language-components"):
        th = _language_thresholds(program)
        if rule_id == "exp-language":
            return bool(th["ielts_overalls"] or th["toefl_overalls"])
        return bool(th["component_sets"])
    if rule_id == "exp-academic":
        return bool(_alevel_requirements(program))
    return True


def _placeholder_guard(results: list[RuleResult],
                       program: dict) -> list[RuleResult]:
    """Downgrade any NOT_MET with no numeric threshold behind it to
    UNKNOWN. The sub-evaluators only fail against compared numbers, so
    this is defence in depth: a placeholder requirement can never be
    counted as an obstacle, whatever a future evaluator change does.
    """
    out: list[RuleResult] = []
    for r in results:
        if r.status == "NOT_MET" and not _has_numeric_threshold(program,
                                                                r.rule_id):
            out.append(_r(r.rule_id, "UNKNOWN",
                          "No parseable numeric threshold is stated for "
                          "this requirement, so it cannot be judged "
                          f"failed. ({r.detail})",
                          list(r.evidence_ids), observed=r.observed,
                          threshold=r.threshold))
        else:
            out.append(r)
    return out


def evaluate_expansion(profile: StudentProfile, program: dict) -> list[RuleResult]:
    """Evaluate one expansion programme against a profile.

    Only called for promoted (matchable) programmes. Every rule with
    verified structured data is evaluated; everything else is UNKNOWN.
    Test / other / fee-application requirements and deadlines are not
    rules and are never evaluated.
    """
    results: list[RuleResult] = []
    results.append(_fee_rule(profile, program))
    thresholds = _language_thresholds(program)
    if thresholds["has_any_language_req"]:
        results.extend(_language_rules(profile, program, thresholds))
    alevels = _alevel_requirements(program)
    has_academic_req = any(r.get("category") == "academic"
                           for r in program.get("requirements", []))
    if has_academic_req:
        results.append(_academic_rule(profile, program, alevels))
    return _placeholder_guard(results, program)

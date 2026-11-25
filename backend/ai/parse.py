"""Free-text profile parsing (Day 3).

This endpoint NEVER applies a profile — it only returns the parse.
Applying happens via the normal ``/match`` or ``/profile/validate``
with the user-confirmed profile. The response always carries
``confirmation_required: True``: nothing parsed here is trusted until
the user confirms it.

Two paths, one validator:

- Model path (a provider is configured): the model extracts a
  ``PARSE_SCHEMA``-shaped dict from the user's text (``parse_system``
  prompt, JSON envelope ``{task: "parse", prompt_version, locale,
  text}``). The extraction is validated against the same shape and
  value ranges as the regex path.
- Regex path (no key, or the model call fails): the same fields are
  extracted with regular expressions.

Validation rules (both paths, never silently broken):

- out-of-range or unmapped values go into ``unparsed`` — NEVER clamp,
  rescale, or convert one grading scale into another;
- a value stated without units stays unparsed (e.g. a bare budget
  number with no currency);
- ranges: Gaokao 0..total (total defaults to 750), IELTS 0..9, TOEFL
  0..120, SAT 400..1600, ACT 1..36, IB 0..45, GRE 260..340, GMAT
  205..805, budget amount > 0, intake year 2026..2028;
- ``parsed_profile`` is StudentProfile-shaped and contains ONLY
  extracted fields (sub-objects are omitted entirely when nothing in
  them was extracted; a budget that was extracted carries
  ``period: None`` when no period was stated).

Personal data (an email/phone-like value) is never echoed back: any
segment or model ``unparsed`` entry that looks like personal data is
dropped, never stored and never returned.
"""
from __future__ import annotations

import json
import re

from ai.assistant import contains_personal_data
from ai.chat import _parse_model_json
from ai.prompts import PROMPT_VERSION, parse_system
from ai.provider import ProviderAdapter, ProviderError

# ---------------------------------------------------------------------------
# Shared validation + conversion to a StudentProfile-shaped dict
# ---------------------------------------------------------------------------

_CURRICULA = ("cn_gaokao", "uk_alevel", "ib", "usa", "sg_alevel", "other")
_DEGREE_FIELDS = ("computing", "related", "business", "other")
_DEGREE_CLASSES = ("first", "upper_second", "lower_second", "third", "other")
_CURRENCIES = ("GBP", "SGD", "USD")
_A_LEVEL_GRADES = ("A*", "A", "B", "C", "D", "E", "U")


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _in_int_range(value, lo: int, hi: int) -> bool:
    return _is_int(value) and lo <= value <= hi


def _in_num_range(value, lo: float, hi: float) -> bool:
    return _is_num(value) and lo <= value <= hi


def _convert(raw: dict) -> tuple[dict, list[str], dict]:
    """Validate a PARSE_SCHEMA-shaped dict and convert it to
    ``(parsed_profile, unparsed, confidence)``.

    Out-of-range / wrong-typed / unmapped values are reported in
    ``unparsed`` as ``"<label> <value>"`` and never clamped.
    """
    raw = raw if isinstance(raw, dict) else {}
    unparsed: list[str] = []
    confidence: dict[str, str] = {}
    raw_conf = raw.get("confidence") if isinstance(raw.get("confidence"), dict) else {}

    def conf(dotted: str, short: str, default: str = "medium") -> str:
        for key in (dotted, short):
            value = raw_conf.get(key)
            if value in ("high", "medium", "low"):
                return value
        return default

    def bad(label: str, value) -> None:
        unparsed.append(f"{label} {value}")

    def keep(field: str, dotted: str, short: str, level: str = "medium") -> None:
        confidence[dotted] = conf(dotted, short, level)

    under_raw = raw.get("undergrad") if isinstance(raw.get("undergrad"), dict) else {}
    mast_raw = raw.get("masters") if isinstance(raw.get("masters"), dict) else {}
    lang_raw = raw.get("language") if isinstance(raw.get("language"), dict) else {}
    bud_raw = raw.get("budget") if isinstance(raw.get("budget"), dict) else {}

    # -- undergraduate ------------------------------------------------------
    under: dict = {}
    curriculum = under_raw.get("curriculum")
    if curriculum in _CURRICULA:
        under["curriculum"] = curriculum
        keep("curriculum", "undergrad_profile.curriculum", "curriculum", "high")
    elif curriculum is not None:
        bad("curriculum", curriculum)
    gaokao_total = under_raw.get("gaokao_total")
    total_ok: int | None = None
    if gaokao_total is not None:
        if _in_int_range(gaokao_total, 1, 750):
            under["gaokao_total"] = gaokao_total
            total_ok = gaokao_total
            keep("gaokao_total", "undergrad_profile.gaokao_total", "gaokao_total", "high")
        else:
            bad("Gaokao total", gaokao_total)
    gaokao_score = under_raw.get("gaokao_score")
    if gaokao_score is not None:
        if _in_int_range(gaokao_score, 0, total_ok or 750):
            under["gaokao_score"] = gaokao_score
            keep("gaokao_score", "undergrad_profile.gaokao_score", "gaokao_score", "high")
        else:
            bad("Gaokao score", gaokao_score)
    sat = under_raw.get("sat_total")
    if sat is not None:
        if _in_int_range(sat, 400, 1600):
            under["sat_total"] = sat
            keep("sat_total", "undergrad_profile.sat_total", "sat_total", "high")
        else:
            bad("SAT total", sat)
    act = under_raw.get("act_composite")
    if act is not None:
        if _in_int_range(act, 1, 36):
            under["act_composite"] = act
            keep("act_composite", "undergrad_profile.act_composite", "act_composite", "high")
        else:
            bad("ACT composite", act)
    ib_total = under_raw.get("ib_total")
    if ib_total is not None:
        if _in_int_range(ib_total, 0, 45):
            under["ib_total"] = ib_total
            keep("ib_total", "undergrad_profile.ib_total", "ib_total", "high")
        else:
            bad("IB total", ib_total)
    a_levels = under_raw.get("a_level_grades")
    if a_levels is not None:
        if isinstance(a_levels, list):
            good = [g for g in a_levels
                    if isinstance(g, str) and g.upper() in _A_LEVEL_GRADES]
            for g in a_levels:
                if not (isinstance(g, str) and g.upper() in _A_LEVEL_GRADES):
                    bad("A-level grade", g)
            if good:
                under["a_level_grades"] = [g.upper() for g in good]
                keep("a_level_grades", "undergrad_profile.a_level_grades",
                     "a_level_grades", "high")
        else:
            bad("A-level grades", a_levels)

    # -- masters ------------------------------------------------------------
    mast: dict = {}
    degree_field = mast_raw.get("degree_field")
    if degree_field in _DEGREE_FIELDS:
        mast["degree_field"] = degree_field
        keep("degree_field", "masters_profile.degree_field", "degree_field", "medium")
    elif degree_field is not None:
        bad("degree field", degree_field)
    degree_class = mast_raw.get("degree_class")
    if degree_class in _DEGREE_CLASSES:
        mast["degree_class"] = degree_class
        keep("degree_class", "masters_profile.degree_class", "degree_class", "medium")
    elif degree_class is not None:
        bad("degree class", degree_class)
    it_years = mast_raw.get("it_experience_years")
    if it_years is not None:
        if _in_num_range(it_years, 0, 60):
            mast["it_experience_years"] = it_years
            keep("it_experience_years", "masters_profile.it_experience_years",
                 "it_experience_years", "medium")
        else:
            bad("IT experience years", it_years)
    gre = mast_raw.get("gre_total")
    if gre is not None:
        if _in_int_range(gre, 260, 340):
            mast["gre_total"] = gre
            keep("gre_total", "masters_profile.gre_total", "gre_total", "high")
        else:
            bad("GRE total", gre)
    gmat = mast_raw.get("gmat_total")
    if gmat is not None:
        if _in_int_range(gmat, 205, 805):
            mast["gmat_total"] = gmat
            keep("gmat_total", "masters_profile.gmat_total", "gmat_total", "high")
        else:
            bad("GMAT total", gmat)

    # -- language -----------------------------------------------------------
    lang: dict = {}
    exam = lang_raw.get("exam")
    if exam in ("ielts", "toefl", "none"):
        lang["exam"] = exam
    elif exam is not None:
        bad("language exam", exam)
        exam = None
    if exam in ("ielts", "toefl"):
        is_toefl = exam == "toefl"
        overall_hi = 120.0 if is_toefl else 9.0
        comp_hi = 30.0 if is_toefl else 9.0
        overall = lang_raw.get("overall")
        if overall is not None:
            if _in_num_range(overall, 0, overall_hi):
                if is_toefl:
                    lang["toefl_overall"] = overall
                    keep("toefl_overall", "language.toefl_overall", "toefl_overall", "high")
                else:
                    lang["overall"] = overall
                    keep("overall", "language.overall", "overall", "high")
            else:
                bad("TOEFL overall" if is_toefl else "IELTS overall", overall)
        for field, label in (("listening", "listening"), ("reading", "reading"),
                             ("writing", "writing"), ("speaking", "speaking")):
            value = lang_raw.get(field)
            if value is not None:
                if _in_num_range(value, 0, comp_hi):
                    lang[field] = value
                    keep(field, f"language.{field}", field, "high")
                else:
                    bad(f"{'TOEFL' if is_toefl else 'IELTS'} {label}", value)
    elif exam == "none":
        for field in ("overall", "listening", "reading", "writing", "speaking"):
            if lang_raw.get(field) is not None:
                bad(f"language {field}", lang_raw[field])
    elif exam is None:
        for field in ("overall", "listening", "reading", "writing", "speaking"):
            if lang_raw.get(field) is not None:
                bad(f"language {field}", lang_raw[field])

    # -- budget -------------------------------------------------------------
    budget: dict = {}
    amount = bud_raw.get("amount")
    if amount is not None:
        if _in_num_range(amount, 0, float("inf")) and amount > 0:
            budget["amount"] = int(amount) if float(amount).is_integer() else amount
            keep("amount", "budget.amount", "amount", "medium")
        else:
            bad("Budget amount", amount)
    currency = bud_raw.get("currency")
    if currency in _CURRENCIES:
        budget["currency"] = currency
        keep("currency", "budget.currency", "currency", "high")
    elif currency is not None:
        bad("Budget currency", currency)
    period = bud_raw.get("period")
    if period in ("per_year", "total"):
        budget["period"] = period
        keep("period", "budget.period", "period", "high")
    elif period is not None:
        bad("Budget period", period)
    if budget:
        budget.setdefault("period", None)

    # -- intake -------------------------------------------------------------
    intake = raw.get("target_intake")
    if intake is not None:
        if _in_int_range(intake, 2026, 2028):
            keep("target_intake", "target_intake", "target_intake", "high")
        else:
            bad("Target intake", intake)
            intake = None

    # -- assemble: only extracted fields ------------------------------------
    track = raw.get("application_track")
    if track not in ("undergraduate", "taught_masters", "unknown"):
        track = "unknown"
    if track == "unknown":
        if under and not mast:
            track = "undergraduate"
        elif mast and not under:
            track = "taught_masters"
    profile: dict = {"application_track": track}
    if under:
        profile["undergrad_profile"] = under
    if mast:
        profile["masters_profile"] = mast
    if lang:
        profile["language"] = lang
    if budget:
        profile["budget"] = budget
    if intake is not None:
        profile["target_intake"] = intake

    for entry in raw.get("unparsed") or []:
        if isinstance(entry, str) and entry.strip():
            unparsed.append(entry.strip())
    # Never echo personal data back in unparsed, and never repeat an
    # entry twice.
    seen: set[str] = set()
    clean_unparsed: list[str] = []
    for entry in unparsed:
        if entry in seen or contains_personal_data(entry):
            continue
        seen.add(entry)
        clean_unparsed.append(entry)
    clean_conf = {k: v for k, v in confidence.items()
                  if _field_present(profile, k)}
    return profile, clean_unparsed, clean_conf


def _field_present(profile: dict, dotted: str) -> bool:
    """True when a dotted confidence key names a field in the profile."""
    parts = dotted.split(".")
    node: object = profile
    for part in parts:
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


# ---------------------------------------------------------------------------
# Regex path (no key, or model failure)
# ---------------------------------------------------------------------------

_CURRENCY_WORDS = {
    "gbp": "GBP", "英镑": "GBP", "£": "GBP",
    "sgd": "SGD", "新元": "SGD", "s$": "SGD",
    "usd": "USD", "美元": "USD", "$": "USD",
}

_GAOKAO_RE = re.compile(r"(?:gaokao|高考)\D{0,12}?(\d+)(?:\s*(?:/|out of|满分)\s*(\d+))?",
                        re.IGNORECASE)
_IELTS_RE = re.compile(r"(?:ielts|雅思)\D{0,15}?(\d+(?:\.\d+)?)", re.IGNORECASE)
_TOEFL_RE = re.compile(r"(?:toefl|托福)\D{0,10}?(\d+)", re.IGNORECASE)
_SAT_RE = re.compile(r"\bSAT\D{0,10}?(\d+)", re.IGNORECASE)
_ACT_RE = re.compile(r"\bACT\D{0,10}?(\d+)", re.IGNORECASE)
_GRE_RE = re.compile(r"\bGRE\D{0,10}?(\d+)", re.IGNORECASE)
_GMAT_RE = re.compile(r"\bGMAT\D{0,10}?(\d+)", re.IGNORECASE)
_IB_RE = re.compile(r"\bIB\D{0,12}?(\d+)", re.IGNORECASE)
_BUDGET_RE = re.compile(
    r"(\d[\d,]*\.?\d*)\s*(k|K|万)?\s*(GBP|SGD|USD|英镑|新元|美元|£|S\$|\$)",
    re.IGNORECASE)
_BUDGET_CUR_FIRST_RE = re.compile(
    r"(£|S\$|\$)\s*(\d[\d,]*\.?\d*)\s*(k|K)?", re.IGNORECASE)
_INTAKE_RE = re.compile(
    r"(?:intake|entry|入学|入读|fall|autumn|spring)\D{0,12}?(20\d\d)"
    r"|(20\d\d)\s*(?:intake|entry|入学|入读|年入学)", re.IGNORECASE)
_IT_EXP_RE = re.compile(
    r"(?:it|work|software|programming)?\s*experience\D{0,12}?(\d+(?:\.\d+)?)\s*(?:years?|年)",
    re.IGNORECASE)
_COMP_RE = re.compile(r"(listening|reading|writing|speaking|听力|阅读|写作|口语)\D{0,6}?(\d+(?:\.\d+)?)",
                      re.IGNORECASE)
_COMP_KEY = {"listening": "listening", "reading": "reading",
             "writing": "writing", "speaking": "speaking",
             "听力": "listening", "阅读": "reading",
             "写作": "writing", "口语": "speaking"}


def _regex_parse(text: str) -> dict:
    """Regex extraction into a PARSE_SCHEMA-shaped dict (validated by
    ``_convert`` afterwards, so ranges are enforced identically)."""
    raw: dict = {"application_track": "unknown", "undergrad": {}, "masters": {},
                 "language": {}, "budget": {}, "target_intake": None,
                 "unparsed": [], "confidence": {}}
    conf: dict[str, str] = raw["confidence"]
    under, mast, lang, bud = raw["undergrad"], raw["masters"], raw["language"], raw["budget"]
    track_signals: set[str] = set()

    def _num(group: str | None):
        if group is None:
            return None
        try:
            value = float(group.replace(",", ""))
        except ValueError:
            return None
        return int(value) if value.is_integer() else value

    segments = [s.strip() for s in re.split(r"[,;，；\n]|\s+and\s+", text, flags=re.IGNORECASE)]
    for seg in segments:
        if not seg or contains_personal_data(seg):
            # Personal-data segments are dropped, never echoed.
            continue
        found = False
        m = _GAOKAO_RE.search(seg)
        if m:
            under["curriculum"] = "cn_gaokao"
            under["gaokao_score"] = _num(m.group(1))
            if m.group(2):
                under["gaokao_total"] = _num(m.group(2))
            conf["undergrad_profile.gaokao_score"] = "high"
            conf["undergrad_profile.curriculum"] = "high"
            track_signals.add("undergraduate")
            found = True
        m = _IELTS_RE.search(seg)
        if m:
            lang["exam"] = "ielts"
            lang["overall"] = _num(m.group(1))
            conf["language.overall"] = "high"
            for cm in _COMP_RE.finditer(seg):
                key = _COMP_KEY.get(cm.group(1).lower())
                if key:
                    lang[key] = _num(cm.group(2))
                    conf[f"language.{key}"] = "high"
            found = True
        elif (m := _TOEFL_RE.search(seg)):
            lang["exam"] = "toefl"
            lang["overall"] = _num(m.group(1))
            conf["language.toefl_overall"] = "high"
            found = True
        m = _SAT_RE.search(seg)
        if m:
            under["curriculum"] = "usa"
            under["sat_total"] = _num(m.group(1))
            conf["undergrad_profile.sat_total"] = "high"
            track_signals.add("undergraduate")
            found = True
        m = _ACT_RE.search(seg)
        if m:
            under["curriculum"] = "usa"
            under["act_composite"] = _num(m.group(1))
            conf["undergrad_profile.act_composite"] = "high"
            track_signals.add("undergraduate")
            found = True
        m = _GRE_RE.search(seg)
        if m:
            mast["gre_total"] = _num(m.group(1))
            conf["masters_profile.gre_total"] = "high"
            track_signals.add("taught_masters")
            found = True
        m = _GMAT_RE.search(seg)
        if m:
            mast["gmat_total"] = _num(m.group(1))
            conf["masters_profile.gmat_total"] = "high"
            track_signals.add("taught_masters")
            found = True
        m = _IB_RE.search(seg)
        if m and "ib" in seg.lower():
            under["curriculum"] = "ib"
            under["ib_total"] = _num(m.group(1))
            conf["undergrad_profile.ib_total"] = "high"
            track_signals.add("undergraduate")
            found = True
        if re.search(r"a[ -]?level", seg, re.IGNORECASE):
            grades = re.findall(r"A\*|[A-E]", seg.upper())
            grades = [g for g in grades if g in _A_LEVEL_GRADES]
            if len(grades) >= 3:
                under["curriculum"] = "uk_alevel"
                under["a_level_grades"] = grades[:4]
                conf["undergrad_profile.a_level_grades"] = "high"
                track_signals.add("undergraduate")
                found = True
        if re.search(r"(?:degree|major|bachelor|master|专业|学位)", seg, re.IGNORECASE):
            low = seg.lower()
            if any(w in low for w in ("computer", "computing", "software", "计算机", "软件", "data science", "人工智能")):
                mast["degree_field"] = "computing"
                conf["masters_profile.degree_field"] = "medium"
                found = True
            elif any(w in low for w in ("business", "商科", "管理", "finance", "金融")):
                mast["degree_field"] = "business"
                conf["masters_profile.degree_field"] = "medium"
                found = True
        low = seg.lower()
        if "first class" in low or "一等" in seg:
            mast["degree_class"] = "first"
            conf["masters_profile.degree_class"] = "medium"
            track_signals.add("taught_masters")
            found = True
        elif "upper second" in low or "2:1" in seg or "二等一" in seg:
            mast["degree_class"] = "upper_second"
            conf["masters_profile.degree_class"] = "medium"
            track_signals.add("taught_masters")
            found = True
        elif "lower second" in low or "2:2" in seg:
            mast["degree_class"] = "lower_second"
            conf["masters_profile.degree_class"] = "medium"
            track_signals.add("taught_masters")
            found = True
        m = _IT_EXP_RE.search(seg)
        if m:
            mast["it_experience_years"] = _num(m.group(1))
            conf["masters_profile.it_experience_years"] = "medium"
            track_signals.add("taught_masters")
            found = True
        bm = _BUDGET_RE.search(seg) or _BUDGET_CUR_FIRST_RE.search(seg)
        if bm:
            if bm.re is _BUDGET_RE:
                amount_raw, mult, cur_raw = bm.group(1), bm.group(2), bm.group(3)
            else:
                cur_raw, amount_raw, mult = bm.group(1), bm.group(2), bm.group(3)
            amount = _num(amount_raw)
            if amount is not None:
                if mult and mult.lower() == "k":
                    amount *= 1000
                    conf["budget.amount"] = "medium"  # shorthand: less certain
                elif mult == "万":
                    amount *= 10000
                    conf["budget.amount"] = "medium"
                else:
                    conf["budget.amount"] = "high"
                bud["amount"] = amount
                bud["currency"] = _CURRENCY_WORDS.get(cur_raw.lower(), cur_raw.upper())
                conf["budget.currency"] = "high"
                low_seg = seg.lower()
                if any(w in low_seg for w in ("per year", "每年", "per annum", "annual")):
                    bud["period"] = "per_year"
                elif any(w in low_seg for w in ("total", "总学费", "共计", "一共")):
                    bud["period"] = "total"
                found = True
        m = _INTAKE_RE.search(seg)
        if m:
            year = m.group(1) or m.group(2)
            raw["target_intake"] = int(year)
            conf["target_intake"] = "high"
            found = True
        if re.search(r"\bundergraduate\b|本科", seg, re.IGNORECASE):
            track_signals.add("undergraduate")
            found = found or "本科" in seg
        if re.search(r"\btaught masters\b|\bmaster'?s\b|硕士|研究生", seg, re.IGNORECASE):
            track_signals.add("taught_masters")
            found = found or "硕士" in seg
        if not found:
            raw["unparsed"].append(seg)
    if len(track_signals) == 1:
        raw["application_track"] = next(iter(track_signals))
    return raw


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse_profile(text: str, locale: str = "en",
                  provider: ProviderAdapter | None = None) -> dict:
    """Parse free text into a StudentProfile-shaped dict.

    Returns ``{parsed_profile, unparsed, confidence,
    confirmation_required, parser, ai_status, note}``. ``parser`` is
    ``"model"`` when a validated model extraction was used, else
    ``"regex"``; ``ai_status`` is ``"available"`` only for the model
    path. The profile is NEVER applied here — ``confirmation_required``
    is always True and the note says so: apply only via ``/match`` or
    ``/profile/validate`` with the user-confirmed profile.
    """
    loc = locale if locale in ("en", "zh-CN", "es", "fr", "pt-BR", "ar") else "en"
    provider = provider or ProviderAdapter()
    parser = "regex"
    ai_status = "unavailable"
    raw: dict | None = None
    if provider.available:
        envelope = {"task": "parse", "prompt_version": PROMPT_VERSION,
                    "locale": loc, "text": text}
        try:
            result = provider.chat(
                [{"role": "user", "content": json.dumps(envelope, ensure_ascii=False)}],
                system=parse_system(loc), timeout_s=12.0)
            parsed = _parse_model_json(result.text)
        except ProviderError:
            parsed = None
        if isinstance(parsed, dict):
            raw = parsed
            parser = "model"
            ai_status = "available"
    if raw is None:
        raw = _regex_parse(text)
    profile, unparsed, confidence = _convert(raw)
    return {
        "parsed_profile": profile,
        "unparsed": unparsed,
        "confidence": confidence,
        "confirmation_required": True,
        "parser": parser,
        "ai_status": ai_status,
        "note": ("This is a parse only; the profile is not applied. "
                 "Confirm it, then apply it via /match or /profile/validate "
                 "with the user-confirmed profile."),
    }

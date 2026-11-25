"""小罗盘 (Little Compass) — the PathPilot desktop-pet assistant (Day 3).

Rules/template mode ONLY. No AI model is connected (``ai_status`` is
always ``"unavailable"``) and no model is ever claimed to be answering.
Every fact comes from the verified local catalogue:

- the 8 programmes in ``data/versions/v2/programs.json`` (official pages
  only — fees, IELTS thresholds, deadlines), and
- the 300 ranking entries in ``data/versions/v2/rankings.json``
  (QS 2027 / THE 2027 / ARWU 2026, top 100 each).

Hard policy (test-pinned in ``tests/test_assistant.py``):

- Unknown stays unknown — never guess, never invent a requirement, fee
  or rank. A fact that is not in the verified data is answered with the
  unknown line, never with a plausible-looking value.
- NO admission probabilities and NO guarantees — no ``%``, no
  probability words, no "you will get in" phrasing anywhere.
- NO personal data is collected. A message that looks like it contains
  a name/phone/email is answered with the fixed refusal line; the value
  is never stored and never echoed back.
- Answers are at most 3 lines, conclusion first, then ONE evidence link
  (``evidence_url`` — a verified official page, or an institution's
  provider profile page taken from the official feeds).
- The compiled IELTS reference on institution pages (user-supplied
  table images) is NOT a verified programme requirement and is never
  used here; programme language facts come only from the programme's
  own official requirements.
"""
from __future__ import annotations

import re

from app.data import DATA_VERSION, PROGRAMS, RANKINGS

AI_STATUS = "unavailable"
MAX_ANSWER_LINES = 3

DEGREE_LEVELS = ("undergraduate", "taught_masters")
# Countries with verified programmes (and localised country names in
# _T) so far. The product is global: any other country is accepted and
# degrades to the honest "no verified programme" answer — see
# suggest() — never a 422 and never a guessed route.
COUNTRIES = ("GB", "SG")
BUDGET_BANDS = ("low", "mid", "high")

# Budget bands (annual budget in the country's currency, except SG taught
# masters, where the verified fees are programme totals, so the band is a
# total budget). Each band is (low, high); None means open-ended.
# GB: overseas UG/TM fees are ~GBP 44,400-48,300/year.
# SG UG: international without-grant fees are ~SGD 36,350-40,600/year.
# SG TM: totals are SGD 65,748.80 (NTU) and SGD 69,215 (NUS).
_BANDS: dict[tuple[str, str], dict[str, tuple[float | None, float | None]]] = {
    ("undergraduate", "GB"): {"low": (None, 30_000), "mid": (30_000, 50_000), "high": (50_000, None)},
    ("taught_masters", "GB"): {"low": (None, 30_000), "mid": (30_000, 50_000), "high": (50_000, None)},
    ("undergraduate", "SG"): {"low": (None, 25_000), "mid": (25_000, 45_000), "high": (45_000, None)},
    ("taught_masters", "SG"): {"low": (None, 50_000), "mid": (50_000, 80_000), "high": (80_000, None)},
}

LOCALES = ("en", "zh-CN", "es", "fr", "pt-BR", "ar")

# ---------------------------------------------------------------------------
# Localised templates. Short, fixed sentences only; {placeholders} are
# filled from verified data, never from free text.
# ---------------------------------------------------------------------------
_T: dict[str, dict[str, str]] = {
    "en": {
        "level_undergraduate": "Undergraduate",
        "level_taught_masters": "Taught masters",
        "country_GB": "UK",
        "country_SG": "Singapore",
        "suggest_within": "{level} · {country}: start with {program}.",
        "suggest_above": "{level} · {country}: every verified programme here is above your budget band; the cheapest is {program}.",
        "suggest_none": "{level} · {country}: no verified programme in this track yet, so I don't know.",
        "fee_within": "Tuition {fee} — inside your budget band.",
        "fee_above": "Tuition {fee} — above your budget band.",
        "fee_unknown": "No verified tuition figure for this programme in the data.",
        "next": "Next step: start the eligibility check to confirm grades and language.",
        "ask_fee": "{program} tuition: {fee}.",
        "ask_ielts": "{program} IELTS: {fact}.",
        "ask_ielts_unknown": "The official page does not state the English requirement for {program}, so I don't know.",
        "ask_deadline": "{program} application deadline: {deadline}.",
        "ask_deadline_unknown": "No verified application deadline for {program} in the data.",
        "rank_next": "No verified programme data for this institution yet — see its ranking detail page.",
        "rank_need_name": "Tell me which institution — I only look up the verified top 100.",
        "ambiguous_programme": "I found two matching programmes: {names}. Tell me undergraduate or masters.",
        "ambiguous_rank": "I found several matching institutions: {names}. Tell me which one.",
        "personal": "I don't collect names, phone numbers or email addresses — please don't send them here.",
        "personal_2": "You can start the eligibility check directly; no personal details are needed.",
        "unknown": "I can't find that in the verified data, so I don't know.",
        "unknown_2": "Start the eligibility check to go through your background rule by rule.",
        "greeting": "Hi, I'm 小罗盘. Tap a question below and I'll check the verified route with you.",
        "fee_per_year": "{currency} {amount} per year",
        "fee_total": "{currency} {amount} total",
        "fee_qual_overseas": "overseas",
        "fee_qual_intl": "international, no grant",
        "fee_qual_gst": "incl. 9% GST",
        "ielts_overall": "overall {v}",
        "ielts_each": "minimum {v} in each component",
        "ielts_component": "{name} {v}",
        "rank_present": "{provider} {edition} #{rank}",
        "rank_absent": "{provider} not in the top 100",
        "rank_unavailable": "{provider} rank not verified",
        "comp_reading": "Reading",
        "comp_writing": "Writing",
        "comp_listening": "Listening",
        "comp_speaking": "Speaking",
    },
    "zh-CN": {
        "level_undergraduate": "本科",
        "level_taught_masters": "授课型硕士",
        "country_GB": "英国",
        "country_SG": "新加坡",
        "suggest_within": "{level} · {country}：先看 {program}。",
        "suggest_above": "{level} · {country}：已核实的专业都在你的预算带之上，最便宜的是 {program}。",
        "suggest_none": "{level} · {country}：已核实的目录里还没有这个方向的专业，我不知道。",
        "fee_within": "学费 {fee}，在你的预算带内。",
        "fee_above": "学费 {fee}，高于你的预算带。",
        "fee_unknown": "这个专业的学费在已核实的数据里查不到。",
        "next": "下一步：开始资格检查，确认成绩和语言是否达标。",
        "ask_fee": "{program} 学费：{fee}。",
        "ask_ielts": "{program} 雅思要求：{fact}。",
        "ask_ielts_unknown": "{program} 的英语要求在官网页面上没有说明，我不知道。",
        "ask_deadline": "{program} 申请截止：{deadline}。",
        "ask_deadline_unknown": "{program} 的申请截止日期在已核实的数据里查不到。",
        "rank_next": "这所学校还没有已核实的专业数据，先看它的排名详情页。",
        "rank_need_name": "请告诉我是哪所学校，我只查已核实的前 100 名。",
        "ambiguous_programme": "我找到两个相关专业：{names}。请告诉我是本科还是硕士。",
        "ambiguous_rank": "我找到多所相关学校：{names}。请说具体是哪一所。",
        "personal": "我不收集姓名、电话、邮箱等个人信息，请不要在这里发送。",
        "personal_2": "直接开始资格检查就行，不需要提供这些信息。",
        "unknown": "这个我从已核实的数据里查不到，不知道。",
        "unknown_2": "可以开始资格检查，逐项核对你的背景。",
        "greeting": "你好，我是小罗盘。点下面的问题，我帮你看看已核实的选校路线。",
        "fee_per_year": "{currency} {amount} / 年",
        "fee_total": "{currency} {amount}（总学费）",
        "fee_qual_overseas": "海外学费",
        "fee_qual_intl": "国际生，无助学金",
        "fee_qual_gst": "含 9% GST",
        "ielts_overall": "总分 {v}",
        "ielts_each": "每项最低 {v}",
        "ielts_component": "{name} {v}",
        "rank_present": "{provider} {edition} 第 {rank} 名",
        "rank_absent": "{provider} 未进前 100",
        "rank_unavailable": "{provider} 排名未核实",
        "comp_reading": "阅读",
        "comp_writing": "写作",
        "comp_listening": "听力",
        "comp_speaking": "口语",
    },
    "es": {
        "level_undergraduate": "Grado",
        "level_taught_masters": "Máster impartido",
        "country_GB": "Reino Unido",
        "country_SG": "Singapur",
        "suggest_within": "{level} · {country}: empieza por {program}.",
        "suggest_above": "{level} · {country}: todos los programas verificados superan tu presupuesto; el más barato es {program}.",
        "suggest_none": "{level} · {country}: aún no hay programas verificados en esta vía; no lo sé.",
        "fee_within": "Matrícula {fee}, dentro de tu presupuesto.",
        "fee_above": "Matrícula {fee}, por encima de tu presupuesto.",
        "fee_unknown": "No hay una cifra de matrícula verificada para este programa.",
        "next": "Siguiente paso: inicia la comprobación de requisitos para confirmar notas e idioma.",
        "ask_fee": "Matrícula de {program}: {fee}.",
        "ask_ielts": "IELTS de {program}: {fact}.",
        "ask_ielts_unknown": "La página oficial no indica el requisito de inglés de {program}; no lo sé.",
        "ask_deadline": "Plazo de solicitud de {program}: {deadline}.",
        "ask_deadline_unknown": "No hay un plazo verificado para {program} en los datos.",
        "rank_next": "Aún no hay datos verificados de programas para esta universidad; consulta su página de rankings.",
        "rank_need_name": "Dime qué universidad; solo consulto el top 100 verificado.",
        "ambiguous_programme": "Encontré dos programas: {names}. Dime si es grado o máster.",
        "ambiguous_rank": "Encontré varias universidades: {names}. Dime cuál.",
        "personal": "No recopilo nombres, teléfonos ni correos; no los envíes aquí.",
        "personal_2": "Puedes iniciar la comprobación directamente; no se necesitan datos personales.",
        "unknown": "No lo encuentro en los datos verificados; no lo sé.",
        "unknown_2": "Inicia la comprobación de requisitos para revisar tu perfil regla por regla.",
        "greeting": "Hola, soy 小罗盘. Toca una pregunta y revisamos juntos la ruta verificada.",
        "fee_per_year": "{currency} {amount} al año",
        "fee_total": "{currency} {amount} en total",
        "fee_qual_overseas": "internacional",
        "fee_qual_intl": "internacional, sin beca",
        "fee_qual_gst": "GST del 9 % incluido",
        "ielts_overall": "total {v}",
        "ielts_each": "mínimo {v} en cada parte",
        "ielts_component": "{name} {v}",
        "rank_present": "{provider} {edition}: n.º {rank}",
        "rank_absent": "{provider} fuera del top 100",
        "rank_unavailable": "{provider}: ranking no verificado",
        "comp_reading": "Lectura",
        "comp_writing": "Escritura",
        "comp_listening": "Escucha",
        "comp_speaking": "Habla",
    },
    "fr": {
        "level_undergraduate": "Licence",
        "level_taught_masters": "Master enseigné",
        "country_GB": "Royaume-Uni",
        "country_SG": "Singapour",
        "suggest_within": "{level} · {country} : commencez par {program}.",
        "suggest_above": "{level} · {country} : tous les programmes vérifiés dépassent votre budget ; le moins cher est {program}.",
        "suggest_none": "{level} · {country} : aucun programme vérifié dans cette voie pour l'instant ; je ne sais pas.",
        "fee_within": "Frais {fee}, dans votre budget.",
        "fee_above": "Frais {fee}, au-dessus de votre budget.",
        "fee_unknown": "Aucun montant de frais vérifié pour ce programme.",
        "next": "Étape suivante : lancez la vérification d'éligibilité pour confirmer notes et langue.",
        "ask_fee": "Frais de {program} : {fee}.",
        "ask_ielts": "IELTS de {program} : {fact}.",
        "ask_ielts_unknown": "La page officielle n'indique pas le niveau d'anglais requis pour {program} ; je ne sais pas.",
        "ask_deadline": "Date limite de candidature pour {program} : {deadline}.",
        "ask_deadline_unknown": "Aucune date limite vérifiée pour {program} dans les données.",
        "rank_next": "Pas encore de données de programme vérifiées pour cette université ; voir sa page de classement.",
        "rank_need_name": "Dites-moi quelle université ; je ne consulte que le top 100 vérifié.",
        "ambiguous_programme": "J'ai trouvé deux programmes : {names}. Dites-moi licence ou master.",
        "ambiguous_rank": "J'ai trouvé plusieurs universités : {names}. Précisez laquelle.",
        "personal": "Je ne collecte ni nom, ni téléphone, ni e-mail ; ne les envoyez pas ici.",
        "personal_2": "Vous pouvez lancer la vérification directement ; aucune donnée personnelle n'est nécessaire.",
        "unknown": "Je ne trouve pas cela dans les données vérifiées ; je ne sais pas.",
        "unknown_2": "Lancez la vérification d'éligibilité pour revoir votre profil règle par règle.",
        "greeting": "Bonjour, je suis 小罗盘. Touchez une question et nous vérifierons la route ensemble.",
        "fee_per_year": "{currency} {amount} par an",
        "fee_total": "{currency} {amount} au total",
        "fee_qual_overseas": "international",
        "fee_qual_intl": "international, sans bourse",
        "fee_qual_gst": "GST de 9 % incluse",
        "ielts_overall": "total {v}",
        "ielts_each": "minimum {v} dans chaque partie",
        "ielts_component": "{name} {v}",
        "rank_present": "{provider} {edition} : n° {rank}",
        "rank_absent": "{provider} hors du top 100",
        "rank_unavailable": "{provider} : classement non vérifié",
        "comp_reading": "Lecture",
        "comp_writing": "Écriture",
        "comp_listening": "Écoute",
        "comp_speaking": "Expression orale",
    },
    "pt-BR": {
        "level_undergraduate": "Graduação",
        "level_taught_masters": "Mestrado profissional",
        "country_GB": "Reino Unido",
        "country_SG": "Singapura",
        "suggest_within": "{level} · {country}: comece por {program}.",
        "suggest_above": "{level} · {country}: todos os programas verificados estão acima do seu orçamento; o mais barato é {program}.",
        "suggest_none": "{level} · {country}: ainda não há programas verificados nesta área; não sei.",
        "fee_within": "Mensalidade {fee}, dentro do seu orçamento.",
        "fee_above": "Mensalidade {fee}, acima do seu orçamento.",
        "fee_unknown": "Não há valor de mensalidade verificado para este programa.",
        "next": "Próximo passo: inicie a verificação de elegibilidade para confirmar notas e idioma.",
        "ask_fee": "Mensalidade de {program}: {fee}.",
        "ask_ielts": "IELTS de {program}: {fact}.",
        "ask_ielts_unknown": "A página oficial não informa o requisito de inglês de {program}; não sei.",
        "ask_deadline": "Prazo de inscrição de {program}: {deadline}.",
        "ask_deadline_unknown": "Não há prazo verificado para {program} nos dados.",
        "rank_next": "Ainda não há dados verificados de programas para esta universidade; veja a página de rankings.",
        "rank_need_name": "Diga qual universidade; só consulto o top 100 verificado.",
        "ambiguous_programme": "Encontrei dois programas: {names}. Diga se é graduação ou mestrado.",
        "ambiguous_rank": "Encontrei várias universidades: {names}. Diga qual delas.",
        "personal": "Não coleto nomes, telefones nem e-mails; não os envie aqui.",
        "personal_2": "Você pode iniciar a verificação diretamente; não são necessários dados pessoais.",
        "unknown": "Não encontro isso nos dados verificados; não sei.",
        "unknown_2": "Inicie a verificação de elegibilidade para revisar seu perfil regra por regra.",
        "greeting": "Olá, eu sou 小罗盘. Toque em uma pergunta e vamos conferir a rota verificada.",
        "fee_per_year": "{currency} {amount} por ano",
        "fee_total": "{currency} {amount} no total",
        "fee_qual_overseas": "internacional",
        "fee_qual_intl": "internacional, sem bolsa",
        "fee_qual_gst": "GST de 9% incluído",
        "ielts_overall": "total {v}",
        "ielts_each": "mínimo de {v} em cada parte",
        "ielts_component": "{name} {v}",
        "rank_present": "{provider} {edition}: nº {rank}",
        "rank_absent": "{provider} fora do top 100",
        "rank_unavailable": "{provider}: ranking não verificado",
        "comp_reading": "Leitura",
        "comp_writing": "Escrita",
        "comp_listening": "Escuta",
        "comp_speaking": "Fala",
    },
    "ar": {
        "level_undergraduate": "بكالوريوس",
        "level_taught_masters": "ماجستير دراسي",
        "country_GB": "المملكة المتحدة",
        "country_SG": "سنغافورة",
        "suggest_within": "{level} · {country}: ابدأ بـ{program}.",
        "suggest_above": "{level} · {country}: جميع البرامج الموثّقة أعلى من ميزانيتك؛ وأرخصها {program}.",
        "suggest_none": "{level} · {country}: لا يوجد برنامج موثّق في هذا المسار بعد؛ لا أعرف.",
        "fee_within": "الرسوم {fee}، ضمن ميزانيتك.",
        "fee_above": "الرسوم {fee}، أعلى من ميزانيتك.",
        "fee_unknown": "لا يوجد مبلغ رسوم موثّق لهذا البرنامج.",
        "next": "الخطوة التالية: ابدأ فحص الأهلية لتأكيد الدرجات واللغة.",
        "ask_fee": "رسوم {program}: {fee}.",
        "ask_ielts": "آيلتس {program}: {fact}.",
        "ask_ielts_unknown": "الصفحة الرسمية لا تذكر متطلب اللغة الإنجليزية لـ{program}؛ لا أعرف.",
        "ask_deadline": "الموعد النهائي للتقديم لـ{program}: {deadline}.",
        "ask_deadline_unknown": "لا يوجد موعد نهائي موثّق لـ{program} في البيانات.",
        "rank_next": "لا توجد بيانات برامج موثّقة لهذه الجامعة بعد؛ اطّلع على صفحة التصنيف الخاصة بها.",
        "rank_need_name": "أخبرني باسم الجامعة؛ أبحث فقط في أفضل 100 جامعة موثّقة.",
        "ambiguous_programme": "وجدت برنامجين مطابقين: {names}. أخبرني: بكالوريوس أم ماجستير؟",
        "ambiguous_rank": "وجدت عدة جامعات مطابقة: {names}. حدّد أيّها تقصد.",
        "personal": "لا أجمع الأسماء أو أرقام الهواتف أو البريد الإلكتروني؛ لا ترسلها هنا.",
        "personal_2": "يمكنك بدء فحص الأهلية مباشرة؛ لا حاجة لأي بيانات شخصية.",
        "unknown": "لا أجد ذلك في البيانات الموثّقة؛ لا أعرف.",
        "unknown_2": "ابدأ فحص الأهلية لمراجعة ملفك قاعدةً قاعدة.",
        "greeting": "مرحبًا، أنا 小罗盘. اضغط على سؤال وسنراجع معًا المسار الموثّق.",
        "fee_per_year": "{currency} {amount} سنويًا",
        "fee_total": "{currency} {amount} إجمالًا",
        "fee_qual_overseas": "للطلاب الدوليين",
        "fee_qual_intl": "دولي، بدون منحة",
        "fee_qual_gst": "شامل ضريبة 9٪",
        "ielts_overall": "المجموع {v}",
        "ielts_each": "الحد الأدنى {v} في كل جزء",
        "ielts_component": "{name} {v}",
        "rank_present": "{provider} {edition}: المرتبة {rank}",
        "rank_absent": "{provider} خارج أفضل 100",
        "rank_unavailable": "{provider}: التصنيف غير موثّق",
        "comp_reading": "القراءة",
        "comp_writing": "الكتابة",
        "comp_listening": "الاستماع",
        "comp_speaking": "التحدث",
    },
}


def _t(locale: str, key: str) -> str:
    loc = locale if locale in _T else "en"
    return _T[loc].get(key) or _T["en"][key]


def _fmt(key: str, locale: str, **vars) -> str:
    return _t(locale, key).format(**vars)


def _money(amount) -> str:
    """1,234 or 1,234.56 — never a float artefact."""
    if amount is None:
        return ""
    f = float(amount)
    return f"{f:,.2f}" if f != int(f) else f"{int(f):,}"


def _score(value) -> str:
    """An IELTS/TOEFL component score: always one decimal (7.0, 6.5)."""
    return f"{float(value):.1f}"


# ---------------------------------------------------------------------------
# Verified fee figures (backend data shape)
# ---------------------------------------------------------------------------
def program_fee_range(program: dict):
    """(low, high, currency, period, qualifier) from verified fee fields.

    GB: overseas per-year fee. SG UG: international without-grant per-year
    fee (NTU is a range — lab vs non-lab is unverified, so both verified
    figures are kept). SG TM: total incl. GST. Returns None when no
    verified fee figure exists.
    """
    fees = program.get("fees") or {}
    currency = fees.get("currency") or ""
    period = fees.get("period")
    if period == "total":
        total = fees.get("total_sgd_incl_gst")
        if isinstance(total, (int, float)):
            return (total, total, currency, "total", "fee_qual_gst")
        return None
    vals = []
    for key in ("overseas_per_year_gbp",
                "international_without_grant_per_year_sgd",
                "international_without_grant_lab_per_year_sgd",
                "international_without_grant_nonlab_per_year_sgd"):
        v = fees.get(key)
        if isinstance(v, (int, float)):
            vals.append(v)
    if not vals:
        return None
    qual = "fee_qual_overseas" if currency == "GBP" else "fee_qual_intl"
    return (min(vals), max(vals), currency, "per_year", qual)


def fee_text(fee_range, locale: str) -> str:
    low, high, currency, period, qual = fee_range
    if period == "total":
        base = _fmt("fee_total", locale, currency=currency, amount=_money(low))
        return f"{base} ({_t(locale, qual)})"
    if low == high:
        base = _fmt("fee_per_year", locale, currency=currency, amount=_money(low))
    else:
        base = _fmt("fee_per_year", locale, currency=currency,
                    amount=f"{_money(low)}–{_money(high)}")
    return f"{base} ({_t(locale, qual)})"


def fee_fit(fee_range, degree_level: str, country: str, budget_band: str) -> str:
    """within / above / unknown against the band's ceiling.

    Only the ceiling matters for affordability — a cheaper programme is
    always affordable. A fee range that straddles the ceiling is unknown,
    not a guess.
    """
    if fee_range is None:
        return "unknown"
    _low, high, _cur, _per, _q = fee_range
    _lo_bound, ceiling = _BANDS[(degree_level, country)][budget_band]
    if ceiling is None:
        return "within"
    if high <= ceiling:
        return "within"
    if _low > ceiling:
        return "above"
    return "unknown"


def program_display_name(program: dict) -> str:
    return f"{program.get('institution', '')} — {program.get('official_name', '')}"


def program_evidence_url(program: dict) -> str | None:
    sources = program.get("sources") or []
    return sources[0].get("url") if sources else None


# ---------------------------------------------------------------------------
# Suggestion from the 3 answers
# ---------------------------------------------------------------------------
def suggest(degree_level: str, country: str, budget_band: str,
            locale: str = "en") -> dict:
    """The 3-question flow's answer: cheapest verified programme in the
    track/country that fits the budget band, else the cheapest overall
    with an honest 'above your band' line. At most 3 lines."""
    loc = locale if locale in _T else "en"
    level = _t(loc, f"level_{degree_level}")
    # Global scope: only GB/SG have a localised country name in _T.
    # Any other country has no verified programme, so the answer below
    # is the honest "no verified programme" one — fall back to the raw
    # country code for the name instead of raising KeyError.
    country_name = (_T[loc].get(f"country_{country}")
                    or _T["en"].get(f"country_{country}") or country)
    candidates = [p for p in PROGRAMS.values()
                  if p.get("degree_level") == degree_level and p.get("country") == country]
    if not candidates:
        return {"lines": [_fmt("suggest_none", loc, level=level, country=country_name),
                          _t(loc, "unknown_2")],
                "program_id": None, "program_name": None, "evidence_url": None,
                "fee_fit": "unknown", "fee_text": None,
                "ai_status": AI_STATUS, "data_version": DATA_VERSION,
                "next_steps": {"wizard": "/wizard", "program": None}}

    def sort_key(p: dict):
        fr = program_fee_range(p)
        return (fr[0] if fr else float("inf"), p["id"])

    candidates.sort(key=sort_key)
    within = [p for p in candidates
              if fee_fit(program_fee_range(p), degree_level, country, budget_band) == "within"]
    picked = within[0] if within else candidates[0]
    fr = program_fee_range(picked)
    fit = fee_fit(fr, degree_level, country, budget_band)
    name = program_display_name(picked)
    if fit == "within":
        line1 = _fmt("suggest_within", loc, level=level, country=country_name, program=name)
        line2 = _fmt("fee_within", loc, fee=fee_text(fr, loc)) if fr else _t(loc, "fee_unknown")
    elif fit == "above":
        line1 = _fmt("suggest_above", loc, level=level, country=country_name, program=name)
        line2 = _fmt("fee_above", loc, fee=fee_text(fr, loc)) if fr else _t(loc, "fee_unknown")
    else:
        line1 = _fmt("suggest_within", loc, level=level, country=country_name, program=name)
        line2 = _t(loc, "fee_unknown")
    lines = [line1, line2, _t(loc, "next")][:MAX_ANSWER_LINES]
    return {"lines": lines,
            "program_id": picked["id"], "program_name": name,
            "evidence_url": program_evidence_url(picked),
            "fee_fit": fit, "fee_text": fee_text(fr, loc) if fr else None,
            "ai_status": AI_STATUS, "data_version": DATA_VERSION,
            "next_steps": {"wizard": "/wizard", "program": f"/programs/{picked['id']}"}}


# ---------------------------------------------------------------------------
# Free-text questions
# ---------------------------------------------------------------------------
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE_CANDIDATE_RE = re.compile(r"\+?[\d][\d\s().-]{7,}\d")


def contains_personal_data(text: str) -> bool:
    """Email address, or a phone-like run of 10+ digits.

    Years (2027), fees (46,700) and dates (2026-11-25) stay below the
    digit threshold, so ordinary questions are never flagged.
    """
    if _EMAIL_RE.search(text):
        return True
    for cand in _PHONE_CANDIDATE_RE.findall(text):
        if sum(ch.isdigit() for ch in cand) >= 10:
            return True
    return False


# Institution aliases (Chinese + English short names) -> institution id.
# Only ids present in the verified rankings file are listed here.
_INSTITUTION_ALIASES: dict[str, str] = {
    "ucl": "ucl", "伦敦大学学院": "ucl", "university college london": "ucl",
    "imperial": "imperial", "帝国理工": "imperial", "帝国理工大学": "imperial",
    "nus": "nus", "national university of singapore": "nus", "新加坡国立": "nus", "国大": "nus",
    "ntu": "ntu", "nanyang technological university": "ntu", "南洋理工": "ntu",
    "national taiwan university": "national-taiwan-university", "台湾大学": "national-taiwan-university",
    "oxford": "university-of-oxford", "牛津": "university-of-oxford",
    "cambridge": "university-of-cambridge", "剑桥": "university-of-cambridge",
    "mit": "massachusetts-institute-of-technology", "麻省理工": "massachusetts-institute-of-technology",
    "harvard": "harvard-university", "哈佛": "harvard-university",
    "stanford": "stanford-university", "斯坦福": "stanford-university",
    "tsinghua": "tsinghua-university", "清华": "tsinghua-university",
    "peking": "peking-university", "北大": "peking-university", "北京大学": "peking-university",
    "eth": "eth-zurich", "苏黎世联邦理工": "eth-zurich",
    "caltech": "california-institute-of-technology", "加州理工": "california-institute-of-technology",
    "princeton": "princeton-university", "普林斯顿": "princeton-university",
    "yale": "yale-university", "耶鲁": "yale-university",
    "cornell": "cornell-university", "康奈尔": "cornell-university",
    "columbia": "columbia-university", "哥伦比亚": "columbia-university",
    "chicago": "university-of-chicago", "芝加哥": "university-of-chicago",
    "tokyo": "university-of-tokyo", "东京大学": "university-of-tokyo",
    "seoul": "seoul-national-university", "首尔大学": "seoul-national-university",
    "toronto": "university-of-toronto", "多伦多": "university-of-toronto",
    "melbourne": "university-of-melbourne", "墨尔本": "university-of-melbourne",
    "edinburgh": "university-of-edinburgh", "爱丁堡": "university-of-edinburgh",
    "manchester": "university-of-manchester", "曼彻斯特": "university-of-manchester",
    "sydney": "university-of-sydney", "悉尼": "university-of-sydney",
    "kings": "king-s-college-london", "伦敦国王学院": "king-s-college-london",
    "lse": "london-school-of-economics-and-political-science", "伦敦政经": "london-school-of-economics-and-political-science",
    "nyu": "new-york-university", "纽约大学": "new-york-university",
    "duke": "duke-university", "杜克": "duke-university",
    "zhejiang": "zhejiang-university", "浙江大学": "zhejiang-university",
    "fudan": "fudan-university", "复旦": "fudan-university",
    "shanghai jiao tong": "shanghai-jiao-tong-university", "上海交通大学": "shanghai-jiao-tong-university",
    "hong kong university": "university-of-hong-kong", "香港大学": "university-of-hong-kong",
    "kaist": "korea-advanced-institute-of-science-and-technology",
    "tum": "technical-university-of-munich", "慕尼黑工业大学": "technical-university-of-munich",
}

# Programme aliases -> programme id.
_PROGRAM_ALIASES: dict[str, str] = {
    "ucl cs bsc": "ucl-cs-bsc-2026", "ucl bsc": "ucl-cs-bsc-2026",
    "ucl cs msc": "ucl-cs-msc-2027", "ucl msc": "ucl-cs-msc-2027",
    "imperial beng": "imperial-comp-beng-2027", "imperial bsc": "imperial-comp-beng-2027",
    "imperial msc": "imperial-msc-computing-2027",
    "nus mcomp": "nus-mcomp-cs", "nus mcs": "nus-mcomp-cs",
    "nus bcomp": "nus-bcomp-cs-2027", "nus bcomp cs": "nus-bcomp-cs-2027",
    "ntu bcomp": "ntu-bcomp-cs-2027", "ntu bcomp cs": "ntu-bcomp-cs-2027",
    "ntu msai": "ntu-msai-2027", "msai": "ntu-msai-2027",
    "ucl本科": "ucl-cs-bsc-2026", "ucl硕士": "ucl-cs-msc-2027",
    "帝国理工本科": "imperial-comp-beng-2027", "帝国理工硕士": "imperial-msc-computing-2027",
    "nus硕士": "nus-mcomp-cs", "nus本科": "nus-bcomp-cs-2027",
    "ntu本科": "ntu-bcomp-cs-2027", "ntu硕士": "ntu-msai-2027",
    "南洋理工人工智能硕士": "ntu-msai-2027",
}

# Institution keyword -> the programmes of that institution.
_INSTITUTION_PROGRAMMES: dict[str, list[str]] = {
    "ucl": ["ucl-cs-bsc-2026", "ucl-cs-msc-2027"],
    "伦敦大学学院": ["ucl-cs-bsc-2026", "ucl-cs-msc-2027"],
    "imperial": ["imperial-comp-beng-2027", "imperial-msc-computing-2027"],
    "帝国理工": ["imperial-comp-beng-2027", "imperial-msc-computing-2027"],
    "nus": ["nus-mcomp-cs", "nus-bcomp-cs-2027"],
    "新加坡国立": ["nus-mcomp-cs", "nus-bcomp-cs-2027"],
    "国大": ["nus-mcomp-cs", "nus-bcomp-cs-2027"],
    "ntu": ["ntu-bcomp-cs-2027", "ntu-msai-2027"],
    "南洋理工": ["ntu-bcomp-cs-2027", "ntu-msai-2027"],
}

_UG_WORDS = ("本科", "undergrad", "bsc", "beng", "bcomp", "bachelor")
_TM_WORDS = ("硕士", "master", "msc", "mcomp", "msai", "postgrad", "taught")

_RANK_WORDS = ("排名", "rank", "qs", "泰晤士", "软科", "arwu", "第几")
_FEE_WORDS = ("学费", "fee", "tuition", "多少钱", "cost")
_IELTS_WORDS = ("雅思", "ielts", "英语", "english", "语言")
_DEADLINE_WORDS = ("截止", "deadline", "申请时间", "什么时候申请", "什么时候截止")
_GREETING_WORDS = ("你好", "您好", "hello", "hi", "hey", "在吗", "在么", "在不")

_STOPWORDS = {"the", "university", "college", "institute", "of", "school",
              "national", "universitat", "université", "universidad"}


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _institution_by_alias(message: str) -> str | None:
    for alias, inst_id in _INSTITUTION_ALIASES.items():
        if alias in message:
            return inst_id
    return None


def _institutions_by_name_token(message: str) -> list[dict]:
    """Generic fallback: a distinctive word of the official name appears
    in the message (e.g. 'toronto' -> University of Toronto)."""
    found: list[dict] = []
    for inst in RANKINGS.get("institutions", []):
        name = inst.get("official_name", "").lower()
        words = {w.strip("-,.'") for w in re.split(r"[\s\-]+", name)}
        distinctive = {w for w in words if len(w) >= 4 and w not in _STOPWORDS}
        if any(w in message for w in distinctive):
            found.append(inst)
    return found


def _rank_lines(inst: dict, locale: str) -> tuple[list[str], str | None]:
    """One line with the verified ranks per provider (absent provider =
    'not in the top 100', which the data itself establishes)."""
    entries = {e["provider"]: e for e in RANKINGS.get("entries", [])
               if e.get("institution_id") == inst["id"]}
    parts = []
    for provider, label in (("qs", "QS"), ("the", "THE"), ("arwu", "ARWU")):
        entry = entries.get(provider)
        if entry and entry.get("verification_status") == "verified":
            parts.append(_fmt("rank_present", locale, provider=label,
                              edition=entry.get("edition_label", ""),
                              rank=entry.get("rank_display", "")))
        elif entry:
            # An entry exists but its rank could not be verified: say so,
            # never "not in the top 100" (that is only true when no entry
            # exists at all for this provider).
            parts.append(_fmt("rank_unavailable", locale, provider=label))
        else:
            parts.append(_fmt("rank_absent", locale, provider=label))
    profiles = inst.get("provider_profiles") or {}
    evidence = profiles.get("qs") or profiles.get("the") or profiles.get("arwu")
    if not evidence:
        for e in entries.values():
            evidence = e.get("source_url")
            if evidence:
                break
    return [f"{inst.get('official_name', '')}: {' · '.join(parts)}.",
            _t(locale, "rank_next")], evidence


def _match_programmes(message: str) -> list[str]:
    """Programme ids the message refers to (0, 1 or 2)."""
    for alias, pid in _PROGRAM_ALIASES.items():
        if alias in message:
            return [pid]
    for keyword, pids in _INSTITUTION_PROGRAMMES.items():
        if keyword in message:
            level = None
            if any(w in message for w in _UG_WORDS):
                level = "undergraduate"
            elif any(w in message for w in _TM_WORDS):
                level = "taught_masters"
            if level is None:
                return list(pids)
            matched = [pid for pid in pids
                       if PROGRAMS[pid].get("degree_level") == level]
            return matched or list(pids)
    return []


def _ielts_fact(program: dict, locale: str) -> str | None:
    """'overall 6.5, minimum 6.0 in each component' from the verified
    language threshold — or None when the official page states no
    requirement (UCL MSc). The compiled IELTS reference is never used."""
    for req in program.get("requirements", []):
        if req.get("category") != "language":
            continue
        desc = req.get("description", "")
        if desc.startswith("UNKNOWN"):
            return None
        th = req.get("threshold") or {}
        overall = th.get("overall", th.get("ielts_overall"))
        if overall is None:
            continue
        parts = [_fmt("ielts_overall", locale, v=_score(overall))]
        each = th.get("each_component")
        if each is not None:
            parts.append(_fmt("ielts_each", locale, v=_score(each)))
        for key, tkey in (("ielts_reading", "comp_reading"),
                          ("ielts_writing", "comp_writing"),
                          ("ielts_listening", "comp_listening"),
                          ("ielts_speaking", "comp_speaking")):
            if th.get(key) is not None:
                parts.append(_fmt("ielts_component", locale,
                                  name=_t(locale, tkey), v=_score(th[key])))
        return ", ".join(parts)
    return None


def _ask_result(lines: list[str], locale: str, program_id: str | None = None,
                institution_id: str | None = None,
                evidence_url: str | None = None) -> dict:
    program = PROGRAMS.get(program_id) if program_id else None
    return {"lines": lines[:MAX_ANSWER_LINES],
            "program_id": program_id,
            "program_name": program_display_name(program) if program else None,
            "institution_id": institution_id,
            "evidence_url": evidence_url,
            "ai_status": AI_STATUS, "data_version": DATA_VERSION,
            "next_steps": {"wizard": "/wizard",
                           "program": f"/programs/{program_id}" if program_id else None,
                           "institution": f"/institutions/{institution_id}" if institution_id else None}}


def ask(message: str, locale: str = "en") -> dict:
    """Free-text question, answered only from verified data.

    Order: personal-data guard -> greeting -> rank lookup -> programme
    facts (fee / IELTS / deadline) -> unknown. Nothing is stored.
    """
    loc = locale if locale in _T else "en"
    msg = _norm(message or "")

    if contains_personal_data(message or ""):
        return _ask_result([_t(loc, "personal"), _t(loc, "personal_2")], loc)

    if msg and len(msg) <= 12 and any(w in msg for w in _GREETING_WORDS):
        return _ask_result([_t(loc, "greeting")], loc)

    if any(w in msg for w in _RANK_WORDS):
        inst_id = _institution_by_alias(msg)
        inst = None
        if inst_id:
            inst = next((i for i in RANKINGS.get("institutions", [])
                         if i["id"] == inst_id), None)
        candidates = [inst] if inst else _institutions_by_name_token(msg)
        if len(candidates) == 1 and candidates[0] is not None:
            lines, evidence = _rank_lines(candidates[0], loc)
            return _ask_result(lines, loc, institution_id=candidates[0]["id"],
                               evidence_url=evidence)
        if len(candidates) > 1:
            names = "、".join(i.get("official_name", "") for i in candidates[:3])
            return _ask_result([_fmt("ambiguous_rank", loc, names=names)], loc)
        return _ask_result([_t(loc, "rank_need_name"), _t(loc, "unknown_2")], loc)

    fact = None
    if any(w in msg for w in _FEE_WORDS):
        fact = "fee"
    elif any(w in msg for w in _IELTS_WORDS):
        fact = "ielts"
    elif any(w in msg for w in _DEADLINE_WORDS):
        fact = "deadline"
    if fact:
        pids = _match_programmes(msg)
        if len(pids) == 1:
            program = PROGRAMS[pids[0]]
            name = program_display_name(program)
            if fact == "fee":
                fr = program_fee_range(program)
                if fr is None:
                    return _ask_result([_t(loc, "fee_unknown"), _t(loc, "unknown_2")],
                                       loc, program_id=pids[0],
                                       evidence_url=program_evidence_url(program))
                return _ask_result([_fmt("ask_fee", loc, program=name, fee=fee_text(fr, loc)),
                                    _t(loc, "next")],
                                   loc, program_id=pids[0],
                                   evidence_url=program_evidence_url(program))
            if fact == "ielts":
                ielts = _ielts_fact(program, loc)
                if ielts is None:
                    return _ask_result([_fmt("ask_ielts_unknown", loc, program=name),
                                        _t(loc, "unknown_2")],
                                       loc, program_id=pids[0],
                                       evidence_url=program_evidence_url(program))
                return _ask_result([_fmt("ask_ielts", loc, program=name, fact=ielts),
                                    _t(loc, "next")],
                                   loc, program_id=pids[0],
                                   evidence_url=program_evidence_url(program))
            deadline = program.get("application_deadline")
            if not deadline:
                return _ask_result([_fmt("ask_deadline_unknown", loc, program=name),
                                    _t(loc, "unknown_2")],
                                   loc, program_id=pids[0],
                                   evidence_url=program_evidence_url(program))
            return _ask_result([_fmt("ask_deadline", loc, program=name, deadline=deadline),
                                _t(loc, "next")],
                               loc, program_id=pids[0],
                               evidence_url=program_evidence_url(program))
        if len(pids) > 1:
            names = "、".join(program_display_name(PROGRAMS[pid]) for pid in pids)
            return _ask_result([_fmt("ambiguous_programme", loc, names=names)], loc)

    return _ask_result([_t(loc, "unknown"), _t(loc, "unknown_2")], loc)


# Words that must never appear in any pet answer (probabilities, guarantees).
# NOTE: a bare "%" is NOT in this list — the verified fee fact "9% GST"
# legitimately contains one. The test pins that "%" appears only there.
FORBIDDEN_WORDS = ("概率", "probability", "likely", "chance",
                   "guarantee", "保证", "一定能", "肯定能", "录取率",
                   "admission rate", "will get in", "包录")


def check_no_forbidden(lines: list[str]) -> list[str]:
    """Test helper: returns the forbidden words found in the lines."""
    joined = "\n".join(lines).lower()
    return [w for w in FORBIDDEN_WORDS if w.lower() in joined]

"""小罗盘 (Little Compass) — the PathPilot desktop-pet assistant (Day 3).

Rules/template mode ONLY. No AI model is connected (``ai_status`` is
always ``"unavailable"``) and no model is ever claimed to be answering.
Every fact comes from the verified local catalogue:

- the 8 programmes in ``data/versions/v2/programs.json`` (official pages
  only — fees, IELTS thresholds, deadlines), plus the expansion
  catalogue (``data/expansions/expansion.json`` — 886 programmes, 593
  of them matchable), and
- the 300 ranking entries in ``data/versions/v2/rankings.json``
  (QS 2027 / THE 2027 / ARWU 2026, top 100 each).

Round 9: the pet's retrieval covers the FULL catalogue, all countries
— never GB/SG only. A country question is answered from that
country's own verified programmes/institutions; only a country with
no verified programme at all gets the honest "no verified programme"
answer.

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

from app.data import (DATA_VERSION, EXPANSION_INSTITUTIONS,
                      EXPANSION_MATCHABLE, EXPANSION_PROGRAMS, PROGRAMS,
                      RANKINGS)

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
        "country_CH": "Switzerland",
        "country_FR": "France",
        "country_DE": "Germany",
        "country_US": "United States",
        "suggest_within": "{level} · {country}: start with {program}.",
        "suggest_above": "{level} · {country}: every verified programme here is above your budget band; the cheapest is {program}.",
        "suggest_none": "{level} · {country}: no verified programme in this track yet, so I don't know.",
        "country_list": "{country} verified institutions: {names} — {n} verified programmes in total (all levels and fields).",
        "fee_within": "Tuition {fee} — inside your budget band.",
        "fee_above": "Tuition {fee} — above your budget band.",
        "fee_unknown": "No verified tuition figure for this programme in the data.",
        "fee_plain": "Tuition {fee}.",
        "next": "Next step: start the eligibility check to confirm grades and language.",
        "ask_fee": "{program} tuition: {fee}.",
        "ask_ielts": "{program} IELTS: {fact}.",
        "ask_ielts_unknown": "The official page does not state the English requirement for {program}, so I don't know.",
        "ask_deadline": "{program} application deadline: {deadline}.",
        "ask_deadline_unknown": "No verified application deadline for {program} in the data.",
        "rank_next": "No verified programme data for this institution yet — see its ranking detail page.",
        "rank_need_name": "Tell me which institution — I only look up the verified top 100.",
        "ambiguous_programme": "I found {count} matching programmes: {names}. Tell me undergraduate or masters.",
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
        "country_CH": "瑞士",
        "country_FR": "法国",
        "country_DE": "德国",
        "country_US": "美国",
        "suggest_within": "{level} · {country}：先看 {program}。",
        "suggest_above": "{level} · {country}：已核实的专业都在你的预算带之上，最便宜的是 {program}。",
        "suggest_none": "{level} · {country}：已核实的目录里还没有这个方向的专业，我不知道。",
        "country_list": "{country}已核实的学校：{names}，共 {n} 个已验证项目（全部学位/方向）。",
        "fee_within": "学费 {fee}，在你的预算带内。",
        "fee_above": "学费 {fee}，高于你的预算带。",
        "fee_unknown": "这个专业的学费在已核实的数据里查不到。",
        "fee_plain": "学费 {fee}。",
        "next": "下一步：开始资格检查，确认成绩和语言是否达标。",
        "ask_fee": "{program} 学费：{fee}。",
        "ask_ielts": "{program} 雅思要求：{fact}。",
        "ask_ielts_unknown": "{program} 的英语要求在官网页面上没有说明，我不知道。",
        "ask_deadline": "{program} 申请截止：{deadline}。",
        "ask_deadline_unknown": "{program} 的申请截止日期在已核实的数据里查不到。",
        "rank_next": "这所学校还没有已核实的专业数据，先看它的排名详情页。",
        "rank_need_name": "请告诉我是哪所学校，我只查已核实的前 100 名。",
        "ambiguous_programme": "我找到 {count} 个相关专业：{names}。请告诉我是本科还是硕士。",
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
        "country_CH": "Suiza",
        "country_FR": "Francia",
        "country_DE": "Alemania",
        "country_US": "Estados Unidos",
        "suggest_within": "{level} · {country}: empieza por {program}.",
        "suggest_above": "{level} · {country}: todos los programas verificados superan tu presupuesto; el más barato es {program}.",
        "suggest_none": "{level} · {country}: aún no hay programas verificados en esta vía; no lo sé.",
        "country_list": "Instituciones verificadas en {country}: {names} — {n} programas verificados en total (todos los niveles y campos).",
        "fee_within": "Matrícula {fee}, dentro de tu presupuesto.",
        "fee_above": "Matrícula {fee}, por encima de tu presupuesto.",
        "fee_unknown": "No hay una cifra de matrícula verificada para este programa.",
        "fee_plain": "Matrícula {fee}.",
        "next": "Siguiente paso: inicia la comprobación de requisitos para confirmar notas e idioma.",
        "ask_fee": "Matrícula de {program}: {fee}.",
        "ask_ielts": "IELTS de {program}: {fact}.",
        "ask_ielts_unknown": "La página oficial no indica el requisito de inglés de {program}; no lo sé.",
        "ask_deadline": "Plazo de solicitud de {program}: {deadline}.",
        "ask_deadline_unknown": "No hay un plazo verificado para {program} en los datos.",
        "rank_next": "Aún no hay datos verificados de programas para esta universidad; consulta su página de rankings.",
        "rank_need_name": "Dime qué universidad; solo consulto el top 100 verificado.",
        "ambiguous_programme": "Encontré {count} programas: {names}. Dime si es grado o máster.",
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
        "country_CH": "Suisse",
        "country_FR": "France",
        "country_DE": "Allemagne",
        "country_US": "États-Unis",
        "suggest_within": "{level} · {country} : commencez par {program}.",
        "suggest_above": "{level} · {country} : tous les programmes vérifiés dépassent votre budget ; le moins cher est {program}.",
        "suggest_none": "{level} · {country} : aucun programme vérifié dans cette voie pour l'instant ; je ne sais pas.",
        "country_list": "Établissements vérifiés en {country} : {names} — {n} programmes vérifiés au total (tous niveaux et domaines).",
        "fee_within": "Frais {fee}, dans votre budget.",
        "fee_above": "Frais {fee}, au-dessus de votre budget.",
        "fee_unknown": "Aucun montant de frais vérifié pour ce programme.",
        "fee_plain": "Frais {fee}.",
        "next": "Étape suivante : lancez la vérification d'éligibilité pour confirmer notes et langue.",
        "ask_fee": "Frais de {program} : {fee}.",
        "ask_ielts": "IELTS de {program} : {fact}.",
        "ask_ielts_unknown": "La page officielle n'indique pas le niveau d'anglais requis pour {program} ; je ne sais pas.",
        "ask_deadline": "Date limite de candidature pour {program} : {deadline}.",
        "ask_deadline_unknown": "Aucune date limite vérifiée pour {program} dans les données.",
        "rank_next": "Pas encore de données de programme vérifiées pour cette université ; voir sa page de classement.",
        "rank_need_name": "Dites-moi quelle université ; je ne consulte que le top 100 vérifié.",
        "ambiguous_programme": "J'ai trouvé {count} programmes : {names}. Dites-moi licence ou master.",
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
        "country_CH": "Suíça",
        "country_FR": "França",
        "country_DE": "Alemanha",
        "country_US": "Estados Unidos",
        "suggest_within": "{level} · {country}: comece por {program}.",
        "suggest_above": "{level} · {country}: todos os programas verificados estão acima do seu orçamento; o mais barato é {program}.",
        "suggest_none": "{level} · {country}: ainda não há programas verificados nesta área; não sei.",
        "country_list": "Instituições verificadas em {country}: {names} — {n} programas verificados no total (todos os níveis e áreas).",
        "fee_within": "Mensalidade {fee}, dentro do seu orçamento.",
        "fee_above": "Mensalidade {fee}, acima do seu orçamento.",
        "fee_unknown": "Não há valor de mensalidade verificado para este programa.",
        "fee_plain": "Mensalidade {fee}.",
        "next": "Próximo passo: inicie a verificação de elegibilidade para confirmar notas e idioma.",
        "ask_fee": "Mensalidade de {program}: {fee}.",
        "ask_ielts": "IELTS de {program}: {fact}.",
        "ask_ielts_unknown": "A página oficial não informa o requisito de inglês de {program}; não sei.",
        "ask_deadline": "Prazo de inscrição de {program}: {deadline}.",
        "ask_deadline_unknown": "Não há prazo verificado para {program} nos dados.",
        "rank_next": "Ainda não há dados verificados de programas para esta universidade; veja a página de rankings.",
        "rank_need_name": "Diga qual universidade; só consulto o top 100 verificado.",
        "ambiguous_programme": "Encontrei {count} programas: {names}. Diga se é graduação ou mestrado.",
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
        "country_CH": "سويسرا",
        "country_FR": "فرنسا",
        "country_DE": "ألمانيا",
        "country_US": "الولايات المتحدة",
        "suggest_within": "{level} · {country}: ابدأ بـ{program}.",
        "suggest_above": "{level} · {country}: جميع البرامج الموثّقة أعلى من ميزانيتك؛ وأرخصها {program}.",
        "suggest_none": "{level} · {country}: لا يوجد برنامج موثّق في هذا المسار بعد؛ لا أعرف.",
        "country_list": "المؤسسات الموثّقة في {country}: {names} — {n} برنامجًا موثّقًا في المجموع (جميع المستويات والمجالات).",
        "fee_within": "الرسوم {fee}، ضمن ميزانيتك.",
        "fee_above": "الرسوم {fee}، أعلى من ميزانيتك.",
        "fee_unknown": "لا يوجد مبلغ رسوم موثّق لهذا البرنامج.",
        "fee_plain": "الرسوم {fee}.",
        "next": "الخطوة التالية: ابدأ فحص الأهلية لتأكيد الدرجات واللغة.",
        "ask_fee": "رسوم {program}: {fee}.",
        "ask_ielts": "آيلتس {program}: {fact}.",
        "ask_ielts_unknown": "الصفحة الرسمية لا تذكر متطلب اللغة الإنجليزية لـ{program}؛ لا أعرف.",
        "ask_deadline": "الموعد النهائي للتقديم لـ{program}: {deadline}.",
        "ask_deadline_unknown": "لا يوجد موعد نهائي موثّق لـ{program} في البيانات.",
        "rank_next": "لا توجد بيانات برامج موثّقة لهذه الجامعة بعد؛ اطّلع على صفحة التصنيف الخاصة بها.",
        "rank_need_name": "أخبرني باسم الجامعة؛ أبحث فقط في أفضل 100 جامعة موثّقة.",
        "ambiguous_programme": "وجدت {count} برامج مطابقة: {names}. أخبرني: بكالوريوس أم ماجستير؟",
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

    Expansion (round 6): the programme's own fees.amount for its stated
    period; qualifier None (no GB-overseas / SG-international wording
    applies — fee_text renders no parenthetical then).
    """
    if program.get("id") in EXPANSION_MATCHABLE:
        fees = program.get("fees") or {}
        amount = fees.get("amount")
        # per_credit has no credit count in any profile, so there is no
        # comparable fee figure — unknown, never rendered as per-year.
        if fees.get("period") == "per_credit":
            return None
        if isinstance(amount, (int, float)) and not isinstance(amount, bool):
            return (amount, amount, fees.get("currency") or "",
                    fees.get("period") or "per_year", None)
        return None
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
    elif low == high:
        base = _fmt("fee_per_year", locale, currency=currency, amount=_money(low))
    else:
        base = _fmt("fee_per_year", locale, currency=currency,
                    amount=f"{_money(low)}–{_money(high)}")
    if qual is None:
        return base
    return f"{base} ({_t(locale, qual)})"


def fee_fit(fee_range, degree_level: str, country: str, budget_band: str) -> str:
    """within / above / unknown against the band's ceiling.

    Only the ceiling matters for affordability — a cheaper programme is
    always affordable. A fee range that straddles the ceiling is unknown,
    not a guess. Budget bands are defined only for GB/SG (the guided
    flow's countries); any other country has no band, so the fit is
    unknown — never a KeyError, never an invented band.
    """
    if fee_range is None:
        return "unknown"
    if (degree_level, country) not in _BANDS:
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


def _lookup_program(program_id: str) -> dict | None:
    """v2 programme or promoted expansion programme (round 6)."""
    return PROGRAMS.get(program_id) or EXPANSION_MATCHABLE.get(program_id)


def program_display_name(program: dict) -> str:
    return f"{program.get('institution', '')} — {program.get('official_name', '')}"


def program_evidence_url(program: dict) -> str | None:
    sources = program.get("sources") or []
    return sources[0].get("url") if sources else None


def country_display_name(code: str, locale: str = "en") -> str:
    """Localised country name for a country code: the template table
    first (GB/SG/CH/FR/DE/US), else the official country_name from the
    verified rankings data (English), else the raw code — never a
    guessed translation."""
    loc = locale if locale in _T else "en"
    name = (_T[loc].get(f"country_{code}") or _T["en"].get(f"country_{code}"))
    if name:
        return name
    for inst in RANKINGS.get("institutions", []):
        if inst.get("country") == code and inst.get("country_name"):
            return inst["country_name"]
    return code


def _qs_rank(institution_id: str) -> int | None:
    """QS 2027 rank number for an institution, or None (no verified
    QS entry). rank_display may be a tie ("=8")."""
    for entry in RANKINGS.get("entries", []):
        if (entry.get("institution_id") == institution_id
                and entry.get("provider") == "qs"
                and entry.get("verification_status") == "verified"):
            raw = str(entry.get("rank_display", "")).lstrip("=").strip()
            try:
                return int(raw)
            except ValueError:
                return None
    return None


def country_programmes(country: str) -> list[dict]:
    """Every verified programme in a country (v2 + all expansion
    programmes, matchable or display-only), by id. A country with no
    verified programme yields [] — never a guess."""
    pool = [p for p in list(PROGRAMS.values())
            + list(EXPANSION_PROGRAMS.values())
            if p.get("country") == country]
    return sorted(pool, key=lambda p: p["id"])


def country_institutions(country: str) -> list[tuple[str, str]]:
    """(institution_id, official_name) with verified programmes in the
    country, best QS rank first (no QS entry sorts last), then name.
    Deterministic; institutions with no programme never appear."""
    seen: dict[str, str] = {}
    for p in country_programmes(country):
        iid = p.get("institution_id")
        if iid and iid not in seen:
            seen[iid] = p.get("institution", "") or iid
    # v2 programmes carry no institution_id; resolve via the mapping.
    from app.data import V2_PROGRAM_INSTITUTION
    for p in country_programmes(country):
        if not p.get("institution_id") and p["id"] in V2_PROGRAM_INSTITUTION:
            iid = V2_PROGRAM_INSTITUTION[p["id"]]
            if iid not in seen:
                seen[iid] = p.get("institution", "") or iid
    return sorted(seen.items(),
                  key=lambda kv: (_qs_rank(kv[0]) if _qs_rank(kv[0]) is not None
                                  else 10 ** 9, kv[1]))


def country_answer(country: str, locale: str = "en") -> dict | None:
    """Template answer to 'which good schools are in <country>?':
    the country's top verified institutions (at most 3, best QS rank
    first) and its total verified programme count — scoped as ALL
    levels/fields, so the count can never contradict a filtered
    (e.g. undergraduate-computing) count elsewhere. Returns None when
    the country has no verified programme at all."""
    loc = locale if locale in _T else "en"
    programmes = country_programmes(country)
    if not programmes:
        return None
    institutions = country_institutions(country)
    sep = "、" if loc == "zh-CN" else ", "
    names = sep.join(name for _iid, name in institutions[:3])
    country_name = country_display_name(country, loc)
    line1 = _fmt("country_list", loc, country=country_name, names=names,
                 n=len(programmes))
    # Evidence programme: the top institution's first undergraduate
    # programme (then first by id) — e.g. ETH Zurich's CS BSc for CH.
    top_id = institutions[0][0] if institutions else None
    own = [p for p in programmes if p.get("institution_id") == top_id]
    if not own:
        from app.data import V2_PROGRAM_INSTITUTION
        own = [p for p in programmes
               if V2_PROGRAM_INSTITUTION.get(p["id"]) == top_id]
    own.sort(key=lambda p: (0 if p.get("degree_level") == "undergraduate" else 1,
                            p["id"]))
    picked = own[0] if own else programmes[0]
    return {"lines": [line1, _t(loc, "next")],
            "program_id": picked["id"],
            "program_name": program_display_name(picked),
            "institution_id": top_id,
            "evidence_url": program_evidence_url(picked),
            "ai_status": AI_STATUS, "data_version": DATA_VERSION,
            "next_steps": {"wizard": "/wizard",
                           "program": f"/programs/{picked['id']}",
                           "institution": (f"/institutions/{top_id}"
                                           if top_id else None)}}


# ---------------------------------------------------------------------------
# Suggestion from the 3 answers
# ---------------------------------------------------------------------------
def suggest(degree_level: str, country: str, budget_band: str,
            locale: str = "en") -> dict:
    """The 3-question flow's answer: cheapest verified programme in the
    track/country that fits the budget band, else the cheapest overall
    with an honest 'above your band' line. At most 3 lines.

    Round 9: the candidate pool is the FULL verified catalogue (v2 +
    matchable expansion programmes) for countries the v2 set does not
    cover at all (CH/FR/DE/US/...) — those previously got a false
    "no verified programme" answer. GB/SG keep the curated v2 pool
    exactly: the flow names no field, so a cheapest-overall pick
    across the expansion catalogue would surface an irrelevant
    cheapest programme (e.g. a Marketing BA) instead of the CS route
    the flow was built around. GB/SG keep their budget-band logic
    exactly; other countries have no band, so the cheapest programme
    is named with its plain fee line (``fee_fit`` "unknown"), never a
    band claim."""
    loc = locale if locale in _T else "en"
    level = _t(loc, f"level_{degree_level}")
    country_name = country_display_name(country, loc)
    pool = (list(PROGRAMS.values()) if country in ("GB", "SG")
            else list(PROGRAMS.values()) + list(EXPANSION_MATCHABLE.values()))
    candidates = [p for p in pool
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
    if (degree_level, country) not in _BANDS:
        picked = candidates[0]
        fr = program_fee_range(picked)
        name = program_display_name(picked)
        line1 = _fmt("suggest_within", loc, level=level, country=country_name, program=name)
        line2 = _fmt("fee_plain", loc, fee=fee_text(fr, loc)) if fr else _t(loc, "fee_unknown")
        lines = [line1, line2, _t(loc, "next")][:MAX_ANSWER_LINES]
        return {"lines": lines,
                "program_id": picked["id"], "program_name": name,
                "evidence_url": program_evidence_url(picked),
                "fee_fit": "unknown", "fee_text": fee_text(fr, loc) if fr else None,
                "ai_status": AI_STATUS, "data_version": DATA_VERSION,
                "next_steps": {"wizard": "/wizard", "program": f"/programs/{picked['id']}"}}
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

    Years (2027), fees (48,600) and dates (2026-11-25) stay below the
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
    "epfl": "ecole-polytechnique-federale-de-lausanne",
    "洛桑联邦理工": "ecole-polytechnique-federale-de-lausanne",
    "洛桑联邦理工学院": "ecole-polytechnique-federale-de-lausanne",
    "university of zurich": "university-of-zurich",
    "苏黎世大学": "university-of-zurich",
    "university of basel": "university-of-basel",
    "巴塞尔大学": "university-of-basel",
    "university of geneva": "university-of-geneva",
    "日内瓦大学": "university-of-geneva",
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

_UG_WORDS = ("本科", "学士", "undergrad", "bsc", "beng", "bcomp", "bachelor")
_TM_WORDS = ("硕士", "master", "msc", "mcomp", "msai", "postgrad", "taught")

# Wizard tracks (Round 22, W2): the profile track a chat question is
# asked under. An undergraduate profile must NEVER match an MSc
# programme, and vice versa — the matcher filters by it.
_TRACKS = ("undergraduate", "taught_masters")

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


# Chinese country names -> ISO code (the rankings data supplies the
# official English country_name per institution; see _detect_country).
_COUNTRY_ZH_ALIASES: dict[str, str] = {
    "瑞士": "CH", "法国": "FR", "德国": "DE", "美国": "US",
    "英国": "GB", "新加坡": "SG", "澳大利亚": "AU", "加拿大": "CA",
    "日本": "JP", "韩国": "KR", "荷兰": "NL", "中国": "CN",
    "香港": "HK", "爱尔兰": "IE", "意大利": "IT", "西班牙": "ES",
    "瑞典": "SE", "丹麦": "DK", "新西兰": "NZ", "马来西亚": "MY",
    "台湾": "TW", "挪威": "NO", "比利时": "BE", "奥地利": "AT",
    "以色列": "IL", "沙特": "SA", "阿根廷": "AR",
}


# Question markers for the country branch in ask(): a country
# question ("瑞士有哪些好学校？") is answered from that country's
# own data, but a mere mention ("我想去瑞士，因为那边环境优美")
# is a preference statement, not a question — it must keep the
# template unknown so the pref-chat flow's own retrieval (climate
# cities) stays exactly as pinned.
_COUNTRY_QUESTION_WORDS = ("哪些", "哪", "什么", "怎么", "如何", "推荐",
                           "建议", "？", "?", "which", "what", "best",
                           "recommend", "suggest")
_SUGGEST_WORDS_ASK = ("推荐", "建议", "recommend", "suggest")


def _looks_like_suggestion(message: str) -> bool:
    """A recommendation request (suggest word + degree-level word):
    the guided flow's constructed message, or "Recommend an
    undergraduate programme in Switzerland". Those are answered by
    the suggestion pick, never by the country list."""
    msg = _norm(message or "")
    if not any(w in msg for w in _SUGGEST_WORDS_ASK):
        return False
    return any(w in msg for w in _UG_WORDS + _TM_WORDS)


def _detect_country(message: str) -> str | None:
    """Country code from a message: official English country names
    from the verified rankings data, plus the Chinese aliases above.
    Short names match on word boundaries only, so "us" never fires
    inside another word."""
    msg = _norm(message or "")
    names: dict[str, str] = dict(_COUNTRY_ZH_ALIASES)
    for inst in RANKINGS.get("institutions", []):
        name = (inst.get("country_name") or "").strip().lower()
        code = inst.get("country")
        if name and code and name not in names:
            names[name] = code
    for alias, code in sorted(names.items(), key=lambda kv: -len(kv[0])):
        if len(alias) <= 3:
            if re.search(r"(?<![a-z])" + re.escape(alias) + r"(?![a-z])", msg):
                return code
        elif alias in msg:
            return code
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


def _filter_by_track(pids: list[str], track) -> list[str]:
    """Candidates restricted to the wizard track, or unchanged when no
    (valid) track is given. An explicitly named programme in the other
    track filters to [] — never a cross-track match."""
    if track not in _TRACKS:
        return list(pids)
    return [pid for pid in pids
            if (_lookup_program(pid) or {}).get("degree_level") == track]


def _degree_name_strings(program: dict) -> list[str]:
    """Verified degree-name strings for a programme, lowercased: the
    official English name plus every localised name (``name_localized``,
    e.g. zh-CN "计算机科学理学学士"). These are the names the cards
    actually show, so a user typing the card's Chinese name must match
    here — the old matcher only knew English tokens."""
    out: list[str] = []
    official = (program.get("official_name") or "").strip()
    if official:
        out.append(official.lower())
    for value in (program.get("name_localized") or {}).values():
        if isinstance(value, str) and value.strip():
            out.append(value.strip().lower())
    return out


def _institution_strings(program: dict) -> list[str]:
    """Institution name strings for a programme, lowercased: the
    programme's own institution name, the rankings entry's Chinese
    name (``name_zh``), and every alias key that maps to the
    institution — so "ETH Zurich", "eth" and "苏黎世联邦理工" all
    identify the same institution."""
    out: list[str] = []
    inst = (program.get("institution") or "").strip()
    if inst:
        out.append(inst.lower())
    from app.data import V2_PROGRAM_INSTITUTION
    iid = program.get("institution_id") or V2_PROGRAM_INSTITUTION.get(
        program.get("id", ""))
    if iid:
        for inst_entry in RANKINGS.get("institutions", []):
            if inst_entry.get("id") == iid:
                name_zh = (inst_entry.get("name_zh") or "").strip()
                if name_zh:
                    out.append(name_zh.lower())
                break
        for alias, alias_iid in _INSTITUTION_ALIASES.items():
            if alias_iid == iid and alias not in out:
                out.append(alias)
    return out


def _program_institution_id(program: dict | None) -> str | None:
    """Institution id for a verified programme (v2 programmes carry
    none — resolve via the mapping)."""
    if program is None:
        return None
    from app.data import V2_PROGRAM_INSTITUTION
    return (program.get("institution_id")
            or V2_PROGRAM_INSTITUTION.get(program.get("id", "")))


def _institution_strings_for(inst_id: str) -> set[str]:
    """Every name string that identifies an institution: its alias
    keys, its rankings official name and its Chinese name."""
    out: set[str] = set()
    for alias, iid in _INSTITUTION_ALIASES.items():
        if iid == inst_id:
            out.add(alias)
    for inst in RANKINGS.get("institutions", []):
        if inst.get("id") == inst_id:
            for key in ("official_name", "name_zh"):
                name = (inst.get(key) or "").strip().lower()
                if name:
                    out.add(name)
    return out


# Words that carry no degree meaning, stripped when extracting the
# degree phrase a question names ("what is the tuition fee for ..."
# leaves "computer science"; "…计算机本科的学费是多少？" leaves
# "计算机"). Degree words themselves — science, computer, data,
# engineering — are never in this list.
_DEGREE_PHRASE_STRIP_WORDS = frozenset(
    _FEE_WORDS + _IELTS_WORDS + _DEADLINE_WORDS + _RANK_WORDS
    + _UG_WORDS + _TM_WORDS + (
        "undergraduate", "undergraduates", "masters", "postgraduate",
        "postgraduates", "graduate", "graduates",
        # Round 23 (W5): "What are Oxford's tuition fees?" left the
        # phrase "are fees" — "fees" is the plural of a fee word and
        # "are" is filler — so a bare institution+fee question
        # matched no programme at all. Filler verbs / pronouns and
        # plural fee words carry no degree meaning either.
        "are", "were", "was", "been", "be", "am", "have", "has", "had",
        "will", "would", "can", "could", "should", "may", "might",
        "i", "you", "we", "they", "it", "its", "this", "that",
        "these", "those", "there", "here", "want", "wants", "know",
        "like", "need", "get", "find", "show", "list", "give",
        "what", "is", "the", "for", "of", "in", "and", "how", "much",
        "does", "do", "tell", "me", "about", "please", "a", "an", "to",
        "which", "programme", "program", "programmes", "programs",
        "course", "courses", "degree", "school", "university",
        "college", "institute", "qué", "cuál", "cuánto", "cuesta",
        "el", "la", "los", "las", "de", "un", "una", "quel", "quelle",
        "combien", "le", "les", "des", "du", "une", "quanto", "custa",
        "o", "a", "os", "as", "do", "da", "um", "uma", "كم", "ما",
        "هو", "هي",
    ))
_DEGREE_PHRASE_STRIP_SUBSTRINGS = (
    "学费", "雅思", "要求", "申请", "截止", "什么时候", "费用", "多少钱",
    "告诉", "请问", "本科", "硕士", "学士", "大学", "学院", "学校",
    "的", "是", "吗", "多少", "什么", "哪个", "哪一", "怎么", "如何",
)


def _degree_phrase(message: str, inst_id: str) -> str | None:
    """The degree phrase a question names, after removing the
    institution's own name strings and every non-degree word — or
    None when the question names no degree at all ("What is the fee
    for ETH Zurich?"). Latin tokens are dropped word by word; CJK
    runs are stripped of level / fee / particle substrings, so
    "计算机本科的学费" becomes "计算机"."""
    msg = _norm(message or "")
    for s in sorted(_institution_strings_for(inst_id),
                    key=len, reverse=True):
        if s:
            msg = msg.replace(s, " ")
    msg = re.sub(r"[^\w\u4e00-\u9fff]+", " ", msg)
    for sub in _DEGREE_PHRASE_STRIP_SUBSTRINGS:
        msg = msg.replace(sub, " ")
    # A token is filler when it IS a strip word, or when it starts
    # with one ("fees" is the plural of "fee", "masters" of "master",
    # "tuitions" of "tuition") — a bare institution+fee question
    # must leave no phrase at all, not a bogus one.
    def _filler(token: str) -> bool:
        if token in _DEGREE_PHRASE_STRIP_WORDS:
            return True
        return any(len(w) >= 3 and token.startswith(w)
                   for w in _DEGREE_PHRASE_STRIP_WORDS)
    tokens = [t for t in msg.split() if len(t) > 1 and not _filler(t)]
    phrase = " ".join(tokens).strip()
    return phrase or None


def _degree_name_matches(program: dict | None, phrase: str) -> bool:
    """A programme's verified degree name contains the phrase — as
    one string ("computer science" in "Bachelor of Science in
    Computer Science", "计算机" in "计算机科学理学学士"), or with
    every whitespace token of the phrase inside a single degree
    name. A phrase no degree name contains never matches."""
    if program is None or not phrase:
        return False
    names = _degree_name_strings(program)
    if any(phrase in name for name in names):
        return True
    tokens = phrase.split()
    if len(tokens) > 1:
        return any(all(tok in name for tok in tokens) for name in names)
    return False


def _filter_by_level_words(pids: list[str], message: str) -> list[str]:
    """Candidates restricted to the level the message's level words
    name (undergraduate / taught_masters), or unchanged when the
    message names none. Unlike the old institution branches, a level
    that matches nothing filters to [] — never a cross-level guess."""
    if any(w in message for w in _UG_WORDS):
        level = "undergraduate"
    elif any(w in message for w in _TM_WORDS):
        level = "taught_masters"
    else:
        return list(pids)
    return [pid for pid in pids
            if (_lookup_program(pid) or {}).get("degree_level") == level]


def _match_institution(message: str, inst_id: str,
                       scope_ids=None) -> list[str]:
    """Programmes of ONE institution that a question refers to.

    Round 23 (W5): an institution token present in the question
    constrains the match to that institution in every branch — a
    question about ETH can never again answer with Peking,
    Tsinghua or Toronto programmes, and a degree that institution
    does not offer (ETH Medicine) matches nothing, so the answer
    is the honest unknown instead of a substitute. Order:
    exact degree name (in any locale) -> degree phrase from the
    message matched inside the degree name ("computer science"
    reaches ETH's BSc and MSc, whose full names never appear in
    the message) -> no degree named: the institution's own
    programmes (the v2 set when the institution has one, else its
    promoted expansion set — the old branches' behaviour, kept so
    a bare "UCL雅思要求" still lists UCL's two programmes).
    A caller scope narrows the pool first. Level words filter
    every branch; the wizard track filters at the caller."""
    pool_ids = (list(scope_ids) if scope_ids else
                [p["id"] for p in list(PROGRAMS.values())
                 + list(EXPANSION_MATCHABLE.values())])
    pool = [pid for pid in pool_ids
            if _program_institution_id(_lookup_program(pid)) == inst_id]
    titled = _match_by_display_title(message, pool)
    if titled:
        return _filter_by_level_words(titled, message)
    phrase = _degree_phrase(message, inst_id)
    if phrase:
        matched = [pid for pid in pool
                   if _degree_name_matches(_lookup_program(pid), phrase)]
        return _filter_by_level_words(matched, message)
    for keyword, pids in _INSTITUTION_PROGRAMMES.items():
        if keyword in message:
            own = [pid for pid in pids if pid in pool]
            if own:
                return _filter_by_level_words(own, message)
    return _filter_by_level_words(pool, message)


def _match_by_display_title(message: str, pool_ids) -> list[str]:
    """Programmes in ``pool_ids`` whose verified degree name (official
    English name or any localised name) appears in the message.

    A degree name shared by several programmes — the Chinese
    "计算机科学理学学士" is held by 20 programmes worldwide — narrows
    by an institution token in the message ("ETH Zurich" / "eth" /
    "苏黎世联邦理工"); with no institution token the shared name stays
    ambiguous and all hits are returned. [] when no degree name
    appears at all. Only verified catalogue data is consulted, never
    a guessed translation.

    Round 23 (W5): when an institution token IS present, the
    narrowing never falls back to the unfiltered hits — the old
    ``narrowed or hits`` returned Peking / Tsinghua / Toronto for
    an ETH question, because ETH's full degree name ("Bachelor of
    Science in Computer Science") is not a substring of the short
    phrase "computer science" in the message while those three
    programmes' official name is exactly "Computer Science". The
    phrase itself is matched by ``_match_institution``; this
    function only ever returns programmes the message's full degree
    name names, narrowed to the named institution."""
    hits: list[str] = []
    for pid in pool_ids:
        prog = _lookup_program(pid)
        if prog is None:
            continue
        if any(name in message for name in _degree_name_strings(prog)):
            hits.append(pid)
    if len(hits) <= 1:
        return hits
    narrowed = [pid for pid in hits
                if any(s in message
                       for s in _institution_strings(_lookup_program(pid)))]
    if _institution_by_alias(message) is not None:
        return narrowed
    return narrowed or hits


def _match_programmes(message: str, scope_ids=None, track=None) -> list[str]:
    """Programme ids the message refers to (0, 1 or 2+).

    ``scope_ids`` (Round 22, W2) is the caller-supplied visible batch:
    the display-title match runs against those programmes first, so a
    card's Chinese name resolves to the one programme in view even
    when the same degree name is shared catalogue-wide. ``track`` is
    the wizard track (undergraduate / taught_masters): every branch's
    result is filtered by it, so an undergraduate profile can never
    match an MSc programme. Either may be None (the old behaviour).

    Round 23 (W5): a message naming an institution goes through
    ``_match_institution`` — the institution token constrains every
    branch, and a degree phrase the institution does not offer
    matches nothing (honest unknown, never a substitute from
    another institution). Without an institution token the old
    branches run unchanged: programme aliases, then display titles
    (a shared short name such as "Computer Science" stays
    ambiguous across institutions), then the v2 institution
    keywords."""
    for alias, pid in _PROGRAM_ALIASES.items():
        if alias in message:
            return _filter_by_track([pid], track)
    # Round 23 (W5): institution token first — see _match_institution.
    inst_id = _institution_by_alias(message)
    if inst_id is not None:
        return _filter_by_track(
            _match_institution(message, inst_id, scope_ids), track)
    # Round 22 (W2): the card's own localised display title. The pool
    # is the visible batch when one is in scope, else the whole
    # verified catalogue — a degree name that is unique in the pool
    # answers at once; a shared one needs its institution token.
    pool = (list(scope_ids) if scope_ids else
            [p["id"] for p in list(PROGRAMS.values())
             + list(EXPANSION_MATCHABLE.values())])
    titled = _match_by_display_title(message, pool)
    if titled:
        # An explicitly titled programme in the other track is no
        # match at all — never fall through to a cross-track guess.
        return _filter_by_track(titled, track)
    for keyword, pids in _INSTITUTION_PROGRAMMES.items():
        if keyword in message:
            level = None
            if any(w in message for w in _UG_WORDS):
                level = "undergraduate"
            elif any(w in message for w in _TM_WORDS):
                level = "taught_masters"
            if level is None:
                return _filter_by_track(list(pids), track)
            matched = [pid for pid in pids
                       if PROGRAMS[pid].get("degree_level") == level]
            return _filter_by_track(matched or list(pids), track)
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
        overall = (th.get("overall") or th.get("ielts_overall")
                   or th.get("ielts"))
        if overall is None:
            continue
        parts = [_fmt("ielts_overall", locale, v=_score(overall))]
        each = (th.get("each_component") or th.get("ielts_min_each")
                or th.get("min_section"))
        if each is not None:
            parts.append(_fmt("ielts_each", locale, v=_score(each)))
        for key, tkey in (("ielts_reading", "comp_reading"),
                          ("ielts_writing", "comp_writing"),
                          ("ielts_listening", "comp_listening"),
                          ("ielts_speaking", "comp_speaking"),
                          ("reading", "comp_reading"),
                          ("writing", "comp_writing"),
                          ("listening", "comp_listening"),
                          ("speaking", "comp_speaking")):
            v = th.get(key)
            # Bare component keys are IELTS scores only when <= 9;
            # larger values are TOEFL section scores, not IELTS.
            if v is not None and (key.startswith("ielts_") or v <= 9):
                parts.append(_fmt("ielts_component", locale,
                                  name=_t(locale, tkey), v=_score(v)))
        return ", ".join(parts)
    return None


def _ask_result(lines: list[str], locale: str, program_id: str | None = None,
                institution_id: str | None = None,
                evidence_url: str | None = None) -> dict:
    program = _lookup_program(program_id) if program_id else None
    return {"lines": lines[:MAX_ANSWER_LINES],
            "program_id": program_id,
            "program_name": program_display_name(program) if program else None,
            "institution_id": institution_id,
            "evidence_url": evidence_url,
            "ai_status": AI_STATUS, "data_version": DATA_VERSION,
            "next_steps": {"wizard": "/wizard",
                           "program": f"/programs/{program_id}" if program_id else None,
                           "institution": f"/institutions/{institution_id}" if institution_id else None}}


def ask(message: str, locale: str = "en", track: str | None = None) -> dict:
    """Free-text question, answered only from verified data.

    Order: personal-data guard -> greeting -> rank lookup -> programme
    facts (fee / IELTS / deadline) -> unknown. Nothing is stored.

    ``track`` (Round 22, W2) is the wizard track the question is asked
    under (undergraduate / taught_masters, else None): programme
    matching filters by it, so an undergraduate profile can never
    match an MSc programme.
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
        pids = _match_programmes(msg, track=track)
        if len(pids) == 1:
            program = _lookup_program(pids[0])
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
            names = "、".join(program_display_name(_lookup_program(pid))
                              for pid in pids)
            # Round 23 (W5): the count word comes from the same list
            # that is rendered — the template used to hard-code "two"
            # while the list held three (or ten) programmes.
            return _ask_result([_fmt("ambiguous_programme", loc,
                                     count=len(pids), names=names)], loc)

    # Round 9 (R3): a country QUESTION ("瑞士有哪些好学校？") is
    # answered from that country's own verified programmes and
    # institutions — never "no Swiss data" while the catalogue holds
    # 25 CH programmes. A mere country mention (a preference
    # statement) and a suggestion request are not country questions:
    # they fall through to the honest unknown / suggestion pick.
    # Only a country with no verified programme at all falls through
    # to the honest unknown below.
    country = _detect_country(msg)
    if (country and not _looks_like_suggestion(msg)
            and any(w in msg for w in _COUNTRY_QUESTION_WORDS)):
        result = country_answer(country, loc)
        if result is not None:
            return _ask_result(result["lines"], loc,
                               program_id=result["program_id"],
                               institution_id=result["institution_id"],
                               evidence_url=result["evidence_url"])

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

#!/usr/bin/env python3
"""Generate the frontend offline mirrors for the expansion programmes,
the success cases and the school reviews, and add the locale keys for
the homepage cases/news sections, the cases page, and the institution-page
expansion display.

Sources of truth (never edited by this script):
  data/expansions/expansion.json
  data/expansions/success_cases.json
  data/expansions/school_reviews.json  (may not exist yet — see below)

Outputs (derived — re-run this script after the sources change):
  frontend/src/lib/expansion.ts   (all expansion programmes, frontend shape)
  frontend/src/lib/cases.ts       (41 applicant cards / 53 offers, frontend shape)
  frontend/src/lib/reviews.ts     (school reviews; empty array until the
                                   source file lands, so the build stays green)
  frontend/messages/*.json        (new keys appended; existing keys untouched)

Rules the mirrors follow:
- No fact is invented. A missing fee stays null, a missing deadline stays
  null, a missing case field stays null; the UI renders nothing for nulls.
- Round 6 (2026-11-26): expansion programmes with at least one evaluable
  rule (fee / language / academic) and a wizard track are matchable=true
  and are evaluated by the generic evaluator; the mirror carries the
  programme's city, its matchable flag, and each requirement's threshold
  verbatim so the offline evaluator can run on them.
- Every case keeps its label "网友分享，未经官方核实" verbatim; the UI
  renders the translated equivalent of that label via cases.unverifiedLabel.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPANSION_SRC = os.path.join(ROOT, "data", "expansions", "expansion.json")
CASES_SRC = os.path.join(ROOT, "data", "expansions", "success_cases.json")
REVIEWS_SRC = os.path.join(ROOT, "data", "expansions", "school_reviews.json")
EXPANSION_OUT = os.path.join(ROOT, "frontend", "src", "lib", "expansion.ts")
CLIMATE_SRC = os.path.join(ROOT, "data", "expansions", "climate.json")
CLIMATE_OUT = os.path.join(ROOT, "frontend", "src", "lib", "climate.ts")
CASES_OUT = os.path.join(ROOT, "frontend", "src", "lib", "cases.ts")
REVIEWS_OUT = os.path.join(ROOT, "frontend", "src", "lib", "reviews.ts")
MESSAGES_DIR = os.path.join(ROOT, "frontend", "messages")
LOCALES = ["en", "zh-CN", "es", "fr", "pt-BR", "ar"]

# Homepage featured cases: complete backgrounds, spanning US / UK / SG / AU,
# taught masters, three platforms. (Round 8: the only undergraduate case
# was removed — it was not a success story — so the set is TM-only now.)
FEATURED_CASE_IDS = ["sc-001", "sc-026", "sc-051", "sc-033", "sc-012", "sc-039"]


def _dump_ts(path, header, const_name, type_name, value):
    body = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    with open(path, "w", encoding="utf-8") as f:
        f.write(header)
        f.write(f"export const {const_name}: {type_name} = {body};\n")


def generate_expansion():
    with open(EXPANSION_SRC, encoding="utf-8") as f:
        data = json.load(f)
    programs = []
    for p in data["programs"]:
        fees = p.get("fees") or {}
        app_fee = fees.get("application_fee")
        programs.append({
            "id": p["id"],
            "institutionId": p["institution_id"],
            "institution": p["institution"],
            "country": p["country"],
            "city": p.get("city") or "",
            "matchable": p.get("matchable") is True,
            "degreeLevel": p["degree_level"],
            "officialName": p["official_name"],
            "nameLocalized": p.get("name_localized") or {},
            "field": p.get("field") or p.get("subject") or "",
            "duration": p.get("duration") or "",
            "durationMonths": p.get("duration_months"),
            "intakeYear": p.get("intake_year") or 0,
            "start": p.get("start") or "",
            "studyMode": p.get("study_mode") or "",
            "fees": {
                "amount": fees.get("amount"),
                "amountMin": fees.get("amount_min"),
                "amountMax": fees.get("amount_max"),
                "currency": fees.get("currency") or "",
                "period": fees.get("period") or "",
                "residency": fees.get("residency"),
                "notes": fees.get("notes"),
                "academicYear": fees.get("academic_year"),
                "applicationFee": (
                    {"amount": app_fee["amount"], "currency": app_fee["currency"]}
                    if isinstance(app_fee, dict) and app_fee.get("amount") is not None
                    else None
                ),
            },
            "applicationDeadline": p.get("application_deadline"),
            "applicationStatus": p.get("application_status") or "unknown",
            "requirements": [
                {
                    "id": r["id"],
                    "category": r["category"],
                    "description": r["description"],
                    "threshold": r.get("threshold"),
                    "sourceIds": list(r.get("source_ids") or []),
                }
                for r in p.get("requirements") or []
            ],
            "sources": [
                {
                    "id": s["id"],
                    "url": s["url"],
                    "title": s.get("title") or s["id"],
                    "retrievedAt": s.get("retrieved_at") or "",
                }
                for s in p.get("sources") or []
            ],
        })
    header = (
        "// Generated by tools/generate_frontend_mirrors.py from\n"
        "// data/expansions/expansion.json — do not edit by hand.\n"
        "// Round 6: each programme carries its city, its matchable flag\n"
        "// (true only for UG/TM programmes with >=1 evaluable rule) and\n"
        "// each requirement's threshold verbatim, so the offline\n"
        "// evaluator (lib/api.ts evaluateLocal) can run on it. A missing\n"
        "// fee or deadline stays null and the UI renders nothing for it.\n"
        "import type { ExpansionProgram } from './types';\n\n"
    )
    _dump_ts(EXPANSION_OUT, header, "EXPANSION_PROGRAMS", "ExpansionProgram[]", programs)
    return len(programs)


def generate_climate():
    """Curated city -> climate table (see docs/CLIMATE.md) as a
    frontend mirror: city name -> {climate, sourceUrl, note?}."""
    with open(CLIMATE_SRC, encoding="utf-8") as f:
        data = json.load(f)
    table = {}
    for e in data.get("cities", []):
        entry = {"climate": e["climate"], "sourceUrl": e["source_url"]}
        if e.get("note"):
            entry["note"] = e["note"]
        table[e["city"]] = entry
    header = (
        "// Generated by tools/generate_frontend_mirrors.py from\n"
        "// data/expansions/climate.json — do not edit by hand.\n"
        "// Curated city -> climate class (warm / cool / four_seasons /\n"
        "// mild), one sourced entry per city. A city with no entry gets\n"
        "// no climate signal — its programmes are never demoted.\n"
        "import type { ClimateClass } from './types';\n\n"
    )
    _dump_ts(CLIMATE_OUT, header, "CLIMATE_CITIES",
             "Record<string, { climate: ClimateClass; sourceUrl: string; note?: string }>",
             table)
    return len(table)


def generate_cases():
    with open(CASES_SRC, encoding="utf-8") as f:
        data = json.load(f)
    cases = []
    for c in data["cases"]:
        # One card per applicant; `offers` lists every offer that applicant
        # shared (Round 8 dedupe — one person was previously split across
        # several cards). `key_experience` is the experience shared for the
        # applicant as a whole; per-offer notes live on each offer.
        cases.append({
            "id": c["id"],
            "platform": c["platform"],
            "sourceUrl": c["source_url"],
            "sourceRef": c.get("source_ref"),
            "postedDate": c.get("posted_date"),
            "authorDisplay": c.get("author_display"),
            "undergradInstitution": c.get("undergrad_institution"),
            "undergradMajor": c.get("undergrad_major"),
            "gpa": c.get("gpa"),
            "languageScores": c.get("language_scores"),
            "keyExperience": c.get("key_experience"),
            "offers": [
                {
                    "institution": o["institution"],
                    "programme": o.get("programme"),
                    "level": o["level"],
                    "intake": o.get("intake"),
                    "note": o.get("note"),
                }
                for o in c["offers"]
            ],
            "label": c["label"],
            "collectedDate": c["collected_date"],
        })
    ids = {c["id"] for c in cases}
    missing = [i for i in FEATURED_CASE_IDS if i not in ids]
    if missing:
        raise SystemExit(f"featured case ids missing from source: {missing}")
    header = (
        "// Generated by tools/generate_frontend_mirrors.py from\n"
        "// data/expansions/success_cases.json — do not edit by hand.\n"
        "// Netizen-shared offer stories, NOT officially verified admission\n"
        "// outcomes. One card per applicant (41 cards, 53 offers); a card\n"
        "// lists every offer that applicant shared. Missing fields stay\n"
        "// null; the UI renders nothing for them and never invents a value.\n"
        "// No contact info, no agency cases.\n"
        "import type { SuccessCase } from './types';\n\n"
    )
    _dump_ts(CASES_OUT, header, "SUCCESS_CASES", "SuccessCase[]", cases)
    featured = json.dumps(FEATURED_CASE_IDS, ensure_ascii=False)
    with open(CASES_OUT, "a", encoding="utf-8") as f:
        f.write(
            "\n// Homepage featured cases: complete backgrounds, spanning US / UK /\n"
            "// SG / AU, taught masters, three platforms.\n"
            f"export const FEATURED_CASE_IDS: string[] = {featured};\n"
        )
    return len(cases)


def generate_reviews():
    """Mirror data/expansions/school_reviews.json to frontend/src/lib/reviews.ts.

    The source file is collected by another agent and may not exist yet:
    when it is missing the mirror is generated as an empty array so the
    build still passes and the homepage reviews carousel simply hides
    itself. When the file lands, re-run this script and the carousel
    lights up — no frontend code change is needed.
    Reviews are netizen-shared impressions, NOT officially verified; a
    missing field stays null and the UI renders nothing for it. There
    is no rating / stars data — the UI never shows any.
    """
    if not os.path.exists(REVIEWS_SRC):
        header = (
            "// Generated by tools/generate_frontend_mirrors.py — do not edit by hand.\n"
            "// Source data/expansions/school_reviews.json has not landed yet;\n"
            "// this empty mirror keeps the build green and the homepage\n"
            "// reviews carousel hidden until the data arrives. Re-run the\n"
            "// generator after the source lands.\n"
            "import type { SchoolReview } from './types';\n\n"
        )
        _dump_ts(REVIEWS_OUT, header, "SCHOOL_REVIEWS", "SchoolReview[]", [])
        return 0
    with open(REVIEWS_SRC, encoding="utf-8") as f:
        data = json.load(f)
    reviews = []
    for r in data["reviews"]:
        if not (r.get("quote") or "").strip():
            raise SystemExit(f"review {r.get('id')} has no quote")
        if r.get("label") != "网友分享，未经官方核实":
            raise SystemExit(f"review {r.get('id')} has a wrong label")
        reviews.append({
            "id": r["id"],
            "institutionId": r.get("institution_id"),
            "institution": r["institution"],
            "programme": r.get("programme"),
            "level": r.get("level"),
            "authorDisplay": r.get("author_display"),
            "source": r.get("source"),
            "sourceUrl": r.get("source_url"),
            "postedDate": r.get("posted_date"),
            "quote": r["quote"],
            "quoteLang": r.get("quote_lang"),
            "quoteZh": r.get("quote_zh"),
            "label": r.get("label"),
            "collectedDate": r.get("retrieved_at"),
        })
    header = (
        "// Generated by tools/generate_frontend_mirrors.py from\n"
        "// data/expansions/school_reviews.json — do not edit by hand.\n"
        "// Netizen-shared school impressions, NOT officially verified.\n"
        "// Missing fields stay null; the UI renders nothing for them\n"
        "// and never invents a value. No rating / stars in this data.\n"
        "import type { SchoolReview } from './types';\n\n"
    )
    _dump_ts(REVIEWS_OUT, header, "SCHOOL_REVIEWS", "SchoolReview[]", reviews)
    return len(reviews)


# New locale keys: key -> locale -> string. Every key must have all 6 locales,
# non-empty, or scripts/check-locales.mjs fails the build.
TRANSLATIONS = {
    "nav.cases": {
        "en": "Cases", "zh-CN": "成功案例", "es": "Casos", "fr": "Témoignages",
        "pt-BR": "Casos", "ar": "قصص",
    },
    "home.casesTitle": {
        "en": "Success cases shared by applicants",
        "zh-CN": "网友分享的成功案例",
        "es": "Casos de éxito compartidos por solicitantes",
        "fr": "Témoignages de réussite partagés par des candidats",
        "pt-BR": "Casos de sucesso compartilhados por candidatos",
        "ar": "قصص نجاح شاركها المتقدمون",
    },
    "home.casesSub": {
        "en": "Real offer stories collected from public forums — backgrounds, scores and outcomes as the posters shared them. Not official admission data.",
        "zh-CN": "从公开论坛收集的真实录取分享——背景、成绩与结果均为发帖人自述，非官方录取数据。",
        "es": "Historias reales de admisión recogidas en foros públicos: antecedentes, notas y resultados tal como los compartieron sus autores. No son datos oficiales de admisión.",
        "fr": "Témoignages réels d'admission recueillis sur des forums publics : parcours, notes et résultats tels que partagés par leurs auteurs. Il ne s'agit pas de données officielles d'admission.",
        "pt-BR": "Histórias reais de admissão coletadas em fóruns públicos: formação, notas e resultados conforme compartilhados pelos autores. Não são dados oficiais de admissão.",
        "ar": "قصص قبول حقيقية جُمعت من منتديات عامة — الخلفيات والدرجات والنتائج كما شاركها أصحابها. ليست بيانات قبول رسمية.",
    },
    "home.casesViewAll": {
        # Round 8: the count is interpolated from SUCCESS_CASES.length
        # (tf('home.casesViewAll', {count})) — never hardcoded again.
        "en": "View all {count} cases", "zh-CN": "查看全部 {count} 个案例",
        "es": "Ver los {count} casos", "fr": "Voir les {count} témoignages",
        "pt-BR": "Ver os {count} casos", "ar": "عرض جميع القصص الـ {count}",
    },
    "cases.unverifiedLabel": {
        "en": "Shared by a netizen — not officially verified",
        "zh-CN": "网友分享，未经官方核实",
        "es": "Compartido por un usuario; sin verificación oficial",
        "fr": "Partagé par un internaute — non vérifié officiellement",
        "pt-BR": "Compartilhado por um internauta — sem verificação oficial",
        "ar": "مشاركة من أحد مستخدمي الإنترنت — غير موثقة رسميًا",
    },
    "cases.offer": {
        "en": "Offer", "zh-CN": "录取", "es": "Admisión", "fr": "Admission",
        "pt-BR": "Admissão", "ar": "القبول",
    },
    "cases.background": {
        "en": "Background", "zh-CN": "本科背景", "es": "Formación", "fr": "Parcours",
        "pt-BR": "Formação", "ar": "الخلفية",
    },
    "cases.scores": {
        "en": "Language / test scores", "zh-CN": "语言 / 考试成绩",
        "es": "Idioma / exámenes", "fr": "Langue / examens",
        "pt-BR": "Idioma / exames", "ar": "اللغة / درجات الاختبار",
    },
    "cases.experience": {
        "en": "Key experience", "zh-CN": "关键经历", "es": "Experiencia clave",
        "fr": "Expérience clé", "pt-BR": "Experiência principal", "ar": "الخبرة الرئيسية",
    },
    "cases.offersCount": {
        # Eyebrow on a multi-offer card: how many offers this applicant shared.
        "en": "{count} offers", "zh-CN": "{count} 个录取",
        "es": "{count} admisiones", "fr": "{count} admissions",
        "pt-BR": "{count} admissões", "ar": "{count} عروض قبول",
    },
    "cases.viewSource": {
        "en": "View original post", "zh-CN": "查看原帖",
        "es": "Ver la publicación original", "fr": "Voir la publication d'origine",
        "pt-BR": "Ver a publicação original", "ar": "عرض المنشور الأصلي",
    },
    "home.newsTitle": {
        "en": "Latest news & policy", "zh-CN": "最新资讯与政策",
        "es": "Últimas noticias y políticas", "fr": "Actualités et politiques",
        "pt-BR": "Últimas notícias e políticas", "ar": "أحدث الأخبار والسياسات",
    },
    "home.newsSub": {
        "en": "First-hand updates from official university and government pages — titles and links only, never copied text.",
        "zh-CN": "来自院校与政府官网的一手更新——只提供标题与链接，不复制正文。",
        "es": "Actualizaciones de primera mano de páginas oficiales de universidades y gobiernos: solo títulos y enlaces, nunca texto copiado.",
        "fr": "Mises à jour de première main issues des pages officielles des universités et des gouvernements : titres et liens uniquement, jamais de texte copié.",
        "pt-BR": "Atualizações em primeira mão de páginas oficiais de universidades e governos — apenas títulos e links, nunca texto copiado.",
        "ar": "تحديثات مباشرة من الصفحات الرسمية للجامعات والحكومات — العناوين والروابط فقط، دون نسخ النصوص.",
    },
    "home.newsRead": {
        "en": "Read on the official site", "zh-CN": "在官网阅读全文",
        "es": "Leer en el sitio oficial", "fr": "Lire sur le site officiel",
        "pt-BR": "Ler no site oficial", "ar": "اقرأ على الموقع الرسمي",
    },
    "home.newsChecked": {
        "en": "Checked 25 Nov 2026", "zh-CN": "核实于 2026 年 11 月 25 日",
        "es": "Verificado el 25 nov 2026", "fr": "Vérifié le 25 nov. 2026",
        "pt-BR": "Verificado em 25 de nov. de 2026", "ar": "تم التحقق في 25 نوفمبر 2026",
    },
    "home.policyTitle": {
        "en": "Deadlines & visas — check before you act",
        "zh-CN": "截止日期与签证——行动前请核对官网",
        "es": "Plazos y visados: compruébalos antes de actuar",
        "fr": "Dates limites et visas — vérifiez avant d'agir",
        "pt-BR": "Prazos e vistos — confira antes de agir",
        "ar": "المواعيد النهائية والتأشيرات — تحقق قبل التصرف",
    },
    "home.policyNote": {
        "en": "Check the official page before acting on any date or rule.",
        "zh-CN": "任何日期或规定，行动前请以官网为准。",
        "es": "Antes de actuar, comprueba la página oficial.",
        "fr": "Avant d'agir, vérifiez la page officielle.",
        "pt-BR": "Antes de agir, confira a página oficial.",
        "ar": "قبل التصرف، تحقق من الصفحة الرسمية.",
    },
    "home.browseSub": {
        "en": "Eight programmes with full verified requirements — the eligibility check covers these. Browse the full catalogue of verified programmes from universities worldwide.",
        "zh-CN": "8 个已完整核实的专业——资格检查覆盖这些专业；浏览全球大学已核实课程的完整目录。",
        "es": "Ocho programas con requisitos verificados completos: la comprobación de elegibilidad cubre estos. Explora el catálogo completo de programas verificados de universidades de todo el mundo.",
        "fr": "Huit programmes aux exigences entièrement vérifiées — la vérification d'éligibilité couvre ceux-ci. Parcourez le catalogue complet des programmes vérifiés des universités du monde entier.",
        "pt-BR": "Oito programas com requisitos totalmente verificados — a verificação de elegibilidade cobre estes. Explore o catálogo completo de programas verificados de universidades do mundo todo.",
        "ar": "ثمانية برامج بمتطلبات موثقة بالكامل — يشملها فحص الأهلية. تصفح الدليل الكامل للبرامج الموثقة من جامعات حول العالم.",
    },
    "home.browseRankings": {
        "en": "Browse all 100 ranked institutions", "zh-CN": "浏览全部 100 所排名院校",
        "es": "Ver las 100 instituciones del ranking",
        "fr": "Parcourir les 100 établissements classés",
        "pt-BR": "Ver as 100 instituições do ranking",
        "ar": "تصفح المؤسسات المئة المصنفة",
    },
    "institution.reqTitle": {
        "en": "Verified requirements", "zh-CN": "已核实的要求",
        "es": "Requisitos verificados", "fr": "Exigences vérifiées",
        "pt-BR": "Requisitos verificados", "ar": "المتطلبات الموثقة",
    },
    "institution.reqAcademic": {
        "en": "Academic", "zh-CN": "学术", "es": "Académico", "fr": "Académique",
        "pt-BR": "Acadêmico", "ar": "أكاديمي",
    },
    "institution.reqLanguage": {
        "en": "Language", "zh-CN": "语言", "es": "Idioma", "fr": "Langue",
        "pt-BR": "Idioma", "ar": "اللغة",
    },
    "institution.reqTest": {
        "en": "Admissions test", "zh-CN": "入学考试", "es": "Examen de admisión",
        "fr": "Examen d'admission", "pt-BR": "Exame de admissão", "ar": "اختبار القبول",
    },
    "institution.reqFee": {
        "en": "Fees", "zh-CN": "费用", "es": "Tasas", "fr": "Frais",
        "pt-BR": "Taxas", "ar": "الرسوم",
    },
    "institution.reqOther": {
        "en": "Other", "zh-CN": "其他", "es": "Otros", "fr": "Autres",
        "pt-BR": "Outros", "ar": "أخرى",
    },
    "institution.deadline": {
        "en": "Application deadline", "zh-CN": "申请截止日期",
        "es": "Fecha límite de solicitud", "fr": "Date limite de candidature",
        "pt-BR": "Prazo de candidatura", "ar": "الموعد النهائي للتقديم",
    },
    "institution.statusOpen": {
        "en": "Applications open", "zh-CN": "申请开放中",
        "es": "Solicitudes abiertas", "fr": "Candidatures ouvertes",
        "pt-BR": "Candidaturas abertas", "ar": "التقديم مفتوح",
    },
    "institution.feeNotPublished": {
        "en": "Tuition fee not published on the official page",
        "zh-CN": "官网未公布学费",
        "es": "La tasa no está publicada en la página oficial",
        "fr": "Frais non publiés sur la page officielle",
        "pt-BR": "Taxa não publicada na página oficial",
        "ar": "الرسوم غير منشورة على الصفحة الرسمية",
    },
    "institution.expansionPrograms": {
        "en": "Programmes with verified requirements",
        "zh-CN": "已核实要求的专业",
        "es": "Programas con requisitos verificados",
        "fr": "Programmes aux exigences vérifiées",
        "pt-BR": "Programas com requisitos verificados",
        "ar": "برامج بمتطلبات موثقة",
    },
    "institution.v2Programs": {
        "en": "Verified programmes — eligibility check available",
        "zh-CN": "已核实专业——可做资格检查",
        "es": "Programas verificados: comprobación de elegibilidad disponible",
        "fr": "Programmes vérifiés — vérification d'éligibilité disponible",
        "pt-BR": "Programas verificados — verificação de elegibilidade disponível",
        "ar": "برامج موثقة — فحص الأهلية متاح",
    },
    "cases.title": {
        "en": "Success cases", "zh-CN": "成功案例", "es": "Casos de éxito",
        "fr": "Témoignages de réussite", "pt-BR": "Casos de sucesso", "ar": "قصص النجاح",
    },
    "cases.sub": {
        # Round 8: {count} is the card count, interpolated from
        # SUCCESS_CASES.length — never hardcoded again.
        "en": "{count} offer stories shared by applicants on public forums. Backgrounds, scores and outcomes are as the posters shared them — not official admission data, and never a guarantee.",
        "zh-CN": "{count} 个申请人在公开论坛分享的录取故事。背景、成绩与结果均为发帖人自述——非官方录取数据，也不代表录取保证。",
        "es": "{count} historias de admisión compartidas por solicitantes en foros públicos. Antecedentes, notas y resultados son tal como los compartieron sus autores: no son datos oficiales de admisión ni una garantía.",
        "fr": "{count} témoignages d'admission partagés par des candidats sur des forums publics. Parcours, notes et résultats sont tels que partagés par leurs auteurs — ni des données officielles d'admission, ni une garantie.",
        "pt-BR": "{count} histórias de admissão compartilhadas por candidatos em fóruns públicos. Formação, notas e resultados são conforme compartilhados pelos autores — não são dados oficiais de admissão nem uma garantia.",
        "ar": "{count} قصة قبول شاركها متقدمون في منتديات عامة. الخلفيات والدرجات والنتائج كما شاركها أصحابها — ليست بيانات قبول رسمية ولا ضمانًا للقبول.",
    },
    "cases.filterAll": {
        "en": "All", "zh-CN": "全部", "es": "Todos", "fr": "Tous",
        "pt-BR": "Todos", "ar": "الكل",
    },
    "cases.filterUg": {
        "en": "Undergraduate", "zh-CN": "本科", "es": "Grado", "fr": "Licence",
        "pt-BR": "Graduação", "ar": "بكالوريوس",
    },
    "cases.filterTm": {
        "en": "Taught masters", "zh-CN": "授课型硕士", "es": "Máster",
        "fr": "Master", "pt-BR": "Mestrado", "ar": "ماجستير",
    },
    "institution.filterFoundation": {
        "en": "Foundation", "zh-CN": "预科", "es": "Fundación",
        "fr": "Fondation", "pt-BR": "Fundação", "ar": "سنة تأسيسية",
    },
    "institution.filterJointHonours": {
        "en": "Joint honours", "zh-CN": "联合学位", "es": "Doble titulación",
        "fr": "Double licence", "pt-BR": "Dupla graduação", "ar": "درجة مشتركة",
    },
    "news.nusAwards": {
        "en": "341 students and graduates recognised for achievements beyond the classroom.",
        "zh-CN": "341 名学生与毕业生因课堂外的成就获得表彰。",
        "es": "341 estudiantes y graduados reconocidos por logros más allá del aula.",
        "fr": "341 étudiants et diplômés récompensés pour leurs réussites hors des cours.",
        "pt-BR": "341 estudantes e formandos reconhecidos por conquistas além da sala de aula.",
        "ar": "تم تكريم 341 طالبًا وخريجًا لإنجازاتهم خارج قاعة الدراسة.",
    },
    "news.nusRag": {
        "en": "A 67-year student tradition of fundraising performances raised close to $260,000 for community programmes.",
        "zh-CN": "一项延续 67 年的学生募捐演出传统，为社区项目筹集了近 26 万美元。",
        "es": "Una tradición estudiantil de 67 años de actuaciones benéficas recaudó casi 260.000 dólares para programas comunitarios.",
        "fr": "Une tradition étudiante de 67 ans de spectacles caritatifs a récolté près de 260 000 dollars pour des programmes communautaires.",
        "pt-BR": "Uma tradição estudantil de 67 anos de apresentações beneficentes arrecadou quase US$ 260 mil para programas comunitários.",
        "ar": "تقاليد طلابية عمرها 67 عامًا من العروض الخيرية جمعت ما يقارب 260 ألف دولار لبرامج مجتمعية.",
    },
    "news.nusCtpclc": {
        "en": "Students and community partners on belonging and service in Singapore's 60th year.",
        "zh-CN": "在新加坡建国 60 周年之际，学生与社区伙伴探讨归属感与服务。",
        "es": "Estudiantes y socios comunitarios hablan de pertenencia y servicio en el 60.º año de Singapur.",
        "fr": "Étudiants et partenaires communautaires sur l'appartenance et le service, en la 60e année de Singapour.",
        "pt-BR": "Estudantes e parceiros comunitários falam de pertencimento e serviço no 60.º ano de Singapura.",
        "ar": "طلاب وشركاء مجتمع يتحدثون عن الانتماء والخدمة في عام سنغافورة الستين.",
    },
    "news.bcLiyuan": {
        "en": "A Chinese graduate on settling into UK study and building her own business back home.",
        "zh-CN": "一位中国毕业生谈适应英国学习，以及回国创业的经历。",
        "es": "Una graduada china habla de adaptarse a estudiar en Reino Unido y de crear su propia empresa en su país.",
        "fr": "Une diplômée chinoise raconte son adaptation aux études au Royaume-Uni et la création de sa propre entreprise chez elle.",
        "pt-BR": "Uma formada chinesa fala sobre se adaptar aos estudos no Reino Unido e criar sua própria empresa em casa.",
        "ar": "خريجة صينية تتحدث عن التأقلم مع الدراسة في المملكة المتحدة وبناء مشروعها الخاص في بلدها.",
    },
    "news.bcMariam": {
        "en": "A Nigerian GREAT scholar on moving from environmental science to ethical finance — and meeting royalty.",
        "zh-CN": "一位尼日利亚 GREAT 奖学金获得者谈从环境科学转向伦理金融——以及与王室成员的会面。",
        "es": "Una becaria GREAT nigeriana habla de pasar de las ciencias ambientales a las finanzas éticas, y de conocer a la realeza.",
        "fr": "Une boursière GREAT nigériane raconte son passage des sciences de l'environnement à la finance éthique — et sa rencontre avec la famille royale.",
        "pt-BR": "Uma bolsista GREAT nigeriana fala sobre migrar da ciência ambiental para as finanças éticas — e conhecer a realeza.",
        "ar": "حاصلة على منحة GREAT من نيجيريا تتحدث عن الانتقال من العلوم البيئية إلى التمويل الأخلاقي — ولقاء أفراد من العائلة المالكة.",
    },
    "news.bcSumaiya": {
        "en": "A fully funded Bangladeshi scholar who graduated with distinction in Newcastle.",
        "zh-CN": "一位获得全额资助的孟加拉国奖学金获得者，在纽卡斯尔以优异成绩毕业。",
        "es": "Una becaria bangladesí con financiación completa que se graduó con distinción en Newcastle.",
        "fr": "Une boursière bangladaise entièrement financée, diplômée avec distinction à Newcastle.",
        "pt-BR": "Uma bolsista de Bangladesh com financiamento integral que se formou com distinção em Newcastle.",
        "ar": "حاصلة على منحة ممولة بالكامل من بنغلاديش تخرجت بامتياز في نيوكاسل.",
    },
    "news.bcArjun": {
        "en": "An Indian GREAT scholar who received offers from 7 of 10 UK universities.",
        "zh-CN": "一位印度 GREAT 奖学金获得者，收到了 10 所英国大学中的 7 所录取。",
        "es": "Un becario GREAT indio que recibió ofertas de 7 de 10 universidades británicas.",
        "fr": "Un boursier GREAT indien qui a reçu des offres de 7 universités britanniques sur 10.",
        "pt-BR": "Um bolsista GREAT indiano que recebeu ofertas de 7 das 10 universidades britânicas.",
        "ar": "حاصل على منحة GREAT من الهند تلقى عروضًا من 7 من أصل 10 جامعات بريطانية.",
    },
    "news.uclLondon": {
        "en": "A Pakistani student's first months in London on a Public Policy MSc.",
        "zh-CN": "一位巴基斯坦学生在伦敦攻读公共政策硕士的最初几个月。",
        "es": "Los primeros meses en Londres de un estudiante pakistaní en un máster de Políticas Públicas.",
        "fr": "Les premiers mois à Londres d'un étudiant pakistanais en master de politiques publiques.",
        "pt-BR": "Os primeiros meses em Londres de um estudante paquistanês no mestrado em Políticas Públicas.",
        "ar": "الأشهر الأولى لطالب باكستاني في لندن خلال ماجستير السياسة العامة.",
    },
    "news.uclGreece": {
        "en": "A Language and Culture student on arriving in London.",
        "zh-CN": "一位语言与文化专业学生讲述初到伦敦的经历。",
        "es": "Una estudiante de Lengua y Cultura cuenta su llegada a Londres.",
        "fr": "Une étudiante en langue et culture raconte son arrivée à Londres.",
        "pt-BR": "Uma estudante de Língua e Cultura conta sua chegada a Londres.",
        "ar": "طالبة في اللغة والثقافة تروي وصولها إلى لندن.",
    },
    "policy.ucas": {
        "en": "Equal consideration deadline 13 Jan 2027 for most undergraduate courses; 15 Oct 2026 for Oxford, Cambridge and medicine.",
        "zh-CN": "多数本科课程的同等考虑截止日期为 2027 年 1 月 13 日；牛津、剑桥与医学为 2026 年 10 月 15 日。",
        "es": "Fecha límite de consideración igualitaria: 13 ene 2027 para la mayoría de los grados; 15 oct 2026 para Oxford, Cambridge y medicina.",
        "fr": "Date limite d'examen à égalité : 13 janv. 2027 pour la plupart des licences ; 15 oct. 2026 pour Oxford, Cambridge et la médecine.",
        "pt-BR": "Prazo de consideração igualitária: 13 de jan. de 2027 para a maioria dos cursos de graduação; 15 de out. de 2026 para Oxford, Cambridge e medicina.",
        "ar": "الموعد النهائي للنظر المتساوي 13 يناير 2027 لمعظم برامج البكالوريوس؛ و15 أكتوبر 2026 لأكسفورد وكامبريدج والطب.",
    },
    "policy.visa": {
        "en": "Official guidance on UK Student visas: requirements, sponsors and conditions.",
        "zh-CN": "英国学生签证官方指南：要求、担保人与条件。",
        "es": "Guía oficial sobre visados de estudiante del Reino Unido: requisitos, patrocinadores y condiciones.",
        "fr": "Guide officiel sur les visas étudiant britanniques : exigences, parrains et conditions.",
        "pt-BR": "Guia oficial sobre vistos de estudante do Reino Unido: requisitos, patrocinadores e condições.",
        "ar": "إرشادات رسمية حول تأشيرات الطلاب في المملكة المتحدة: المتطلبات والكفلاء والشروط.",
    },
    "policy.pass": {
        "en": "Apply 2–3 months before your course starts; your institution registers you in SOLAR first. Check ICA for the current fees and process.",
        "zh-CN": "开课前 2–3 个月申请；学校会先在 SOLAR 系统中为你注册。费用与流程以 ICA 官网为准。",
        "es": "Solicítalo 2–3 meses antes de que empiece el curso; tu institución te registra primero en SOLAR. Consulta en ICA las tasas y el proceso actuales.",
        "fr": "Candidatez 2 à 3 mois avant le début du cours ; votre établissement vous inscrit d'abord dans SOLAR. Vérifiez les frais et la procédure en vigueur auprès de l'ICA.",
        "pt-BR": "Solicite 2–3 meses antes do início do curso; sua instituição registra você no SOLAR primeiro. Confira as taxas e o processo atuais na ICA.",
        "ar": "قدّم قبل بدء دورتك بشهرين إلى ثلاثة أشهر؛ تسجّلك مؤسستك أولًا في نظام SOLAR. تحقق من الرسوم والإجراءات الحالية لدى ICA.",
    },
    # --- Preference chat (wizard step 7, 2026-11-25): the form became a
    # full-page chat with 小罗盘. Warm, spoken, one question at a time.
    # The pet's opinions only state facts from the verified catalogue
    # (which institutions are in London / Singapore, how many verified
    # programmes a city has); nothing else is ever claimed.
    "wizard.chatTitle": {
        "en": "Chat with Little Compass about what you like",
        "zh-CN": "和小罗盘聊聊你的喜好",
        "es": "Charla con la Brújula sobre lo que te gusta",
        "fr": "Discute avec la Petite Boussole de tes préférences",
        "pt-BR": "Converse com a Bussolinha sobre o que você gosta",
        "ar": "تحدث مع البوصلة الصغيرة عما تحب",
    },
    "wizard.chatIntro": {
        "en": "Hi, I'm Little Compass! No forms — let's just chat like friends, and I'll get a feel for the place you'd love.",
        "zh-CN": "嗨，我是小罗盘！先别填表啦，咱们像朋友一样聊几句，我就知道你喜欢什么样的留学地啦～",
        "es": "¡Hola, soy la Brújula! Nada de formularios: charlemos como amigos y sabré qué lugar te encantaría.",
        "fr": "Salut, c'est la Petite Boussole ! Pas de formulaire : discutons comme des amis, et je saurai quel endroit te plairait.",
        "pt-BR": "Oi, eu sou a Bussolinha! Nada de formulário — vamos conversar como amigos e vou entender o lugar ideal para você.",
        "ar": "مرحبًا، أنا البوصلة الصغيرة! لا نماذج — لنتحدث كأصدقاء وسأعرف المكان الذي يناسبك.",
    },
    "wizard.chatQCountries": {
        "en": "Which countries do you like? Name any that catch your eye.",
        "zh-CN": "你喜欢哪些国家呀？随便说说，哪个都行～",
        "es": "¿Qué países te gustan? Dime los que te llamen la atención.",
        "fr": "Quels pays aimes-tu ? Dis-moi ceux qui te font envie.",
        "pt-BR": "De quais países você gosta? Me diga os que chamam sua atenção.",
        "ar": "ما الدول التي تحبها؟ أخبرني بما يلفت انتباهك.",
    },
    "wizard.chatQClimate": {
        "en": "And the climate? Do you like it warm, or cooler?",
        "zh-CN": "那气候呢？你喜欢暖和一点，还是凉快一点？",
        "es": "¿Y el clima? ¿Te gusta más el calor o el fresquito?",
        "fr": "Et le climat ? Tu préfères quand il fait chaud, ou plutôt frais ?",
        "pt-BR": "E o clima? Você prefere calor ou um clima mais fresco?",
        "ar": "وماذا عن المناخ؟ هل تحب الدفء أم البرودة؟",
    },
    "wizard.chatQEnvironment": {
        "en": "What kind of environment do you like — a buzzing big city, or a quiet small town?",
        "zh-CN": "喜欢什么样的环境？大城市的热闹，还是安静的小城？",
        "es": "¿Qué ambiente prefieres: el bullicio de una gran ciudad o un pueblo tranquilo?",
        "fr": "Quel environnement préfères-tu : l'agitation d'une grande ville, ou une petite ville tranquille ?",
        "pt-BR": "Que ambiente você prefere: a agitação de uma cidade grande ou uma cidadezinha tranquila?",
        "ar": "ما البيئة التي تحبها: صخب مدينة كبيرة أم هدوء مدينة صغيرة؟",
    },
    "wizard.chatQCity": {
        "en": "Any city you have in mind?",
        "zh-CN": "有没有特别想去的城市？",
        "es": "¿Hay alguna ciudad que tengas en mente?",
        "fr": "Une ville en tête ?",
        "pt-BR": "Tem alguma cidade em mente?",
        "ar": "هل هناك مدينة معينة في ذهنك؟",
    },
    "wizard.chatQAfterGrad": {
        "en": "After graduation, where would you like to build your life?",
        "zh-CN": "毕业之后，你想在哪里发展呀？",
        "es": "Después de graduarte, ¿dónde te gustaría hacer tu vida?",
        "fr": "Après tes études, où aimerais-tu construire ta vie ?",
        "pt-BR": "Depois de se formar, onde você gostaria de construir sua vida?",
        "ar": "بعد التخرج، أين تريد أن تبني حياتك؟",
    },
    "wizard.chatQSalary": {
        "en": "Can I ask — roughly what salary would you hope for after graduation?",
        "zh-CN": "悄悄问一句，毕业后你期望的薪资大概是多少？",
        "es": "¿Te puedo preguntar qué salario esperarías ganar al graduarte?",
        "fr": "Je peux te demander quel salaire tu espérerais après tes études ?",
        "pt-BR": "Posso perguntar que salário você esperaria ganhar depois de se formar?",
        "ar": "هل يمكنني أن أسأل عن الراتب الذي تأمل به بعد التخرج؟",
    },
    "wizard.chatQPressure": {
        "en": "How much academic pressure can you handle?",
        "zh-CN": "学业压力呢？你能扛多少？",
        "es": "¿Cuánta presión académica crees que puedes soportar?",
        "fr": "Quelle pression académique penses-tu pouvoir supporter ?",
        "pt-BR": "Quanta pressão acadêmica você acha que aguenta?",
        "ar": "كم من الضغط الدراسي تستطيع أن تتحمل؟",
    },
    "wizard.chatQTeaching": {
        "en": "Last one — how do you like to learn?",
        "zh-CN": "最后一个问题～你喜欢什么样的上课方式？",
        "es": "Última pregunta: ¿cómo te gusta aprender?",
        "fr": "Dernière question : comment aimes-tu apprendre ?",
        "pt-BR": "Última pergunta: como você gosta de aprender?",
        "ar": "سؤال أخير: كيف تحب أن تتعلم؟",
    },
    "wizard.chatSkip": {
        "en": "Skip", "zh-CN": "跳过", "es": "Saltar", "fr": "Passer",
        "pt-BR": "Pular", "ar": "تخطَّ",
    },
    "wizard.chatSkipAll": {
        "en": "Skip all, go to recommendations",
        "zh-CN": "跳过全部，直接看推荐",
        "es": "Saltar todo e ir a las recomendaciones",
        "fr": "Tout passer, voir les recommandations",
        "pt-BR": "Pular tudo e ver as recomendações",
        "ar": "تخطَّ الكل وانتقل إلى التوصيات",
    },
    "wizard.chatNext": {
        "en": "Done, next question", "zh-CN": "好了，下一题",
        "es": "Listo, siguiente pregunta", "fr": "C'est noté, question suivante",
        "pt-BR": "Pronto, próxima pergunta", "ar": "تم، السؤال التالي",
    },
    "wizard.chatSend": {
        "en": "Send", "zh-CN": "发送", "es": "Enviar", "fr": "Envoyer",
        "pt-BR": "Enviar", "ar": "إرسال",
    },
    "wizard.chatTypePlaceholder": {
        "en": "Or just type it to me…",
        "zh-CN": "直接打字告诉我也行…",
        "es": "O escríbemelo directamente…",
        "fr": "Ou écris-le-moi directement…",
        "pt-BR": "Ou digite para mim…",
        "ar": "أو اكتب لي مباشرة…",
    },
    "wizard.chatBack": {
        "en": "Previous question", "zh-CN": "上一题",
        "es": "Pregunta anterior", "fr": "Question précédente",
        "pt-BR": "Pergunta anterior", "ar": "السؤال السابق",
    },
    "wizard.chatRestart": {
        "en": "Chat again from the start", "zh-CN": "重新聊一遍",
        "es": "Empezar la charla de nuevo", "fr": "Recommencer la discussion",
        "pt-BR": "Conversar de novo do início", "ar": "ابدأ المحادثة من جديد",
    },
    "wizard.chatProgress": {
        "en": "Question {n} of {total}", "zh-CN": "第 {n} / {total} 题",
        "es": "Pregunta {n} de {total}", "fr": "Question {n} sur {total}",
        "pt-BR": "Pergunta {n} de {total}", "ar": "السؤال {n} من {total}",
    },
    "wizard.chatProgressDone": {
        "en": "All done — {total} questions", "zh-CN": "聊完啦，共 {total} 题",
        "es": "Listo: {total} preguntas", "fr": "Terminé : {total} questions",
        "pt-BR": "Pronto: {total} perguntas", "ar": "تم كل شيء: {total} أسئلة",
    },
    "wizard.chatSummary": {
        "en": "Here's what I noted down: {summary}",
        "zh-CN": "我记下了：{summary}",
        "es": "Esto es lo que anoté: {summary}",
        "fr": "Voilà ce que j'ai noté : {summary}",
        "pt-BR": "Isto é o que anotei: {summary}",
        "ar": "هذا ما دوّنته: {summary}",
    },
    "wizard.chatSummaryEmpty": {
        "en": "No worries if you skipped everything — I'll note no preferences and we can look at the results directly.",
        "zh-CN": "你什么都没说也没关系，我先不记偏好，直接看结果也行～",
        "es": "No pasa nada si lo saltaste todo: no anoto preferencias y miramos los resultados directamente.",
        "fr": "Aucun souci si tu as tout passé : je ne note aucune préférence et on regarde les résultats directement.",
        "pt-BR": "Sem problema se você pulou tudo: não vou anotar preferências e vamos direto aos resultados.",
        "ar": "لا بأس إن تخطيت كل شيء: لن أدوّن أي تفضيلات وسننتقل إلى النتائج مباشرة.",
    },
    "wizard.chatSalaryNote": {
        "en": "I have no official salary data to compare against, so I'll just note your expectation.",
        "zh-CN": "薪资这块我没有官方数据对照，先记下你的期望就好啦。",
        "es": "No tengo datos oficiales de salarios para comparar, así que solo anoto tu expectativa.",
        "fr": "Je n'ai pas de données officielles sur les salaires pour comparer, je note juste ton attente.",
        "pt-BR": "Não tenho dados oficiais de salários para comparar, então só vou anotar sua expectativa.",
        "ar": "ليست لدي بيانات رسمية عن الرواتب للمقارنة، لذا سأدوّن توقعك فقط.",
    },
    "wizard.chatOpThanks": {
        "en": "Got it, noted!", "zh-CN": "收到，记下啦～",
        "es": "¡Entendido, anotado!", "fr": "Noté, merci !",
        "pt-BR": "Entendi, anotado!", "ar": "فهمت، تم التدوين!",
    },
    "wizard.chatOpGB": {
        "en": "London has {schools}, all right in the city centre — I hear the vibe is great!",
        "zh-CN": "伦敦那边有{schools}，都在市中心，听说氛围不错耶！",
        "es": "En Londres están {schools}, en pleno centro: ¡dicen que el ambiente es genial!",
        "fr": "À Londres, il y a {schools}, en plein centre-ville — on dit que l'ambiance y est super !",
        "pt-BR": "Em Londres ficam {schools}, bem no centro da cidade — dizem que o clima lá é ótimo!",
        "ar": "في لندن توجد {schools}، في وسط المدينة تمامًا — سمعت أن الأجواء هناك رائعة!",
    },
    "wizard.chatOpSG": {
        "en": "Singapore has {schools} — and it's summer all year round there. Could you handle that?",
        "zh-CN": "新加坡那边有{schools}，一年四季都是夏天，你受得了吗？",
        "es": "En Singapur están {schools}, ¡y es verano todo el año! ¿Lo aguantarías?",
        "fr": "À Singapour, il y a {schools} — et c'est l'été toute l'année ! Tu supporterais ?",
        "pt-BR": "Em Singapura ficam {schools} — e é verão o ano todo! Você aguentaria?",
        "ar": "في سنغافورة توجد {schools} — والصيف هناك طوال العام! هل تستطيع تحمل ذلك؟",
    },
    "wizard.chatOpWarm": {
        "en": "You like it warm — Singapore is summer all year round, could you handle that?",
        "zh-CN": "喜欢暖和的呀，那新加坡那边一年四季都是夏天，你受得了吗？",
        "es": "Te gusta el calor: en Singapur es verano todo el año, ¿lo aguantarías?",
        "fr": "Tu aimes la chaleur : à Singapour, c'est l'été toute l'année, tu supporterais ?",
        "pt-BR": "Você gosta de calor: em Singapura é verão o ano todo, você aguentaria?",
        "ar": "تحب الدفء: في سنغافورة الصيف طوال العام، هل تستطيع تحمل ذلك؟",
    },
    # --- Climate opinions (round 6, 2026-11-26): the pet answers a climate
    # preference with the best matching city from the climate table
    # (Edinburgh for cool, Seoul for four seasons, London for mild).
    "wizard.chatOpCool": {
        "en": "Cool weather fan — Edinburgh is cool all year round, with {count} verified programmes there. How does that sound?",
        "zh-CN": "喜欢凉快的呀，爱丁堡那边一年四季都挺凉的，有 {count} 个已核实的专业，你觉得怎么样？",
        "es": "Te gusta el fresco: en Edimburgo hace fresco todo el año, con {count} programas verificados. ¿Qué te parece?",
        "fr": "Tu aimes la fraîcheur : à Édimbourg, il fait frais toute l'année, avec {count} programmes vérifiés. Ça te dit ?",
        "pt-BR": "Você gosta de frio: em Edimburgo faz frio o ano todo, com {count} programas verificados. O que acha?",
        "ar": "تحب البرودة: في إدنبرة الجو بارد طوال العام، وهناك {count} برامج موثقة. ما رأيك؟",
    },
    "wizard.chatOpFourSeasons": {
        "en": "Four seasons, right? Seoul has all four in full, with {count} verified programmes there. Tempted?",
        "zh-CN": "喜欢四季分明呀，首尔那边四季都很分明，有 {count} 个已核实的专业，心动不？",
        "es": "Cuatro estaciones, ¿verdad? En Seúl se viven las cuatro a fondo, con {count} programas verificados. ¿Te tienta?",
        "fr": "Quatre saisons, n'est-ce pas ? À Séoul, les quatre sont bien marquées, avec {count} programmes vérifiés. Tenté ?",
        "pt-BR": "Quatro estações, né? Em Seul as quatro são bem marcadas, com {count} programas verificados. Animou?",
        "ar": "تحب الفصول الأربعة، أليس كذلك؟ في سيول الفصول الأربعة واضحة تمامًا، وهناك {count} برامج موثقة. هل أعجبك ذلك؟",
    },
    "wizard.chatOpMild": {
        "en": "Mild weather — London is mild all year round, with {count} verified programmes there. Sound good?",
        "zh-CN": "喜欢温和的天气呀，伦敦那边一年四季都很温和，有 {count} 个已核实的专业，怎么样？",
        "es": "Clima templado: en Londres es suave todo el año, con {count} programas verificados. ¿Te parece bien?",
        "fr": "Un climat doux : à Londres, il est doux toute l'année, avec {count} programmes vérifiés. Ça te va ?",
        "pt-BR": "Clima ameno: em Londres é ameno o ano todo, com {count} programas verificados. Parece bom?",
        "ar": "تحب الطقس المعتدل: في لندن الطقس معتدل طوال العام، وهناك {count} برامج موثقة. هل يعجبك ذلك؟",
    },
    "wizard.chatOpSGCool": {
        "en": "Heads up — Singapore is warm all year round, which clashes with the cool weather you wanted. Still want it on the list?",
        "zh-CN": "提醒一下哦，新加坡一年四季都是夏天，跟你想要的凉快天气有点冲突，还要把它留在备选里吗？",
        "es": "Ojo: en Singapur hace calor todo el año, y eso choca con el fresquito que buscas. ¿Aun así lo dejamos en la lista?",
        "fr": "Attention : à Singapour, il fait chaud toute l'année, ce qui ne colle pas avec la fraîcheur que tu veux. On le garde quand même dans la liste ?",
        "pt-BR": "Atenção: em Singapura faz calor o ano todo, o que não combina com o frio que você quer. Ainda assim deixo na lista?",
        "ar": "تنبيه: في سنغافورة الجو حار طوال العام، وهذا يتعارض مع البرودة التي تريدها. هل تريد إبقاءها في القائمة؟",
    },
    "results.prefClimateConflict": {
        "en": "This city's climate clashes with the climate you wanted — kept in the list, just ranked lower.",
        "zh-CN": "这座城市的气候跟你想要的不太合，留着没删，只是排后了一点。",
        "es": "El clima de esta ciudad no coincide con el que buscas: se queda en la lista, solo más abajo.",
        "fr": "Le climat de cette ville ne correspond pas à celui que tu veux : elle reste dans la liste, juste plus bas.",
        "pt-BR": "O clima desta cidade não combina com o que você quer: continua na lista, só mais abaixo.",
        "ar": "مناخ هذه المدينة لا يناسب المناخ الذي تريده — بقيت في القائمة، لكن في مرتبة أدنى.",
    },
    "wizard.recChatClimateConflict": {
        "en": "Heads up: {city} doesn't match the {climate} weather you asked for.",
        "zh-CN": "提醒一下，{city}的气候跟你想要的{climate}不太合哦。",
        "es": "Ojo: {city} no coincide con el clima {climate} que pediste.",
        "fr": "Attention : {city} ne correspond pas au climat {climate} que tu as demandé.",
        "pt-BR": "Atenção: {city} não combina com o clima {climate} que você pediu.",
        "ar": "تنبيه: {city} لا تطابق طقس {climate} الذي طلبته.",
    },
    "wizard.chatOpCity": {
        "en": "Noted {city} — there are {count} verified programmes there, take your time browsing!",
        "zh-CN": "{city}我记下了，那边有 {count} 个已核实的专业，你慢慢挑～",
        "es": "Anotado: {city}. Hay {count} programas verificados allí, ¡míralos con calma!",
        "fr": "Noté : {city}. Il y a {count} programmes vérifiés là-bas, prends ton temps !",
        "pt-BR": "Anotado: {city}. Há {count} programas verificados por lá, veja com calma!",
        "ar": "تم التدوين: {city}. هناك {count} برامج موثقة هناك، تصفحها على مهل!",
    },
    "wizard.chatOpAfterGradUndecided": {
        "en": "That's totally fine — no need to decide so far ahead, you can figure it out once you're there.",
        "zh-CN": "没关系呀，先不想那么远，到了那边再慢慢想～",
        "es": "No pasa nada: no hace falta decidirlo tan pronto, ya lo pensarás cuando estés allí.",
        "fr": "Aucun souci : pas besoin de décider si tôt, tu y réfléchiras une fois sur place.",
        "pt-BR": "Sem problema: não precisa decidir tão cedo, você pensa nisso quando estiver lá.",
        "ar": "لا بأس إطلاقًا: لا داعي للقرار الآن، يمكنك التفكير في ذلك عندما تصل إلى هناك.",
    },
    "wizard.chatOpSalary": {
        "en": "I have no official salary data to compare against, so I'll just note your expectation — it won't be used to rank schools.",
        "zh-CN": "薪资这块我没有官方数据对照，先帮你记下期望，不拿它来排学校哦～",
        "es": "No tengo datos oficiales de salarios para comparar, así que solo anoto tu expectativa: no se usará para ordenar universidades.",
        "fr": "Je n'ai pas de données officielles sur les salaires pour comparer, je note juste ton attente — ça ne servira pas à classer les universités.",
        "pt-BR": "Não tenho dados oficiais de salários para comparar, então só vou anotar sua expectativa — não será usada para classificar universidades.",
        "ar": "ليست لدي بيانات رسمية عن الرواتب للمقارنة، لذا سأدوّن توقعك فقط — ولن تُستخدم لترتيب الجامعات.",
    },
    "wizard.chatOpPressureLow": {
        "en": "No rush — taking it at your own pace matters most.",
        "zh-CN": "没事，慢慢来最重要，找到适合自己的节奏就好～",
        "es": "Sin prisa: lo importante es ir a tu propio ritmo.",
        "fr": "Pas de précipitation : l'essentiel, c'est d'aller à ton rythme.",
        "pt-BR": "Sem pressa: o importante é ir no seu próprio ritmo.",
        "ar": "لا تستعجل: الأهم أن تسير وفق إيقاعك الخاص.",
    },
    # --- Recommend chat (wizard step 8, 2026-11-25): the confirmation
    # page became a chat too. Comments use only verified data (status,
    # intake, fee vs the user's own budget, same currency only).
    "wizard.recChatTitle": {
        "en": "Little Compass's picks", "zh-CN": "小罗盘的推荐",
        "es": "Las elegidas de la Brújula", "fr": "Les choix de la Petite Boussole",
        "pt-BR": "As escolhas da Bussolinha", "ar": "اختيارات البوصلة الصغيرة",
    },
    "wizard.recChatNote": {
        "en": "Filtered by your conditions; every comment sticks to verified facts.",
        "zh-CN": "按你的条件筛出来的，点评只说已核实的东西。",
        "es": "Filtradas según tus condiciones; cada comentario se basa solo en datos verificados.",
        "fr": "Filtrés selon tes conditions ; chaque commentaire s'appuie uniquement sur des données vérifiées.",
        "pt-BR": "Filtradas pelas suas condições; cada comentário usa apenas dados verificados.",
        "ar": "مصفاة وفق شروطك؛ كل تعليق يعتمد على بيانات موثقة فقط.",
    },
    "wizard.recChatIntro": {
        "en": "All right, I went through your conditions — here are the ones I think fit you best!",
        "zh-CN": "好啦，我按你的条件筛了一遍，这几所我觉得最适合你～",
        "es": "¡Listo! Revisé tus condiciones y estas son las que más te encajan.",
        "fr": "Voilà, j'ai passé tes conditions en revue — voici celles qui te correspondent le mieux !",
        "pt-BR": "Pronto! Revisei suas condições — estas são as que mais combinam com você!",
        "ar": "حسنًا، راجعت شروطك — هذه البرامج هي الأنسب لك!",
    },
    "wizard.recChatMet": {
        "en": "You meet all of this programme's requirements.",
        "zh-CN": "你的条件都符合这所的要求。",
        "es": "Cumples todos los requisitos de este programa.",
        "fr": "Tu remplis toutes les conditions de ce programme.",
        "pt-BR": "Você atende a todos os requisitos deste programa.",
        "ar": "أنت تستوفي جميع متطلبات هذا البرنامج.",
    },
    "wizard.recChatPartial": {
        "en": "A few things are still uncertain — extra documents might help.",
        "zh-CN": "有几项还不确定，补上材料可能更稳。",
        "es": "Aún hay cosas por confirmar: con más documentos podría ir mejor.",
        "fr": "Quelques points restent incertains — des documents en plus pourraient aider.",
        "pt-BR": "Alguns pontos ainda estão incertos — mais documentos podem ajudar.",
        "ar": "بعض النقاط ما زالت غير مؤكدة — مستندات إضافية قد تساعد.",
    },
    "wizard.recChatNotMet": {
        "en": "A few things don't quite fit here — keep it as a reference.",
        "zh-CN": "这所有几项不太符合，先放着参考。",
        "es": "Aquí hay cosas que no encajan del todo: déjalo como referencia.",
        "fr": "Quelques points ne correspondent pas tout à fait ici — garde-le comme référence.",
        "pt-BR": "Alguns pontos não batem muito aqui — guarde como referência.",
        "ar": "بعض النقاط لا تناسب هنا تمامًا — احتفظ به كمرجع.",
    },
    "wizard.recChatFee": {
        "en": "Tuition {fee}.", "zh-CN": "学费 {fee}。",
        "es": "Matrícula: {fee}.", "fr": "Frais de scolarité : {fee}.",
        "pt-BR": "Mensalidade: {fee}.", "ar": "الرسوم الدراسية: {fee}.",
    },
    "wizard.recChatFeeAbove": {
        "en": "Tuition {fee} — a bit above your budget, worth another thought.",
        "zh-CN": "学费 {fee}，比你的预算高一点，要再想想哦。",
        "es": "Matrícula: {fee}, un poco por encima de tu presupuesto. Vale la pena pensarlo.",
        "fr": "Frais de scolarité : {fee} — un peu au-dessus de ton budget, ça vaut le coup d'y réfléchir.",
        "pt-BR": "Mensalidade: {fee} — um pouco acima do seu orçamento, vale pensar melhor.",
        "ar": "الرسوم الدراسية: {fee} — أعلى قليلًا من ميزانيتك، يستحق التفكير.",
    },
    "wizard.recChatFeeWithin": {
        "en": "Tuition {fee} — within your budget.",
        "zh-CN": "学费 {fee}，在你的预算内。",
        "es": "Matrícula: {fee}, dentro de tu presupuesto.",
        "fr": "Frais de scolarité : {fee} — dans ton budget.",
        "pt-BR": "Mensalidade: {fee} — dentro do seu orçamento.",
        "ar": "الرسوم الدراسية: {fee} — ضمن ميزانيتك.",
    },
    "wizard.recChatIntake": {
        "en": "Starts {intake}.", "zh-CN": "{intake}入学。",
        "es": "Empieza en {intake}.", "fr": "Rentrée : {intake}.",
        "pt-BR": "Início em {intake}.", "ar": "تبدأ في {intake}.",
    },
    "wizard.recChatMore": {
        "en": "Show me another batch", "zh-CN": "换一批看看",
        "es": "Ver otro grupo", "fr": "Voir un autre groupe",
        "pt-BR": "Ver outro grupo", "ar": "اعرض مجموعة أخرى",
    },
    "wizard.recChatEditPrefs": {
        "en": "Let me tweak my preferences", "zh-CN": "我再改改偏好",
        "es": "Quiero ajustar mis preferencias", "fr": "Je veux ajuster mes préférences",
        "pt-BR": "Quero ajustar minhas preferências", "ar": "أريد تعديل تفضيلاتي",
    },
    "wizard.recChatTypePlaceholder": {
        "en": "Try naming a country or a city — or ask me anything…",
        "zh-CN": "试着说一个国家或城市，或者直接问我…",
        "es": "Prueba con un país o una ciudad… o pregúntame lo que sea…",
        "fr": "Essaie un pays ou une ville… ou pose-moi une question…",
        "pt-BR": "Tente dizer um país ou uma cidade… ou pergunte o que quiser…",
        "ar": "جرّب ذكر بلد أو مدينة… أو اسألني أي شيء…",
    },
    "wizard.recChatFilteredCountry": {
        "en": "Got it — showing only {country} for now!",
        "zh-CN": "好，我只留{country}的给你看～",
        "es": "¡Hecho! Te muestro solo {country} por ahora.",
        "fr": "C'est fait — je te montre seulement {country} pour l'instant !",
        "pt-BR": "Pronto! Mostrando só {country} por enquanto!",
        "ar": "تم! أعرض {country} فقط الآن!",
    },
    "wizard.recChatFilteredCity": {
        "en": "Got it — showing only {city} for now!",
        "zh-CN": "好，我只留{city}的给你看～",
        "es": "¡Hecho! Te muestro solo {city} por ahora.",
        "fr": "C'est fait — je te montre seulement {city} pour l'instant !",
        "pt-BR": "Pronto! Mostrando só {city} por enquanto!",
        "ar": "تم! أعرض {city} فقط الآن!",
    },
    "wizard.recChatUnknown": {
        "en": "I didn't quite catch that… you can tap a button below, or try rephrasing — for example, name a country or a city.",
        "zh-CN": "这个我没太听懂…你可以直接点下面的按钮，或者换个说法，比如说一个国家或城市的名字。",
        "es": "No te entendí del todo… Puedes tocar un botón de abajo o decirlo de otra forma, por ejemplo, el nombre de un país o una ciudad.",
        "fr": "Je n'ai pas bien compris… Tu peux toucher un bouton ci-dessous, ou reformuler — par exemple, le nom d'un pays ou d'une ville.",
        "pt-BR": "Não entendi muito bem… Você pode tocar num botão abaixo ou dizer de outro jeito — por exemplo, o nome de um país ou uma cidade.",
        "ar": "لم أفهم تمامًا… يمكنك الضغط على أحد الأزرار أدناه أو إعادة الصياغة — مثلًا، باسم دولة أو مدينة.",
    },
    "wizard.recChatClearFilter": {
        "en": "Show all", "zh-CN": "看全部",
        "es": "Ver todo", "fr": "Tout afficher",
        "pt-BR": "Ver tudo", "ar": "عرض الكل",
    },
    "wizard.recChatBatch": {
        "en": "Batch {n} of {total}", "zh-CN": "第 {n} 批，共 {total} 批",
        "es": "Grupo {n} de {total}", "fr": "Groupe {n} sur {total}",
        "pt-BR": "Grupo {n} de {total}", "ar": "المجموعة {n} من {total}",
    },
    # --- Welcome banner, returning-visit variant (2026-11-25): the
    # banner now shows every session, with different copy once a check
    # is done.
    "home.welcomeBackTitle": {
        "en": "Welcome back!", "zh-CN": "欢迎回来！",
        "es": "¡Bienvenido de nuevo!", "fr": "Bon retour !",
        "pt-BR": "Bem-vindo de volta!", "ar": "مرحبًا بعودتك!",
    },
    "home.welcomeBackBody": {
        "en": "Your eligibility check is done — see how your matches look.",
        "zh-CN": "你的资格检查已完成，看看匹配结果如何。",
        "es": "Tu comprobación de elegibilidad está lista: mira cómo van tus coincidencias.",
        "fr": "Ta vérification d'éligibilité est terminée — regarde tes résultats.",
        "pt-BR": "Sua verificação de elegibilidade está pronta — veja seus resultados.",
        "ar": "اكتمل فحص الأهلية الخاص بك — اطّلع على نتائج المطابقة.",
    },
    "home.welcomeBackCta": {
        "en": "See my results", "zh-CN": "查看我的结果",
        "es": "Ver mis resultados", "fr": "Voir mes résultats",
        "pt-BR": "Ver meus resultados", "ar": "عرض نتائجي",
    },
    # --- Results page, pet-voiced preference line (2026-11-25): the
    # summary is not just a field list. Only countries / cities that
    # actually appear in the verified results are named.
    "results.prefVoiceCountries": {
        "en": "As you said, I've marked the {countries} schools in your results — take your time!",
        "zh-CN": "按你说的，{countries}的学校我在结果里帮你标出来了，慢慢挑～",
        "es": "Como dijiste, marqué las universidades de {countries} en tus resultados. ¡Míralas con calma!",
        "fr": "Comme tu me l'as dit, j'ai marqué les universités de {countries} dans tes résultats — prends ton temps !",
        "pt-BR": "Como você disse, marquei as universidades de {countries} nos seus resultados — veja com calma!",
        "ar": "كما قلت، علّمت جامعات {countries} في نتائجك — تصفحها على مهل!",
    },
    "results.prefVoiceCity": {
        "en": "There are {count} verified programmes in {city} in your results — take your time!",
        "zh-CN": "{city}有 {count} 个已核实的专业在结果里，慢慢挑～",
        "es": "Hay {count} programas verificados en {city} en tus resultados. ¡Míralos con calma!",
        "fr": "Il y a {count} programmes vérifiés à {city} dans tes résultats — prends ton temps !",
        "pt-BR": "Há {count} programas verificados em {city} nos seus resultados — veja com calma!",
        "ar": "هناك {count} برامج موثقة في {city} ضمن نتائجك — تصفحها على مهل!",
    },
    # --- Fan carousel arrows (2026-11-25).
    "home.carouselPrev": {
        "en": "Previous", "zh-CN": "上一个",
        "es": "Anterior", "fr": "Précédent",
        "pt-BR": "Anterior", "ar": "السابق",
    },
    "home.carouselNext": {
        "en": "Next", "zh-CN": "下一个",
        "es": "Siguiente", "fr": "Suivant",
        "pt-BR": "Próximo", "ar": "التالي",
    },
    # --- School reviews carousel (2026-11-25). No rating / stars data.
    "home.reviewsTitle": {
        "en": "School reviews", "zh-CN": "学校评价",
        "es": "Opiniones sobre las universidades", "fr": "Avis sur les universités",
        "pt-BR": "Avaliações das universidades", "ar": "آراء حول الجامعات",
    },
    "home.reviewsSub": {
        "en": "Study experiences and reviews shared by netizens — as the posters shared them, not officially verified.",
        "zh-CN": "网友分享的在读体验与评价——均为发帖人自述，未经官方核实。",
        "es": "Experiencias y opiniones compartidas por usuarios: tal como las contaron, sin verificación oficial.",
        "fr": "Expériences et avis partagés par des internautes — tels qu'ils les ont racontés, sans vérification officielle.",
        "pt-BR": "Experiências e avaliações compartilhadas por internautas — como foram contadas, sem verificação oficial.",
        "ar": "تجارب وآراء شاركها مستخدمو الإنترنت — كما رووها، دون توثيق رسمي.",
    },
}


def add_locale_keys():
    for loc in LOCALES:
        path = os.path.join(MESSAGES_DIR, f"{loc}.json")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for key, per_locale in TRANSLATIONS.items():
            value = per_locale.get(loc)
            if not value or not value.strip():
                raise SystemExit(f"missing {loc} translation for {key}")
            if key in data:
                # Idempotent re-run: identical value is fine, a conflict is not.
                if data[key] != value:
                    raise SystemExit(f"{loc}.json has a different value for {key}")
                continue
            data[key] = value
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
            f.write("\n")
    return len(TRANSLATIONS)


def main():
    n_exp = generate_expansion()
    n_climate = generate_climate()
    n_cases = generate_cases()
    n_rev = generate_reviews()
    n_keys = add_locale_keys()
    print(f"expansion programmes: {n_exp}")
    print(f"climate cities: {n_climate}")
    print(f"success cases: {n_cases}")
    print(f"school reviews: {n_rev}")
    print(f"locale keys added x6: {n_keys}")


if __name__ == "__main__":
    main()

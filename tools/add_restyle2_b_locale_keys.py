"""Add the Restyle 2 behaviour-half keys to all 6 locale files.

New keys (10): pet.suggestDeadlines / pet.suggestCompare /
pet.suggestDocuments (the pet greeting's 3 quick suggestions),
pet.planChangeAsk / pet.planConfirm / pet.planSkip (the plan-change
confirm bubble, Gen UI "Selected N + Skip" pattern),
pet.summaryMissing (the proactive summary's still-missing list),
results.trackingTitle / results.trackingDaysLeft /
results.trackingInterview (the follow-up tracking section on
/results).
Run: python3 tools/add_restyle2_b_locale_keys.py (from the project root).
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MESSAGES = ROOT / "frontend" / "messages"

NEW_KEYS: dict[str, dict[str, str]] = {
    "pet.suggestDeadlines": {
        "en": "Check deadlines",
        "zh-CN": "查截止日期",
        "es": "Revisar los plazos",
        "fr": "Vérifier les délais",
        "pt-BR": "Verificar os prazos",
        "ar": "التحقق من المواعيد النهائية",
    },
    "pet.suggestCompare": {
        "en": "Compare schools",
        "zh-CN": "比较学校",
        "es": "Comparar universidades",
        "fr": "Comparer les écoles",
        "pt-BR": "Comparar universidades",
        "ar": "مقارنة الجامعات",
    },
    "pet.suggestDocuments": {
        "en": "Prepare documents",
        "zh-CN": "准备申请材料",
        "es": "Preparar los documentos",
        "fr": "Préparer les documents",
        "pt-BR": "Preparar os documentos",
        "ar": "تجهيز المستندات",
    },
    "pet.planChangeAsk": {
        "en": "Update your plan with this change?",
        "zh-CN": "要按这个变化更新你的计划吗？",
        "es": "¿Actualizo tu plan con este cambio?",
        "fr": "Mettre à jour votre plan avec ce changement ?",
        "pt-BR": "Atualizar seu plano com esta mudança?",
        "ar": "هل أُحدِث خطتك بهذا التغيير؟",
    },
    "pet.planConfirm": {
        "en": "Confirm change",
        "zh-CN": "确认更改",
        "es": "Confirmar el cambio",
        "fr": "Confirmer le changement",
        "pt-BR": "Confirmar a alteração",
        "ar": "تأكيد التغيير",
    },
    "pet.planSkip": {
        "en": "Skip",
        "zh-CN": "跳过",
        "es": "Omitir",
        "fr": "Ignorer",
        "pt-BR": "Pular",
        "ar": "تخطَّ",
    },
    "pet.summaryMissing": {
        "en": "Still missing",
        "zh-CN": "尚未填写",
        "es": "Aún falta",
        "fr": "Encore manquant",
        "pt-BR": "Ainda falta",
        "ar": "ما زال ناقصًا",
    },
    "results.trackingTitle": {
        "en": "Follow-up tracking",
        "zh-CN": "申请跟进",
        "es": "Seguimiento",
        "fr": "Suivi",
        "pt-BR": "Acompanhamento",
        "ar": "المتابعة",
    },
    "results.trackingDaysLeft": {
        "en": "{days} days left",
        "zh-CN": "还剩 {days} 天",
        "es": "Quedan {days} días",
        "fr": "Plus que {days} jours",
        "pt-BR": "Faltam {days} dias",
        "ar": "متبقٍ {days} يوم",
    },
    "results.trackingInterview": {
        "en": "Interview steps",
        "zh-CN": "面试环节",
        "es": "Pasos de la entrevista",
        "fr": "Étapes d’entretien",
        "pt-BR": "Etapas da entrevista",
        "ar": "خطوات المقابلة",
    },
}

LOCALES = ["en", "zh-CN", "es", "fr", "pt-BR", "ar"]


def main() -> None:
    for loc in LOCALES:
        path = MESSAGES / f"{loc}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for key, values in NEW_KEYS.items():
            assert key not in data, f"{loc}: {key} already exists"
            assert set(values) == set(LOCALES), f"{key} missing a locale"
            assert all(v.strip() for v in values.values()), f"{key} has an empty value"
            data[key] = values[loc]
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )
        print(f"{loc}.json: {len(data)} keys")


if __name__ == "__main__":
    main()

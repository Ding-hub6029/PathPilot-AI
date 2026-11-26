"""Add the round 7 chat keys to all 6 locale files.

New keys (18): model-led PrefChat progress ("已了解 X / 8 项" + the
still-missing items), the honest offline line for the model-led chat,
the no-verified-cities line, the country-scoped climate opinion keys,
the AI retry action, the backend-waking line, and the pet's
saved-preferences greeting.
Also removes 6 keys the scoped opinions / count-based progress replace:
wizard.chatOpCool, wizard.chatOpFourSeasons, wizard.chatOpMild and
wizard.chatOpWarm (each hardcoded a city the user may not have chosen —
Edinburgh / Seoul / London / Singapore — replaced by the generic
wizard.chatOpClimateCity + wizard.chatOpClimateNoMatch), and
wizard.chatProgress / wizard.chatProgressDone ("第 n / 8 题", replaced
by the count-based wizard.chatPrefProgress).
Run: python3 tools/add_round7_locale_keys.py (from the project root).
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MESSAGES = ROOT / "frontend" / "messages"

NEW_KEYS: dict[str, dict[str, str]] = {
    "wizard.chatPrefProgress": {
        "en": "Understood {n} of {total}",
        "zh-CN": "已了解 {n} / {total} 项",
        "es": "Entendido {n} de {total}",
        "fr": "Compris {n} sur {total}",
        "pt-BR": "Entendido {n} de {total}",
        "ar": "تم فهم {n} من {total}",
    },
    "wizard.chatPrefRemaining": {
        "en": "Still to learn: {items}",
        "zh-CN": "还差：{items}",
        "es": "Aún falta: {items}",
        "fr": "Reste à connaître : {items}",
        "pt-BR": "Ainda falta: {items}",
        "ar": "ما زال ينقص: {items}",
    },
    "wizard.chatPrefNameCountries": {
        "en": "Countries",
        "zh-CN": "国家",
        "es": "Países",
        "fr": "Pays",
        "pt-BR": "Países",
        "ar": "البلدان",
    },
    "wizard.chatPrefNameClimate": {
        "en": "Climate",
        "zh-CN": "气候",
        "es": "Clima",
        "fr": "Climat",
        "pt-BR": "Clima",
        "ar": "المناخ",
    },
    "wizard.chatPrefNameEnvironment": {
        "en": "Environment",
        "zh-CN": "环境",
        "es": "Entorno",
        "fr": "Cadre de vie",
        "pt-BR": "Ambiente",
        "ar": "البيئة",
    },
    "wizard.chatPrefNameCity": {
        "en": "City",
        "zh-CN": "城市",
        "es": "Ciudad",
        "fr": "Ville",
        "pt-BR": "Cidade",
        "ar": "المدينة",
    },
    "wizard.chatPrefNameAfterGrad": {
        "en": "After graduation",
        "zh-CN": "毕业去向",
        "es": "Tras graduarte",
        "fr": "Après les études",
        "pt-BR": "Depois da formatura",
        "ar": "بعد التخرج",
    },
    "wizard.chatPrefNameSalary": {
        "en": "Salary hopes",
        "zh-CN": "期望薪资",
        "es": "Salario esperado",
        "fr": "Salaire espéré",
        "pt-BR": "Salário esperado",
        "ar": "الراتب المتوقع",
    },
    "wizard.chatPrefNamePressure": {
        "en": "Pressure",
        "zh-CN": "学业压力",
        "es": "Presión",
        "fr": "Pression",
        "pt-BR": "Pressão",
        "ar": "الضغط الدراسي",
    },
    "wizard.chatPrefNameTeaching": {
        "en": "Teaching style",
        "zh-CN": "上课方式",
        "es": "Estilo de clase",
        "fr": "Façon d'apprendre",
        "pt-BR": "Estilo de aula",
        "ar": "أسلوب التدريس",
    },
    "wizard.chatPrefOffline": {
        "en": "The AI chat can't be reached right now, so I'll ask the guided questions instead — nothing here pretends to be an AI answer.",
        "zh-CN": "AI 对话暂时连不上，我先用引导问题继续问你，这里不会有假装是 AI 的回答。",
        "es": "El chat de IA no está disponible ahora, así que seguiré con las preguntas guiadas; nada aquí fingirá ser una respuesta de IA.",
        "fr": "Le chat IA est injoignable pour le moment, je passe aux questions guidées — rien ici ne se fera passer pour une réponse d'IA.",
        "pt-BR": "O chat de IA não está acessível agora, então vou seguir com as perguntas guiadas — nada aqui vai fingir ser uma resposta de IA.",
        "ar": "تعذّر الوصول إلى محادثة الذكاء الاصطناعي الآن، لذا سأتابع بالأسئلة الموجَّهة — ولن يتظاهر أي شيء هنا بأنه إجابة ذكاء اصطناعي.",
    },
    "wizard.chatNoCityChips": {
        "en": "No verified programme cities for the countries you picked yet — just type the city you have in mind.",
        "zh-CN": "你选的国家还没有已核实的城市，先直接告诉我你想去的城市吧。",
        "es": "Aún no hay ciudades con programas verificados para los países elegidos; escribe la ciudad que tienes en mente.",
        "fr": "Aucune ville avec des programmes vérifiés pour les pays choisis pour l'instant — écris simplement la ville à laquelle tu penses.",
        "pt-BR": "Ainda não há cidades com programas verificados para os países escolhidos — digite a cidade que você tem em mente.",
        "ar": "لا توجد مدن ببرامج موثّقة بعد للبلدان التي اخترتها — اكتب المدينة التي تفكر فيها.",
    },
    "wizard.chatOpClimateCity": {
        "en": "{city} has a {climate} climate, with {count} verified programmes there. How does that sound?",
        "zh-CN": "{city}是{climate}气候，那边有 {count} 个已核实的专业，你觉得怎么样？",
        "es": "{city} tiene clima {climate}, con {count} programas verificados. ¿Qué te parece?",
        "fr": "À {city}, le climat est {climate}, avec {count} programmes vérifiés. Ça te dit ?",
        "pt-BR": "Em {city} o clima é {climate}, com {count} programas verificados. O que acha?",
        "ar": "مناخ {city} هو {climate}، وهناك {count} برامج موثّقة. ما رأيك؟",
    },
    "wizard.chatOpClimateNoMatch": {
        "en": "None of the cities in your chosen countries has a {want} climate: {cities}. Want to try a different climate, or another country?",
        "zh-CN": "你选的国家里没有{want}气候的城市：{cities}。要换个气候偏好，或者换个国家看看吗？",
        "es": "Ninguna ciudad de tus países elegidos tiene clima {want}: {cities}. ¿Quieres probar otro clima u otro país?",
        "fr": "Aucune ville de tes pays choisis n'a un climat {want} : {cities}. Tu veux essayer un autre climat, ou un autre pays ?",
        "pt-BR": "Nenhuma cidade dos países escolhidos tem clima {want}: {cities}. Quer tentar outro clima ou outro país?",
        "ar": "لا توجد مدينة في البلدان التي اخترتها بمناخ {want}: {cities}. هل تريد تجربة مناخ آخر أو بلد آخر؟",
    },
    "wizard.chatPrefRetry": {
        "en": "Retry the AI chat",
        "zh-CN": "重新试试 AI 对话",
        "es": "Reintentar el chat de IA",
        "fr": "Réessayer le chat IA",
        "pt-BR": "Tentar o chat de IA novamente",
        "ar": "إعادة محاولة محادثة الذكاء الاصطناعي",
    },
    "pet.waking": {
        "en": "Waking the backend — one moment…",
        "zh-CN": "正在唤醒后端，请稍等…",
        "es": "Despertando el servidor… un momento…",
        "fr": "Réveil du serveur… un instant…",
        "pt-BR": "Acordando o servidor… um momento…",
        "ar": "جارٍ إيقاظ الخادم… لحظة من فضلك…",
    },
    "pet.retry": {
        "en": "Retry",
        "zh-CN": "重试",
        "es": "Reintentar",
        "fr": "Réessayer",
        "pt-BR": "Tentar novamente",
        "ar": "إعادة المحاولة",
    },
    "pet.greetingKnown": {
        "en": "I still remember your preferences: {prefs} — no need to ask all over again.",
        "zh-CN": "我还记得你的偏好：{prefs}，不用再问一遍啦～",
        "es": "Aún recuerdo tus preferencias: {prefs}; no hace falta preguntar todo de nuevo.",
        "fr": "Je me souviens encore de tes préférences : {prefs} — pas besoin de tout redemander.",
        "pt-BR": "Ainda lembro das suas preferências: {prefs} — não preciso perguntar tudo de novo.",
        "ar": "ما زلت أتذكر تفضيلاتك: {prefs} — لا حاجة لإعادة السؤال من جديد.",
    },
}

REMOVED_KEYS = [
    "wizard.chatOpCool",
    "wizard.chatOpFourSeasons",
    "wizard.chatOpMild",
    "wizard.chatOpWarm",
    "wizard.chatProgress",
    "wizard.chatProgressDone",
]

LOCALES = ["en", "zh-CN", "es", "fr", "pt-BR", "ar"]


def main() -> None:
    for loc in LOCALES:
        path = MESSAGES / f"{loc}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in REMOVED_KEYS:
            assert key in data, f"{loc}: {key} missing, cannot remove"
            del data[key]
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

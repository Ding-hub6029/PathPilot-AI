"""Add the round 6 Job A chat keys to all 6 locale files.

New keys (29): pet.aiLive, pet.aiChecking, pet.q3Low/Mid/High,
wizard.chatAiOffline, wizard.chatParseConfirm/Yes/No,
wizard.parse* (19 field labels), wizard.recChatOffline.
Also updates wizard.recChatTypePlaceholder (free text now also asks
the model) and removes pet.rulesMode (it claimed "no live model",
which is no longer true).
Run: python3 tools/add_job_a_locale_keys.py (from the project root).
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MESSAGES = ROOT / "frontend" / "messages"

NEW_KEYS: dict[str, dict[str, str]] = {
    "pet.aiLive": {
        "en": "AI answers · grounded in verified sources",
        "zh-CN": "AI 回答 · 只用已核实资料",
        "es": "Respuestas de IA · solo datos verificados",
        "fr": "Réponses IA · données vérifiées uniquement",
        "pt-BR": "Respostas de IA · só dados verificados",
        "ar": "إجابات الذكاء الاصطناعي · بيانات موثّقة فقط",
    },
    "pet.aiChecking": {
        "en": "Checking the AI connection…",
        "zh-CN": "正在确认 AI 是否可用…",
        "es": "Comprobando la conexión de IA…",
        "fr": "Vérification de la connexion IA…",
        "pt-BR": "Verificando a conexão de IA…",
        "ar": "جارٍ التحقق من اتصال الذكاء الاصطناعي…",
    },
    "pet.q3Low": {
        "en": "Low budget",
        "zh-CN": "预算较低",
        "es": "Presupuesto bajo",
        "fr": "Petit budget",
        "pt-BR": "Orçamento baixo",
        "ar": "ميزانية منخفضة",
    },
    "pet.q3Mid": {
        "en": "Medium budget",
        "zh-CN": "预算中等",
        "es": "Presupuesto medio",
        "fr": "Budget moyen",
        "pt-BR": "Orçamento médio",
        "ar": "ميزانية متوسطة",
    },
    "pet.q3High": {
        "en": "High budget",
        "zh-CN": "预算较高",
        "es": "Presupuesto alto",
        "fr": "Budget élevé",
        "pt-BR": "Orçamento alto",
        "ar": "ميزانية مرتفعة",
    },
    "wizard.chatAiOffline": {
        "en": "The AI can't be reached right now — the guided questions below still work, and I'll only show you labelled offline answers.",
        "zh-CN": "AI 暂时无法连接，下面的引导问题还能继续用，我只会给你标明了“离线”的回答。",
        "es": "La IA no está disponible ahora — las preguntas guiadas siguen funcionando y solo verás respuestas sin conexión etiquetadas.",
        "fr": "L'IA est injoignable pour le moment — les questions guidées fonctionnent toujours, et je ne montrerai que des réponses hors ligne étiquetées.",
        "pt-BR": "A IA não está acessível no momento — as perguntas guiadas continuam funcionando, e só mostrarei respostas off-line marcadas.",
        "ar": "تعذّر الوصول إلى الذكاء الاصطناعي الآن — الأسئلة الموجَّهة أدناه ما زالت تعمل، ولن أعرض إلا إجابات دون اتصال موسومة.",
    },
    "wizard.chatParseConfirm": {
        "en": "I understood you as: {summary}. Is that right?",
        "zh-CN": "我理解你是：{summary}，对吗？",
        "es": "Entendí esto de ti: {summary}. ¿Es correcto?",
        "fr": "J'ai compris ceci : {summary}. C'est bien ça ?",
        "pt-BR": "Entendi isto de você: {summary}. Está certo?",
        "ar": "فهمت منك ما يلي: {summary}. هل هذا صحيح؟",
    },
    "wizard.chatParseYes": {
        "en": "Yes, that's right",
        "zh-CN": "对，就是这样",
        "es": "Sí, así es",
        "fr": "Oui, c'est ça",
        "pt-BR": "Sim, é isso",
        "ar": "نعم، هذا صحيح",
    },
    "wizard.chatParseNo": {
        "en": "No, that's not it",
        "zh-CN": "不对",
        "es": "No, no es eso",
        "fr": "Non, ce n'est pas ça",
        "pt-BR": "Não, não é isso",
        "ar": "لا، ليس هذا",
    },
    "wizard.parseCurriculum": {
        "en": "Curriculum: {value}",
        "zh-CN": "课程体系：{value}",
        "es": "Plan de estudios: {value}",
        "fr": "Programme scolaire : {value}",
        "pt-BR": "Currículo: {value}",
        "ar": "المنهج الدراسي: {value}",
    },
    "wizard.parseGaokao": {
        "en": "Gaokao {value}",
        "zh-CN": "高考 {value}",
        "es": "Gaokao {value}",
        "fr": "Gaokao {value}",
        "pt-BR": "Gaokao {value}",
        "ar": "غاوكاو {value}",
    },
    "wizard.parseGaokaoTotal": {
        "en": "Gaokao total {value}",
        "zh-CN": "高考满分 {value}",
        "es": "Gaokao total {value}",
        "fr": "Gaokao total {value}",
        "pt-BR": "Gaokao total {value}",
        "ar": "المجموع الكلي للغاوكاو {value}",
    },
    "wizard.parseSat": {
        "en": "SAT {value}",
        "zh-CN": "SAT {value}",
        "es": "SAT {value}",
        "fr": "SAT {value}",
        "pt-BR": "SAT {value}",
        "ar": "SAT {value}",
    },
    "wizard.parseAct": {
        "en": "ACT {value}",
        "zh-CN": "ACT {value}",
        "es": "ACT {value}",
        "fr": "ACT {value}",
        "pt-BR": "ACT {value}",
        "ar": "ACT {value}",
    },
    "wizard.parseIb": {
        "en": "IB total {value}",
        "zh-CN": "IB 总分 {value}",
        "es": "IB total {value}",
        "fr": "Total IB {value}",
        "pt-BR": "IB total {value}",
        "ar": "مجموع البكالوريا الدولية {value}",
    },
    "wizard.parseAlevel": {
        "en": "A-levels {value}",
        "zh-CN": "A-level 成绩 {value}",
        "es": "A-levels {value}",
        "fr": "A-levels {value}",
        "pt-BR": "A-levels {value}",
        "ar": "مستويات A {value}",
    },
    "wizard.parseDegree": {
        "en": "Degree field: {value}",
        "zh-CN": "学位方向：{value}",
        "es": "Campo del título: {value}",
        "fr": "Domaine du diplôme : {value}",
        "pt-BR": "Área do diploma: {value}",
        "ar": "مجال الشهادة: {value}",
    },
    "wizard.parseDegreeClass": {
        "en": "Degree class: {value}",
        "zh-CN": "学位等级：{value}",
        "es": "Clasificación del título: {value}",
        "fr": "Mention du diplôme : {value}",
        "pt-BR": "Classificação do diploma: {value}",
        "ar": "تقدير الشهادة: {value}",
    },
    "wizard.parseItYears": {
        "en": "IT experience: {value} years",
        "zh-CN": "IT 工作经验 {value} 年",
        "es": "Experiencia en TI: {value} años",
        "fr": "Expérience en informatique : {value} ans",
        "pt-BR": "Experiência em TI: {value} anos",
        "ar": "خبرة تقنية المعلومات: {value} سنوات",
    },
    "wizard.parseGre": {
        "en": "GRE {value}",
        "zh-CN": "GRE {value}",
        "es": "GRE {value}",
        "fr": "GRE {value}",
        "pt-BR": "GRE {value}",
        "ar": "GRE {value}",
    },
    "wizard.parseGmat": {
        "en": "GMAT {value}",
        "zh-CN": "GMAT {value}",
        "es": "GMAT {value}",
        "fr": "GMAT {value}",
        "pt-BR": "GMAT {value}",
        "ar": "GMAT {value}",
    },
    "wizard.parseIelts": {
        "en": "IELTS overall {value}",
        "zh-CN": "雅思总分 {value}",
        "es": "IELTS general {value}",
        "fr": "IELTS global {value}",
        "pt-BR": "IELTS geral {value}",
        "ar": "الدرجة الكلية لآيلتس {value}",
    },
    "wizard.parseToefl": {
        "en": "TOEFL {value}",
        "zh-CN": "托福 {value}",
        "es": "TOEFL {value}",
        "fr": "TOEFL {value}",
        "pt-BR": "TOEFL {value}",
        "ar": "توفل {value}",
    },
    "wizard.parseIeltsListening": {
        "en": "IELTS listening {value}",
        "zh-CN": "雅思听力 {value}",
        "es": "IELTS listening {value}",
        "fr": "IELTS listening {value}",
        "pt-BR": "IELTS listening {value}",
        "ar": "استماع آيلتس {value}",
    },
    "wizard.parseIeltsReading": {
        "en": "IELTS reading {value}",
        "zh-CN": "雅思阅读 {value}",
        "es": "IELTS reading {value}",
        "fr": "IELTS reading {value}",
        "pt-BR": "IELTS reading {value}",
        "ar": "قراءة آيلتس {value}",
    },
    "wizard.parseIeltsWriting": {
        "en": "IELTS writing {value}",
        "zh-CN": "雅思写作 {value}",
        "es": "IELTS writing {value}",
        "fr": "IELTS writing {value}",
        "pt-BR": "IELTS writing {value}",
        "ar": "كتابة آيلتس {value}",
    },
    "wizard.parseIeltsSpeaking": {
        "en": "IELTS speaking {value}",
        "zh-CN": "雅思口语 {value}",
        "es": "IELTS speaking {value}",
        "fr": "IELTS speaking {value}",
        "pt-BR": "IELTS speaking {value}",
        "ar": "تحدث آيلتس {value}",
    },
    "wizard.parseIntake": {
        "en": "Intake year {value}",
        "zh-CN": "入学年份 {value}",
        "es": "Año de ingreso {value}",
        "fr": "Année d'entrée {value}",
        "pt-BR": "Ano de ingresso {value}",
        "ar": "سنة الالتحاق {value}",
    },
    "wizard.recChatOffline": {
        "en": "The AI can't be reached right now — try naming a country or a city, or use the buttons below.",
        "zh-CN": "AI 暂时无法连接——可以试着说一个国家或城市，或者用下面的按钮。",
        "es": "La IA no está disponible ahora — prueba con un país o una ciudad, o usa los botones de abajo.",
        "fr": "L'IA est injoignable pour le moment — essaie un pays ou une ville, ou utilise les boutons ci-dessous.",
        "pt-BR": "A IA não está acessível no momento — tente dizer um país ou uma cidade, ou use os botões abaixo.",
        "ar": "تعذّر الوصول إلى الذكاء الاصطناعي الآن — جرّب ذكر بلد أو مدينة، أو استخدم الأزرار أدناه.",
    },
}

UPDATED_VALUES: dict[str, dict[str, str]] = {
    "wizard.recChatTypePlaceholder": {
        "en": "Try naming a country or a city — or ask me anything…",
        "zh-CN": "试着说一个国家或城市，或者直接问我…",
        "es": "Prueba con un país o una ciudad… o pregúntame lo que sea…",
        "fr": "Essaie un pays ou une ville… ou pose-moi une question…",
        "pt-BR": "Tente dizer um país ou uma cidade… ou pergunte o que quiser…",
        "ar": "جرّب ذكر بلد أو مدينة… أو اسألني أي شيء…",
    },
}

REMOVED_KEYS = ["pet.rulesMode"]

LOCALES = ["en", "zh-CN", "es", "fr", "pt-BR", "ar"]


def main() -> None:
    for loc in LOCALES:
        path = MESSAGES / f"{loc}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in REMOVED_KEYS:
            data.pop(key, None)
        for key, values in UPDATED_VALUES.items():
            assert key in data, f"{loc}: {key} missing, cannot update"
            data[key] = values[loc]
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

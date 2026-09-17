"""Работодатель запретил отвечать с помощью ИИ.

Живьём 2026-09-17 (лид #1411, `jobs.ashbyhq.com/makai-labs`) в обязательном поле
анкеты стоит прямая просьба: «we ask that you answer the screening questions
without the use of AI writing tools (e.g., ChatGPT) … any use of AI assistance
may lead to disqualification». Ответы наш бот пишет моделью, поэтому подать их
туда — значит нарушить явное условие работодателя и подставить владельца под
снятие с рассмотрения. Такой лид уходит в ручные, а не заполняется молча.

Правило нарочно узкое. Вакансии ПРО ИИ — половина потока (та же #1411 называется
«AI Engineer» и спрашивает про опыт с LLM), и по слову «AI» срабатывать нельзя.
Ловим только связку из трёх частей рядом:

  1. запрет: «without the use of», «do not use», «без использования», …;
  2. инструмент: «ChatGPT», «AI writing tools», «AI assistance», «нейросеть», …;
  3. адресат — кандидат и его ОТВЕТЫ: «you», «your answers», «вы», «анкета».

Третья часть отсекает рассказ компании о себе: «We don't use LLMs for ranking» —
это про их поиск, а не условие для откликающегося.

Здесь только строки: ни сети, ни браузера, ни разметки.
"""
import re

# Запрет. Каждый вариант говорит именно о ПРИМЕНЕНИИ инструмента — «без опыта с
# LLM» под него не подходит и поймано не будет.
_BAN = (
    r"(?:with(?:out|-out)\s+(?:the\s+)?(?:use|using|help|assistance|aid|support)\s+of|"
    r"without\s+using|without\s+any\s+use\s+of|"
    r"(?:do|does|did)\s+not\s+use|don'?t\s+use|"
    r"(?:may|must|should|can|will)\s+not\s+(?:use|be\s+used)|"
    r"no\s+use\s+of|not\s+(?:permitted|allowed)\s+to\s+use|"
    r"refrain\s+from\s+(?:using|the\s+use\s+of)|avoid\s+using|"
    r"prohibit\w*\s+(?:the\s+)?use|"
    r"не\s+использ\w+|без\s+использования|без\s+помощи|запрещ\w*\s+использ\w*)"
)

# Инструмент, которым пишут за кандидата. Голое «AI» сюда не входит намеренно:
# оно стоит в названии половины вакансий.
_TOOL = (
    r"(?:chat\s?-?gpt|gpt-?[0-9o]+|copilot|claude|gemini|bard|deepseek|"
    r"ai\s*[-/]?\s*(?:writing|written|generated|generation|assistance|assistant|"
    r"assisted|tool|tools|chatbot|chat\s+bot|bot)\w*|"
    r"generative\s+ai|gen\s?ai|"
    r"(?:large\s+language\s+model|llm)s?|"
    r"нейросет\w*|чат\s?-?гпт|искусственн\w+\s+интеллект\w*|\bии\b)"
)

# Кому и о чём это сказано. «you» и «вы» здесь работают как признак обращения к
# кандидату — им отличается условие анкеты от рассказа компании о своём стеке.
_ADDRESSEE = re.compile(
    r"\b(?:you|your|yours|applicant|applicants|candidate|candidates|"
    r"answer|answers|answering|respond|response|responses|reply|"
    r"question|questions|questionnaire|application|applications|essay|essays|"
    r"submission|writing\s+sample|cover\s+letter)\b|"
    r"вы|ваш\w*|отвеч\w*|ответ\w*|вопрос\w*|анкет\w*|заявк\w*|кандидат\w*",
    re.IGNORECASE)

# Насколько близко должны стоять запрет и инструмент. Живьём между ними один
# пробел («without the use of AI writing tools»); запас — на вставленное
# «any»/«the help of» и на перенос строки.
_GAP = 60
# Окно, в котором ищется адресат: то самое предложение и соседнее с ним.
_CONTEXT = 220
# Сколько знаков цитаты уходит человеку в заметку.
_QUOTE = 160

_BAN_RE = re.compile(_BAN, re.IGNORECASE)
_TOOL_RE = re.compile(_TOOL, re.IGNORECASE)


def ai_answers_forbidden(text: str | None) -> str:
    """Цитата запрета отвечать с помощью ИИ — или пустая строка, если запрета нет.

    Возвращается именно кусок текста, а не True: человеку в таблице нужна та
    самая фраза работодателя, иначе причину «ответь сам» не проверить.
    """
    flat = re.sub(r"\s+", " ", text or "")
    if not flat:
        return ""
    for ban in _BAN_RE.finditer(flat):
        tool = _TOOL_RE.search(flat, ban.end(), ban.end() + _GAP)
        if not tool:
            continue
        window = flat[max(0, ban.start() - _CONTEXT):tool.end() + _CONTEXT]
        if not _ADDRESSEE.search(window):
            continue
        quote = flat[max(0, ban.start() - 40):tool.end() + 40].strip()
        return quote[:_QUOTE]
    return ""

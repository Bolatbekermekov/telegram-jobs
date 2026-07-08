"""OpenAI-backed message generator for outreach."""
import json

from openai import OpenAI

_QUESTIONS_SYSTEM = (
    "Ты отвечаешь на обязательные вопросы работодателя в отклике на hh.ru ОТ ЛИЦА "
    "кандидата. Опирайся ТОЛЬКО на факты из CV и PROFILE, ничего не выдумывай. "
    "Свободные текстовые ответы: коротко, по делу, честно, на русском, 1-3 предложения, "
    "без тире («—»/«–») и без плейсхолдеров. Если по вакансии просят описать интерес или "
    "опыт, свяжи с реальным опытом из CV. "
    "Вопросы с вариантами (choice): выбери ОДИН технически самый правильный вариант "
    "(это часто тест знаний по QA/разработке), верни его индекс (0 = первый вариант). "
    "Верни СТРОГО JSON вида "
    '{"answers":[{"id":"<id>","text":"<для type=text>"},{"id":"<id>","choice":<индекс для type=choice>}]} '
    "с ответом на КАЖДЫЙ вопрос по его id. Без пояснений вне JSON."
)

_SYSTEM = (
    "Ты пишешь персональное сообщение для отклика на вакансию ОТ ЛИЦА кандидата "
    "(software engineer, fullstack, рассматривает и разработку, и QA). "
    "Сообщение читает опытный HR в крупной компании: скользит по тексту за 15 секунд, "
    "ценит краткость, конкретику и честность, сверяет всё с приложенным CV. "
    "Точно следуй СТРУКТУРЕ и правилам из PROFILE и опирайся ТОЛЬКО на факты из CV; "
    "ничего не выдумывай. "
    "Пиши несколько КОРОТКИХ абзацев через пустую строку (не стена текста, не список). "
    "Определи роль из вакансии (QA / Fullstack / Backend / Frontend) и подай опыт под неё. "
    "ОБЯЗАТЕЛЬНО укажи в начале, где кандидат работает СЕЙЧАС и чем занимается (см. раздел "
    "PROFILE «Чем я занимаюсь сейчас»), затем привяжи релевантный опыт к вакансии. "
    "Веди с конкретного релевантного опыта, привязанного к задачам вакансии; используй "
    "результаты и факты из CV, а не общий процесс. "
    "Обязательно отрази КОНКРЕТНЫЕ навыки, требования и стек, перечисленные в самой вакансии, "
    "и свяжи их со своим опытом, чтобы было видно, что прочитана именно эта вакансия. "
    "Стек подавай ПОД РОЛЬ: сначала строкой 'Мой стек:' (через двоеточие) технологии, "
    "релевантные вакансии (для React Native — React Native, TypeScript, JavaScript, REST API), "
    "и только потом, отдельно и короче, бэкенд/инфраструктуру как 'плюс к пониманию системы "
    "целиком'. Не вали фронт и бэк в одну кучу. Если в вакансии названы инструменты (Postman, "
    "Swagger, Chrome DevTools, Jira, k6, Git), упомяни именно их при наличии опыта в CV. "
    "Где возможно, добавь конкретную цифру (пользователи, ускорение отклика, %, снижение ошибок). "
    "Названия компаний пиши обычным текстом, без markdown-ссылок вида [Название](url). "
    "Включи 1-2 предложения искреннего интереса к этой вакансии, опираясь на текст вакансии "
    "(продукт, домен, стек; если упомянут AI/ML, скажи, что интересно работать с AI). "
    "НЕ выдумывай факты о компании сверх вакансии и НИКОГДА не оставляй плейсхолдеров или "
    "квадратных скобок. "
    "НИКОГДА не называй уровень кандидата словом (junior/middle/senior). "
    "НЕ вставляй ссылки и URL в тело письма. НЕ добавляй подпись и контакты в конце. "
    "Без заискивания и хеджей ('если вам релевантен', 'надеюсь на ответ'). "
    "Язык сообщения = язык вакансии. Объём примерно 100-160 слов. "
    "КРИТИЧЕСКОЕ правило стиля: НИКОГДА не используй тире, ни длинное «—», ни среднее «–». "
    "Вместо тире ставь запятую, точку или скобки. Обычный дефис допустим только внутри слов. "
    "Верни ТОЛЬКО текст сообщения, без пояснений."
)


def _strip_dashes(text: str) -> str:
    """Safety net: remove em/en dashes even if the model slips one in."""
    for sep in (" — ", " – ", " —", "— ", " –", "– "):
        text = text.replace(sep, ", ")
    text = text.replace("—", ", ").replace("–", ", ")
    while ", ," in text:
        text = text.replace(", ,", ",")
    return text.replace("  ", " ").strip()


class OpenAIMessageGenerator:
    def __init__(self, api_key: str, model: str):
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def generate(self, cv_text: str, profile_text: str, vacancy_context: str) -> str:
        user = (
            f"=== PROFILE (правила позиционирования) ===\n{profile_text}\n\n"
            f"=== CV ===\n{cv_text}\n\n"
            f"=== ВАКАНСИЯ ===\n{vacancy_context}\n\n"
            "Напиши сообщение для HR по правилам выше."
        )
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": user},
            ],
        )
        return _strip_dashes((resp.choices[0].message.content or "").strip())

    def answer_questions(self, cv_text: str, profile_text: str, vacancy_context: str,
                         questions: list) -> dict:
        """Answer hh employer questions. Returns {question_id: {"text"|"choice"}}."""
        from app.application.hh_questions import parse_ai_answers

        lines = []
        for q in questions:
            if q.get("type") == "choice":
                opts = "; ".join(f"[{i}] {o}" for i, o in enumerate(q.get("options", [])))
                lines.append(f'- id={q["id"]} (выбор одного): {q["prompt"]}\n  Варианты: {opts}')
            else:
                lines.append(f'- id={q["id"]} (свободный текст): {q["prompt"]}')
        user = (
            f"=== PROFILE ===\n{profile_text}\n\n=== CV ===\n{cv_text}\n\n"
            f"=== ВАКАНСИЯ ===\n{vacancy_context}\n\n"
            f"=== ВОПРОСЫ ===\n" + "\n".join(lines) + "\n\nОтветь JSON по правилам."
        )
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": _QUESTIONS_SYSTEM},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
        )
        return parse_ai_answers(resp.choices[0].message.content or "{}")

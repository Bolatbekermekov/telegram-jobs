"""OpenAI-backed message generator for outreach."""
import json
import re

from openai import OpenAI

from app.domain.message_language import detect_language, language_rule

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
    "с ответом на КАЖДЫЙ вопрос по его id — id верни СТРОКОЙ, ровно как в вопросе. "
    "СОБЛЮДАЙ ограничения, написанные в самом вопросе — они часто в скобках "
    "(«не приводите рабочие примеры», «одним предложением», «только цифра», "
    "«на английском»). Ответ, нарушающий условие вопроса, хуже пустого. "
    "Пропускать вопросы нельзя: если точного факта в CV нет, дай честный ответ по "
    "смыслу (например, для вопроса о минимальной зарплате — разумное число для "
    "этой роли и рынка вакансии, только число и валюту). Без пояснений вне JSON."
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


def _note_rules(limit: int) -> str:
    """Добавка к системному промпту, превращающая одну генерацию в письмо + записку.

    Живёт отдельной строкой, а не внутри `_SYSTEM`: `generate()` обслуживает
    Telegram, hh, Threads и email, и правка промпта ради LinkedIn не должна иметь
    возможности до них дотянуться.
    """
    return (
        " Кроме письма напиши КОРОТКУЮ записку для запроса на контакт в LinkedIn. "
        f"Записка: не длиннее {limit} символов, законченный текст из 1-2 предложений "
        "(приветствие, чем зацепила именно эта вакансия, короткая просьба принять "
        "контакт). Это НЕ начало письма и НЕ его сокращение, а самостоятельное "
        "сообщение, которое читают отдельно. Без подписи, без ссылок, без "
        "плейсхолдеров и квадратных скобок. "
        "Записка на ТОМ ЖЕ языке, что и письмо (то есть на языке вакансии): "
        "английская вакансия значит и письмо, и записка на английском. "
        'Верни СТРОГО один JSON-объект и ничего кроме него: '
        '{"letter": "<полное письмо>", "note": "<записка>"}'
    )


def _parse_letter_and_note(raw: str) -> tuple[str, str]:
    """Ответ модели -> (письмо, записка). Записка пустая, если её не разобрать.

    Асимметрия намеренная: без записки вызывающий сократит письмо и всё равно
    отправит приглашение, а без письма лид умирает. Поэтому ответ, который даже
    не пытался быть JSON, целиком считается письмом — модель просто написала
    прозой вместо формата, и письмо от этого не хуже.

    А вот ответ, который пытался быть JSON и не разобрался, письмом считать
    нельзя: получается `{"letter": "Здравствуйте.` в качестве текста живому
    человеку. Такой ответ это сбой генерации, и он поднимается наверх — там
    он уже обрабатывается как обвал OpenAI: лид остаётся неотправленным и
    повторится в следующем прогоне.

    Во всех отказных ветках отдаём `text`, а не `raw`: маркеры ограждения
    иначе попадут в письмо, которое прочитает человек.
    """
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    looks_like_json = text.startswith("{") or text.startswith("[")
    try:
        data = json.loads(text)
    except Exception:  # noqa: BLE001 — чужой текст, любой разбор может не удаться
        if looks_like_json:
            raise ValueError("модель вернула неразобранный JSON вместо письма")
        return text, ""
    if not isinstance(data, dict):
        raise ValueError("модель вернула не объект JSON вместо письма")
    letter = str(data.get("letter") or "").strip()
    note = str(data.get("note") or "").strip()
    if not letter:
        raise ValueError("в ответе модели нет поля letter")
    return letter, note


class OpenAIMessageGenerator:
    def __init__(self, api_key: str, model: str, max_output_tokens: int = 2000):
        self._client = OpenAI(api_key=api_key)
        self._model = model
        self._max_output_tokens = max_output_tokens

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
                # Язык называем прямо, а не оставляем правилу «язык сообщения =
                # язык вакансии» внутри _SYSTEM: живьём оно проигрывало русскому
                # языку самого промпта, и английские вакансии получали русские
                # письма (лиды 6, 13, 17).
                {"role": "system",
                 "content": _SYSTEM + language_rule(detect_language(vacancy_context))},
                {"role": "user", "content": user},
            ],
            max_completion_tokens=self._max_output_tokens,
        )
        return _strip_dashes((resp.choices[0].message.content or "").strip())

    def generate_with_note(self, cv_text: str, profile_text: str,
                           vacancy_context: str, note_limit: int) -> tuple[str, str]:
        """(письмо, записка) за ОДИН запрос.

        `generate()` намеренно не тронут: по нему ходят все остальные каналы, и
        изменение промпта ради LinkedIn не должно иметь к ним доступа. Пустая
        записка это не ошибка — вызывающий сократит письмо (см. _invite_note).
        """
        user = (
            f"=== PROFILE (правила позиционирования) ===\n{profile_text}\n\n"
            f"=== CV ===\n{cv_text}\n\n"
            f"=== ВАКАНСИЯ ===\n{vacancy_context}\n\n"
            "Напиши сообщение для HR и записку по правилам выше. Верни JSON."
        )
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system",
                 "content": _SYSTEM + _note_rules(note_limit)
                 + language_rule(detect_language(vacancy_context))},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            max_completion_tokens=self._max_output_tokens,
        )
        letter, note = _parse_letter_and_note(resp.choices[0].message.content or "")
        return _strip_dashes(letter), _strip_dashes(note)

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
            max_completion_tokens=self._max_output_tokens,
        )
        return parse_ai_answers(resp.choices[0].message.content or "{}")

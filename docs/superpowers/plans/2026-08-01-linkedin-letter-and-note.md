# LinkedIn: полное письмо контакту и отдельная записка к приглашению

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Принявшему контакту уходит письмо целиком, а к запросу на контакт — самостоятельная короткая записка, а не обрубок письма.

**Architecture:** У LinkedIn два пути с несопоставимыми лимитами: сообщение контакту (тысячи символов) и записка к приглашению (жёсткие ~200). Сейчас канал несёт один `body_limit = 300`, применяемый в `format_for_channel` до того, как канал узнает свой путь, поэтому режется и то, что резать не надо. Разделяем тексты: `OutreachContent` получает поле `note`, LinkedIn снимает `body_limit`, а генератор отдаёт оба текста за один запрос к модели. Существующий `generate()` не трогается — остальные каналы идут прежним путём.

**Tech Stack:** Python 3.14, pytest, Playwright (только косвенно), OpenAI chat completions.

## Global Constraints

- Правка касается **только LinkedIn**. Общий `_truncate` в `app/application/format_content.py` и поведение Telegram / hh / Threads / email не меняются.
- `OpenAIMessageGenerator.generate()` остаётся байт-в-байт прежним: любые изменения промпта живут в новом методе.
- Каждое новое поле имеет дефолт, чтобы существующие конструкторы `OutreachContent` продолжали работать.
- Комментарии и docstring-и — на языке окружающего кода (русский в этом проекте), и объясняют **почему**, а не что.
- Никакой правки статусов лидов и никаких отправок в рамках этого плана.
- Запускать тесты только так: `cd /Users/bolatbek/telegram-jobs/sender && .venv/bin/python -m pytest ...`
- TDD: сначала падающий тест, потом минимальная реализация. Коммит в конце каждой задачи.

---

### Task 1: Обрезка по границе предложения

**Files:**
- Modify: `sender/app/infrastructure/channels/linkedin.py` (добавить рядом с `_NOTE_LIMIT`, строка 146)
- Test: `sender/tests/test_note_trim.py` (создать)

**Interfaces:**
- Consumes: ничего.
- Produces: `_trim_to_sentence(text: str, limit: int) -> str` в `app.infrastructure.channels.linkedin`.

- [ ] **Step 1: Написать падающий тест**

Создать `sender/tests/test_note_trim.py`:

```python
"""Сокращение записки без порчи смысла.

Все письма в LinkedIn уходили обрезанными на полумысли — «…amoCRM, Google Sheets
и», «…нужно доводить», «…Это» — потому что канал нёс один предел (300, размер
записки к приглашению), а общий `_truncate` режет по ближайшему пробелу. Там, где
сокращать действительно надо, сокращаем по границе предложения.
"""
from app.infrastructure.channels.linkedin import _trim_to_sentence


def test_text_within_the_limit_is_untouched():
    assert _trim_to_sentence("Здравствуйте. Коротко.", 100) == "Здравствуйте. Коротко."


def test_shortens_to_the_last_whole_sentence():
    text = "Здравствуйте. Откликаюсь на вакансию Backend. Готов обсудить детали."
    out = _trim_to_sentence(text, 50)
    assert out == "Здравствуйте. Откликаюсь на вакансию Backend."
    assert len(out) <= 50


def test_question_and_exclamation_end_a_sentence():
    text = "Здравствуйте! Есть вопрос по вакансии? И ещё текст."
    assert _trim_to_sentence(text, 40) == "Здравствуйте! Есть вопрос по вакансии?"


def test_a_dot_inside_a_word_is_not_a_sentence_end():
    """«Atlanti.ai» — название продукта, а не конец мысли."""
    text = "Работаю в Atlanti.ai и строю интеграции. Дальше не влезет."
    assert _trim_to_sentence(text, 45) == "Работаю в Atlanti.ai и строю интеграции."


def test_falls_back_to_a_word_boundary_when_no_sentence_fits():
    """Обрезанное первое предложение лучше пустой записки: слать больше нечего."""
    assert _trim_to_sentence("Очень длинное первое предложение без конца", 20) == "Очень длинное"


def test_empty_and_none_are_safe():
    assert _trim_to_sentence("", 10) == ""
    assert _trim_to_sentence(None, 10) == ""
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd /Users/bolatbek/telegram-jobs/sender && .venv/bin/python -m pytest tests/test_note_trim.py -q`
Expected: FAIL — `ImportError: cannot import name '_trim_to_sentence'`

- [ ] **Step 3: Реализовать**

В `sender/app/infrastructure/channels/linkedin.py` сразу после строки `_NOTE_LIMIT = 200` добавить:

```python
# Конец предложения: знак, за которым идёт пробел или конец строки. Просмотр
# вперёд обязателен — точка внутри «Atlanti.ai» или «t.me» концом мысли не
# является, а без этого условия записка обрывалась бы ровно на названии продукта.
_SENTENCE_END = re.compile(r"[.!?…](?=\s|$)")


def _trim_to_sentence(text: str, limit: int) -> str:
    """`text`, сокращённый до `limit` символов по границе предложения.

    Письмо пишется прозой на 100-160 слов, и срез по ближайшему пробелу
    заканчивает его на полумысли: именно так лиды 156/160/161/172/177/179
    получили «…Это близко» и «…нужно доводить». Если не влезает даже первое
    предложение, отступаем к границе слова: обрезанное предложение всё равно
    лучше пустой записки, отправлять больше нечего.
    """
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    window = text[:limit]
    ends = [m.end() for m in _SENTENCE_END.finditer(window)]
    if ends:
        return window[:ends[-1]].rstrip()
    cut = window.rfind(" ")
    return window[:cut].rstrip() if cut > 0 else window
```

`re` в этом файле уже импортирован (строка 7) — новый импорт не нужен.

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd /Users/bolatbek/telegram-jobs/sender && .venv/bin/python -m pytest tests/test_note_trim.py -q`
Expected: PASS, 6 passed

- [ ] **Step 5: Коммит**

```bash
cd /Users/bolatbek/telegram-jobs
git add sender/app/infrastructure/channels/linkedin.py sender/tests/test_note_trim.py
git commit -m "feat(linkedin): обрезка текста по границе предложения"
```

---

### Task 2: Поле `note` в OutreachContent

**Files:**
- Modify: `sender/app/domain/channel.py:40-45` (dataclass `OutreachContent`)
- Modify: `sender/app/application/format_content.py:15-22` (`format_for_channel`)
- Test: `sender/tests/test_format_content.py` (дописать)

**Interfaces:**
- Consumes: ничего.
- Produces: `OutreachContent(body, subject=None, attachment_path=None, note="")`;
  `format_for_channel(channel, body, subject, attachment_path, note="") -> OutreachContent`.

- [ ] **Step 1: Написать падающий тест**

Дописать в конец `sender/tests/test_format_content.py`:

```python
def test_the_note_is_carried_through_untouched():
    """Записка живёт по своим правилам: её пишут сразу под лимит площадки, и
    `body_limit` (предел ПИСЬМА) к ней отношения не имеет."""
    ch = _Ch(body_limit=10)
    c = format_for_channel(ch, body="hello world foo", subject=None,
                           attachment_path=None, note="Короткая записка целиком.")
    assert c.note == "Короткая записка целиком."
    assert c.body == "hello"


def test_the_note_defaults_to_empty():
    c = format_for_channel(_Ch(), body="b", subject=None, attachment_path=None)
    assert c.note == ""
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd /Users/bolatbek/telegram-jobs/sender && .venv/bin/python -m pytest tests/test_format_content.py -q`
Expected: FAIL — `TypeError: format_for_channel() got an unexpected keyword argument 'note'`

- [ ] **Step 3: Реализовать**

В `sender/app/domain/channel.py` заменить dataclass:

```python
@dataclass
class OutreachContent:
    body: str
    subject: str | None = None        # used by channels with needs_subject (email)
    attachment_path: str | None = None
    # Короткий самостоятельный текст для записки к запросу на контакт в LinkedIn.
    # У записки жёсткий предел площадки (LinkedInChannel.note_limit), которого у
    # письма нет, поэтому её пишут отдельно, а не отрезают от письма. Для всех
    # остальных каналов поле пустое, и они его не читают.
    note: str = ""
```

В том же файле обновить комментарий протокола (строка 50):

```python
    body_limit: int | None     # предел ДЛИНЫ ПИСЬМА; None = без предела
```

В `sender/app/application/format_content.py` заменить `format_for_channel`:

```python
def format_for_channel(channel, body: str, subject: str | None,
                       attachment_path: str | None, note: str = "") -> OutreachContent:
    out_body = body
    if channel.body_limit is not None:
        out_body = _truncate(body, channel.body_limit)
    out_subject = subject if channel.needs_subject else None
    # `note` не режется здесь: её предел принадлежит каналу, а не письму, и канал
    # применяет его сам (см. LinkedInChannel.note_limit).
    return OutreachContent(body=out_body, subject=out_subject,
                           attachment_path=attachment_path, note=note)
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd /Users/bolatbek/telegram-jobs/sender && .venv/bin/python -m pytest tests/test_format_content.py -q`
Expected: PASS

- [ ] **Step 5: Коммит**

```bash
cd /Users/bolatbek/telegram-jobs
git add sender/app/domain/channel.py sender/app/application/format_content.py sender/tests/test_format_content.py
git commit -m "feat: OutreachContent несёт отдельную записку для запроса на контакт"
```

---

### Task 3: LinkedIn перестаёт резать письмо и берёт записку из своего поля

**Files:**
- Modify: `sender/app/infrastructure/channels/linkedin.py:501` (`message_or_connect`)
- Modify: `sender/app/infrastructure/channels/linkedin.py:779-782` (атрибуты `LinkedInChannel`)
- Modify: `sender/app/infrastructure/channels/linkedin.py` (добавить `_invite_note` перед `message_or_connect`)
- Test: `sender/tests/test_linkedin_note_text.py` (создать)

**Interfaces:**
- Consumes: `_trim_to_sentence` (Task 1), `OutreachContent.note` (Task 2).
- Produces: `_invite_note(content: OutreachContent) -> str`; `LinkedInChannel.note_limit: int`;
  `LinkedInChannel.body_limit is None`.

- [ ] **Step 1: Написать падающий тест**

Создать `sender/tests/test_linkedin_note_text.py`:

```python
"""Что уходит в запрос на контакт, а что в сообщение принявшему.

Лиды 156/160/161/172/177/179 ушли ПРЯМЫМИ сообщениями людям, которые уже приняли
заявку, и каждое было обрезано на полумысли около 290 символов: канал нёс один
`body_limit = 300`, рассчитанный на записку к приглашению. Записка и письмо это
два разных текста с двумя разными пределами, поэтому теперь они и едут отдельно.
"""
import pytest

from app.domain.channel import InvitePendingError, OutreachContent
from app.infrastructure.channels.linkedin import (
    SEL_INVITE_SEND,
    SEL_MENU_CONNECT,
    SEL_MORE_BTN,
    SEL_NOTE_BOX,
    SEL_PERSONALIZE,
    LinkedInChannel,
    _NOTE_LIMIT,
    _invite_note,
    message_or_connect,
)
from tests.test_linkedin_channel import _FakePage


def test_the_message_path_is_not_capped_at_note_length():
    """Принявшему контакту уходит письмо целиком; жёсткий предел только у записки."""
    assert LinkedInChannel.body_limit is None
    assert LinkedInChannel.note_limit == _NOTE_LIMIT


def test_the_note_comes_from_its_own_field():
    content = OutreachContent(body="Длинное письмо на несколько абзацев.",
                              note="Здравствуйте! Пишу по вакансии Backend.")
    assert _invite_note(content) == "Здравствуйте! Пишу по вакансии Backend."


def test_without_a_note_the_letter_is_shortened_at_a_sentence():
    letter = "Здравствуйте. " + "Пишу по вакансии Backend в вашей команде. " * 12
    out = _invite_note(OutreachContent(body=letter))
    assert len(out) <= _NOTE_LIMIT
    assert out.endswith(".")


def test_an_overlong_note_is_shortened_not_sliced():
    note = "Здравствуйте. " + "Очень подробная записка про опыт и стек. " * 12
    out = _invite_note(OutreachContent(body="письмо", note=note))
    assert len(out) <= _NOTE_LIMIT
    assert out.endswith(".")


def test_message_or_connect_fills_the_note_not_the_letter():
    page = _FakePage({SEL_MORE_BTN: 1, SEL_MENU_CONNECT: 1, SEL_PERSONALIZE: 1,
                      SEL_NOTE_BOX: 1, SEL_INVITE_SEND: 1})
    content = OutreachContent(body="ПИСЬМО целиком, много текста.",
                              note="ЗАПИСКА для приглашения.")
    with pytest.raises(InvitePendingError):
        message_or_connect(page, "https://linkedin.com/in/x", content)

    filled = next(a[2] for a in page.actions
                  if a[0] == "fill" and a[1] == SEL_NOTE_BOX)
    assert filled == "ЗАПИСКА для приглашения."
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd /Users/bolatbek/telegram-jobs/sender && .venv/bin/python -m pytest tests/test_linkedin_note_text.py -q`
Expected: FAIL — `ImportError: cannot import name '_invite_note'`

- [ ] **Step 3: Реализовать**

3a. В `sender/app/infrastructure/channels/linkedin.py` добавить функцию непосредственно перед `def message_or_connect(`:

```python
def _invite_note(content: OutreachContent) -> str:
    """Текст, который поедет в запросе на контакт.

    `content.note` написан именно под этот слот и в предел уже укладывается.
    Откат нужен только для генерации, которая записку не вернула вовсе: берём
    письмо, сокращённое по границе предложения. Резать письмо по пробелу нельзя —
    записка выходит оборванной на полумысли, а это первое, что читает человек.
    """
    note = (content.note or "").strip()
    return _trim_to_sentence(note or content.body, _NOTE_LIMIT)
```

3b. В `message_or_connect` (строка 501) заменить

```python
            _fill_invite_note(page, content.body)
```

на

```python
            _fill_invite_note(page, _invite_note(content))
```

3c. В `LinkedInChannel` (строка 781) заменить

```python
    body_limit = 300          # safe for connection notes; messages allow more
```

на

```python
    # Письмо принявшему контакту предела не имеет: LinkedIn пропускает тысячи
    # символов, а модель пишет 100-160 слов. Здесь стояло 300 — размер записки к
    # приглашению — и три четверти каждого письма уходили в мусор вместе с
    # подписью (лиды 156/160/161/172/177/179).
    body_limit = None
    # Жёсткий предел записки к приглашению, замерен живьём 2026-07-09. Объявлен
    # здесь, чтобы генератор писал под ту же цифру, по которой канал потом
    # подстраховывается: два разных числа разъезжаются молча.
    note_limit = _NOTE_LIMIT
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd /Users/bolatbek/telegram-jobs/sender && .venv/bin/python -m pytest tests/test_linkedin_note_text.py tests/test_linkedin_channel.py -q`
Expected: PASS

- [ ] **Step 5: Коммит**

```bash
cd /Users/bolatbek/telegram-jobs
git add sender/app/infrastructure/channels/linkedin.py sender/tests/test_linkedin_note_text.py
git commit -m "fix(linkedin): письмо контакту не режется, записка едет своим полем"
```

---

### Task 4: Модель отдаёт письмо и записку за один запрос

**Files:**
- Modify: `sender/app/infrastructure/openai_client.py:1-4` (импорты)
- Modify: `sender/app/infrastructure/openai_client.py` (добавить `_note_rules`, `_parse_letter_and_note`, метод `generate_with_note`)
- Test: `sender/tests/test_letter_and_note_parsing.py` (создать)

**Interfaces:**
- Consumes: ничего.
- Produces: `_parse_letter_and_note(raw: str) -> tuple[str, str]`;
  `OpenAIMessageGenerator.generate_with_note(cv_text, profile_text, vacancy_context, note_limit) -> tuple[str, str]`.

- [ ] **Step 1: Написать падающий тест**

Создать `sender/tests/test_letter_and_note_parsing.py`:

```python
"""Разбор ответа модели, которая просят вернуть письмо и записку сразу.

Записка не может быть куском письма: у неё жёсткий предел площадки и своя задача
(зачем принимать контакт). Просим оба текста одним запросом, но ответ модели это
чужой текст, и разбор обязан выдерживать всё, что она может прислать. Потерять
записку не страшно — вызывающий сократит письмо. Потерять письмо нельзя.
"""
from app.infrastructure.openai_client import _parse_letter_and_note


def test_parses_both_fields():
    raw = '{"letter": "Полное письмо.", "note": "Короткая записка."}'
    assert _parse_letter_and_note(raw) == ("Полное письмо.", "Короткая записка.")


def test_parses_a_fenced_json_block():
    """Модели любят заворачивать JSON в ```json."""
    raw = '```json\n{"letter": "Письмо.", "note": "Записка."}\n```'
    assert _parse_letter_and_note(raw) == ("Письмо.", "Записка.")


def test_plain_prose_becomes_the_letter_with_no_note():
    """Модель проигнорировала формат, но письмо написала годное — лид из-за
    обёртки терять нельзя."""
    assert _parse_letter_and_note("Здравствуйте. Пишу по вакансии.") == (
        "Здравствуйте. Пишу по вакансии.", "")


def test_an_empty_note_field_is_no_note():
    assert _parse_letter_and_note('{"letter": "Письмо.", "note": ""}') == ("Письмо.", "")


def test_a_json_array_is_not_a_result():
    assert _parse_letter_and_note('["a", "b"]') == ('["a", "b"]', "")


def test_json_without_a_letter_falls_back_to_the_raw_text():
    raw = '{"note": "только записка"}'
    assert _parse_letter_and_note(raw) == (raw, "")
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd /Users/bolatbek/telegram-jobs/sender && .venv/bin/python -m pytest tests/test_letter_and_note_parsing.py -q`
Expected: FAIL — `ImportError: cannot import name '_parse_letter_and_note'`

- [ ] **Step 3: Реализовать**

4a. В `sender/app/infrastructure/openai_client.py` заменить строку `import json` на:

```python
import json
import re
```

4b. Добавить после функции `_strip_dashes` (строка 68):

```python
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
        'Верни СТРОГО один JSON-объект и ничего кроме него: '
        '{"letter": "<полное письмо>", "note": "<записка>"}'
    )


def _parse_letter_and_note(raw: str) -> tuple[str, str]:
    """Ответ модели -> (письмо, записка). Записка пустая, если её не разобрать.

    Асимметрия намеренная: без записки вызывающий сократит письмо и всё равно
    отправит приглашение, а без письма лид умирает. Поэтому любой неразобранный
    ответ целиком считается письмом, а не ошибкой.
    """
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        data = json.loads(text)
    except Exception:  # noqa: BLE001 — чужой текст, любой разбор может не удаться
        return (raw or "").strip(), ""
    if not isinstance(data, dict):
        return (raw or "").strip(), ""
    letter = str(data.get("letter") or "").strip()
    note = str(data.get("note") or "").strip()
    if not letter:
        return (raw or "").strip(), ""
    return letter, note
```

4c. Добавить метод в класс `OpenAIMessageGenerator`, сразу после `generate` (после строки 92):

```python
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
                {"role": "system", "content": _SYSTEM + _note_rules(note_limit)},
                {"role": "user", "content": user},
            ],
            max_completion_tokens=self._max_output_tokens,
        )
        letter, note = _parse_letter_and_note(resp.choices[0].message.content or "")
        return _strip_dashes(letter), _strip_dashes(note)
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd /Users/bolatbek/telegram-jobs/sender && .venv/bin/python -m pytest tests/test_letter_and_note_parsing.py -q`
Expected: PASS, 6 passed

- [ ] **Step 5: Коммит**

```bash
cd /Users/bolatbek/telegram-jobs
git add sender/app/infrastructure/openai_client.py sender/tests/test_letter_and_note_parsing.py
git commit -m "feat(openai): письмо и записка за один запрос, устойчивый разбор ответа"
```

---

### Task 5: Слой use-case — подпись только на письме

**Files:**
- Modify: `sender/app/application/generate_message.py:4-36`
- Test: `sender/tests/test_generate_with_note.py` (создать)

**Interfaces:**
- Consumes: `OpenAIMessageGenerator.generate_with_note` (Task 4), `LinkedInChannel.note_limit` (Task 3).
- Produces: `GenerateMessage.execute_with_note(lead, note_limit) -> tuple[str, str]`;
  `generate_for(generator, lead, channel) -> tuple[str | None, str, Exception | None]`.

- [ ] **Step 1: Написать падающий тест**

Создать `sender/tests/test_generate_with_note.py`:

```python
"""Два текста на лид, и кто из каналов их вообще просит.

Подпись приклеивается только к письму: в записку на 200 символов она не влезает,
да и LinkedIn рядом с приглашением показывает имя отправителя сам. Канал, который
не объявил `note_limit`, продолжает ходить прежним однотекстовым путём — так
правка ради LinkedIn физически не достаёт до Telegram, hh, Threads и email.
"""
from app.application.generate_message import (
    GenerateMessage, generate_for,
)
from app.domain.lead import STATUS_NEW, Lead


def _lead():
    return Lead(row=2, lead_id="1", platform="linkedin", target="t",
                vacancy_context="Backend Engineer", raw_text="", status=STATUS_NEW)


class _Ai:
    def __init__(self, letter="Письмо.", note="Записка."):
        self.note_limits = []
        self._letter, self._note = letter, note

    def generate(self, cv_text, profile_text, vacancy_context):
        return self._letter

    def generate_with_note(self, cv_text, profile_text, vacancy_context, note_limit):
        self.note_limits.append(note_limit)
        return self._letter, self._note


class _Boom:
    def generate_with_note(self, **kw):
        raise RuntimeError("openai down")

    def generate(self, **kw):
        raise RuntimeError("openai down")


class _Chan:
    def __init__(self, note_limit=None):
        if note_limit is not None:
            self.note_limit = note_limit


def test_the_signature_rides_the_letter_only():
    g = GenerateMessage(_Ai(), "cv", "profile", signature_text="Болатбек, +7 777")
    letter, note = g.execute_with_note(_lead(), 200)
    assert letter == "Письмо.\n\nБолатбек, +7 777"
    assert note == "Записка."


def test_the_channel_limit_reaches_the_model():
    ai = _Ai()
    GenerateMessage(ai, "cv", "profile").execute_with_note(_lead(), 200)
    assert ai.note_limits == [200]


def test_a_channel_with_a_note_limit_gets_both_texts():
    body, note, err = generate_for(GenerateMessage(_Ai(), "cv", "p"), _lead(),
                                   _Chan(note_limit=200))
    assert (body, note, err) == ("Письмо.", "Записка.", None)


def test_a_channel_without_a_note_limit_keeps_the_single_text_path():
    body, note, err = generate_for(GenerateMessage(_Ai(), "cv", "p"), _lead(), _Chan())
    assert body == "Письмо."
    assert note == ""
    assert err is None


def test_a_generation_failure_is_returned_not_raised():
    """Ровно тот контракт, что и у generate_body: обвал OpenAI не должен убивать
    прогон, лид остаётся `new` и повторится."""
    body, note, err = generate_for(GenerateMessage(_Boom(), "cv", "p"), _lead(),
                                   _Chan(note_limit=200))
    assert body is None
    assert note == ""
    assert isinstance(err, RuntimeError)
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd /Users/bolatbek/telegram-jobs/sender && .venv/bin/python -m pytest tests/test_generate_with_note.py -q`
Expected: FAIL — `ImportError: cannot import name 'generate_for'`

- [ ] **Step 3: Реализовать**

В `sender/app/application/generate_message.py` добавить метод в класс `GenerateMessage` (после `execute`):

```python
    def execute_with_note(self, lead: Lead, note_limit: int) -> tuple[str, str]:
        """(письмо, записка) для канала, у которого есть отдельная короткая форма.

        Подпись приклеивается ТОЛЬКО к письму: в записку на ~200 символов она не
        влезает, а LinkedIn рядом с приглашением и так показывает, кто пишет.
        """
        letter, note = self._ai.generate_with_note(
            cv_text=self._cv_text,
            profile_text=self._profile_text,
            vacancy_context=lead.vacancy_context or lead.raw_text,
            note_limit=note_limit,
        )
        if self._signature_text:
            letter = f"{letter}\n\n{self._signature_text}"
        return letter, note
```

И добавить функцию после `generate_body`:

```python
def generate_for(generator, lead, channel):
    """(body, note, err) для конкретного канала.

    Канал, объявивший `note_limit`, получает два текста за один запрос; любой
    другой идёт прежним однотекстовым путём и о существовании записки не знает.
    Проверка по атрибуту, а не по имени канала: список каналов растёт, и правка
    ради LinkedIn не должна требовать помнить про этот if в каждом новом.

    Ошибки возвращаются, а не бросаются, ровно по той же причине, что и в
    `generate_body`: обвал OpenAI не должен уносить весь прогон.
    """
    note_limit = getattr(channel, "note_limit", None)
    if not note_limit:
        body, err = generate_body(generator, lead)
        return body, "", err
    try:
        body, note = generator.execute_with_note(lead, note_limit)
        return body, note, None
    except Exception as exc:  # noqa: BLE001 — как generate_body: пропуск лида, не крах
        return None, "", exc
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd /Users/bolatbek/telegram-jobs/sender && .venv/bin/python -m pytest tests/test_generate_with_note.py tests/test_generate_body.py -q`
Expected: PASS

- [ ] **Step 5: Коммит**

```bash
cd /Users/bolatbek/telegram-jobs
git add sender/app/application/generate_message.py sender/tests/test_generate_with_note.py
git commit -m "feat: generate_for отдаёт письмо и записку каналу, который её просит"
```

---

### Task 6: Прошивка в цикле отправки

**Files:**
- Modify: `sender/app/interface/cli.py:16-18` (импорты)
- Modify: `sender/app/interface/cli.py:205-216` (`_followup_invited`)
- Modify: `sender/app/interface/cli.py:427-445` (основной цикл)
- Test: `sender/tests/test_followup_invited.py` (дописать)

**Interfaces:**
- Consumes: `generate_for` (Task 5), `format_for_channel(..., note)` (Task 2), `LinkedInChannel.note_limit` (Task 3).
- Produces: ничего для последующих задач.

- [ ] **Step 1: Написать падающий тест**

Дописать в конец `sender/tests/test_followup_invited.py`:

```python
class _NoteChannel(_Channel):
    """Канал, который просит записку — как настоящий LinkedInChannel."""
    note_limit = 200


class _NoteGen:
    def execute(self, lead):
        return "Письмо."

    def execute_with_note(self, lead, note_limit):
        return "Полное письмо принявшему контакту.", "Короткая записка."


def test_the_accepted_contact_gets_the_whole_letter_and_the_note_rides_along():
    """Человек принял заявку, значит письмо идёт прямым сообщением и резать его
    нечем. Записка едет своим полем на случай, если канал пойдёт путём
    приглашения."""
    lead = _lead()
    repo = _Repo([lead])
    channel = _NoteChannel(state="accepted")
    _followup_invited(repo, _Switcher(channel), _NoteGen())

    (_target, content), = channel.sent
    assert content.body == "Полное письмо принявшему контакту."
    assert content.note == "Короткая записка."
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd /Users/bolatbek/telegram-jobs/sender && .venv/bin/python -m pytest tests/test_followup_invited.py -q`
Expected: FAIL — `content.body` равен `"Письмо."` (старый однотекстовый путь) и `content.note` пуст

- [ ] **Step 3: Реализовать**

6a. В `sender/app/interface/cli.py` в импорте из `app.application.generate_message` (строка 18) добавить `generate_for`:

```python
from app.application.generate_message import (
    GenerateMessage, generate_body, generate_for, subject_for,
)
```

(`generate_body` остаётся: им пользуются другие места файла.)

6b. В `_followup_invited` заменить строку 205:

```python
        body, gen_err = generate_body(generator, lead)
```

на

```python
        body, note, gen_err = generate_for(generator, lead, channel)
```

и строку 216:

```python
        content = format_for_channel(channel, body, subject, attachment)
```

на

```python
        content = format_for_channel(channel, body, subject, attachment, note)
```

6c. В основном цикле заменить строку 427:

```python
            body, gen_err = generate_body(generator, lead)
```

на

```python
            body, note, gen_err = generate_for(generator, lead, channel)
```

строку 443:

```python
            content = format_for_channel(channel, body, subject, attachment)
```

на

```python
            content = format_for_channel(channel, body, subject, attachment, note)
```

и строку 445 (проверку плейсхолдеров):

```python
            if config.AUTO_SEND and has_placeholder(content.body):
```

на

```python
            # Записка это тоже текст, который прочитает живой человек, и шаблон в
            # ней ничем не лучше шаблона в письме.
            if config.AUTO_SEND and (has_placeholder(content.body)
                                     or has_placeholder(content.note)):
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd /Users/bolatbek/telegram-jobs/sender && .venv/bin/python -m pytest tests/test_followup_invited.py -q`
Expected: PASS

- [ ] **Step 5: Прогнать весь набор целиком**

Run: `cd /Users/bolatbek/telegram-jobs/sender && .venv/bin/python -m pytest -q`
Expected: PASS, ноль упавших. Особое внимание: `test_format_content.py`, `test_generate_body.py`,
`test_linkedin_channel.py`, `test_send_plan.py`, `test_record_sent.py`, `test_vacancy_mirror.py`.

Если что-то упало — чинить причину, а не подгонять тест под новое поведение.

- [ ] **Step 6: Коммит**

```bash
cd /Users/bolatbek/telegram-jobs
git add sender/app/interface/cli.py sender/tests/test_followup_invited.py
git commit -m "feat(cli): LinkedIn получает письмо и записку раздельно"
```

---

## Проверка живьём (после Task 6, вручную, без отправки)

Отправлять ничего не нужно и не следует: квота персональных приглашений исчерпана,
и путь записки сейчас всё равно не задействуется. Достаточно убедиться, что модель
возвращает оба текста и они разумны:

```bash
cd /Users/bolatbek/telegram-jobs
sender/.venv/bin/python - <<'PY'
import sys; sys.path.insert(0, "sender")
from app import config
from app.infrastructure.channels.linkedin import LinkedInChannel
from app.infrastructure.cv_loader import load_cv_text, load_text_file
from app.infrastructure.openai_client import OpenAIMessageGenerator

ai = OpenAIMessageGenerator(config.OPENAI_API_KEY, config.OPENAI_MODEL,
                            max_output_tokens=config.OPENAI_MAX_OUTPUT_TOKENS)
letter, note = ai.generate_with_note(
    cv_text=load_cv_text(config.CV_PATH),
    profile_text=load_text_file(config.PROFILE_PATH),
    vacancy_context="Backend Engineer, Python, FastAPI, PostgreSQL, удалённо",
    note_limit=LinkedInChannel.note_limit,
)
print("ПИСЬМО", len(letter), "симв.\n", letter, "\n")
print("ЗАПИСКА", len(note), "симв.\n", note)
PY
```

Ожидаем: письмо на 700–1300 символов, заканчивается подписью только после прошивки
через `GenerateMessage`; записка не длиннее `note_limit`, законченная, с просьбой
принять контакт, и НЕ являющаяся первым абзацем письма.

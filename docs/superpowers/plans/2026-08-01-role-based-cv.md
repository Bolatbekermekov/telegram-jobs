# CV под роль — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Каждому лиду уходит CV, собранное под его роль, а не один файл на все восемь направлений.

**Architecture:** Дешёвая модель читает вакансию и возвращает одну роль из закрытого списка. `CvLibrary` отдаёт по роли текст CV (для промпта) и путь к PDF (для вложения), с цепочкой откатов на `fullstack`. Ни лист, ни `intake-bot` не участвуют: роль нигде не хранится, она вычисляется на каждый прогон.

**Tech Stack:** Python 3.14, pytest, OpenAI chat completions (`response_format=json_object`), pypdf.

## Global Constraints

- Роли ровно эти, порядок и написание точные: `("ai", "backend-node", "backend-go", "backend-python", "frontend", "mobile", "qa", "fullstack")`.
- `DEFAULT_ROLE = "fullstack"` — и отдельная роль, и запасной вариант для всего непонятного.
- Классификатор ходит на `config.OPENAI_MODEL_CHEAP` (сейчас `gpt-5.4-nano`), тем же способом, что `OpenAIRelevanceScorer`.
- Ни одна ветка отказа не теряет лид: худший случай равен сегодняшнему поведению.
- Лист, `COLUMNS`, `sender/app/domain/lead.py` и весь `intake-bot/` не трогаются.
- Ограничение стека в письме: главная строка «Мой стек» не более **7** технологий, хвост «плюс к пониманию системы целиком» не более **4**.
- Тесты: `./sender/.venv/bin/python -m pytest sender/tests -q -m "not live"`. Сейчас 752 проходят, ноль падений — это база, ниже опускаться нельзя.
- Все комментарии и сообщения пользователю на русском, как во всём проекте.

## Два отклонения от спеки

**1. `cv_text` идёт в вызов, а не в конструктор.** Спека (раздел 3.4) обещала не трогать `GenerateMessage` и держать в CLI словарь «роль → экземпляр». В плане вместо этого `cv_text` передаётся **в вызов** (`execute(lead, cv_text="")`) необязательным параметром. Причина: словарь генераторов всё равно пришлось бы протаскивать в `_followup_invited` отдельным аргументом, то есть сигнатура меняется в обоих вариантах, а вариант с параметром убирает лишний кэш и делает CV явным входом конкретной генерации. Существующие тесты и `sender/test_send.py` продолжают работать без правок.

**2. `config.cv_path_for(role)` не появляется.** Спека называла такую функцию, но `config.py` сегодня не импортирует ничего из `app/` и импортируется отовсюду — добавлять туда цепочку откатов значит тащить в него `cv_loader` и рисковать циклом. Поиск по роли живёт в `app/domain/cv_files.py` (чистый pathlib), откаты — в `CvLibrary`. В `config.py` остаётся ровно одна правка: `_resolve_cv_path()` учится видеть подпапки, иначе приложение умрёт на импорте, когда верхний уровень `sender/cv/` опустеет.

## Структура файлов

| Файл | Ответственность |
|---|---|
| `sender/app/domain/cv_role.py` | **создать.** Словарь ролей: список, значение по умолчанию, описания для промпта, нормализация |
| `sender/app/domain/cv_files.py` | **создать.** Чистый поиск файла CV на диске по папке роли |
| `sender/app/application/cv_library.py` | **создать.** Роль → `CvVariant(role, text, pdf_path)`, кэш текста, цепочка откатов |
| `sender/app/application/classify_role.py` | **создать.** Промпт, разбор ответа, обёртка, проглатывающая сбои |
| `sender/app/infrastructure/openai_role.py` | **создать.** Вызов модели, строение как у `openai_relevance.py`, но с `response_format` |
| `sender/app/config.py` | **править.** `_resolve_cv_path()` должен находить CV в подпапке |
| `sender/app/application/generate_message.py` | **править.** `cv_text` необязательным параметром вызова |
| `sender/app/interface/cli.py` | **править.** Проводка обоих путей отправки + печать роли |
| `sender/profile.md` | **править.** Ограничение длины стека |

---

### Task 1: Словарь ролей

**Files:**
- Create: `sender/app/domain/cv_role.py`
- Test: `sender/tests/test_cv_role.py`

**Interfaces:**
- Consumes: ничего
- Produces: `ROLES: tuple[str, ...]`, `DEFAULT_ROLE: str`, `ROLE_DESCRIPTIONS: dict[str, str]`, `normalize_role(raw: str) -> str`

- [ ] **Step 1: Написать падающий тест**

Создать `sender/tests/test_cv_role.py`:

```python
"""Словарь ролей: он один на весь проект, разъехаться ему нельзя."""
from app.domain.cv_role import (
    DEFAULT_ROLE,
    ROLE_DESCRIPTIONS,
    ROLES,
    normalize_role,
)


def test_roles_are_exactly_the_eight_agreed():
    assert ROLES == ("ai", "backend-node", "backend-go", "backend-python",
                     "frontend", "mobile", "qa", "fullstack")


def test_default_role_is_in_the_list():
    assert DEFAULT_ROLE == "fullstack"
    assert DEFAULT_ROLE in ROLES


def test_every_role_has_a_description_for_the_prompt():
    """Классификатор выбирает по описанию, поэтому роль без описания слепа."""
    assert set(ROLE_DESCRIPTIONS) == set(ROLES)
    assert all(desc.strip() for desc in ROLE_DESCRIPTIONS.values())


def test_normalize_accepts_a_valid_role():
    assert normalize_role("qa") == "qa"


def test_normalize_is_forgiving_about_shape():
    """Модель вернёт то, что вернёт: регистр, пробелы, подчёркивание вместо дефиса."""
    assert normalize_role("  QA  ") == "qa"
    assert normalize_role("Backend_Node") == "backend-node"
    assert normalize_role("BACKEND-GO") == "backend-go"


def test_normalize_falls_back_on_anything_unknown():
    assert normalize_role("devops") == DEFAULT_ROLE
    assert normalize_role("") == DEFAULT_ROLE
    assert normalize_role(None) == DEFAULT_ROLE
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `./sender/.venv/bin/python -m pytest sender/tests/test_cv_role.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'app.domain.cv_role'`

- [ ] **Step 3: Написать модуль**

Создать `sender/app/domain/cv_role.py`:

```python
"""Роли, под которые собраны отдельные CV. Единственный источник правды.

Имя роли это одновременно имя папки в `sender/cv/` и значение, которое
возвращает классификатор. Разъедутся они молча, поэтому список один.
"""

ROLES = ("ai", "backend-node", "backend-go", "backend-python",
         "frontend", "mobile", "qa", "fullstack")

# Служит двум целям сразу: это отдельное CV для честно фуллстековых вакансий и
# запасной вариант для всего, что не опознали.
DEFAULT_ROLE = "fullstack"

# Идут в промпт классификатора: он выбирает по смыслу описания, а не по
# совпадению слов с заголовком вакансии.
ROLE_DESCRIPTIONS = {
    "ai": "AI/ML инженер: LLM, агенты, RAG, промпты, встраивание моделей в продукт",
    "backend-node": "бэкенд на Node.js или TypeScript: Express, NestJS, API, очереди",
    "backend-go": "бэкенд на Go: Gin, gRPC, производительность, сервисы",
    "backend-python": "бэкенд на Python: FastAPI, Django, SQLAlchemy, API",
    "frontend": "веб-фронтенд: React, Next.js, Vue, вёрстка, состояние, UI",
    "mobile": "мобильная разработка: React Native, Expo, iOS, Android",
    "qa": "тестирование: ручное, автотесты, API-тесты, нагрузочное",
    "fullstack": "и фронтенд, и бэкенд сразу, либо роль не определяется однозначно",
}


def normalize_role(raw) -> str:
    """Ответ модели -> валидная роль. Всё неопознанное становится DEFAULT_ROLE.

    Прощаем форму, а не содержание: регистр, пробелы и подчёркивание вместо
    дефиса это та же роль, а `devops` это не роль из нашего списка.
    """
    role = str(raw or "").strip().lower().replace("_", "-")
    return role if role in ROLES else DEFAULT_ROLE
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `./sender/.venv/bin/python -m pytest sender/tests/test_cv_role.py -q`
Expected: PASS, 6 тестов

- [ ] **Step 5: Коммит**

```bash
git add sender/app/domain/cv_role.py sender/tests/test_cv_role.py
git commit -m "feat: словарь ролей для CV под роль"
```

---

### Task 2: Поиск файла CV на диске

**Files:**
- Create: `sender/app/domain/cv_files.py`
- Modify: `sender/app/config.py:38-53` (`_resolve_cv_path`)
- Test: `sender/tests/test_cv_files.py`

**Interfaces:**
- Consumes: `DEFAULT_ROLE` из Task 1
- Produces: `CV_SUFFIXES: tuple[str, ...]`, `find_role_cv(cv_dir, role) -> Path | None`, `find_any_cv(cv_dir, prefer_role=DEFAULT_ROLE) -> Path | None`

**Почему правится `config.py`:** сегодня `_resolve_cv_path()` смотрит только файлы верхнего уровня `sender/cv/`. Как только CV переедут в подпапки, верхний уровень останется пустым, функция бросит `FileNotFoundError` **на импорте конфига**, и умрёт всё приложение, а не одна фича.

- [ ] **Step 1: Написать падающий тест**

Создать `sender/tests/test_cv_files.py`:

```python
"""Поиск файла CV. Чистый pathlib, никакой загрузки содержимого."""
from app.domain.cv_files import find_any_cv, find_role_cv


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4 fake")
    return path


def test_finds_the_pdf_in_the_role_folder(tmp_path):
    want = _touch(tmp_path / "qa" / "Bolatbek_QA.pdf")
    assert find_role_cv(tmp_path, "qa") == want


def test_missing_role_folder_gives_none(tmp_path):
    assert find_role_cv(tmp_path, "qa") is None


def test_empty_role_folder_gives_none(tmp_path):
    (tmp_path / "qa").mkdir()
    assert find_role_cv(tmp_path, "qa") is None


def test_ignores_files_that_are_not_a_cv(tmp_path):
    (tmp_path / "qa").mkdir()
    (tmp_path / "qa" / "cv.tex").write_text("\\documentclass{article}")
    (tmp_path / "qa" / ".DS_Store").write_bytes(b"junk")
    assert find_role_cv(tmp_path, "qa") is None


def test_txt_counts_as_a_cv(tmp_path):
    want = _touch(tmp_path / "ai" / "cv.txt")
    assert find_role_cv(tmp_path, "ai") == want


def test_any_cv_prefers_a_top_level_file(tmp_path):
    """Обратная совместимость: у кого CV лежит как раньше, тот ничего не заметит."""
    top = _touch(tmp_path / "Bolatbek.pdf")
    _touch(tmp_path / "ai" / "ai.pdf")
    assert find_any_cv(tmp_path) == top


def test_any_cv_then_prefers_the_default_role(tmp_path):
    """Без файла наверху берём fullstack, а не первую папку по алфавиту."""
    _touch(tmp_path / "ai" / "ai.pdf")
    want = _touch(tmp_path / "fullstack" / "fs.pdf")
    assert find_any_cv(tmp_path) == want


def test_any_cv_falls_back_to_the_first_subfolder(tmp_path):
    want = _touch(tmp_path / "ai" / "ai.pdf")
    _touch(tmp_path / "mobile" / "mob.pdf")
    assert find_any_cv(tmp_path) == want


def test_any_cv_on_an_empty_dir_gives_none(tmp_path):
    assert find_any_cv(tmp_path) is None


def test_any_cv_on_a_missing_dir_gives_none(tmp_path):
    assert find_any_cv(tmp_path / "нет-такой") is None
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `./sender/.venv/bin/python -m pytest sender/tests/test_cv_files.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'app.domain.cv_files'`

- [ ] **Step 3: Написать модуль**

Создать `sender/app/domain/cv_files.py`:

```python
"""Где лежит файл CV. Только pathlib: содержимое читает CvLibrary."""
from pathlib import Path

from app.domain.cv_role import DEFAULT_ROLE

CV_SUFFIXES = (".pdf", ".txt")


def _first_cv(directory: Path) -> Path | None:
    """Первый по алфавиту файл-CV прямо в этой папке."""
    if not directory.is_dir():
        return None
    files = sorted(p for p in directory.iterdir()
                   if p.is_file() and p.suffix.lower() in CV_SUFFIXES)
    return files[0] if files else None


def find_role_cv(cv_dir, role: str) -> Path | None:
    """CV для конкретной роли, то есть файл в папке с её именем."""
    return _first_cv(Path(cv_dir) / role)


def find_any_cv(cv_dir, prefer_role: str = DEFAULT_ROLE) -> Path | None:
    """Хоть какое-нибудь CV: верхний уровень, затем prefer_role, затем любая папка.

    Верхний уровень идёт первым ради обратной совместимости: у кого файл лежит
    как раньше, прямо в `sender/cv/`, тот не должен заметить появления папок.
    """
    root = Path(cv_dir)
    if not root.is_dir():
        return None
    found = _first_cv(root) or find_role_cv(root, prefer_role)
    if found is not None:
        return found
    for sub in sorted(p for p in root.iterdir() if p.is_dir()):
        found = _first_cv(sub)
        if found is not None:
            return found
    return None
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `./sender/.venv/bin/python -m pytest sender/tests/test_cv_files.py -q`
Expected: PASS, 10 тестов

- [ ] **Step 5: Починить `_resolve_cv_path`**

В `sender/app/config.py` добавить импорт рядом с существующими:

```python
from app.domain.cv_files import find_any_cv
```

и заменить тело поиска (сейчас `sender/app/config.py:42-47`):

```python
    if CV_DIR.is_dir():
        files = sorted(
            p for p in CV_DIR.iterdir()
            if p.is_file() and p.suffix.lower() in (".pdf", ".txt")
        )
        if files:
            return str(files[0])
```

на:

```python
    # Ищем и в подпапках ролей тоже. Иначе, как только CV переедут в
    # sender/cv/<роль>/, верхний уровень опустеет и эта функция бросит
    # FileNotFoundError прямо на импорте конфига, уронив всё приложение.
    if CV_DIR.is_dir():
        found = find_any_cv(CV_DIR)
        if found is not None:
            return str(found)
```

- [ ] **Step 6: Проверить, что приложение поднимается при CV только в подпапке**

Run:

```bash
cd /Users/bolatbek/telegram-jobs && ./sender/.venv/bin/python - <<'PY'
import sys, tempfile, pathlib
sys.path.insert(0, "sender")
from app.domain.cv_files import find_any_cv
with tempfile.TemporaryDirectory() as d:
    root = pathlib.Path(d)
    (root / "fullstack").mkdir()
    (root / "fullstack" / "cv.pdf").write_bytes(b"x")
    print("нашёл:", find_any_cv(root))
PY
```

Expected: печатает путь, оканчивающийся на `fullstack/cv.pdf`

- [ ] **Step 7: Прогнать весь набор тестов**

Run: `./sender/.venv/bin/python -m pytest sender/tests -q -m "not live"`
Expected: PASS, не меньше 762

- [ ] **Step 8: Коммит**

```bash
git add sender/app/domain/cv_files.py sender/app/config.py sender/tests/test_cv_files.py
git commit -m "feat: поиск CV в подпапках ролей, конфиг больше не падает при пустом верхнем уровне"
```

---

### Task 3: CvLibrary

**Files:**
- Create: `sender/app/application/cv_library.py`
- Test: `sender/tests/test_cv_library.py`

**Interfaces:**
- Consumes: `find_role_cv` (Task 2), `normalize_role`, `DEFAULT_ROLE` (Task 1), `load_cv_text` из `app.infrastructure.cv_loader`
- Produces: `CvVariant(role: str, text: str, pdf_path: str)` (frozen dataclass), `CvLibrary(cv_dir, fallback_pdf: str, load_text=load_cv_text)` с методом `for_role(role: str) -> CvVariant`

- [ ] **Step 1: Написать падающий тест**

Создать `sender/tests/test_cv_library.py`:

```python
"""CvLibrary: роль -> текст CV для промпта и PDF для вложения."""
from app.application.cv_library import CvLibrary, CvVariant


def _touch(path, body=b"%PDF fake"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


def _lib(tmp_path, fallback="/нет/такого.pdf"):
    """Загрузчик подменён: настоящий парсит PDF, а нам нужна проверяемая строка."""
    return CvLibrary(tmp_path, fallback, load_text=lambda p: f"ТЕКСТ:{p}")


def test_returns_the_cv_of_the_requested_role(tmp_path):
    want = _touch(tmp_path / "qa" / "Bolatbek_QA.pdf")
    variant = _lib(tmp_path).for_role("qa")
    assert variant == CvVariant(role="qa", text=f"ТЕКСТ:{want}", pdf_path=str(want))


def test_unknown_role_name_falls_back_to_fullstack(tmp_path):
    want = _touch(tmp_path / "fullstack" / "fs.pdf")
    variant = _lib(tmp_path).for_role("devops")
    assert variant.role == "fullstack"
    assert variant.pdf_path == str(want)


def test_missing_role_folder_falls_back_to_fullstack(tmp_path):
    """Роль валидная, но CV под неё ещё не собрали."""
    want = _touch(tmp_path / "fullstack" / "fs.pdf")
    variant = _lib(tmp_path).for_role("mobile")
    assert variant.role == "fullstack"
    assert variant.pdf_path == str(want)


def test_without_any_folder_falls_back_to_the_legacy_file(tmp_path):
    """Последняя ступень: ровно то, что уходит сегодня."""
    legacy = _touch(tmp_path.parent / "legacy.pdf")
    variant = CvLibrary(tmp_path, str(legacy), load_text=lambda p: f"ТЕКСТ:{p}").for_role("ai")
    assert variant.role == "fullstack"
    assert variant.pdf_path == str(legacy)


def test_the_file_is_read_only_once(tmp_path):
    """Разбор PDF дорогой, а лидов в прогоне сотни."""
    _touch(tmp_path / "ai" / "ai.pdf")
    calls = []

    def counting_load(path):
        calls.append(path)
        return "текст"

    lib = CvLibrary(tmp_path, "/нет.pdf", load_text=counting_load)
    lib.for_role("ai")
    lib.for_role("ai")
    assert len(calls) == 1


def test_two_roles_falling_back_to_the_same_file_read_it_once(tmp_path):
    _touch(tmp_path / "fullstack" / "fs.pdf")
    calls = []

    def counting_load(path):
        calls.append(path)
        return "текст"

    lib = CvLibrary(tmp_path, "/нет.pdf", load_text=counting_load)
    lib.for_role("ai")
    lib.for_role("mobile")
    assert len(calls) == 1
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `./sender/.venv/bin/python -m pytest sender/tests/test_cv_library.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'app.application.cv_library'`

- [ ] **Step 3: Написать модуль**

Создать `sender/app/application/cv_library.py`:

```python
"""Роль -> CV: текст для промпта и файл для вложения, с откатами."""
from dataclasses import dataclass
from pathlib import Path

from app.domain.cv_files import find_role_cv
from app.domain.cv_role import DEFAULT_ROLE, normalize_role
from app.infrastructure.cv_loader import load_cv_text


@dataclass(frozen=True)
class CvVariant:
    role: str        # роль, чьё CV РЕАЛЬНО отдали (после откатов), а не запрошенная
    text: str        # для промпта генерации письма
    pdf_path: str    # для вложения к письму


class CvLibrary:
    """Отдаёт CV под роль, откатываясь до тех пор, пока что-нибудь не найдётся.

    Цепочка: папка роли -> папка fullstack -> файл, который уходит сегодня.
    Последняя ступень важнее всего: она гарантирует, что худший случай равен
    нынешнему поведению, и ни один лид не остаётся без CV.
    """

    def __init__(self, cv_dir, fallback_pdf: str, load_text=load_cv_text):
        self._cv_dir = Path(cv_dir)
        self._fallback_pdf = fallback_pdf
        self._load_text = load_text
        self._by_role: dict[str, CvVariant] = {}
        self._text_by_path: dict[str, str] = {}

    def for_role(self, role: str) -> CvVariant:
        role = normalize_role(role)
        if role not in self._by_role:
            self._by_role[role] = self._build(role)
        return self._by_role[role]

    def _build(self, role: str) -> CvVariant:
        path = find_role_cv(self._cv_dir, role)
        resolved = role
        if path is None:
            path = find_role_cv(self._cv_dir, DEFAULT_ROLE)
            resolved = DEFAULT_ROLE
        if path is None:
            path = Path(self._fallback_pdf)
            resolved = DEFAULT_ROLE
        return CvVariant(role=resolved, text=self._text_for(str(path)),
                         pdf_path=str(path))

    def _text_for(self, path: str) -> str:
        # Кэш по ПУТИ, а не по роли: разбор PDF дорогой, а несколько ролей,
        # откатившихся на один и тот же файл, читать его повторно не должны.
        if path not in self._text_by_path:
            self._text_by_path[path] = self._load_text(path)
        return self._text_by_path[path]
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `./sender/.venv/bin/python -m pytest sender/tests/test_cv_library.py -q`
Expected: PASS, 6 тестов

- [ ] **Step 5: Коммит**

```bash
git add sender/app/application/cv_library.py sender/tests/test_cv_library.py
git commit -m "feat: CvLibrary отдаёт CV под роль с откатом на fullstack"
```

---

### Task 4: Классификация роли

**Files:**
- Create: `sender/app/application/classify_role.py`
- Test: `sender/tests/test_classify_role.py`

**Interfaces:**
- Consumes: `ROLE_DESCRIPTIONS`, `DEFAULT_ROLE`, `normalize_role` (Task 1)
- Produces: `RoleClassifier` (Protocol с методом `classify(vacancy_context: str) -> str`), `build_role_prompt(vacancy_context: str) -> tuple[str, str]`, `parse_role_response(raw: str) -> str`, `classify_role(classifier, vacancy_context: str) -> str`

Строение повторяет `app/application/relevance.py`: чистый промпт и разбор живут в application, вызов модели — в infrastructure.

- [ ] **Step 1: Написать падающий тест**

Создать `sender/tests/test_classify_role.py`:

```python
"""Определение роли по вакансии: чистая часть, без похода в сеть."""
from app.application.classify_role import (
    build_role_prompt,
    classify_role,
    parse_role_response,
)
from app.domain.cv_role import DEFAULT_ROLE


def test_parse_clean_json():
    assert parse_role_response('{"role": "backend-go"}') == "backend-go"


def test_parse_extracts_json_amid_prose():
    assert parse_role_response('Конечно: {"role": "qa"} готово') == "qa"


def test_parse_normalizes_shape():
    assert parse_role_response('{"role": "Backend_Node"}') == "backend-node"


def test_parse_unknown_role_falls_back():
    assert parse_role_response('{"role": "devops"}') == DEFAULT_ROLE


def test_parse_malformed_falls_back():
    assert parse_role_response("это вообще не json") == DEFAULT_ROLE
    assert parse_role_response("") == DEFAULT_ROLE


def test_prompt_lists_every_role_with_its_description():
    system, user = build_role_prompt("текст вакансии")
    assert "ai" in system and "backend-go" in system and "qa" in system
    assert "LLM" in system            # описание роли ai
    assert "текст вакансии" in user
    assert "JSON" in system


def test_classify_returns_what_the_model_said():
    class _Ok:
        def classify(self, vacancy_context):
            return "frontend"

    assert classify_role(_Ok(), "React, Next.js, вёрстка") == "frontend"


def test_classify_swallows_a_failure():
    """Обвал OpenAI не должен ронять прогон: лид получит запасное CV."""
    class _Boom:
        def classify(self, vacancy_context):
            raise RuntimeError("сеть легла")

    assert classify_role(_Boom(), "любой текст") == DEFAULT_ROLE


def test_classify_does_not_call_the_model_on_empty_text():
    """Пустая вакансия это не роль, а отсутствие данных. Платить за неё незачем."""
    class _Counting:
        calls = 0

        def classify(self, vacancy_context):
            _Counting.calls += 1
            return "ai"

    assert classify_role(_Counting(), "   ") == DEFAULT_ROLE
    assert _Counting.calls == 0
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `./sender/.venv/bin/python -m pytest sender/tests/test_classify_role.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'app.application.classify_role'`

- [ ] **Step 3: Написать модуль**

Создать `sender/app/application/classify_role.py`:

```python
"""Какая роль у вакансии. Решает модель, потому что слова решают плохо.

Регулярка по ключевым словам на 101 отправленном письме не смогла определить
роль в 9 случаях: объявление вида «ищем инженера, который соберёт пайплайны с
моделями и не боится бэкенда» не содержит ни `AI`, ни `backend` в узнаваемом
виде. Поэтому выбор идёт по смыслу требований.
"""
import json
import re
from typing import Protocol

from app.domain.cv_role import DEFAULT_ROLE, ROLE_DESCRIPTIONS, normalize_role

_ROLE_LINES = "\n".join(f"- {role}: {desc}"
                        for role, desc in ROLE_DESCRIPTIONS.items())

_ROLE_SYSTEM = (
    "Ты определяешь, к какой роли относится вакансия. "
    'Верни ТОЛЬКО JSON: {"role": "<один ключ из списка ниже>"}. '
    "Выбирай ПО СМЫСЛУ задач и требований, а не по совпадению слов в заголовке. "
    "Если вакансия про несколько направлений сразу или роль не ясна, верни "
    f'"{DEFAULT_ROLE}". Ключи ролей:\n{_ROLE_LINES}'
)


class RoleClassifier(Protocol):
    def classify(self, vacancy_context: str) -> str:
        ...


def build_role_prompt(vacancy_context: str) -> tuple[str, str]:
    user = f"=== ВАКАНСИЯ ===\n{vacancy_context}\n\nВерни только JSON."
    return _ROLE_SYSTEM, user


def parse_role_response(raw: str) -> str:
    """Ответ модели -> валидная роль. Любой мусор становится DEFAULT_ROLE."""
    try:
        m = re.search(r"\{.*\}", raw or "", re.DOTALL)
        data = json.loads(m.group(0)) if m else {}
        return normalize_role(data.get("role"))
    except Exception:  # noqa: BLE001 — чужой текст, разбор может не удаться
        return DEFAULT_ROLE


def classify_role(classifier, vacancy_context: str) -> str:
    """Роль лида. Никогда не бросает: без роли лид всё равно должен уехать.

    Ошибки проглатываются по той же причине, что и в `generate_body`: обвал
    OpenAI не должен уносить весь прогон. Лид получит запасное CV, то есть
    ровно то, которое уходит сегодня.
    """
    try:
        # Проверка ВНУТРИ try, как в `generate_body`: снаружи она сама
        # становится веткой, которая бросает — на нестроковом входе `.strip()`
        # даёт AttributeError мимо всех except, и прогон падает целиком.
        # Тип проверяется отдельно от пустоты, а не приведением str(): str(12345)
        # даёт непустую "12345", и нестроковый объект уехал бы в классификатор.
        if not isinstance(vacancy_context, str) or not vacancy_context.strip():
            return DEFAULT_ROLE
        return normalize_role(classifier.classify(vacancy_context))
    except Exception:  # noqa: BLE001 — сбой классификации это не потеря лида
        return DEFAULT_ROLE
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `./sender/.venv/bin/python -m pytest sender/tests/test_classify_role.py -q`
Expected: PASS, 9 тестов

- [ ] **Step 5: Коммит**

```bash
git add sender/app/application/classify_role.py sender/tests/test_classify_role.py
git commit -m "feat: классификация роли вакансии с откатом на fullstack"
```

---

### Task 5: Вызов модели

**Files:**
- Create: `sender/app/infrastructure/openai_role.py`

**Interfaces:**
- Consumes: `build_role_prompt`, `parse_role_response` (Task 4)
- Produces: `OpenAIRoleClassifier(api_key: str, model: str, max_output_tokens: int = 2000)` с методом `classify(vacancy_context: str) -> str`

- Test: `sender/tests/test_model_routing.py` (существующий файл, дополняется)

**Поправка к первой редакции плана.** Здесь стояло «отдельного юнит-теста нет намеренно, потому что `openai_relevance.py` рядом устроен так же». Это было **фактически неверно** и проверено при исполнении: `test_model_routing.py:45,54,82` тестирует `OpenAIRelevanceScorer` через `_FakeClient`, а `:109` существует ровно затем, чтобы поймать потерю `response_format` при рефакторинге. Тест нужен, и он идёт в тот же файл, где живёт вся оснастка.

- [ ] **Step 1: Написать модуль**

Создать `sender/app/infrastructure/openai_role.py`:

```python
"""Определение роли вакансии дешёвой моделью. Зеркало openai_relevance.py."""
from openai import OpenAI

from app.application.classify_role import build_role_prompt, parse_role_response


class OpenAIRoleClassifier:
    """Один короткий вызов на лид, поэтому модель дешёвая (OPENAI_MODEL_CHEAP).

    Идёт ДО генерации письма: текст выбранного CV попадает в промпт генерации,
    значит роль должна быть известна раньше.
    """

    def __init__(self, api_key: str, model: str, max_output_tokens: int = 2000):
        self._client = OpenAI(api_key=api_key)
        self._model = model
        self._max_output_tokens = max_output_tokens

    def classify(self, vacancy_context: str) -> str:
        system, user = build_role_prompt(vacancy_context)
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            max_completion_tokens=self._max_output_tokens,
        )
        return parse_role_response(resp.choices[0].message.content or "")
```

- [ ] **Step 2: Дописать тесты в `sender/tests/test_model_routing.py`**

Файл уже содержит `_FakeClient`/`_FakeCompletions` — новый файл не заводить. Фабрика рядом с `_scorer`, по её форме:

```python
def _classifier(content='{"role": "backend-go"}', **kw):
    c = OpenAIRoleClassifier.__new__(OpenAIRoleClassifier)
    c._client = _FakeClient(content)
    c._model = kw.get("model", "cheap-model")
    c._max_output_tokens = kw.get("max_output_tokens", 2000)
    return c
```

В секцию `# --- model routing ---`:

```python
def test_role_classification_uses_the_model_it_was_given():
    """Классификация идёт на КАЖДЫЙ лид, поэтому модель обязана быть дешёвой."""
    c = _classifier(model="gpt-5.4-nano")
    c.classify("Backend Engineer. Go, Gin, PostgreSQL.")

    (kw,) = c._client.chat.completions.calls
    assert kw["model"] == "gpt-5.4-nano"
```

В секцию `# --- output cap ---`:

```python
def test_role_classification_caps_the_reply_length():
    c = _classifier(max_output_tokens=800)
    c.classify("Backend Engineer. Go, Gin, PostgreSQL.")

    (kw,) = c._client.chat.completions.calls
    assert kw["max_completion_tokens"] == 800


def test_role_classification_still_requests_json():
    """Разбор ответа ищет JSON: без response_format парсер молча съедет на fullstack."""
    c = _classifier()
    c.classify("Backend Engineer. Go, Gin, PostgreSQL.")

    (kw,) = c._client.chat.completions.calls
    assert kw["response_format"] == {"type": "json_object"}
```

В секцию `# --- defaults ---`:

```python
def test_role_classifier_is_capped_even_when_the_caller_omits_the_kwarg():
    c = OpenAIRoleClassifier("key-unused", "some-model")
    assert c._max_output_tokens > 0
```

- [ ] **Step 3: Прогнать весь набор тестов**

Run: `./sender/.venv/bin/python -m pytest sender/tests -q -m "not live"`
Expected: PASS, не меньше 781

- [ ] **Step 4: Живая проверка на настоящих вакансиях**

Run:

```bash
cd /Users/bolatbek/telegram-jobs/sender && ./.venv/bin/python - <<'PY'
import sys; sys.path.insert(0, ".")
from app import config
from app.infrastructure.openai_role import OpenAIRoleClassifier
from app.application.classify_role import classify_role

CASES = {
    "AI": "Ищем инженера, который соберёт пайплайны с языковыми моделями: "
          "промпты, агенты, retrieval поверх нашей базы знаний. Python.",
    "Go": "Backend Engineer. Go, Gin, PostgreSQL, gRPC, высокая нагрузка.",
    "QA": "Нужен тестировщик: тест-кейсы, регресс, баг-репорты в Jira, "
          "автотесты на Playwright, проверка API через Postman.",
    "RN": "React Native разработчик. Expo, публикация в App Store и Google Play.",
    "Front": "Frontend: React, Next.js, TypeScript, Zustand, вёрстка макетов.",
    "Node": "Backend Node.js: NestJS, Prisma, PostgreSQL, очереди BullMQ.",
}
c = OpenAIRoleClassifier(config.OPENAI_API_KEY, config.OPENAI_MODEL_CHEAP)
for name, text in CASES.items():
    print(f"{name:6} -> {classify_role(c, text)}")
PY
```

Expected: `AI -> ai`, `Go -> backend-go`, `QA -> qa`, `RN -> mobile`, `Front -> frontend`, `Node -> backend-node`. Если хоть одна не совпала — не идти дальше, а поправить описания в `ROLE_DESCRIPTIONS` или системный промпт и прогнать снова.

- [ ] **Step 5: Коммит**

```bash
git add sender/app/infrastructure/openai_role.py sender/tests/test_model_routing.py
git commit -m "feat: OpenAIRoleClassifier на дешёвой модели"
```

---

### Task 6: CV передаётся в вызов генерации

**Files:**
- Modify: `sender/app/application/generate_message.py:13-37` (`execute`, `execute_with_note`), `:40-74` (`generate_body`, `generate_for`)
- Test: `sender/tests/test_generate_with_cv_text.py`

**Interfaces:**
- Consumes: ничего нового
- Produces: `GenerateMessage.execute(lead, cv_text: str = "") -> str`, `GenerateMessage.execute_with_note(lead, note_limit: int, cv_text: str = "") -> tuple[str, str]`, `generate_body(generator, lead, cv_text: str = "")`, `generate_for(generator, lead, channel, cv_text: str = "")`

Параметр необязательный: без него поведение прежнее (берётся `cv_text` из конструктора). Поэтому `sender/test_send.py` и существующие тесты не правятся.

- [ ] **Step 1: Написать падающий тест**

Создать `sender/tests/test_generate_with_cv_text.py`:

```python
"""CV выбирается на каждый лид, значит приходит в вызов, а не в конструктор."""
from app.application.generate_message import GenerateMessage, generate_for
from app.domain.lead import Lead


class _Ai:
    def __init__(self):
        self.seen_cv = None

    def generate(self, cv_text, profile_text, vacancy_context):
        self.seen_cv = cv_text
        return "письмо"

    def generate_with_note(self, cv_text, profile_text, vacancy_context, note_limit):
        self.seen_cv = cv_text
        return "письмо", "записка"


class _Chan:
    name = "linkedin"
    note_limit = 200


class _Plain:
    name = "telegram"


def _lead():
    return Lead(row=2, lead_id="1", platform="linkedin", target="u",
                vacancy_context="вакансия", raw_text="вакансия", status="new")


def test_per_call_cv_wins_over_the_constructor_one():
    ai = _Ai()
    GenerateMessage(ai, "СТАРОЕ-CV", "profile").execute(_lead(), "CV-ПОД-РОЛЬ")
    assert ai.seen_cv == "CV-ПОД-РОЛЬ"


def test_without_a_per_call_cv_the_constructor_one_is_used():
    ai = _Ai()
    GenerateMessage(ai, "СТАРОЕ-CV", "profile").execute(_lead())
    assert ai.seen_cv == "СТАРОЕ-CV"


def test_the_note_path_gets_the_same_cv():
    ai = _Ai()
    GenerateMessage(ai, "СТАРОЕ-CV", "profile").execute_with_note(
        _lead(), 200, "CV-ПОД-РОЛЬ")
    assert ai.seen_cv == "CV-ПОД-РОЛЬ"


def test_generate_for_passes_the_cv_on_the_note_channel():
    ai = _Ai()
    generate_for(GenerateMessage(ai, "СТАРОЕ-CV", "p"), _lead(), _Chan(), "CV-ПОД-РОЛЬ")
    assert ai.seen_cv == "CV-ПОД-РОЛЬ"


def test_generate_for_passes_the_cv_on_a_plain_channel():
    ai = _Ai()
    generate_for(GenerateMessage(ai, "СТАРОЕ-CV", "p"), _lead(), _Plain(), "CV-ПОД-РОЛЬ")
    assert ai.seen_cv == "CV-ПОД-РОЛЬ"
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `./sender/.venv/bin/python -m pytest sender/tests/test_generate_with_cv_text.py -q`
Expected: FAIL, `TypeError: execute() takes 2 positional arguments but 3 were given`

- [ ] **Step 3: Править `generate_message.py`**

`execute` (сейчас строки 13-21):

```python
    def execute(self, lead: Lead, cv_text: str = "") -> str:
        body = self._ai.generate(
            cv_text=cv_text or self._cv_text,
            profile_text=self._profile_text,
            vacancy_context=lead.vacancy_context or lead.raw_text,
        )
        if self._signature_text:
            return f"{body}\n\n{self._signature_text}"
        return body
```

`execute_with_note` (сейчас строки 23-37) — поменять сигнатуру и первый аргумент вызова:

```python
    def execute_with_note(self, lead: Lead, note_limit: int,
                          cv_text: str = "") -> tuple[str, str]:
        """(письмо, записка) для канала, у которого есть отдельная короткая форма.

        Подпись приклеивается ТОЛЬКО к письму: в записку на ~200 символов она не
        влезает, а LinkedIn рядом с приглашением и так показывает, кто пишет.
        """
        letter, note = self._ai.generate_with_note(
            cv_text=cv_text or self._cv_text,
            profile_text=self._profile_text,
            vacancy_context=lead.vacancy_context or lead.raw_text,
            note_limit=note_limit,
        )
        if self._signature_text:
            letter = f"{letter}\n\n{self._signature_text}"
        return letter, note
```

`generate_body` — добавить параметр и передать:

```python
def generate_body(generator, lead, cv_text: str = ""):
```

и внутри `try`: `return generator.execute(lead, cv_text), None`

`generate_for` — добавить параметр и протащить в обе ветки:

```python
def generate_for(generator, lead, channel, cv_text: str = ""):
```

```python
    note_limit = getattr(channel, "note_limit", None)
    if not note_limit:
        body, err = generate_body(generator, lead, cv_text)
        return body, "", err
    try:
        body, note = generator.execute_with_note(lead, note_limit, cv_text)
        return body, note, None
```

В докстроке `GenerateMessage.__init__` дополнить комментарий про `cv_text`:

```python
        # cv_text здесь это запасной вариант: реальное CV выбирается под роль
        # лида и приходит в execute/execute_with_note отдельным аргументом.
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `./sender/.venv/bin/python -m pytest sender/tests/test_generate_with_cv_text.py -q`
Expected: PASS, 5 тестов

- [ ] **Step 5: Проверить, что старые тесты не сломались**

Run: `./sender/.venv/bin/python -m pytest sender/tests -q -m "not live"`
Expected: PASS, не меньше 782

- [ ] **Step 6: Коммит**

```bash
git add sender/app/application/generate_message.py sender/tests/test_generate_with_cv_text.py
git commit -m "feat: CV передаётся в вызов генерации, а не зашивается в генератор"
```

---

### Task 7: Проводка в CLI

**Files:**
- Modify: `sender/app/interface/cli.py:141` (сигнатура `_followup_invited`), `:204,216-217` (путь принятых приглашений), `:236-248` (`run`), `:253` (вызов), `:420-445` (основной цикл)
- Modify: `sender/tests/test_followup_invited.py` — см. предупреждение ниже
- Test: `sender/tests/test_cli_role_wiring.py`

**Предупреждение, найденное ревью Task 6.** `sender/tests/test_followup_invited.py` содержит дак-тайпинговые стенды `_Generator`, `_NoteGen`, `_PlaceholderNoteGen`, чьи `execute`/`execute_with_note` объявлены **без** параметра `cv_text`. Эта задача меняет сигнатуру `_followup_invited` и начинает передавать непустой `variant.text` — стенды либо упадут с `TypeError`, либо, что хуже, тихо провалятся в ветку «генерация не удалась» (`generate_for` глотает любое исключение по политике инцидента row-82) и тесты станут проверять не то, что обещают их имена. Стендам надо дописать `cv_text: str = ""` в обе сигнатуры. Проверь, что после правки они по-прежнему проверяют заявленное поведение, а не откат.

**Interfaces:**
- Consumes: `classify_role` (Task 4), `CvLibrary`/`CvVariant` (Task 3), `OpenAIRoleClassifier` (Task 5), `generate_for(..., cv_text)` (Task 6)
- Produces: `_followup_invited(repo, switcher, generator, classifier, cv_library)`

- [ ] **Step 1: Написать падающий тест**

Создать `sender/tests/test_cli_role_wiring.py`:

```python
"""Проводка: письмо и вложение обязаны прийти из одного и того же CV."""
from app.application.classify_role import classify_role
from app.application.cv_library import CvLibrary
from app.application.generate_message import GenerateMessage, generate_for
from app.domain.lead import Lead


class _Ai:
    def __init__(self):
        self.seen_cv = None

    def generate(self, cv_text, profile_text, vacancy_context):
        self.seen_cv = cv_text
        return "письмо"

    def generate_with_note(self, cv_text, profile_text, vacancy_context, note_limit):
        self.seen_cv = cv_text
        return "письмо", "записка"


class _Chan:
    name = "linkedin"
    note_limit = 200


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF fake")
    return path


def _lead(vacancy):
    return Lead(row=2, lead_id="1", platform="linkedin", target="u",
                vacancy_context=vacancy, raw_text=vacancy, status="new")


def test_letter_and_attachment_come_from_the_same_variant(tmp_path):
    qa_pdf = _touch(tmp_path / "qa" / "Bolatbek_QA.pdf")
    _touch(tmp_path / "fullstack" / "fs.pdf")
    library = CvLibrary(tmp_path, "/нет.pdf", load_text=lambda p: f"ТЕКСТ:{p}")

    class _SaysQa:
        def classify(self, vacancy_context):
            return "qa"

    ai = _Ai()
    role = classify_role(_SaysQa(), "нужен тестировщик")
    variant = library.for_role(role)
    generate_for(GenerateMessage(ai, "ЗАПАСНОЕ", "p"), _lead("нужен тестировщик"),
                 _Chan(), variant.text)

    assert variant.pdf_path == str(qa_pdf)
    assert ai.seen_cv == f"ТЕКСТ:{qa_pdf}"


def test_a_classifier_failure_still_produces_a_usable_pair(tmp_path):
    """Сеть легла: лид всё равно уезжает, с запасным CV."""
    fs_pdf = _touch(tmp_path / "fullstack" / "fs.pdf")
    library = CvLibrary(tmp_path, "/нет.pdf", load_text=lambda p: f"ТЕКСТ:{p}")

    class _Boom:
        def classify(self, vacancy_context):
            raise RuntimeError("сеть легла")

    ai = _Ai()
    variant = library.for_role(classify_role(_Boom(), "любая вакансия"))
    body, note, err = generate_for(GenerateMessage(ai, "ЗАПАСНОЕ", "p"),
                                   _lead("любая вакансия"), _Chan(), variant.text)

    assert err is None
    assert variant.role == "fullstack"
    assert variant.pdf_path == str(fs_pdf)
    assert ai.seen_cv == f"ТЕКСТ:{fs_pdf}"
```

- [ ] **Step 2: Прогнать тест — он должен пройти сразу**

Run: `./sender/.venv/bin/python -m pytest sender/tests/test_cli_role_wiring.py -q`
Expected: PASS, 2 теста

Честно про природу этого теста: он **не ведёт разработку**, он фиксирует контракт. Все части (Tasks 3, 4, 6) уже написаны, и тест собирает их так, как обязан собрать `cli.py`: письмо и вложение приходят из одного и того же `CvVariant`. Развести их — самая правдоподобная ошибка при правке `cli.py`, и после неё письмо про QA уедет с бэкендовым PDF, а тесты этого не заметят. Настоящая проверка самой проводки — шаг 6 (сигнатура и импорт) и шаг 7 (весь набор).

Если тест НЕ прошёл — значит Task 3 или Task 6 не доделан. Вернуться туда, а не чинить здесь.

- [ ] **Step 3: Править `run()` в `cli.py`**

Добавить импорты рядом с существующими (`sender/app/interface/cli.py:42` и соседние):

```python
from app.application.classify_role import classify_role
from app.application.cv_library import CvLibrary
from app.infrastructure.openai_role import OpenAIRoleClassifier
```

В `run()`, после создания `generator` (сейчас строки 242-246), добавить:

```python
    role_classifier = OpenAIRoleClassifier(config.OPENAI_API_KEY,
                                           config.OPENAI_MODEL_CHEAP)
    cv_library = CvLibrary(config.CV_DIR, config.CV_PATH)
```

- [ ] **Step 4: Править основной цикл**

Заменить блок генерации (сейчас `sender/app/interface/cli.py:425-445`). Было:

```python
            print(f"Вакансия: {lead.vacancy_context or lead.raw_text}")
            print("-" * 60)

            print("Генерирую сообщение...")
            body, note, gen_err = generate_for(generator, lead, channel)
```

Стало:

```python
            print(f"Вакансия: {lead.vacancy_context or lead.raw_text}")
            role = classify_role(role_classifier, lead.vacancy_context or lead.raw_text)
            variant = cv_library.for_role(role)
            print(f"Роль: {variant.role}  →  {Path(variant.pdf_path).name}")
            print("-" * 60)

            print("Генерирую сообщение...")
            body, note, gen_err = generate_for(generator, lead, channel, variant.text)
```

и ниже заменить строку вложения (сейчас `:444`):

```python
            attachment = variant.pdf_path if config.ATTACH_CV else None
```

Убедиться, что `Path` импортирован в `cli.py`; если нет — добавить `from pathlib import Path` к импортам стандартной библиотеки.

- [ ] **Step 5: Править путь принятых приглашений**

Сигнатура (сейчас `:141`):

```python
def _followup_invited(repo, switcher, generator, classifier, cv_library) -> None:
```

Блок генерации (сейчас `:204`). Было:

```python
        body, note, gen_err = generate_for(generator, lead, channel)
```

Стало:

```python
        variant = cv_library.for_role(
            classify_role(classifier, lead.vacancy_context or lead.raw_text))
        print(f"   #{lead.lead_id}: роль {variant.role}, "
              f"CV {Path(variant.pdf_path).name}")
        body, note, gen_err = generate_for(generator, lead, channel, variant.text)
```

Вложение (сейчас `:216`):

```python
        attachment = variant.pdf_path if config.ATTACH_CV else None
```

Вызов (сейчас `:253`):

```python
        _followup_invited(repo, switcher, generator, role_classifier, cv_library)
```

- [ ] **Step 6: Проверить, что модуль импортируется и сигнатуры сошлись**

Run:

```bash
cd /Users/bolatbek/telegram-jobs/sender && ./.venv/bin/python -c "
import sys, inspect; sys.path.insert(0, '.')
from app.interface import cli
print(inspect.signature(cli._followup_invited))
print('импорт ок')"
```

Expected: `(repo, switcher, generator, classifier, cv_library)` и `импорт ок`

- [ ] **Step 7: Прогнать весь набор тестов**

Run: `./sender/.venv/bin/python -m pytest sender/tests -q -m "not live"`
Expected: PASS, не меньше 784

- [ ] **Step 8: Коммит**

```bash
git add sender/app/interface/cli.py sender/tests/test_cli_role_wiring.py
git commit -m "feat: CV под роль лида в обоих путях отправки"
```

---

### Task 8: Ограничение длины стека в письме

**Files:**
- Modify: `sender/profile.md:29-35` (пункт 3 раздела «Структура сообщения»), `sender/app/infrastructure/openai_client.py:41-45` (`_SYSTEM`)

**Interfaces:**
- Consumes: ничего
- Produces: ничего (текст промпта)

Замер, ради которого это делается: в 101 отправленном письме строка «Мой стек» содержала в среднем 15,8–18,0 технологий, почти одинаковых во всех ролях. Правило продублировано в двух местах и должно поменяться в обоих, иначе они разъедутся.

- [ ] **Step 1: Править `profile.md`**

В пункте 3 раздела «Структура сообщения» после слов «прямо релевантными вакансии» добавить предложение:

```
   НЕ БОЛЬШЕ 7 технологий в этой строке: рекрутёр читает её за пару секунд, и
   список из шестнадцати пунктов читается как «я знаю всё», то есть как «ничего
   конкретного». Хвост «плюс к пониманию системы целиком» — не больше 4.
```

- [ ] **Step 2: Править `_SYSTEM`**

В `sender/app/infrastructure/openai_client.py`, в строке про стек, заменить:

```python
    "Стек подавай ПОД РОЛЬ: сначала строкой 'Мой стек:' (через двоеточие) технологии, "
    "релевантные вакансии (для React Native — React Native, TypeScript, JavaScript, REST API), "
    "и только потом, отдельно и короче, бэкенд/инфраструктуру как 'плюс к пониманию системы "
    "целиком'. Не вали фронт и бэк в одну кучу. "
```

на:

```python
    "Стек подавай ПОД РОЛЬ: сначала строкой 'Мой стек:' (через двоеточие) технологии, "
    "релевантные вакансии (для React Native — React Native, TypeScript, JavaScript, REST API), "
    "и только потом, отдельно и короче, бэкенд/инфраструктуру как 'плюс к пониманию системы "
    "целиком'. Не вали фронт и бэк в одну кучу. "
    "В строке 'Мой стек:' НЕ БОЛЬШЕ 7 технологий, в хвосте 'плюс к пониманию системы "
    "целиком' не больше 4. Список длиннее читается как 'я знаю всё', то есть как "
    "'ничего конкретного'. Выбирай те, что названы в самой вакансии. "
```

- [ ] **Step 3: Прогнать весь набор тестов**

Run: `./sender/.venv/bin/python -m pytest sender/tests -q -m "not live"`
Expected: PASS, столько же, сколько после Task 7

- [ ] **Step 4: Живая проверка длины стека**

Run:

```bash
cd /Users/bolatbek/telegram-jobs/sender && ./.venv/bin/python - <<'PY'
import re
import sys
sys.path.insert(0, ".")
from pathlib import Path

from app import config
from app.infrastructure.cv_loader import load_cv_text
from app.infrastructure.openai_client import OpenAIMessageGenerator

VAC = ("Backend Engineer (Go). Gin, PostgreSQL, gRPC, Redis, Docker. "
       "Требования: опыт от 3 лет с Go, уверенный SQL, REST и gRPC API.")

g = OpenAIMessageGenerator(config.OPENAI_API_KEY, config.OPENAI_MODEL)
letter = g.generate(
    cv_text=load_cv_text(config.CV_PATH),
    profile_text=Path("profile.md").read_text(),
    vacancy_context=VAC,
)
print(letter)

m = re.search(r"(?:Мой стек|My stack)\s*:\s*([^.\n]+)", letter, re.I)
if m:
    items = [t for t in re.split(r",| и ", m.group(1)) if t.strip()]
    print(f"\n>>> технологий в строке «Мой стек»: {len(items)}")
else:
    print("\n>>> строки «Мой стек» в письме нет")
PY
```

Expected: печатает `>>> технологий в строке: N`, где N не больше 7 (хвост «плюс к пониманию системы целиком» идёт после точки и в эту строку не входит). Если больше — усилить формулировку и повторить.

- [ ] **Step 5: Коммит**

```bash
git add sender/profile.md sender/app/infrastructure/openai_client.py
git commit -m "fix: ограничить строку «Мой стек» семью технологиями"
```

---

## Что этот план НЕ покрывает

**Содержимое восьми CV.** Оно описано в спеке (раздел 4), но требует исходника `.tex` с
Overleaf, которого на момент написания плана нет. Как только он появится — отдельный план:
восемь `.tex`, сборка через `tectonic` (уже установлен, версия 0.17.0) и проверка, что
каждое CV осталось на одной странице.

До появления файлов код работает и не ломается: все восемь ролей откатываются на
последнюю ступень цепочки, то есть на CV, которое уходит сегодня. Проверять это отдельно
не нужно — за это отвечает `test_without_any_folder_falls_back_to_the_legacy_file` в Task 3.

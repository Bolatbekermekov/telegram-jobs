"""Роли, под которые собраны отдельные CV. Единственный источник правды.

Имя роли это одновременно имя папки в `sender/cv/` и значение, которое
возвращает классификатор. Разъедятся они молча, поэтому список один.
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

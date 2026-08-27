from app.application.relevance import build_score_prompt, parse_score_response


def test_parse_clean_json():
    assert parse_score_response('{"score": 82, "reason": "Go backend + AI agents"}') == (
        82, "Go backend + AI agents")


def test_parse_extracts_json_amid_prose_and_clamps():
    assert parse_score_response('Sure: {"score": 200, "reason": "x"} done') == (100, "x")


def test_parse_malformed_returns_zero():
    assert parse_score_response("not json at all") == (0, "")


def test_build_score_prompt_includes_inputs():
    system, user = build_score_prompt("PROF", "TITLE", "DESC")
    assert "JSON" in system or "json" in system
    assert "PROF" in user and "TITLE" in user and "DESC" in user


def test_the_location_reaches_the_model():
    """Полстраницы профиля — про право работать и спонсорство визы, а страна
    вакансии до модели не доезжала: в промпт уходили только название и описание.

    Заметнее всего на remocate: локация там заполнена всегда и точна («🇩🇪
    Germany», «🌎 World»), а в описании карточки страны может не быть вовсе.
    """
    _, user = build_score_prompt("PROF", "TITLE", "DESC", "🇩🇪 Germany")
    assert "🇩🇪 Germany" in user


def test_an_empty_location_leaves_no_dangling_label():
    """Локацию отдают не все площадки, и подпись без значения — не пустое место,
    а факт: «Локация: » модель читает как «страна не указана» ровно так же, как
    `search_leads_repo._vacancy_text` читал бы «Зарплата: .».

    Пробелы считаются пустотой: hh отдаёт локацию через `inner_text` карточки, и
    оттуда приходит и перевод строки, и пустая строка.
    """
    for empty in ("", "   ", "\n\t"):
        _, user = build_score_prompt("PROF", "TITLE", "DESC", empty)
        assert "Локация" not in user


def test_a_multiline_location_stays_one_line():
    """hh кладёт в локацию `inner_text` адресного блока — там бывает несколько
    строк. Внутри «=== ВАКАНСИЯ ===» это разъезжается с описанием."""
    _, user = build_score_prompt("PROF", "TITLE", "DESC", "Астана\nКабанбай батыра")
    assert "Локация: Астана Кабанбай батыра" in user


def test_the_system_prompt_does_not_cap_the_level_below_the_profile():
    """Прежний системный промпт говорил «уровень выше Junior+ — низкий балл»,
    а профиль говорит «Middle — ПОДХОДИТ». Системное сообщение сильнее, и
    выигрывало оно: замер 2026-08-28, 38 прогонов, #422 QA Engineer (Mid/Senior)
    — 18..38 при пороге 60, ни одного прохода, и почти в каждом reason прямым
    текстом «уровень Mid/Senior» / «у профиля выше Junior+». Отклик на эту
    вакансию прогон когда-то ОТПРАВИЛ.

    Список ПОДХОДЯЩИХ уровней есть ровно в одном месте — в профиле, который
    правит владелец; второго, спорящего с ним, в промпте быть не должно. Список
    дисквалифицирующих (senior / lead / staff) там есть, но он списан с самого
    профиля и ему не противоречит.
    """
    system, _ = build_score_prompt("PROF", "TITLE", "DESC")
    assert "Junior" not in system


def test_the_system_prompt_names_what_must_not_lower_the_score():
    """Запрет снижать балл за неудалённый формат стоял в профиле — и не работал:
    профиль едет ПОЛЬЗОВАТЕЛЬСКИМ сообщением и проигрывает системному «будь
    строгим». Замеренные последствия (те же 38 прогонов): «требуется 3+ года»
    как дисквалификация, «гео/удалёнка не ясна» как минус, «нет опыта сетевого
    тестирования» как минус — при том, что профиль не запрещает ни первого, ни
    второго, а третье вообще не про него: профиль перечисляет, что владелец
    ИЩЕТ, а не весь его опыт.

    Одного запрета оказалось мало — рядом стоит ШКАЛА, называющая, за что балл
    ставится. С запретом без шкалы #422 остался на медиане 35, со шкалой —
    68..80 в 22 прогонах из 22.
    """
    system, _ = build_score_prompt("PROF", "TITLE", "DESC")
    assert "стаж" in system
    assert "удал" in system  # «неудалённо» в списке форматов работы
    assert "профиле нет" in system
    assert "Шкала" in system

"""Лид, ушедший в «ручные», обязан сохранить написанное письмо.

Живьём 2026-09-12: двадцать два лида Jobicy получили статус `manual` с точной
причиной и ссылкой — и без текста. Письмо к каждому было сгенерировано (генерация
идёт ДО открытия канала) и выброшено: ветка `manual` звала только `mark_status`,
который пишет статус и заметку, а колонку «Сообщение» не трогает.

Цена этого ровно в том, ради чего система существует. Ручной отклик с готовым
письмом — две минуты копипасты; без письма человек пишет его заново, хотя модель
уже отработала и деньги уже потрачены.
"""
from app.domain.lead import Lead, STATUS_MANUAL


class _Repo:
    def __init__(self):
        self.messages = {}
        self.statuses = {}

    def update_message(self, lead, message):
        self.messages[lead.lead_id] = message

    def mark_status(self, lead, status, note=""):
        self.statuses[lead.lead_id] = (status, note)


def _lead():
    return Lead(row=2, lead_id="1084", platform="remocate",
                target="https://www.remocate.app/jobs/go-dev", vacancy_context="Go dev",
                raw_text="", status="new")


def _record_manual(repo, lead, body, note):
    """Та же связка, что в цикле отправки: письмо, затем статус."""
    from app.interface.cli import _record_manual as impl
    return impl(repo, lead, body, note)


def test_the_letter_is_saved_before_the_status():
    repo = _Repo()
    _record_manual(repo, _lead(), "Здравствуйте! Меня зовут Болатбек…", "форма не распознана")
    assert repo.messages["1084"].startswith("Здравствуйте")


def test_the_status_and_reason_still_land():
    repo = _Repo()
    _record_manual(repo, _lead(), "письмо", "форма не распознана")
    assert repo.statuses["1084"] == (STATUS_MANUAL, "форма не распознана")


def test_an_empty_letter_does_not_blank_the_column():
    """Генерация могла и не состояться — затирать колонку пустотой нельзя."""
    repo = _Repo()
    _record_manual(repo, _lead(), "", "форма не распознана")
    assert "1084" not in repo.messages
    assert repo.statuses["1084"][0] == STATUS_MANUAL

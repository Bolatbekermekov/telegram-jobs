"""Выключатель площадки: прогон идёт, но забаненную площадку не трогает.

Нужен после бана LinkedIn 2026-08-26. Без него любой прогон открывал LinkedIn
первым же делом — проверкой приглашённых, — так что нельзя было отправить даже
Remocate, не засветив аккаунт под ограничением.

Главное правило здесь: пауза НЕ меняет статус лида. Он остаётся `new` и ждёт
снятия паузы. `skipped` был бы концом лида — прогон его больше не возьмёт, и
человек, которому мы собирались написать, тихо выпал бы из очереди.
"""
from app.domain.paused import is_paused, parse_paused


def test_empty_means_nothing_paused():
    assert parse_paused("") == frozenset()
    assert parse_paused(None) == frozenset()


def test_single_platform():
    assert parse_paused("linkedin") == frozenset({"linkedin"})


def test_comma_separated_with_spaces_and_case():
    # .env правят руками, поэтому пробелы и регистр — норма, а не ошибка ввода.
    assert parse_paused(" LinkedIn , HH ") == frozenset({"linkedin", "hh"})


def test_blank_items_dropped():
    # "linkedin,," — обычный след правки; пустая строка не должна стать площадкой,
    # иначе is_paused("") вернул бы True и прогон встал бы на лиде без площадки.
    assert parse_paused("linkedin,,") == frozenset({"linkedin"})


def test_is_paused_matches_case_insensitively():
    paused = parse_paused("LinkedIn")
    assert is_paused("linkedin", paused) is True
    assert is_paused("LINKEDIN", paused) is True


def test_is_paused_false_for_other_platforms():
    paused = parse_paused("linkedin")
    assert is_paused("remocate", paused) is False
    assert is_paused("hh", paused) is False


def test_blank_platform_is_never_paused():
    # Лид без площадки разбирает skip_reason, а не пауза: у него своя причина и
    # своя заметка человеку. Пауза не должна его перехватывать.
    assert is_paused("", parse_paused("linkedin")) is False
    assert is_paused(None, parse_paused("linkedin")) is False


# --- очередь прогона --------------------------------------------------------

from app.domain.paused import partition_paused   # noqa: E402


class _L:
    def __init__(self, lead_id, platform):
        self.lead_id, self.platform = lead_id, platform


def test_partition_keeps_order_and_splits_by_pause():
    leads = [_L("1", "remocate"), _L("2", "linkedin"), _L("3", "hh"),
             _L("4", "linkedin")]
    runnable, held = partition_paused(leads, parse_paused("linkedin"))

    assert [l.lead_id for l in runnable] == ["1", "3"]
    assert [l.lead_id for l in held] == ["2", "4"]


def test_partition_without_pause_runs_everything():
    leads = [_L("1", "remocate"), _L("2", "linkedin")]
    runnable, held = partition_paused(leads, frozenset())

    assert [l.lead_id for l in runnable] == ["1", "2"]
    assert held == []


# --- проверка приглашённых --------------------------------------------------
#
# Она открывает LinkedIn ПЕРВЫМ делом в каждом прогоне, до всякой очереди.
# Именно поэтому во время бана нельзя было запустить даже Remocate.

from datetime import datetime, timedelta        # noqa: E402

from app.domain.lead import STATUS_INVITED, Lead  # noqa: E402
from app.interface.cli import _followup_invited   # noqa: E402


class _Repo:
    def __init__(self, leads):
        self._leads, self.statuses, self.sent = leads, [], []

    def fetch_by_status(self, status):
        return list(self._leads) if status == STATUS_INVITED else []

    def mark_status(self, lead, status, note=""):
        self.statuses.append((lead.lead_id, status, note))

    def mark_sent(self, lead, message, status, note=""):
        self.sent.append((lead.lead_id, status))

    def update_vacancy(self, lead, vacancy_context):
        pass


class _Channel:
    name, body_limit, needs_subject = "linkedin", None, False

    def __init__(self):
        self.checked = []

    def invite_state(self, target):
        self.checked.append(target)
        return "pending"


class _Switcher:
    def __init__(self, channel):
        self._channel = channel
        self.opened = []

    def for_platform(self, platform):
        self.opened.append(platform)
        return self._channel


def _invited_lead():
    return Lead(row=80, lead_id="79", platform="linkedin",
                target="https://linkedin.com/in/x", vacancy_context="Backend",
                raw_text="", status=STATUS_INVITED,
                sent_at=datetime.now() - timedelta(days=1))


def test_paused_platform_invites_are_not_opened():
    repo, channel = _Repo([_invited_lead()]), _Channel()
    switcher = _Switcher(channel)

    _followup_invited(repo, switcher, None, None, None,
                      paused=parse_paused("linkedin"))

    assert switcher.opened == []        # канал вообще не поднимался
    assert channel.checked == []        # ни один профиль не открыт
    assert repo.statuses == []          # лид остался `invited`


def test_invites_are_checked_when_platform_is_not_paused():
    # Контроль: без паузы стенды выше действительно ходят в канал, иначе
    # предыдущий тест проходил бы и на сломанной проверке.
    repo, channel = _Repo([_invited_lead()]), _Channel()
    switcher = _Switcher(channel)

    _followup_invited(repo, switcher, None, None, None, paused=frozenset())

    assert switcher.opened == ["linkedin"]
    assert channel.checked == ["https://linkedin.com/in/x"]

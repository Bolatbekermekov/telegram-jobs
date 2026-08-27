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


# --- поиск ------------------------------------------------------------------
#
# Пауза родилась выключателем ОТПРАВКИ, и это была половина защиты: поиск ведёт
# свой список площадок (SEARCH_PLATFORMS), про паузу не знал вовсе и поднимал
# LinkedIn мимо неё — `make search`, `make search_linkedin` и авто-поиск воркера
# трижды в день. То есть аккаунт под баном открывался ровно тем, что было
# поставлено на паузу, чтобы туда не ходить.

import pytest                                                    # noqa: E402

from app import config                                           # noqa: E402
from app.application.worker_tick import worker_tick              # noqa: E402
from app.domain.paused import SearchPaused, partition_platforms  # noqa: E402
from app.domain.search_request import (                          # noqa: E402
    REQ_DONE, REQ_ERROR, SEARCH_PLATFORMS, SearchRequest,
)
from app.interface.cli import _make_run_one, run_search_once      # noqa: E402


def test_partition_platforms_splits_names_and_keeps_scrape_order():
    # На вход поиску приходят имена площадок, а не лиды, поэтому partition_paused
    # тут не годится. Порядок — это порядок обхода из SEARCH_PLATFORMS.
    runnable, held = partition_platforms(
        ["linkedin", "wellfound", "remoteok"], parse_paused("linkedin"))

    assert runnable == ["wellfound", "remoteok"]
    assert held == ["linkedin"]


def test_partition_platforms_without_pause_searches_everything():
    runnable, held = partition_platforms(["linkedin", "hh"], frozenset())

    assert runnable == ["linkedin", "hh"]
    assert held == []


class _FakeSearcher:
    def __init__(self, name):
        self.name, self.started = name, False

    def start(self):
        self.started = True

    def search(self, keywords, location, limit):
        return []

    def stop(self):
        pass


class _FakeCandidates:
    def known_urls(self):
        return set()

    def add_new(self, found):
        return 0


def _offline(monkeypatch):
    """Ни скоринга, ни живого Telegram: тест про паузу, а не про них."""
    monkeypatch.setattr(config, "RELEVANCE_ENABLED", False)
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")


def test_worker_request_searches_everything_but_the_paused_platform(monkeypatch):
    _offline(monkeypatch)
    searchers = {p: _FakeSearcher(p) for p in SEARCH_PLATFORMS}
    run_one = _make_run_one(searchers, _FakeCandidates(), parse_paused("linkedin"))

    run_one(SearchRequest(id="1", platform="all", status="running"))

    assert [p for p, s in searchers.items() if s.started] == [
        "wellfound", "remoteok", "remotive", "remocate", "hh"]


def test_pausing_remocate_stops_its_search_too(monkeypatch):
    """Выключатель обязан подхватить новую площадку сам, без правок в нём.

    Он и подхватывает — ровно потому, что поиск назвал площадку `remocate`, тем
    же словом, каким её зовут лиды в листе и канал отправки. Ошибись именем
    («remocate.app», «external») — и пауза прикрывала бы отправку, продолжая
    ходить на площадку поиском.
    """
    _offline(monkeypatch)
    searchers = {p: _FakeSearcher(p) for p in SEARCH_PLATFORMS}
    run_one = _make_run_one(searchers, _FakeCandidates(), parse_paused("remocate"))

    run_one(SearchRequest(id="1", platform="all", status="running"))

    assert not searchers["remocate"].started
    assert searchers["remoteok"].started


def test_worker_request_for_a_paused_platform_is_refused_out_loud(monkeypatch):
    _offline(monkeypatch)
    searchers = {p: _FakeSearcher(p) for p in SEARCH_PLATFORMS}
    said = []
    run_one = _make_run_one(searchers, _FakeCandidates(), parse_paused("linkedin"),
                            notify=said.append)

    with pytest.raises(SearchPaused):
        run_one(SearchRequest(id="7", platform="linkedin", status="running"))

    assert not any(s.started for s in searchers.values())
    # Команду прислали из таблицы, то есть человека у ноута нет. Без ответа в
    # Telegram он узнает об отказе только по красной строке, где причины нет.
    assert said and "linkedin" in said[0] and "PAUSED_PLATFORMS" in said[0]


class _FakeControl:
    def __init__(self, pending):
        self._pending, self.marked = pending, []

    def touch(self):
        pass

    def pending_requests(self):
        return self._pending

    def mark(self, request_id, status):
        self.marked.append((request_id, status))


def test_refused_request_is_never_marked_done(monkeypatch):
    # `done` в таблице значит «поиск прошёл и вот результат». Поиска не было —
    # и строка обязана это показывать, иначе отказ неотличим от выполненной
    # команды, по которой просто ничего не нашлось.
    _offline(monkeypatch)
    control = _FakeControl(
        [SearchRequest(id="7", platform="linkedin", status="pending")])
    run_one = _make_run_one({p: _FakeSearcher(p) for p in SEARCH_PLATFORMS},
                            _FakeCandidates(), parse_paused("linkedin"),
                            notify=lambda text: None)

    worker_tick(control, run_one)

    assert ("7", REQ_DONE) not in control.marked
    assert ("7", REQ_ERROR) in control.marked


def _no_outside_world(monkeypatch):
    """Разовый поиск по приостановленной площадке не должен успеть даже открыть
    таблицу — не то что браузер. Любая попытка здесь = провал теста."""
    import gspread
    from google.oauth2 import service_account

    def _boom(*args, **kwargs):
        raise AssertionError("поиск полез наружу, хотя площадка на паузе")

    monkeypatch.setattr(service_account.Credentials,
                        "from_service_account_file", _boom)
    monkeypatch.setattr(gspread, "authorize", _boom)


def test_search_once_for_a_paused_platform_opens_nothing(monkeypatch, capsys):
    _no_outside_world(monkeypatch)
    monkeypatch.setattr(config, "PAUSED_PLATFORMS", "linkedin")

    run_search_once(["linkedin"])

    assert "Ищу вакансии" not in capsys.readouterr().out


def test_search_once_says_what_is_paused_and_how_to_lift_it(monkeypatch, capsys):
    # `make search_linkedin` — человек попросил ИМЕННО эту площадку. Молчаливый
    # выход он прочтёт как «поискали, ничего не нашлось».
    _no_outside_world(monkeypatch)
    monkeypatch.setattr(config, "PAUSED_PLATFORMS", "linkedin")

    run_search_once(["linkedin"])

    out = capsys.readouterr().out
    assert "linkedin" in out and "паузе" in out
    assert "PAUSED_PLATFORMS" in out


class _FakeBook:
    def open_by_key(self, key):
        return self

    def worksheet(self, name):
        return None


def test_search_once_builds_searchers_only_for_live_platforms(monkeypatch, capsys):
    # Главное здесь — `built`: searcher приостановленной площадки не создаётся,
    # значит и браузеру с её сессией открыться не на чем.
    import gspread
    from google.oauth2 import service_account

    from app.infrastructure import search_leads_repo
    from app.infrastructure.search import registry

    _offline(monkeypatch)
    monkeypatch.setattr(config, "PAUSED_PLATFORMS", "linkedin")
    monkeypatch.setattr(service_account.Credentials, "from_service_account_file",
                        lambda *a, **k: object())
    monkeypatch.setattr(gspread, "authorize", lambda creds: _FakeBook())
    monkeypatch.setattr(search_leads_repo, "SearchLeadsRepo",
                        lambda *a, **k: _FakeCandidates())
    built = []
    monkeypatch.setattr(registry, "build_searcher",
                        lambda p: built.append(p) or _FakeSearcher(p))

    run_search_once(["linkedin", "remotive"])

    assert built == ["remotive"]
    assert "Ищу вакансии: remotive" in capsys.readouterr().out

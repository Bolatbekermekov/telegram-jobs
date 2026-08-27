"""Chrome с отладочным портом не поднят — и Wellfound молча даёт ноль.

Замер 2026-08-27: Wellfound не отдал ни одной вакансии за прогон, потому что
`make login_wellfound` в тот день не запускали, а его Chrome — единственный
способ попасть на площадку (Cloudflare заворачивает любой браузер, который мы
поднимаем сами; см. wellfound_search.WellfoundSearcher.start).

Узнать это было неоткуда. `start()` падает внутри run_search, тот отдаёт
исключение в on_error — и в консоли остаётся сырой текст patchright
«BrowserType.connect_over_cdp: connect ECONNREFUSED 127.0.0.1:9222», а в
Telegram-отчёте только «• wellfound: 0 с, ошибка». Оба текста говорят «что-то
сломалось», ни один не говорит «подними Chrome». Отклик ходит через тот же
порт (channels/registry.py), так что прогон отправки ломается ровно так же.

Поэтому порт проверяется ЗАРАНЕЕ — `cdp_alive` из app.application.login — и
зависимость называется вслух до того, как площадка потратит своё время.
"""
import pytest

from app import config
from app.application import notify as notify_mod
from app.interface import cli
from app.interface.cli import (
    _warn_if_wellfound_chrome_down, run_search_once,
)


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


class _FakeBook:
    def open_by_key(self, key):
        return self

    def worksheet(self, name):
        return None


def _dead_port(monkeypatch):
    """Порт никто не слушает. Живьём сюда ходит httpx — в тесте не должен."""
    monkeypatch.setattr(cli, "cdp_alive", lambda *a, **k: False)


def _live_port(monkeypatch):
    monkeypatch.setattr(cli, "cdp_alive", lambda *a, **k: True)


def test_warning_names_the_command_that_lifts_the_chrome(monkeypatch, capsys):
    _dead_port(monkeypatch)

    _warn_if_wellfound_chrome_down(["linkedin", "wellfound"])

    out = capsys.readouterr().out
    assert "wellfound" in out.lower()
    assert "make login_wellfound" in out


def test_silent_while_the_chrome_answers(monkeypatch, capsys):
    _live_port(monkeypatch)

    _warn_if_wellfound_chrome_down(["wellfound"])

    assert capsys.readouterr().out == ""


def test_silent_when_wellfound_is_not_in_this_run(monkeypatch, capsys):
    """`make search_hh` и площадка на паузе — предупреждение было бы шумом."""
    _dead_port(monkeypatch)

    _warn_if_wellfound_chrome_down(["hh", "remotive"])

    assert capsys.readouterr().out == ""


def test_a_dead_port_never_stops_the_other_platforms(monkeypatch, capsys):
    """Предупреждение — это предупреждение, а не отказ: hh и remotive к Chrome
    Wellfound отношения не имеют и обязаны отработать."""
    import gspread
    from google.oauth2 import service_account

    from app.infrastructure import search_leads_repo
    from app.infrastructure.search import registry

    _dead_port(monkeypatch)
    monkeypatch.setattr(config, "RELEVANCE_ENABLED", False)
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(config, "PAUSED_PLATFORMS", "")
    monkeypatch.setattr(service_account.Credentials, "from_service_account_file",
                        lambda *a, **k: object())
    monkeypatch.setattr(gspread, "authorize", lambda creds: _FakeBook())
    monkeypatch.setattr(search_leads_repo, "SearchLeadsRepo",
                        lambda *a, **k: _FakeCandidates())
    built = []
    monkeypatch.setattr(registry, "build_searcher",
                        lambda p: built.append(p) or _FakeSearcher(p))

    run_search_once(["wellfound", "remotive"])

    out = capsys.readouterr().out
    assert "make login_wellfound" in out
    assert built == ["wellfound", "remotive"]
    assert "Ищу вакансии: wellfound, remotive" in out


def test_search_warns_before_it_starts_scraping(monkeypatch, capsys):
    """Порядок и есть смысл правки: сказать надо ДО того, как поиск потратит
    минуты, а не после, разбором чужого ECONNREFUSED."""
    import gspread
    from google.oauth2 import service_account

    from app.infrastructure import search_leads_repo
    from app.infrastructure.search import registry

    _dead_port(monkeypatch)
    monkeypatch.setattr(config, "RELEVANCE_ENABLED", False)
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(config, "PAUSED_PLATFORMS", "")
    monkeypatch.setattr(service_account.Credentials, "from_service_account_file",
                        lambda *a, **k: object())
    monkeypatch.setattr(gspread, "authorize", lambda creds: _FakeBook())
    monkeypatch.setattr(search_leads_repo, "SearchLeadsRepo",
                        lambda *a, **k: _FakeCandidates())
    monkeypatch.setattr(registry, "build_searcher", _FakeSearcher)

    run_search_once(["wellfound"])

    out = capsys.readouterr().out
    assert out.index("make login_wellfound") < out.index("Ищу вакансии")


def test_paused_wellfound_is_not_warned_about(monkeypatch, capsys):
    """Пауза уже сказала своё: площадку не трогают, Chrome ей не нужен.
    Два предупреждения об одном и том же противоречили бы друг другу."""
    import gspread
    from google.oauth2 import service_account

    from app.infrastructure import search_leads_repo
    from app.infrastructure.search import registry

    _dead_port(monkeypatch)
    monkeypatch.setattr(config, "RELEVANCE_ENABLED", False)
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(config, "PAUSED_PLATFORMS", "wellfound")
    monkeypatch.setattr(service_account.Credentials, "from_service_account_file",
                        lambda *a, **k: object())
    monkeypatch.setattr(gspread, "authorize", lambda creds: _FakeBook())
    monkeypatch.setattr(search_leads_repo, "SearchLeadsRepo",
                        lambda *a, **k: _FakeCandidates())
    monkeypatch.setattr(registry, "build_searcher", _FakeSearcher)

    run_search_once(["wellfound", "remotive"])

    out = capsys.readouterr().out
    assert "make login_wellfound" not in out
    assert "паузе" in out


def test_the_send_run_warns_on_its_own_queue(monkeypatch, capsys):
    """Отклик Wellfound ходит через ТОТ ЖЕ порт (channels/registry.py), и
    мёртвый Chrome ломает его так же, как поиск: лид уходит в `failed` с чужим
    ECONNREFUSED в «Заметке». Прогон смотрит на СВОЮ очередь, а не на список
    площадок вообще — предупреждение на каждый `make run` без единого лида
    Wellfound было бы шумом, а шум перестают читать."""
    _dead_port(monkeypatch)

    cli._warn_if_wellfound_chrome_down({"linkedin", "wellfound"})

    assert "make login_wellfound" in capsys.readouterr().out


def test_the_send_run_stays_quiet_without_wellfound_leads(monkeypatch, capsys):
    _dead_port(monkeypatch)

    cli._warn_if_wellfound_chrome_down({"linkedin", "telegram"})

    assert capsys.readouterr().out == ""


def test_message_lives_in_notify_so_both_console_and_telegram_use_one_text():
    assert hasattr(notify_mod, "wellfound_offline_message")


# --- воркер: консоли у него нет ----------------------------------------------
#
# Воркер живёт неделями и ищет трижды в день, а человек в это время не у ноута.
# Предупреждения при старте процесса ему хватит ровно до того дня, когда Chrome
# закроется сам — дальше единственным следом останется «• wellfound: 0 с,
# ошибка» в Telegram, то есть та же немая строка, ради которой всё и делалось.

def test_worker_search_tells_telegram_about_the_dead_chrome(monkeypatch):
    from app.domain.search_request import SEARCH_PLATFORMS, SearchRequest

    _dead_port(monkeypatch)
    monkeypatch.setattr(config, "RELEVANCE_ENABLED", False)
    said = []
    run_one = cli._make_run_one({p: _FakeSearcher(p) for p in SEARCH_PLATFORMS},
                                _FakeCandidates(), notify=said.append)

    run_one(SearchRequest(id="1", platform="all", status="running"))

    assert any("make login_wellfound" in text for text in said)


def test_worker_search_stays_quiet_when_the_chrome_answers(monkeypatch):
    from app.domain.search_request import SEARCH_PLATFORMS, SearchRequest

    _live_port(monkeypatch)
    monkeypatch.setattr(config, "RELEVANCE_ENABLED", False)
    said = []
    run_one = cli._make_run_one({p: _FakeSearcher(p) for p in SEARCH_PLATFORMS},
                                _FakeCandidates(), notify=said.append)

    run_one(SearchRequest(id="1", platform="all", status="running"))

    assert not any("make login_wellfound" in text for text in said)


def test_worker_search_of_another_platform_says_nothing(monkeypatch):
    """`/start_search hh` — Wellfound в этом запросе не участвует."""
    from app.domain.search_request import SearchRequest

    _dead_port(monkeypatch)
    monkeypatch.setattr(config, "RELEVANCE_ENABLED", False)
    said = []
    run_one = cli._make_run_one({"hh": _FakeSearcher("hh")}, _FakeCandidates(),
                                notify=said.append)

    run_one(SearchRequest(id="1", platform="hh", status="running"))

    assert not any("make login_wellfound" in text for text in said)


@pytest.mark.parametrize("platforms", [[], ["remoteok"]])
def test_no_wellfound_no_probe(monkeypatch, platforms):
    """Порт не дёргается вовсе, когда площадки нет в списке: httpx с таймаутом
    2 с на каждый `make search_hh` — плата ни за что."""
    probed = []
    monkeypatch.setattr(cli, "cdp_alive",
                        lambda *a, **k: probed.append(a) or False)

    _warn_if_wellfound_chrome_down(platforms)

    assert probed == []

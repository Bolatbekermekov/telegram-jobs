"""Статья teletype.in: вакансия и контакт живут ВНУТРИ неё, а не в сообщении.

Замер 2026-09-13 по 19 живым статьям сети каналов Inflow (@Remoteit, @relocats):
страница отдаётся обычным HTTP за 0,3–0,45 с, текст целиком в `<article>`, а в
посте канала ссылка на статью всегда видна текстом (34 из 34). Контакт внутри:
t.me-ссылка — 9 статей; кнопка «APPLY» со спрятанной ссылкой — 10, из них на
ATS (Ashby, Lever) 5, на hirify.me и career.habr.com (обе требуют входа) 4, на
сайт компании 1; Google-форма — 1.

Сообщение из канала контакта не несёт вовсе: «Backend Developer (NODE.JS) |
REMOTE | … https://teletype.in/@remoteit/wezaa_ODi05». Интейк искал контакт
только в сообщении, отвечал «Не нашёл контакт» и статью не открывал никогда.

Решение владельца 2026-09-13 про «APPLY», ведущий не в Telegram, почту, hh или
ATS: такой лид не сохранять, а объяснить в ответе, куда ведёт ссылка.

Фикстуры повторяют живую вёрстку teletype — article с itemprop, пустые якоря
`<a name>`, Vue-комментарии `<!--[-->`, `&amp;` в адресе, — но ники, адреса и
компании в них вымышленные: репозиторий публичный.
"""
import asyncio
from pathlib import Path

import pytest

import api.webhook as wh
import app.infrastructure.vacancy_fetcher as vf
from app.application.extract_lead import ArticleWithoutContact, ExtractLeadFromText
from app.domain.contact import Contact, detect_contact
from app.domain.post_contact import pick_article_contact
from app.domain.vacancy_text import (
    extract_teletype_post, is_fetchable_vacancy_url, is_teletype_post_url, pick_vacancy_url,
)

_FX = Path(__file__).parent / "fixtures" / "teletype"
TME_HTML = (_FX / "contact_tme.html").read_text(encoding="utf-8")
ATS_HTML = (_FX / "apply_ats.html").read_text(encoding="utf-8")
OTHER_HTML = (_FX / "apply_other.html").read_text(encoding="utf-8")

ARTICLE = "https://teletype.in/@remoteit/wezaa_ODi05"
MESSAGE = ("Backend Developer (NODE.JS) | REMOTE | GAMEDEV GTA LIKE #remote #fulltime "
           f"#itjob #backend #nodejs #gamedev {ARTICLE}")
ASHBY = ("https://jobs.ashbyhq.com/example-co/fb5ebb6e-c624-44d1-8db9-757fedb006b4"
         "?utm_source=inflow&workplaceType=Remote")


# --- ссылка на статью -------------------------------------------------------------

def test_an_article_link_is_a_teletype_post():
    assert is_teletype_post_url(ARTICLE)
    assert is_teletype_post_url("https://teletype.in/@relocats/GC_vV-nBALg")


def test_the_author_page_and_lookalike_hosts_are_not_posts():
    assert not is_teletype_post_url("https://teletype.in/@remoteit")
    assert not is_teletype_post_url("https://teletype.in.example.com/@remoteit/wezaa_ODi05")
    assert not is_teletype_post_url("https://t.me/remoteit/123")


def test_an_article_is_a_page_the_vacancy_can_be_read_from():
    assert is_fetchable_vacancy_url(ARTICLE)
    assert pick_vacancy_url(MESSAGE) == ARTICLE


def test_a_link_typed_without_the_scheme_is_still_found():
    assert pick_vacancy_url("вот: teletype.in/@remoteit/wezaa_ODi05") == ARTICLE


# --- текст статьи -----------------------------------------------------------------

def test_the_article_text_is_read_without_markup():
    text = extract_teletype_post(TME_HTML)
    assert "Backend Developer — Node.js" in text
    assert "<" not in text and "[--" not in text


def test_the_article_is_read_line_by_line_not_as_one_blob():
    """Строки разделяют пункты списка; одной строкой сводка теряет структуру."""
    lines = extract_teletype_post(TME_HTML).splitlines()
    assert "Backend Developer — Node.js" in lines
    assert "— Перевод новых модулей на TypeScript" in lines


def test_a_visible_link_appears_once():
    assert extract_teletype_post(TME_HTML).count("https://t.me/hr_example") == 1


def test_a_link_hidden_behind_a_word_becomes_visible():
    """«APPLY» — всё, что видит читатель; адрес живёт только в href."""
    assert f"APPLY: {ASHBY}" in extract_teletype_post(ATS_HTML)


def test_only_the_article_is_read_not_the_page_around_it():
    """Ссылки автора и подвала — не контакт работодателя."""
    text = extract_teletype_post(TME_HTML)
    assert "teletype.in/@remoteit" not in text
    assert "t.me/teletype" not in text


def test_a_page_without_an_article_yields_nothing():
    """Удалённая статья отвечает 404 со страницей-заглушкой (замер: пять из 24)."""
    assert extract_teletype_post("<html><body>Страница не найдена</body></html>") == ""
    assert extract_teletype_post("") == ""


def test_the_fetcher_reads_an_article_with_the_teletype_extractor(monkeypatch):
    monkeypatch.setattr(vf, "_get", lambda url, timeout, ua=None: TME_HTML)
    assert "Backend Developer — Node.js" in vf.fetch_vacancy_text(ARTICLE)


# --- контакт в статье -------------------------------------------------------------

def _plain(text):
    return detect_contact(text)


def test_a_telegram_link_in_the_article_is_the_contact():
    contact, _ = pick_article_contact(extract_teletype_post(TME_HTML), _plain)
    assert contact.platform == "telegram" and "hr_example" in contact.target


def test_an_ats_link_behind_apply_is_the_contact():
    contact, _ = pick_article_contact(extract_teletype_post(ATS_HTML), _plain)
    assert contact.platform == "ats"
    assert contact.target.startswith("https://jobs.ashbyhq.com/example-co/")


def test_an_email_in_the_article_is_a_contact():
    contact, _ = pick_article_contact("Резюме присылайте на hr@example.com", _plain)
    assert contact == Contact("email", "hr@example.com")


def test_a_person_in_telegram_beats_a_form():
    contact, _ = pick_article_contact(f"Вопросы: https://t.me/hr_example\nAPPLY: {ASHBY}", _plain)
    assert contact.platform == "telegram"


def test_a_linkedin_link_does_not_hide_the_ats_link():
    """В детекторе LinkedIn стоит РАНЬШЕ ATS: для сообщения это верно, а в статье
    ссылка на страницу компании в LinkedIn — не адрес отклика и не вправе
    перекрыть «APPLY»."""
    text = f"Компания: https://www.linkedin.com/company/example-co/\nAPPLY: {ASHBY}"
    contact, _ = pick_article_contact(text, _plain)
    assert contact.platform == "ats"


def test_a_channel_link_rejected_by_the_oracle_is_not_the_contact():
    def detect(text):
        return detect_contact(text, telegram_writable=lambda t: "remoteit" not in t.lower())
    contact, _ = pick_article_contact(f"Наш канал: https://t.me/Remoteit\nAPPLY: {ASHBY}", detect)
    assert contact.platform == "ats"


def test_an_apply_link_to_a_site_we_do_not_serve_is_named_not_taken():
    contact, hosts = pick_article_contact(extract_teletype_post(OTHER_HTML), _plain)
    assert contact is None
    assert hosts == ["hirify.me"]


# --- сценарий интейка ---------------------------------------------------------------

class _Summ:
    def summarize(self, text):
        return "Backend Developer — Node.js, удалённо"


class _Repo:
    def __init__(self):
        self.saved = []

    def append_lead(self, lead):
        self.saved.append(lead)
        return 1


def _use_case(pages, repo, summarizer=None):
    fetched = []

    def fetch(url):
        fetched.append(url)
        return pages.get(url, "")

    return ExtractLeadFromText(_plain, summarizer or _Summ(), repo, fetcher=fetch), fetched


def test_a_message_with_only_an_article_link_takes_the_contact_from_the_article():
    repo = _Repo()
    uc, fetched = _use_case({ARTICLE: extract_teletype_post(TME_HTML)}, repo)
    lead = uc.execute(MESSAGE)
    assert fetched == [ARTICLE]
    assert lead.platform == "telegram" and "hr_example" in lead.target
    assert "статьи teletype" in lead.note and ARTICLE in lead.note
    assert repo.saved == [lead]


def test_an_ats_link_behind_apply_becomes_an_ats_lead():
    uc, _ = _use_case({ARTICLE: extract_teletype_post(ATS_HTML)}, _Repo())
    lead = uc.execute(MESSAGE)
    assert lead.platform == "ats"
    assert lead.target.startswith("https://jobs.ashbyhq.com/example-co/")


def test_the_vacancy_is_summarised_from_the_article_not_the_headline():
    class _Recording:
        seen = ""

        def summarize(self, text):
            _Recording.seen = text
            return "x"

    uc, _ = _use_case({ARTICLE: extract_teletype_post(TME_HTML)}, _Repo(), _Recording())
    uc.execute(MESSAGE)
    assert "Перевод новых модулей на TypeScript" in _Recording.seen


def test_an_apply_link_elsewhere_is_not_saved_and_says_where_it_leads():
    """Решение владельца 2026-09-13: не сохранять, а объяснить."""
    repo = _Repo()
    uc, _ = _use_case({ARTICLE: extract_teletype_post(OTHER_HTML)}, repo)
    with pytest.raises(ArticleWithoutContact) as err:
        uc.execute(MESSAGE)
    assert (err.value.url, err.value.hosts, err.value.read) == (ARTICLE, ["hirify.me"], True)
    assert repo.saved == []


def test_an_article_that_could_not_be_read_is_said_to_be_unread():
    repo = _Repo()
    uc, _ = _use_case({}, repo)
    with pytest.raises(ArticleWithoutContact) as err:
        uc.execute(MESSAGE)
    assert err.value.read is False
    assert repo.saved == []


def test_it_is_still_the_no_contact_error_for_every_older_caller():
    """Вебхук ловит ValueError целиком: подкласс не вправе сломать общий путь."""
    uc, _ = _use_case({}, _Repo())
    with pytest.raises(ValueError, match="no_contact"):
        uc.execute(MESSAGE)


def test_a_contact_named_in_the_message_still_wins_and_the_article_is_read():
    uc, fetched = _use_case({ARTICLE: extract_teletype_post(ATS_HTML)}, _Repo())
    lead = uc.execute(f"Пиши @ivan_hr {ARTICLE}")
    assert (lead.platform, lead.target) == ("telegram", "@ivan_hr")
    assert fetched == [ARTICLE]


# --- ответ бота ----------------------------------------------------------------------

class _FakeRequest:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


def _reply_to_failure(monkeypatch, exc):
    monkeypatch.setattr(wh.config, "TELEGRAM_WEBHOOK_SECRET", "", raising=False)
    replies = []
    monkeypatch.setattr(wh, "_reply", lambda chat_id, text: replies.append(text))

    def _raise(_self, _text):
        raise exc

    monkeypatch.setattr(wh, "_build_use_case", lambda: type("_UC", (), {"execute": _raise})())
    update = {"message": {"chat": {"id": 5}, "text": MESSAGE}}
    asyncio.run(wh.telegram_webhook(_FakeRequest(update), ""))
    return replies


def test_the_bot_names_where_the_apply_link_leads(monkeypatch):
    replies = _reply_to_failure(monkeypatch, ArticleWithoutContact(ARTICLE, ["hirify.me"], read=True))
    assert replies and "hirify.me" in replies[0] and "не сохраняю" in replies[0]


def test_the_bot_asks_for_the_text_when_the_article_did_not_open(monkeypatch):
    replies = _reply_to_failure(monkeypatch, ArticleWithoutContact(ARTICLE, [], read=False))
    assert replies and "Не смог прочитать статью" in replies[0] and ARTICLE in replies[0]


def test_an_article_without_any_link_says_so(monkeypatch):
    replies = _reply_to_failure(monkeypatch, ArticleWithoutContact(ARTICLE, [], read=True))
    assert replies and "не нашёл контакт" in replies[0].lower()

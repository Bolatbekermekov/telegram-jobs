import pytest

from app.application.extract_lead import ExtractLeadFromText
from app.domain.contact import Contact


class _FakeSummarizer:
    def __init__(self, text): self._text = text
    def summarize(self, raw): return self._text


class _FakeRepo:
    def __init__(self): self.saved = []
    def append_lead(self, lead): self.saved.append(lead); return 1


def _detector(result):
    return lambda text: result


def test_saves_lead_with_detected_platform_and_target():
    repo = _FakeRepo()
    uc = ExtractLeadFromText(_detector(Contact("linkedin", "linkedin.com/in/x")),
                             _FakeSummarizer("Backend role"), repo)
    lead = uc.execute("some vacancy text linkedin.com/in/x")
    assert lead.platform == "linkedin"
    assert lead.target == "linkedin.com/in/x"
    assert lead.vacancy_context == "Backend role"
    assert repo.saved == [lead]


def test_raises_when_no_contact():
    repo = _FakeRepo()
    uc = ExtractLeadFromText(_detector(None), _FakeSummarizer("x"), repo)
    with pytest.raises(ValueError, match="no_contact"):
        uc.execute("no contact here")
    assert repo.saved == []


def test_falls_back_to_raw_text_when_summary_empty():
    repo = _FakeRepo()
    raw = "Длинный текст вакансии " * 20
    uc = ExtractLeadFromText(_detector(Contact("email", "a@b.com")),
                             _FakeSummarizer(""), repo)
    lead = uc.execute(raw)
    assert lead.vacancy_context == raw.strip()[:280]
    assert len(lead.vacancy_context) <= 280


# --- link-only messages fetch the vacancy -----------------------------------

from app.domain.contact import detect_contact      # noqa: E402


class _RecordingSummarizer:
    """Remembers what it was asked to summarise — that's the thing under test."""

    def __init__(self, text=""):
        self._text = text
        self.seen = None

    def summarize(self, raw):
        self.seen = raw
        return self._text


class _Fetcher:
    def __init__(self, text=""):
        self.text = text
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        return self.text


def test_link_only_message_summarises_the_fetched_vacancy():
    """Without this the summariser sees two URLs, answers that it can't open them,
    and that refusal becomes the «Вакансия» column and the cover letter."""
    raw = ("Vacancy: https://hh.kz/vacancy/135171273?from=share_ios\n\n"
           "Sent via hh mobile app https://hh.ru/mobile?from=share_ios")
    summarizer = _RecordingSummarizer("Специалист по внедрению ИИ, дата-центр")
    fetcher = _Fetcher("Специалист по внедрению ИИ. Мы — Tier IV дата-центр…")

    lead = ExtractLeadFromText(detect_contact, summarizer, _FakeRepo(),
                               fetcher).execute(raw)

    assert fetcher.calls == ["https://hh.ru/vacancy/135171273"]
    assert summarizer.seen == "Специалист по внедрению ИИ. Мы — Tier IV дата-центр…"
    assert lead.vacancy_context.startswith("Специалист по внедрению ИИ")
    assert lead.raw_text == raw          # the original message is still kept


def test_a_pasted_description_is_not_refetched():
    """No network call when the message already carries the vacancy."""
    raw = ("Ищем Middle QA Engineer в финтех. Обязанности: функциональное и "
           "регрессионное тестирование, тест-кейсы, баг-трекинг. Требования: опыт "
           "от 2 лет, REST API. Подробнее: https://hh.ru/vacancy/1")
    fetcher = _Fetcher("НЕ ДОЛЖНО ИСПОЛЬЗОВАТЬСЯ")
    summarizer = _RecordingSummarizer("ok")

    ExtractLeadFromText(detect_contact, summarizer, _FakeRepo(), fetcher).execute(raw)

    assert fetcher.calls == []
    assert summarizer.seen == raw


def test_a_failed_fetch_saves_the_lead_with_no_vacancy_text():
    """hh may throttle the datacenter IP — the lead must still be saved.

    But saved EMPTY. There is nothing to summarise but the URL itself, and what
    came back from summarising a bare URL was the model's refusal ("Не удалось
    извлечь содержание вакансии... Пришлите текст объявления"), which then became
    the brief the cover letter was written from — rows 121 and 141 in the live
    sheet. The sender reads the link again before it generates anything.
    """
    raw = "Vacancy: https://hh.ru/vacancy/135171273?from=share_ios"
    repo = _FakeRepo()
    summarizer = _RecordingSummarizer("Не удалось извлечь содержание вакансии")
    lead = ExtractLeadFromText(detect_contact, summarizer, repo,
                               _Fetcher("")).execute(raw)

    assert lead.platform == "hh"
    assert lead.target == "https://hh.ru/vacancy/135171273"
    assert lead.vacancy_context == ""
    assert repo.saved == [lead]                  # saved, not dropped
    assert summarizer.seen is None               # never handed the bare URL


def test_the_use_case_still_works_without_a_fetcher():
    lead = ExtractLeadFromText(detect_contact, _RecordingSummarizer("s"),
                               _FakeRepo()).execute("Vacancy: https://hh.ru/vacancy/1")
    assert lead.vacancy_context == "s"

def test_linkedin_job_link_is_fetched_too():
    raw = "https://www.linkedin.com/jobs/view/4439324251/"
    summarizer = _RecordingSummarizer("Chatbot Developer в Mindrift")
    fetcher = _Fetcher("Chatbot Developer (WhatsApp, Telegram)\nКомпания: Mindrift\n…")

    ExtractLeadFromText(detect_contact, summarizer, _FakeRepo(), fetcher).execute(raw)

    assert fetcher.calls == ["https://www.linkedin.com/jobs/view/4439324251/"]
    assert summarizer.seen.startswith("Chatbot Developer")


# --- a LinkedIn post is read, and it can re-point the lead -------------------

POST = "https://www.linkedin.com/posts/daria-hr_python-activity-7300000000-AbCd"
AUTHOR = "https://www.linkedin.com/in/daria-hr/"


def test_a_post_link_inside_a_chatty_message_is_still_read():
    """`is_link_only` is False here — the prose outlives the urls — so the old flow
    summarised «посмотри, вроде под тебя» into «Вакансия» and never opened the post.
    A post is not an hh page: its body is the only place where both the description
    and the address to apply to exist, so it is read whatever the message says."""
    raw = ("Привет! Тут в LinkedIn выложили вакансию, вроде как раз под тебя, "
           "посмотри и откликнись если норм: " + POST)
    fetcher = _Fetcher("Ищем Junior Python Developer, удалёнка, 2000-3000 USD.")

    ExtractLeadFromText(detect_contact, _RecordingSummarizer("ok"), _FakeRepo(),
                        fetcher).execute(raw)

    assert fetcher.calls == [POST]


def test_the_summary_sees_the_post_and_the_message_together():
    """What the forwarder wrote is not noise — a salary they happen to know, a
    «готовы на релокацию» the post never says — and replacing it with the post
    loses it."""
    raw = ("Смотри, вот эта вакансия точно под тебя, и они вроде готовы на "
           "релокацию: " + POST)
    summarizer = _RecordingSummarizer("ok")

    ExtractLeadFromText(detect_contact, summarizer, _FakeRepo(),
                        _Fetcher("Ищем Junior Python Developer, удалёнка.")).execute(raw)

    assert "Junior Python Developer" in summarizer.seen
    assert "готовы на релокацию" in summarizer.seen


def test_a_telegram_handle_in_the_post_re_points_the_lead():
    lead = ExtractLeadFromText(
        detect_contact, _RecordingSummarizer("Junior Python Developer"), _FakeRepo(),
        _Fetcher("Ищем Junior Python Developer. Резюме в телеграм @daria_hr"),
    ).execute("Вот вакансия: " + POST)

    assert (lead.platform, lead.target) == ("telegram", "@daria_hr")
    assert lead.note == f"контакт из LinkedIn-поста: {POST}"


def test_an_email_in_the_post_re_points_the_lead():
    lead = ExtractLeadFromText(
        detect_contact, _RecordingSummarizer("s"), _FakeRepo(),
        _Fetcher("Ищем QA Engineer. CV на hr@acme.io"),
    ).execute("Вот вакансия: " + POST)

    assert (lead.platform, lead.target) == ("email", "hr@acme.io")


def test_a_handle_in_the_message_beats_one_in_the_post():
    """Whoever forwarded the message chose that address deliberately. The post is
    consulted only when the message names nobody we can write to directly."""
    lead = ExtractLeadFromText(
        detect_contact, _RecordingSummarizer("s"), _FakeRepo(),
        _Fetcher("Ищем Python-разработчика. Резюме в телеграм @daria_hr"),
    ).execute("Вот вакансия: " + POST + " пиши @ivan_hr")

    assert (lead.platform, lead.target) == ("telegram", "@ivan_hr")
    assert lead.note == ""


def test_a_post_naming_nobody_goes_to_its_author():
    lead = ExtractLeadFromText(
        detect_contact, _RecordingSummarizer("s"), _FakeRepo(),
        _Fetcher("Ищем Go-разработчика в Алматы, гибрид. Откликайтесь!"),
    ).execute("Вот вакансия: " + POST)

    assert (lead.platform, lead.target) == ("linkedin", AUTHOR)
    assert lead.note == f"автор LinkedIn-поста: {POST}"


def test_a_company_share_with_no_author_in_the_url_keeps_the_post_link():
    """`/feed/update/…` carries no author id in its slug. Keeping the post url is
    what lets the sender say it cannot find an author, instead of writing to ""."""
    url = "https://www.linkedin.com/feed/update/urn:li:activity:7300000000/"
    lead = ExtractLeadFromText(
        detect_contact, _RecordingSummarizer("s"), _FakeRepo(),
        _Fetcher("Ищем Go-разработчика, гибрид."),
    ).execute("Вот вакансия: " + url)

    assert (lead.platform, lead.target) == ("linkedin", url)


def test_a_post_that_could_not_be_read_keeps_the_link_for_the_laptop():
    """A throttled read must not cost the lead its only re-readable url. An author
    profile is not a page the vacancy can be re-read from, and
    `needs_vacancy_refetch` + `is_fetchable_vacancy_url(target)` on the laptop is
    what fills «Вакансия» on the second, unhurried attempt."""
    lead = ExtractLeadFromText(detect_contact, _RecordingSummarizer("s"),
                               _FakeRepo(), _Fetcher("")).execute("Вот вакансия: " + POST)

    assert (lead.platform, lead.target) == ("linkedin", POST)
    assert lead.vacancy_context == ""
    assert lead.note == ""


def test_a_telegram_link_behind_the_rewrite_re_points_the_lead():
    """End to end: LinkedIn serves the post's `t.me` link rewritten as `lnkd.in`,
    and the injected resolver is the only reason it becomes a contact."""
    lead = ExtractLeadFromText(
        detect_contact, _RecordingSummarizer("s"), _FakeRepo(),
        _Fetcher("Ищем Python-разработчика. Писать: https://lnkd.in/abc123"),
        resolve_link=lambda _u: "https://t.me/daria_hr",
    ).execute("Вот вакансия: " + POST)

    assert (lead.platform, lead.target) == ("telegram", "https://t.me/daria_hr")

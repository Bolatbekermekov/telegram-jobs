"""Deciding a message has no vacancy text, and pulling one out of hh HTML."""
from app.domain.vacancy_text import extract_hh_vacancy, is_link_only

IOS_SHARE = ("Vacancy: https://hh.kz/vacancy/135171273?from=share_ios\n\n"
             "Sent via hh mobile app https://hh.ru/mobile?from=share_ios")


# --- is_link_only -----------------------------------------------------------

def test_ios_share_counts_as_link_only():
    """The exact shape the phone sends — nothing here to summarise."""
    assert is_link_only(IOS_SHARE)


def test_a_bare_url_counts_as_link_only():
    assert is_link_only("https://hh.ru/vacancy/135171273")


def test_a_pasted_description_does_not():
    text = ("Ищем Middle QA Engineer в финтех. Обязанности: функциональное и "
            "регрессионное тестирование, написание тест-кейсов, работа с баг-трекингом. "
            "Требования: опыт от 2 лет, REST API, знание методологий тестирования.")
    assert not is_link_only(text)


def test_a_description_with_a_link_does_not():
    text = ("Senior frontend в IREV, удалёнка. React и TypeScript, желательно "
            "ClojureScript. Английский для международной команды. Оформление по "
            "контракту, зарплата в долларах. Подробности: https://hh.ru/vacancy/1")
    assert not is_link_only(text)


def test_empty_text_counts_as_link_only():
    assert is_link_only("")


# --- extract_hh_vacancy -----------------------------------------------------

_HTML = """
<html><body>
<h1 data-qa="vacancy-title">Специалист по внедрению ИИ</h1>
<span data-qa="vacancy-salary-compensation-type-net">от 500 000 ₸ на руки</span>
<div data-qa="vacancy-description"><p>Мы — Tier IV дата-центр.</p>
<script>window.x = 1;</script>
<ul><li>Автоматизируем процессы с помощью AI</li></ul></div>
<div data-qa="vacancy-view-employment-mode">полный день</div>
</body></html>
"""


def test_title_salary_and_body_are_extracted():
    out = extract_hh_vacancy(_HTML)
    assert "Специалист по внедрению ИИ" in out
    assert "500 000" in out
    assert "Tier IV дата-центр" in out
    assert "Автоматизируем процессы" in out


def test_markup_and_scripts_are_stripped():
    out = extract_hh_vacancy(_HTML)
    assert "<" not in out and ">" not in out
    assert "window.x" not in out


def test_the_next_block_is_not_swallowed():
    """The description regex stops at the following data-qa block."""
    assert "полный день" not in extract_hh_vacancy(_HTML)


def test_html_without_a_description_yields_nothing():
    assert extract_hh_vacancy("<html><body>404</body></html>") == ""


def test_empty_html_yields_nothing():
    assert extract_hh_vacancy("") == ""


def test_output_is_capped():
    html = ('<div data-qa="vacancy-description">' + ("текст " * 5000)
            + '</div><div data-qa="next">')
    assert len(extract_hh_vacancy(html, max_chars=500)) <= 700   # body cap + title line


def test_html_entities_are_decoded():
    """hh writes "Support &amp; QA"; the raw entity would reach the summary prompt."""
    html = ('<h1 data-qa="vacancy-title">Support &amp; QA</h1>'
            '<div data-qa="vacancy-description">Опыт &gt; 2 лет, зарплата &lt; рынка,'
            ' &quot;гибкий&quot; график</div><div data-qa="next">')
    out = extract_hh_vacancy(html)
    assert "Support & QA" in out
    assert "Опыт > 2 лет" in out
    assert "&amp;" not in out and "&gt;" not in out


# --- LinkedIn job pages -----------------------------------------------------

_LI_HTML = """
<html><body>
<h1 class="top-card-layout__title">Chatbot Developer (WhatsApp, Telegram)</h1>
<a class="topcard__org-name-link" href="#">Mindrift</a>
<div class="show-more-less-html__markup"><p>Mindrift is looking for skilled Bot
Developers to build conversational bots.</p><script>var a=1;</script></div>
</body></html>
"""


def test_linkedin_title_company_and_body_are_extracted():
    from app.domain.vacancy_text import extract_linkedin_vacancy

    out = extract_linkedin_vacancy(_LI_HTML)
    assert "Chatbot Developer" in out
    assert "Mindrift" in out
    assert "conversational bots" in out
    assert "var a=1" not in out and "<" not in out


def test_linkedin_html_without_a_description_yields_nothing():
    from app.domain.vacancy_text import extract_linkedin_vacancy

    assert extract_linkedin_vacancy("<html><body>authwall</body></html>") == ""


def test_a_short_but_real_posting_is_not_link_only():
    """91 chars of real text — the old 120 threshold called this a bare link."""
    assert not is_link_only(
        "Sarvottam Solutions is hiring Junior AI Engineer\n\nFor 2024, 2025 grads\n"
        "Location: Ahemdabad\n\nhttps://www.linkedin.com/jobs/view/4438796193/")


# --- LinkedIn posts (hiring posts, read from og:description) -----------------

def test_linkedin_post_text_from_og_description():
    """A hiring post's text lives in the og:description meta (verified live on
    real leads: /jobs/ selectors don't exist on a /posts/ page)."""
    from app.domain.vacancy_text import extract_linkedin_post

    html = ('<meta property="og:description" content="QA Engineer (ML/Voice AI) '
            '&#8211; Cybernet AI. Алматы (гибрид). Ищем QA, опыт с REST API и '
            'автотестами. Зарплата обсуждается." />')
    out = extract_linkedin_post(html)
    assert "QA Engineer" in out
    assert "Cybernet AI" in out
    assert "REST API" in out
    assert "&#8211;" not in out and "–" in out   # entity decoded


def test_linkedin_post_rejects_the_generic_members_blurb():
    """When a post isn't publicly readable, LinkedIn serves its generic site
    blurb as og:description — that is NOT the vacancy, so drop it (row #110)."""
    from app.domain.vacancy_text import extract_linkedin_post

    html = ('<meta property="og:description" content="500 million+ members | '
            'Manage your professional identity. Build and engage with your '
            'professional network." />')
    assert extract_linkedin_post(html) == ""


def test_linkedin_post_without_og_description_yields_nothing():
    from app.domain.vacancy_text import extract_linkedin_post

    assert extract_linkedin_post("<html><body>authwall</body></html>") == ""
    assert extract_linkedin_post("") == ""


# --- fetch retry ------------------------------------------------------------

class _FakeResp:
    def __init__(self, status, text=""):
        self.status_code = status
        self.text = text


def _patched_httpx(monkeypatch, responses):
    """Feed _get a queue of responses (or exceptions) and count the calls."""
    import types
    calls = []
    queue = list(responses)

    def _get(url, **kw):
        calls.append(url)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(get=_get))
    return calls


import sys  # noqa: E402

from app.infrastructure import vacancy_fetcher as vf  # noqa: E402


def test_linkedin_post_urls_are_fetchable():
    """A bare hiring-post link should now be fetched, not treated as unreadable."""
    post = ("https://www.linkedin.com/posts/assemzhan-nagashybayeva-3bb2a91a7_"
            "qa-engineer-activity-7482667084305424384-5wMi/")
    assert vf.is_linkedin_post_url(post)
    assert vf.is_fetchable_vacancy_url(post)
    assert vf.is_linkedin_post_url("https://www.linkedin.com/feed/update/urn:li:activity:123/")


def test_a_linkedin_profile_is_not_a_fetchable_post():
    """A /in/ profile isn't a post — profiles answer 999 and carry no vacancy."""
    assert not vf.is_linkedin_post_url("https://www.linkedin.com/in/daria-yakovleva/")
    assert not vf.is_fetchable_vacancy_url("https://www.linkedin.com/in/daria-yakovleva/")


def test_fetch_routes_a_post_to_the_og_description_extractor(monkeypatch):
    """A post URL is read via extract_linkedin_post (og:description), not the
    job-page selectors."""
    html = '<meta property="og:description" content="Ищем Go-разработчика, удалёнка." />'
    _patched_httpx(monkeypatch, [_FakeResp(200, html)])
    out = vf.fetch_vacancy_text(
        "https://www.linkedin.com/posts/x_hiring-activity-1-a/", timeout=8.0)
    assert "Go-разработчика" in out


def test_throttled_first_attempt_is_retried(monkeypatch):
    """A burst of backfill requests gets throttled; the page is fine a moment later."""
    calls = _patched_httpx(monkeypatch, [_FakeResp(429), _FakeResp(200, "<ok>")])
    assert vf._get("https://hh.ru/vacancy/1", 8.0, sleep=lambda _s: None) == "<ok>"
    assert len(calls) == 2


def test_a_network_error_is_retried(monkeypatch):
    calls = _patched_httpx(monkeypatch, [OSError("reset"), _FakeResp(200, "<ok>")])
    assert vf._get("https://hh.ru/vacancy/1", 8.0, sleep=lambda _s: None) == "<ok>"
    assert len(calls) == 2


def test_a_restricted_page_is_not_retried(monkeypatch):
    """403 is the site's final answer — retrying only waits longer for nothing."""
    calls = _patched_httpx(monkeypatch, [_FakeResp(403)])
    assert vf._get("https://hh.ru/vacancy/1", 8.0, sleep=lambda _s: None) == ""
    assert len(calls) == 1


def test_a_removed_page_is_not_retried(monkeypatch):
    calls = _patched_httpx(monkeypatch, [_FakeResp(404)])
    assert vf._get("https://linkedin.com/jobs/view/1", 8.0, sleep=lambda _s: None) == ""
    assert len(calls) == 1


def test_it_gives_up_after_the_last_attempt(monkeypatch):
    calls = _patched_httpx(monkeypatch, [_FakeResp(429), _FakeResp(429)])
    assert vf._get("https://hh.ru/vacancy/1", 8.0, sleep=lambda _s: None) == ""
    assert len(calls) == 2


def test_the_timeout_stays_under_a_serverless_budget():
    """A fetch that outlives the function turns a saved lead into a killed request."""
    assert vf._TIMEOUT_SECONDS <= 10


# --- Threads posts --------------------------------------------------------

from pathlib import Path  # noqa: E402

from app.domain.vacancy_text import extract_threads_post  # noqa: E402

_FX = Path(__file__).parent / "fixtures" / "threads"


def test_threads_post_text_comes_from_og_description():
    text = extract_threads_post((_FX / "post.html").read_text(encoding="utf-8"))
    assert text.startswith("Ищу Full Stack Developer")
    assert "Lovable" in text
    # og:description caps the root post here. If Threads moves that cap this number
    # needs re-baselining against a fresh capture.py run — don't delete the assertion:
    # it is the anchor on real markup. The wrong-tag protection (og:description vs the
    # shorter plain `description`) lives in the reordered-tags test at the end.
    assert len(text) == 480


def test_threads_missing_post_yields_nothing():
    """A deleted/non-existent post returns a page with no og tags at all."""
    assert extract_threads_post((_FX / "missing.html").read_text(encoding="utf-8")) == ""


def test_threads_spa_shell_yields_nothing_not_garbage():
    """What a browser User-Agent gets. Must be empty, never partial junk."""
    assert extract_threads_post((_FX / "spa_shell.html").read_text(encoding="utf-8")) == ""


def test_threads_empty_html():
    assert extract_threads_post("") == ""


def test_threads_entities_are_decoded_and_newlines_kept():
    html = ('<meta property="og:description" content="Ищем&#064;QA&amp;Dev'
            '&#10;&#8212; тесты" />')
    text = extract_threads_post(html)
    assert "@" in text and "&" in text and "&amp;" not in text
    assert "\n" in text


def test_threads_respects_max_chars():
    html = '<meta property="og:description" content="' + "a" * 900 + '" />'
    assert len(extract_threads_post(html, max_chars=100)) == 100


def test_the_plain_description_tag_does_not_win_when_it_comes_first():
    """The page carries three description tags: og:description (the post),
    a shorter plain `description`, and `twitter:description`. Matching the loose
    `(?:og:)?description` form passes on the saved fixture only because
    og:description happens to be first there — with the order reversed it would
    return the 152-char blurb as the vacancy. Pin the specific tag."""
    html = (
        '<meta name="description" content="Ищу Full Stack Developer, короткий блурб" />'
        '<meta name="twitter:description" content="Ищу Full Stack Developer, средний блурб" />'
        '<meta property="og:description" content="Ищу Full Stack Developer, полный текст поста" />'
    )
    assert extract_threads_post(html) == "Ищу Full Stack Developer, полный текст поста"


# --- pick_vacancy_url -------------------------------------------------------

def test_the_post_link_is_picked_even_when_the_message_names_a_contact():
    """The bug this function exists for. `detect_contact` answers @ivan_hr here,
    so the fetch was aimed at a Telegram handle, the post was never opened, and
    the lead landed with an empty «Вакансия» that nothing downstream recovered.
    WHICH url carries the description is a different question from WHOM we reply
    to, and it has to be asked separately."""
    text = ("Ребята, вот интересная вакансия, посмотри: "
            "https://www.linkedin.com/posts/acme_hiring-activity-7300000000-AbCd"
            " пиши @ivan_hr")
    assert vf.pick_vacancy_url(text) == (
        "https://www.linkedin.com/posts/acme_hiring-activity-7300000000-AbCd")


def test_a_message_with_no_vacancy_link_picks_nothing():
    assert vf.pick_vacancy_url("Ищем Python-разработчика, пиши @ivan_hr") == ""
    assert vf.pick_vacancy_url("") == ""


def test_a_contact_link_is_not_a_vacancy_link():
    """A t.me link is whom to write to, not a page carrying a description."""
    assert vf.pick_vacancy_url("пиши https://t.me/ivan_hr") == ""


def test_the_sentence_period_is_not_part_of_the_url():
    """`https?://\\S+` swallows the period that ended the sentence, and the site
    answers 404 for the url with it attached — so the read fails and the lead is
    saved with no description at all."""
    assert vf.pick_vacancy_url(
        "Вакансия тут: https://hh.kz/vacancy/135171273.") == \
        "https://hh.kz/vacancy/135171273"


def test_the_first_fetchable_link_wins_when_the_message_carries_several():
    text = ("канал https://t.me/jobs_channel, вакансия "
            "https://hh.kz/vacancy/135171273 и ещё "
            "https://www.linkedin.com/posts/acme_hiring-activity-73-AbCd")
    assert vf.pick_vacancy_url(text) == "https://hh.kz/vacancy/135171273"


# --- resolve_lnkd_in --------------------------------------------------------

_FX_LI = Path(__file__).parent / "fixtures" / "linkedin"


def test_the_address_behind_a_lnkd_in_link_is_recovered(monkeypatch):
    """LinkedIn rewrites every outbound url in post text as `lnkd.in/…`, so a
    Telegram link inside a hiring post is invisible to contact detection until
    the rewrite is undone. The rewrite does not answer 3xx — it answers 200 and
    an interstitial page, and the real address is an href inside it."""
    html = (_FX_LI / "lnkd_interstitial.html").read_text(encoding="utf-8")
    calls = _patched_httpx(monkeypatch, [_FakeResp(200, html)])
    assert vf.resolve_lnkd_in("https://lnkd.in/dpAQNfdG") == \
        "https://t.me/geeklink_jobs_bot"
    assert calls == ["https://lnkd.in/dpAQNfdG"]


def test_only_lnkd_in_is_ever_fetched(monkeypatch):
    """The urls this is fed come out of a stranger's post text. A resolver that
    fetched whatever it was handed would turn any hiring post into a request the
    serverless function makes on the author's behalf."""
    calls = _patched_httpx(monkeypatch, [])
    assert vf.resolve_lnkd_in("https://evil.example/redirect") == ""
    assert vf.resolve_lnkd_in("https://t.me/ivan_hr") == ""
    assert calls == []


def test_an_interstitial_without_the_external_link_resolves_to_nothing(monkeypatch):
    _patched_httpx(monkeypatch, [_FakeResp(200, "<html>Page not found</html>")])
    assert vf.resolve_lnkd_in("https://lnkd.in/dead") == ""


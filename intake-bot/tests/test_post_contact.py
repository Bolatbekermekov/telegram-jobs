"""Whom a LinkedIn hiring post says to write to, read out of the post's own text."""
from app.domain.contact import Contact, detect_contact
from app.domain.post_contact import pick_post_contact, post_author_profile_url

POST_URL = ("https://www.linkedin.com/posts/evgeniy-evsyukov_telegram-"
            "activity-7091693103895449600-thjQ")


# --- pick_post_contact ------------------------------------------------------

def test_a_telegram_handle_in_the_post_is_the_contact():
    text = ("Ищем Junior Python Developer, удалёнка, вилка 2000-3000 USD.\n"
            "Резюме присылайте в телеграм @acme_hr")
    assert pick_post_contact(text, detect_contact) == Contact("telegram", "@acme_hr")


def test_an_email_in_the_post_is_the_contact_when_there_is_no_telegram():
    text = "Ищем QA Engineer. CV на hr@acme.io"
    assert pick_post_contact(text, detect_contact) == Contact("email", "hr@acme.io")


def test_telegram_wins_over_an_email_in_the_same_post():
    """The order the user asked for: telegram first, email second."""
    text = "CV на hr@acme.io или в телеграм @acme_hr"
    assert pick_post_contact(text, detect_contact) == Contact("telegram", "@acme_hr")


def test_a_post_with_no_contact_answers_nothing():
    """Not a guess and not the author — None, so the caller can fall back to the
    author's profile itself. Answering anything else here would send a stranger a
    message about a vacancy they never posted."""
    text = "Ищем Go-разработчика в Алматы, гибрид, от года опыта. Откликайтесь!"
    assert pick_post_contact(text, detect_contact) is None


def test_a_link_that_is_not_a_contact_channel_is_not_taken():
    """`detect_contact` ranks hh and LinkedIn urls as contacts too, because for a
    forwarded MESSAGE they are. Inside a post they are references — «похожая
    вакансия тут» — and routing the lead to one would write to whoever that page
    belongs to instead of the person hiring."""
    text = ("Ищем Python-разработчика. Похожая вакансия: "
            "https://hh.kz/vacancy/135171273 , профиль: "
            "https://www.linkedin.com/in/someone-else/")
    assert pick_post_contact(text, detect_contact) is None


def test_a_telegram_link_behind_the_lnkd_in_rewrite_is_found():
    """LinkedIn rewrites outbound urls in post text, so this is the shape a
    `t.me` link actually arrives in — unreadable until the rewrite is undone."""
    text = "Ищем Python-разработчика. Писать сюда: https://lnkd.in/dpAQNfdG"
    resolved = {"https://lnkd.in/dpAQNfdG": "https://t.me/acme_hr"}
    contact = pick_post_contact(text, detect_contact,
                               resolve_link=resolved.get)
    assert contact == Contact("telegram", "https://t.me/acme_hr")


def test_the_rewrite_is_not_resolved_when_the_post_already_names_a_handle():
    """Every resolution is an extra http request inside a serverless budget that
    has already paid for reading the post."""
    text = "Пишите @acme_hr или тут https://lnkd.in/dpAQNfdG"
    asked = []

    def _resolve(url):
        asked.append(url)
        return "https://t.me/someone_else"

    assert pick_post_contact(text, detect_contact, resolve_link=_resolve) == \
        Contact("telegram", "@acme_hr")
    assert asked == []


def test_only_the_first_two_rewrites_are_resolved():
    """A post can carry a dozen links. Each one costs a request on a clock the
    function shares with reading the post and summarising it."""
    text = ("Вакансия. " + " ".join(
        f"https://lnkd.in/code{i}" for i in range(6)))
    asked = []

    def _resolve(url):
        asked.append(url)
        return "https://example.com/nothing"

    assert pick_post_contact(text, detect_contact, resolve_link=_resolve) is None
    assert asked == ["https://lnkd.in/code0", "https://lnkd.in/code1"]


def test_a_rewrite_that_leads_nowhere_useful_answers_nothing():
    text = "Вакансия. Подробности: https://lnkd.in/dpAQNfdG"
    assert pick_post_contact(text, detect_contact,
                             resolve_link=lambda _u: "") is None


def test_a_resolver_that_throws_costs_the_contact_not_the_lead():
    def _boom(_url):
        raise RuntimeError("network down")

    text = "Вакансия. Подробности: https://lnkd.in/dpAQNfdG"
    assert pick_post_contact(text, detect_contact, resolve_link=_boom) is None


def test_no_post_text_answers_nothing():
    assert pick_post_contact("", detect_contact) is None
    assert pick_post_contact(None, detect_contact) is None


# --- post_author_profile_url ------------------------------------------------

def test_the_author_profile_comes_out_of_the_post_slug():
    assert post_author_profile_url(POST_URL) == \
        "https://www.linkedin.com/in/evgeniy-evsyukov/"


def test_share_tracking_on_the_url_does_not_confuse_the_author():
    assert post_author_profile_url(
        POST_URL + "/?utm_source=share&utm_medium=member_ios") == \
        "https://www.linkedin.com/in/evgeniy-evsyukov/"


def test_a_feed_update_url_has_no_author_in_it():
    """A company share carries no personal author in the slug. None, not a guess —
    the caller keeps the post url and the sender reports it can't find an author."""
    assert post_author_profile_url(
        "https://www.linkedin.com/feed/update/urn:li:activity:7091693103895449600/") \
        is None

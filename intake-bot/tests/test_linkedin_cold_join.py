"""Ссылка LinkedIn через страницу регистрации — это ссылка на пост внутри неё.

Живьём 2026-09-13: четыре лида (#1009, #1023, #1049, #1168) пришли в таблицу с
целью `https://www.linkedin.com/signup/cold-join?session_redirect=<пост>` — так
LinkedIn переписывает ссылку «поделиться», открытую без входа. Канал шёл на
страницу регистрации, не находил ни «Сообщение», ни «Контакт», и все четыре ушли
в `failed`, хотя настоящий пост лежал в параметре `session_redirect`.
"""
from app.domain.contact import canonical_linkedin_url, detect_contact

COLD_JOIN = ("https://www.linkedin.com/signup/cold-join?session_redirect="
             "https%3A%2F%2Fwww%2Elinkedin%2Ecom%2Ffeed%2Fupdate%2Furn%3Ali%3Ashare%3A7498713368221118464"
             "%3Futm_source%3Dshare%26utm_medium%3Dmember_desktop%26rcm%3DACoAAB")
POST = "https://www.linkedin.com/feed/update/urn:li:share:7498713368221118464"


def test_the_post_behind_a_signup_wrapper_is_unwrapped():
    assert canonical_linkedin_url(COLD_JOIN) == POST


def test_the_authwall_wrapper_is_unwrapped_too():
    wrapped = ("https://www.linkedin.com/authwall?trk=bf&sessionRedirect="
               "https%3A%2F%2Fwww.linkedin.com%2Ffeed%2Fupdate%2Furn%3Ali%3Ashare%3A7498713368221118464")
    assert canonical_linkedin_url(wrapped) == POST


def test_a_message_carrying_the_wrapper_becomes_a_lead_for_the_post():
    c = detect_contact(f"Senior React Native Developer {COLD_JOIN}")
    assert (c.platform, c.target) == ("linkedin", POST)


def test_an_ordinary_linkedin_link_is_left_as_it_was():
    assert canonical_linkedin_url("https://www.linkedin.com/jobs/view/4462216262/") == \
        "https://www.linkedin.com/jobs/view/4462216262/"
    assert canonical_linkedin_url("linkedin.com/in/x") == "https://www.linkedin.com/in/x"

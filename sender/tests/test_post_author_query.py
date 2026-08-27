"""Параметры адреса не должны выглядеть ником автора поста.

Живой лид #525 (прогон 2026-08-27):

    https://www.linkedin.com/posts/activity-7498303002928336896-FiK7?utm_source=share&utm_medium=member_desktop

Ника автора в этом адресе нет вовсе — это «share»-ссылка. Но правило
`/posts/([^/_]+)_` требует подчёркивания ПОСЛЕ ника, а подчёркивание в адресе
нашлось: в параметре `utm_source`. Регулярка дошла до него через весь
`activity-…` и выдала за автора `activity-7498303002928336896-FiK7?utm`, из
которого собрался несуществующий профиль
`linkedin.com/in/activity-7498303002928336896-FiK7?utm/`.

Цена не только в упавшем лиде: раз правило вернуло НЕПУСТОЙ ответ, чтение
автора со страницы (добавленное коммитом `84e149c`) не включилось — оно
включается только когда автора не нашли. То есть одна опечатка в регулярке
обесценила весь запасной путь.
"""
from app.domain.candidate import post_author_profile_url


def test_share_link_without_an_author_gives_nothing():
    url = ("https://www.linkedin.com/posts/activity-7498303002928336896-FiK7"
           "?utm_source=share&utm_medium=member_desktop")
    assert post_author_profile_url(url) is None


def test_an_underscore_in_the_query_never_becomes_an_author():
    # Любой параметр с подчёркиванием годится: utm_source, rcm, trackingId.
    url = "https://www.linkedin.com/posts/hiring-react-share-749473?some_param=1"
    assert post_author_profile_url(url) is None


def test_a_real_author_is_still_read_from_the_url():
    url = ("https://www.linkedin.com/posts/chrisguindon_hiring-backend-"
           "activity-7495708880526544896-xQBG?utm_source=share")
    assert post_author_profile_url(url) == "https://www.linkedin.com/in/chrisguindon/"


def test_a_real_author_without_any_query():
    url = ("https://www.linkedin.com/posts/anna-hr_we-are-hiring-"
           "activity-7495708880526544896-xQBG/")
    assert post_author_profile_url(url) == "https://www.linkedin.com/in/anna-hr/"

"""Как добраться от ссылки на вакансию RemoteOK до формы работодателя.

Кнопка Apply — это не ссылка на работодателя, а редирект /l/<id>, и он
обфусцирован: тело ответа отдаёт JS, который расшифровывает строку и делает
window.location.href. Плюс без Referer со страницы вакансии он отвечает 302
обратно на неё же. Поэтому пройти его можно только браузером и только со
страницы вакансии (замер живой страницы 2026-08-03).

Куда он приземляется, тоже измерено: форма ATS (jobs.ashbyhq.com), страница с
ссылкой mailto на почту работодателя, либо экран платной подписки.
"""
from app.domain.remoteok_apply import apply_path, job_id, wall_reason

JOB = "https://remoteok.com/remote-jobs/remote-junior-designer-haystack-1135900"


def test_job_id_is_the_tail_of_the_slug():
    assert job_id(JOB) == "1135900"


def test_job_id_survives_the_capitalised_host_the_api_returns():
    """API отдаёт url с «remoteOK.com» — именно в таком виде он и лежит в листе."""
    assert job_id("https://remoteOK.com/remote-jobs/remote-software-engineer-go-"
                  "wakacje-pl-1135634") == "1135634"


def test_job_id_ignores_a_trailing_slash():
    assert job_id(JOB + "/") == "1135900"


def test_a_link_without_an_id_yields_nothing():
    for url in ("https://remoteok.com/remote-jobs", "", None,
                "https://remoteok.com/remote-jobs/no-digits-here"):
        assert job_id(url) == "", repr(url)


def test_apply_path_is_relative_so_the_referer_survives():
    """Переход обязан идти со страницы вакансии: /l/<id> без Referer отвечает
    302 обратно на вакансию, и отклик не открывается вообще."""
    assert apply_path("1135900") == "/l/1135900"


# --- стены, за которыми отклика нет -----------------------------------------

def test_the_premium_wall_is_reported_as_a_paid_subscription():
    got = wall_reason(
        "https://remoteok.com/premium?skip_url=https%3A%2F%2Fremoteok.com%2Fl%2F1"
        "135900%3Fskip_premium%3D1", JOB)
    assert got is not None
    assert "premium" in got.lower() or "подписк" in got.lower()
    assert JOB in got


def test_a_bounce_to_signup_means_the_session_died():
    """Ровно то, куда RemoteOK уводит гостя. Если мы это увидели — сессия
    протухла, и человеку надо сказать про make login_remoteok, а не про форму."""
    got = wall_reason("https://remoteok.com/sign-up?user_type=worker", JOB)
    assert got is not None
    assert "login_remoteok" in got


def test_the_employer_ats_is_not_a_wall():
    assert wall_reason("https://jobs.ashbyhq.com/superplane/ee9d219f?utm_source="
                       "remoteok.com", JOB) is None


def test_the_mailto_page_is_not_a_wall():
    """Страница «Redirecting you now to your mail app» живёт на самом remoteok.com
    и по URL неотличима от страницы вакансии — на ней настоящая ссылка
    mailto:hrd@mcgrp.com. Разбирать её URL-ом нельзя, это работа external_apply,
    который читает ссылки со страницы."""
    assert wall_reason(JOB, JOB) is None

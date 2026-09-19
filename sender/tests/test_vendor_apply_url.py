"""Где у вендора живёт форма отклика рядом со страницей вакансии.

Живьём 2026-09-13:
    Workable (лид #1164) — ссылка вела на страницу описания
      `apply.workable.com/mlabs/j/C3E3C0C056`, где полей нет, маршрут NONE, и
      лид лёг «форма не распознана». По `…/apply/` та же вакансия отдаёт форму
      из 7 полей.
    Teamtailor (лид #1004) — LinkedIn дал ссылку на чат
      `praktika.teamtailor.com/messenger?job_id=8320426` («Send a message…»).
      Номер вакансии лежит в `job_id`, и форма у неё — по обычному пути
      `/jobs/<id>/applications/new`.
"""
from app.domain.ats_embed import vendor_apply_url


def test_a_workable_job_page_leads_to_its_apply_form():
    assert vendor_apply_url("https://apply.workable.com/mlabs/j/C3E3C0C056", "workable.com") == \
        "https://apply.workable.com/mlabs/j/C3E3C0C056/apply"


def test_a_workable_form_is_not_walked_again():
    assert vendor_apply_url("https://apply.workable.com/mlabs/j/C3E3C0C056/apply/", "workable.com") == ""


def test_a_teamtailor_messenger_link_leads_to_the_jobs_form():
    assert vendor_apply_url("https://praktika.teamtailor.com/messenger?job_id=8320426", "teamtailor.com") == \
        "https://praktika.teamtailor.com/jobs/8320426/applications/new"


def test_an_ordinary_teamtailor_job_page_still_works():
    assert vendor_apply_url("https://acme.teamtailor.com/jobs/77-dev", "teamtailor.com") == \
        "https://acme.teamtailor.com/jobs/77-dev/applications/new"


def test_the_vendor_is_known_on_its_own_host_without_dns():
    """`vendor_behind` доказывает вендора за ЧУЖИМ доменом через CNAME, а на хосте
    самого вендора отвечает None — живьём так было у обоих лидов, и переход к
    форме не случался. Хост вендора доказательств не требует: он и есть вендор."""
    from app.application.apply_guard import vendor_of

    def no_dns(host):
        raise AssertionError("на хосте вендора в DNS ходить незачем")

    url = "https://apply.workable.com/mlabs/j/C3E3C0C056"
    assert vendor_apply_url(url, vendor_of(url, resolve=no_dns)) == url + "/apply"


def test_a_workable_board_is_not_a_job():
    assert vendor_apply_url("https://apply.workable.com/mlabs/", "apply.workable.com") == ""


# --- Ashby: от описания к анкете -----------------------------------------------
# Живьём 2026-09-19 (FunnelFox, Fullstack Engineer): вакансия встроена в сайт
# компании `funnelfox.com/careers/?ashby_jid=<uuid>`. Отправитель сам находит там
# iframe Ashby и входит в него — но попадает на страницу ОПИСАНИЯ
# `jobs.ashbyhq.com/jobs.funnelfox.com/<uuid>?embed=js`, где полей нет. Сухой
# прогон настоящего `external_apply` кончился «форма не распознана». Анкета у
# Ashby лежит рядом, по хвосту `/application`.
#
# Раньше это не мешало: ссылки на Ashby приходили уже с `/application` на конце.
# Обратите внимание на код компании с ТОЧКАМИ — `jobs.funnelfox.com`: Ashby
# называет доску по её собственному хосту.
ASHBY_JOB = "https://jobs.ashbyhq.com/jobs.funnelfox.com/f19afd7e-43c9-416e-9740-44cb675efd7f"


def test_an_ashby_job_page_leads_to_its_application_form():
    assert vendor_apply_url(ASHBY_JOB + "?embed=js", "ashbyhq.com") == \
        ASHBY_JOB + "/application"


def test_an_ashby_form_is_not_walked_again():
    assert vendor_apply_url(ASHBY_JOB + "/application", "ashbyhq.com") == ""


def test_an_ashby_board_root_is_not_given_a_form_tail():
    """К корню доски хвост дал бы 404: вакансии в адресе нет."""
    assert vendor_apply_url("https://jobs.ashbyhq.com/jobs.funnelfox.com",
                            "ashbyhq.com") == ""


def test_the_ashby_vendor_is_known_on_its_own_host_without_dns():
    from app.application.apply_guard import vendor_of

    def no_dns(host):
        raise AssertionError("на хосте вендора в DNS ходить незачем")

    assert vendor_apply_url(ASHBY_JOB, vendor_of(ASHBY_JOB, resolve=no_dns)) == \
        ASHBY_JOB + "/application"

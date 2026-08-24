"""Careers-страница компании на Greenhouse: доехать до формы, а не сдаться.

Замерено живьём 2026-08-24 на вакансии Datadog из Remocate
(careers.datadoghq.com/detail/8052095/?gh_jid=8052095):

* в отрисованном DOM нет ни одного поля, ни одного iframe и ни одной кнопки
  «Apply» — `_reveal_apply_form` кликать нечего, маршрут получается NONE, и лид
  уходил в ручной отклик;
* при этом сама страница ходит за формой на
  `job-boards.greenhouse.io/embed/job_app?for=datadog&validityToken=…&token=8052095`
  и просто не вставляет её в DOM;
* тот же адрес без validityToken отдаёт настоящую форму: 60 полей, загрузка
  файла, first_name на месте, маршрут FORM, а хост `job-boards.greenhouse.io`
  уже есть в белом списке ATS.

Отсюда правило: собрать адрес встроенной формы из того, что страница про себя
рассказывает, и перейти на него. `boards.greenhouse.io/<доска>/jobs/<id>` для
этого НЕ подходит — проверено, Datadog редиректит его обратно на свой сайт.
"""
from app.domain.ats_embed import greenhouse_embed_url

EMBED_SCRIPT = ('<script src="https://boards.greenhouse.io/embed/job_board/js'
                '?for=datadog"></script>')
PAGE_URL = "https://careers.datadoghq.com/detail/8052095/?gh_jid=8052095"
EXPECTED = ("https://job-boards.greenhouse.io/embed/job_app"
            "?for=datadog&token=8052095")


def test_builds_the_embed_form_url():
    assert greenhouse_embed_url(EMBED_SCRIPT, PAGE_URL) == EXPECTED


def test_job_id_may_come_from_the_page_instead_of_the_url():
    """Не всякая careers-страница держит gh_jid в адресе — иногда номер вакансии
    виден только в разметке."""
    html = EMBED_SCRIPT + '<div data-url="/embed/job_app?token=8052095"></div>'
    assert greenhouse_embed_url(html, "https://careers.datadoghq.com/detail/8052095/") \
        == EXPECTED


def test_no_board_token_means_no_url():
    """Без имени доски адрес не собрать, а угадывать его нельзя: попадём на
    чужую вакансию."""
    assert greenhouse_embed_url("<html>no greenhouse here</html>", PAGE_URL) == ""


def test_no_job_id_means_no_url():
    assert greenhouse_embed_url(EMBED_SCRIPT, "https://careers.datadoghq.com/jobs") == ""


def test_already_on_greenhouse_is_left_alone():
    """Иначе переход зациклится: форма Greenhouse тоже несёт свой embed-скрипт."""
    url = "https://job-boards.greenhouse.io/embed/job_app?for=datadog&token=8052095"
    assert greenhouse_embed_url(EMBED_SCRIPT, url) == ""


def test_board_name_is_taken_verbatim():
    """Имя доски — не всегда имя компании: у многих оно вида acme-inc или acme2."""
    html = ('<script src="https://boards.greenhouse.io/embed/job_board/js'
            '?for=acme-inc2"></script>')
    assert greenhouse_embed_url(html, "https://jobs.acme.com/x?gh_jid=42") == (
        "https://job-boards.greenhouse.io/embed/job_app?for=acme-inc2&token=42")


# --- переход внутри автоотклика ----------------------------------------------
from app.domain.channel import ManualApplyRequired, OutreachContent      # noqa: E402
from app.domain.apply_profile import ApplyProfile                        # noqa: E402
from app.domain.page_observation import FieldObs, PageObservation        # noqa: E402
from app.infrastructure.channels import external_apply as ea             # noqa: E402
import pytest                                                            # noqa: E402

PROF = ApplyProfile(full_name="B Y", email="a@b.com")
FORM = PageObservation(url=EXPECTED, fields=[
    FieldObs(tag="input", type="email", label="Email", required=True, ref="0"),
    FieldObs(tag="input", type="file", label="Resume", required=True, ref="1"),
])


class _CareersPage:
    """Пустая careers-страница, которая становится формой после перехода.

    Ровно то, что видно на Datadog: полей нет, iframe нет, кликать не по чему —
    но в разметке лежит embed-скрипт с именем доски.
    """

    def __init__(self, html=EMBED_SCRIPT, url=PAGE_URL):
        self._html = html
        self.url = url
        self._obs = PageObservation(url=url)      # NONE: ни полей, ни ссылок
        self.present = set()
        self.filled = {}
        self.clicks = []
        self.submit_sticks = False
        self.submit_intercepted = False
        self.visited = []

    def content(self):
        return self._html

    def goto(self, url, **kwargs):
        self.visited.append(url)
        self.url = url
        self._obs = FORM
        self.present = {ea.SEL_SUBMIT} | {f'[data-af="{f.ref}"]' for f in FORM.fields}

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, js):
        return ea.observation_to_raw(self._obs)

    def locator(self, sel):
        from tests.test_external_apply import FakeLocator
        return FakeLocator(self, sel)


def test_empty_careers_page_hops_to_the_embedded_form():
    page = _CareersPage()
    ea.external_apply(page, PAGE_URL, OutreachContent(body="hi"), PROF, "C:/cv.pdf")
    assert page.visited == [EXPECTED]
    assert page.filled['[data-af="0"]'] == "a@b.com"
    assert page.filled['[data-af="1"]'] == ("file", "C:/cv.pdf")
    assert ea.SEL_SUBMIT in page.clicks


def test_page_without_a_greenhouse_embed_still_goes_manual():
    """Переход — добавка к прежнему поведению, а не подмена: страница без
    Greenhouse по-прежнему честно уходит в ручной отклик."""
    page = _CareersPage(html="<html>ничего похожего</html>")
    with pytest.raises(ManualApplyRequired, match="форма не распознана"):
        ea.external_apply(page, PAGE_URL, OutreachContent(body="hi"), PROF, "C:/cv.pdf")
    assert page.visited == []


# --- номер вакансии в пути адреса --------------------------------------------
# N26 (та же вакансия из Remocate) устроен так же, но gh_jid у него нет:
# `n26.com/en-eu/careers/positions/7925103`, а имя доски — в том же embed-скрипте
# (`?for=n26`). Собранный из этих двух кусков адрес отдаёт настоящую форму —
# проверено 2026-08-24, заголовок «Job Application for Backend Engineer -
# Engagement at N26», 8 упоминаний first_name и две загрузки файла.

def test_job_id_may_come_from_the_url_path():
    html = ('<script src="https://boards.greenhouse.io/embed/job_board/js'
            '?for=n26"></script>')
    assert greenhouse_embed_url(html, "https://n26.com/en-eu/careers/positions/7925103") \
        == "https://job-boards.greenhouse.io/embed/job_app?for=n26&token=7925103"


def test_gh_jid_wins_over_a_number_in_the_path():
    """Явный параметр надёжнее догадки по пути, и порядок это закрепляет."""
    html = EMBED_SCRIPT
    url = "https://careers.datadoghq.com/detail/999999/?gh_jid=8052095"
    assert greenhouse_embed_url(html, url) == EXPECTED


def test_a_short_number_in_the_path_is_not_a_job_id():
    """Иначе `/careers/2024/backend` превратится в отклик на чужую вакансию."""
    html = EMBED_SCRIPT
    assert greenhouse_embed_url(html, "https://acme.com/careers/2024/backend") == ""


# --- форма вендора на соседнем адресе ----------------------------------------
# Замер 2026-08-24 на `careers.bluethrone.io/jobs/8175038-senior-backend-engineer
# -golang` (Teamtailor): на самой странице вакансии полей нет, кнопки «Apply»
# тоже — она подписана «Join us», под `_REVEAL_SEL` не попадает. Настоящая форма
# лежит на `<адрес вакансии>/applications/new` и даёт 19 полей.
# То же у Recruitee: `jobs.profitap.com/o/<слаг>` — страница вакансии, форма на
# `/o/<слаг>/c/new`.
from app.domain.ats_embed import vendor_apply_url                        # noqa: E402


def test_teamtailor_form_lives_next_to_the_job():
    assert vendor_apply_url(
        "https://careers.bluethrone.io/jobs/8175038-senior-backend-engineer-golang",
        "teamtailor.com",
    ) == ("https://careers.bluethrone.io/jobs/"
          "8175038-senior-backend-engineer-golang/applications/new")


def test_recruitee_form_lives_next_to_the_job():
    assert vendor_apply_url("https://jobs.profitap.com/o/qa-engineer-3",
                            "recruitee.com") == \
        "https://jobs.profitap.com/o/qa-engineer-3/c/new"


def test_a_vendor_without_a_known_apply_path_gets_nothing():
    """Гадать нельзя: чужой адрес это отклик не на ту вакансию."""
    assert vendor_apply_url("https://boards.greenhouse.io/acme/jobs/1",
                            "greenhouse.io") == ""
    assert vendor_apply_url("https://x.test/jobs/1", None) == ""


def test_we_do_not_walk_onto_the_form_we_are_already_on():
    assert vendor_apply_url(
        "https://careers.bluethrone.io/jobs/8175038-x/applications/new",
        "teamtailor.com") == ""

"""Собственный ATS за CDN остаётся ручным, даже когда его форма читается целиком.

Замер 2026-08-25, куст jobs.micro1.ai — 11 лидов на 8 вакансиях, все ушли в
«незнакомый сайт, заполни вручную». Куст соблазнительный: форма распознаётся с
первой попытки (`Route.FORM`, 7 полей), без CAPTCHA, без логина, и пять полей из
семи заполняются прямо из профиля. Отсюда два способа случайно её разрешить, и
оба этот файл ловит.

Первый — счесть вендором CDN. У micro1 в DNS лежит
`jobs.micro1.ai CNAME d25w0q0pa41c84.cloudfront.net`, то есть делегирование есть,
но не вендору ATS, а CloudFront: под ним свой портал micro1 (Next.js,
`prod-api.micro1.ai`, `og:site_name` = «micro1 Job Portal», ни одного вендорского
маркера в разметке). Правило `vendor_behind` держится на том, что хост отдан
ВЕНДОРУ ЦЕЛИКОМ и вёрстку формы пишет он; для CDN это неверно — вёрстку пишет
владелец домена, ровно тот, от кого защищает список.

Второй — переставить проверку хоста после разбора формы. Читаемость формы не
довод: подписи полей и вопросы приходят со страницы, которой мы не управляем, и
уезжают модели вместе с резюме (см. докстроку app/application/apply_guard.py).
"""
from app.application.apply_guard import host_or_vendor_allowed, vendor_behind
from app.domain.apply_profile import ApplyProfile
from app.domain.channel import ManualApplyRequired, OutreachContent
from app.domain.page_observation import FieldObs, PageObservation
from app.infrastructure.channels import external_apply as ea

import pytest

MICRO1_JOB = "https://jobs.micro1.ai/post/bd545591-e88e-48f9-b3a9-cd3716144c8f"


def _chain(*targets):
    return lambda host: tuple(targets)


def test_a_cdn_in_front_of_an_own_ats_is_not_a_vendor():
    """Живая цепочка jobs.micro1.ai, снята 2026-08-25 через dns.google.

    CloudFront в цепочке значит «сайт раздаётся через CDN», а не «форму рисует
    знакомый ATS». Пустить сюда любой CNAME-хоп значит разрешить всякий сайт на
    CloudFront, Fastly или Cloudflare — то есть половину интернета.
    """
    assert vendor_behind(
        MICRO1_JOB, resolve=_chain("d25w0q0pa41c84.cloudfront.net")) is None
    assert not host_or_vendor_allowed(
        MICRO1_JOB, resolve=_chain("d25w0q0pa41c84.cloudfront.net"))


# Живой снимок формы micro1 (замер 2026-08-25, все восемь вакансий дали ровно
# такие семь полей). Обязательность в разметке НЕ проставлена ни у одного поля,
# хотя схема самого micro1 требует имя, телефон, LinkedIn и резюме, — поэтому
# `unmapped_required()` здесь пуст и сам по себе ничего не запретил бы.
def _micro1_form():
    f = lambda **kw: FieldObs(tag=kw.pop("tag", "input"), **kw)
    return PageObservation(url=MICRO1_JOB, file_inputs=1, fields=[
        f(type="text", label="Enter your first name", name="first_name", ref="0"),
        f(type="text", label="Enter your last name", name="last_name", ref="1"),
        f(type="text", label="Enter your email address", name="email_id", ref="2"),
        f(tag="select", type="select-one", label="Phone number country",
          options=["Afghanistan", "Kazakhstan"], ref="3"),
        f(type="tel", label="", name="", ref="4"),
        f(type="text", label="Enter your LinkedIn URL", name="linkedin_url", ref="5"),
        f(type="file", label="Click to upload or drag & drop (.pdf)", name="file",
          ref="6"),
    ])


class _RefusingPage:
    """Страница, которая падает на любом действии, кроме чтения формы.

    Так тест отвечает не только «отказались», но и «ничего не тронули»: заполнить
    поле или нажать кнопку на неразрешённом хосте — уже утечка, даже если отклик
    в итоге не ушёл.
    """

    def __init__(self, obs):
        self._obs = obs
        self.url = obs.url

    def evaluate(self, js, **kw):
        return ea.observation_to_raw(self._obs)

    def locator(self, sel):
        raise AssertionError(
            f"на неразрешённом хосте не должно быть обращений к DOM: {sel}")

    def wait_for_timeout(self, ms):
        pass


def test_a_readable_form_on_an_unlisted_host_is_still_not_filled(monkeypatch):
    """Форма читается целиком — и всё равно ручной отклик, без единого касания.

    Ловит перестановку проверки хоста ниже `build_plan`: план собрался бы из
    подписей чужой страницы, а резюме и ответы модели уехали бы в форму, чью
    вёрстку мы не разбирали.
    """
    monkeypatch.setattr(ea, "vendor_behind", lambda url, *a, **kw: None)
    page = _RefusingPage(_micro1_form())
    with pytest.raises(ManualApplyRequired) as e:
        ea.external_apply(page, MICRO1_JOB, OutreachContent(body="hi"),
                          ApplyProfile(full_name="B Y", email="a@b.com"),
                          "C:/cv.pdf")
    assert "незнакомый сайт" in str(e.value)
    assert MICRO1_JOB in str(e.value)

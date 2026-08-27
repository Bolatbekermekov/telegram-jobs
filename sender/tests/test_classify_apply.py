from app.application.classify_apply import classify, known_ats_iframe
from app.domain.page_observation import FieldObs, PageObservation, Route


def _f(tag, **kw):
    return FieldObs(tag=tag, **kw)


def test_login_wall_is_gated():
    # A real login/registration wall is the only automatic skip.
    obs = PageObservation(url="https://x/apply/authentication", login_required=True,
                          fields=[_f("input", type="email", label="Email")])
    assert classify(obs) is Route.GATED


def test_invisible_captcha_form_is_not_gated():
    # reCAPTCHA presence must NOT skip a fillable form (invisible v3 is on almost
    # every ATS, incl. Comeet, and does not block filling/submitting).
    obs = PageObservation(
        url="https://www.comeet.co/jobs/x/apply",
        fields=[_f("input", type="email", label="Email", required=True),
                _f("input", type="text", label="First Name", required=True)],
        file_inputs=1, captcha=True)
    assert classify(obs) is Route.FORM


def test_lone_email_field_is_not_a_form():
    # A single "apply later" / subscribe email box (e.g. join.com listing page) is
    # not an application form -> not FORM.
    obs = PageObservation(url="https://join.com/companies/x",
                          fields=[_f("input", type="email", label="Email")],
                          apply_buttons=["Apply now", "Apply Later"])
    assert classify(obs) is Route.NONE


def test_ddrive_mailto_is_email():
    # Recon: no form, "Apply" = mailto:hr@ddrive.tech.
    obs = PageObservation(url="https://www.ddrive.tech/team/junior-software-developer",
                          mailto_links=["mailto:hr@ddrive.tech?subject=Junior"],
                          apply_buttons=["Join the team", "Apply"])
    assert classify(obs) is Route.EMAIL


def test_superplay_cookie_checkboxes_plus_comeet_iframe_is_iframe_ats():
    # Recon: visible fields were only cookie/consent checkboxes; real form in Comeet iframe.
    obs = PageObservation(
        url="https://www.superplay.co/careers-position/26.D66/",
        fields=[_f("input", type="checkbox", label="Performance Cookies"),
                _f("input", type="checkbox", label="checkbox label"),
                _f("input", type="text", label="Cookie list search")],
        iframes=["https://www.comeet.co/jobs/28.003/26.D66/apply?token=x&embedded=true"])
    assert classify(obs) is Route.IFRAME_ATS


def test_greenhouse_like_form():
    obs = PageObservation(
        url="https://boards.greenhouse.io/acme/jobs/1",
        fields=[_f("input", type="email", label="Email", required=True),
                _f("input", type="text", label="First Name", required=True)],
        file_inputs=1)
    assert classify(obs) is Route.FORM


def test_empty_page_is_none():
    assert classify(PageObservation(url="https://x.test")) is Route.NONE


# --- страница вакансии, а не форма -------------------------------------------
# Замер 2026-08-24 на живых страницах: `jobs.zalando.com/en/jobs/2723788-…`
# держит форму в `<div id="apply" class="… hidden">`, а `jobs.profitap.com/o/
# qa-engineer-3` (Recruitee) — вообще на соседнем адресе `/c/new`. В обоих
# случаях в DOM видно ТОЛЬКО поля загрузки файла: скрапер берёт их даже
# невидимыми — иначе резюме не приложится ни на одном ATS.
#
# Прежнее правило «есть загрузка файла — значит форма» объявляло такую страницу
# формой. Последствие хуже, чем ручной отклик: обязательных незаполненных полей
# нет (полей вообще нет), CV прикрепляется, `SEL_SUBMIT` находит на странице
# кнопку «Apply», жмёт её, страница уходит на настоящую форму — и проверка
# отправки засчитывает эту навигацию как успешно поданную заявку. Работодатель
# при этом не получил ничего, а лид помечен `sent`.

def test_a_page_with_only_a_file_input_is_not_a_form():
    obs = PageObservation(url="https://jobs.profitap.com/o/qa-engineer-3",
                          fields=[_f("input", type="file", label="CV")],
                          file_inputs=1)
    assert classify(obs) is Route.NONE


def test_a_file_input_plus_one_apply_field_is_a_form():
    """Граница: настоящая форма отклика это загрузка резюме И поля о человеке."""
    obs = PageObservation(url="https://jobs.profitap.com/o/qa-engineer-3/c/new",
                          fields=[_f("input", type="file", label="CV"),
                                  _f("input", type="email", label="Email")],
                          file_inputs=1)
    assert classify(obs) is Route.FORM


# --- кнопка «поделиться» — не адрес отклика ----------------------------------
# Лид #419 (BlueThrone, Teamtailor): полей на странице нет, а единственная
# mailto-ссылка это кнопка «поделиться вакансией» — `mailto:?subject=Check out
# this job…`, БЕЗ адреса получателя. Маршрут вышел EMAIL, разбор адреса вернул
# пустое, и отклик умер с «не разобрал адрес» вместо того, чтобы искать форму
# дальше.

def test_a_mailto_without_an_address_is_not_an_email_route():
    obs = PageObservation(
        url="https://careers.bluethrone.io/jobs/8175038-senior-backend-engineer",
        mailto_links=["mailto:?subject=Check%20out%20this%20job&body=I%20found"])
    assert classify(obs) is Route.NONE


def test_a_real_mailto_still_wins():
    obs = PageObservation(url="https://x.test",
                          mailto_links=["mailto:?subject=share",
                                        "mailto:hr@acme.io?subject=Junior"])
    assert classify(obs) is Route.EMAIL


# --- почтовый ящик, в который отклик слать нельзя -----------------------------
# Замер 2026-08-24 на `jobs.zalando.com/en/jobs/2723788-…`. Единственные mailto
# на странице:
#   до клика «Apply»  — mailto:your-friend@example.com?subject=Zalando Job,
#                       Check out this job — кнопка «поделиться с другом»;
#   после клика       — mailto:datenschutz@zalando.de ×4 из уведомления о
#                       защите данных.
# Оба «адреса» проходят проверку «есть собачка», и заявка ушла бы либо в
# несуществующий пример, либо офицеру по приватности. Ручной отклик тут лучше
# любой отправки.

def test_a_placeholder_address_is_not_an_apply_address():
    """example.com зарезервирован RFC 2606 ровно под примеры — доказуемо не адрес."""
    obs = PageObservation(
        url="https://jobs.zalando.com/en/jobs/2723788-Principal",
        mailto_links=["mailto:your-friend@example.com?subject=Check%20out%20this%20job"])
    assert classify(obs) is Route.NONE


def test_a_privacy_mailbox_is_not_an_apply_address():
    obs = PageObservation(url="https://jobs.zalando.com/en/jobs/2723788-Principal",
                          mailto_links=["mailto:datenschutz@zalando.de"])
    assert classify(obs) is Route.NONE


def test_a_hiring_mailbox_is_still_an_apply_address():
    """Отсев узкий и по делу: обычные ящики найма трогать нельзя, через них
    отклики и уходят — так был отправлен лид #380 (info@m-tex.pro)."""
    for addr in ("hr@ddrive.tech", "jobs@acme.io", "careers@acme.io",
                 "info@m-tex.pro", "maria.ivanova@acme.io"):
        obs = PageObservation(url="https://x.test",
                              mailto_links=[f"mailto:{addr}?subject=Junior"])
        assert classify(obs) is Route.EMAIL, addr


def test_the_first_usable_address_wins_over_the_noise():
    obs = PageObservation(url="https://x.test", mailto_links=[
        "mailto:your-friend@example.com?subject=share",
        "mailto:datenschutz@acme.de",
        "mailto:jobs@acme.de?subject=Application"])
    assert classify(obs) is Route.EMAIL


# --- вендор во встроенном ATS опознаётся по ХОСТУ, а не подстрокой -----------
# Замер 2026-08-27 видимым браузером на живой вакансии SmartRecruiters
# (`jobs.smartrecruiters.com/SmartRecruiters/744000143115219-…`): страницу
# закрывает капча DataDome, и её iframe несёт адрес закрытой страницы В
# ПАРАМЕТРЕ — `geo.captcha-delivery.com/captcha/?…&referer=https%3A%2F%2Fjobs
# .smartrecruiters.com%2F…`. Прежнее правило искало имя вендора подстрокой во
# ВСЁМ адресе, находило «smartrecruiters.com» в этом параметре, маршрут выходил
# IFRAME_ATS — и `_enter_ats_iframe` уводил браузер ВНУТРЬ КАПЧИ вместо формы.
# Оттуда ни формы, ни вакансии: Route.NONE и «форма не распознана».
#
# Хост сравнивается ровно тем же `host_allowed`, что стоит перед отправкой
# (`apply_guard`), и по той же причине: границы меток, а не подстроки. Обрезать
# до самого домена при этом нельзя — вендоры шардят по регионам и клиентам
# (`job-boards.greenhouse.io`, `acme.wd3.myworkdayjobs.com`).

def test_a_captcha_naming_the_vendor_in_a_parameter_is_not_the_vendors_form():
    obs = PageObservation(
        url="https://jobs.smartrecruiters.com/SmartRecruiters/744000143115219-engineer",
        iframes=["https://geo.captcha-delivery.com/captcha/?initialCid=AHrlqAAAAAM"
                 "&cid=n2R1Ir&referer=https%3A%2F%2Fjobs.smartrecruiters.com%2F"
                 "SmartRecruiters%2F744000143115219&hash=A3&t=fe"])
    assert known_ats_iframe(obs.iframes) is None
    assert classify(obs) is Route.NONE


def test_a_lookalike_host_is_not_the_vendor():
    """`greenhouse.io.evil.tld` — это evil.tld; имя вендора в параметре — не вендор."""
    assert known_ats_iframe(["https://greenhouse.io.evil.tld/apply"]) is None
    assert known_ats_iframe(["https://ads.tld/px?utm_source=lever.co"]) is None
    assert known_ats_iframe(["https://evil.tld/www.comeet.co/jobs/1/apply"]) is None


def test_a_vendor_subdomain_is_still_the_vendors_form():
    for src in ("https://www.comeet.co/jobs/28.003/26.D66/apply?token=x&embedded=true",
                "https://job-boards.greenhouse.io/embed/job_app?token=1",
                "https://acme.wd3.myworkdayjobs.com/en-US/careers/job/1",
                "https://jobs.lever.co/acme/1234/apply"):
        assert known_ats_iframe([src]) == src, src


def test_the_first_vendor_iframe_wins_over_the_noise():
    """Капча и аналитика на странице стоят рядом с настоящим встроенным ATS."""
    srcs = ["https://geo.captcha-delivery.com/captcha/?referer=https%3A%2F%2Fx.comeet.co",
            "https://www.googletagmanager.com/ns.html?id=GTM-1",
            "https://www.comeet.co/jobs/28.003/26.D66/apply?token=x"]
    assert known_ats_iframe(srcs) == srcs[2]

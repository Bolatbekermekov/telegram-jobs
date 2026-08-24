"""Guards that stand between an injected page and an irreversible submit.

These don't test that injections are detected — they can't be. They test that a
successful injection still can't reach a submit on an unknown host, and can't
carry the candidate's contact details out through a free-text answer.
"""
import pytest

from app.application.apply_guard import (
    ALLOWED_APPLY_HOSTS, cname_targets, host_allowed, host_or_vendor_allowed,
    leaked_secrets, vendor_behind,
)
from app.domain.apply_profile import ApplyProfile


def _profile(**kw):
    return ApplyProfile(
        email="bolatbek@example.com",
        phone="+7 (700) 123-45-67",
        linkedin="linkedin.com/in/bolatbek",
        **kw,
    )


# --- host allowlist ---------------------------------------------------------

def test_known_ats_host_is_allowed():
    assert host_allowed("https://boards.greenhouse.io/acme/jobs/123")


def test_unknown_host_is_rejected():
    assert not host_allowed("https://careers.random-startup.xyz/apply")


def test_subdomain_of_an_allowed_vendor_is_allowed():
    """Workday shards per customer and region; listing every host is impossible."""
    assert host_allowed("https://acme.wd5.myworkdayjobs.com/en-US/careers/job/1")


def test_lookalike_domain_is_rejected():
    """greenhouse.io.evil.tld must not pass as greenhouse.io."""
    assert not host_allowed("https://boards.greenhouse.io.evil.tld/apply")


def test_allowed_host_as_a_path_segment_is_rejected():
    assert not host_allowed("https://evil.tld/boards.greenhouse.io/apply")


def test_garbage_url_is_rejected():
    for url in ("", "not-a-url", "https://", "mailto:hr@acme.com"):
        assert not host_allowed(url), url


def test_host_matching_ignores_case_and_trailing_dot():
    assert host_allowed("https://Jobs.Lever.CO/acme/1")
    assert host_allowed("https://jobs.lever.co./acme/1")


def test_the_platforms_we_apply_on_are_allowed():
    """hh/wellfound/linkedin route through this driver too — don't lock them out."""
    for host in ("hh.ru", "wellfound.com", "linkedin.com"):
        assert host in ALLOWED_APPLY_HOSTS


# --- contact-detail leak ----------------------------------------------------

def test_a_normal_answer_leaks_nothing():
    text = "Мне интересна разработка на .NET, есть коммерческий опыт с C# и SQL."
    assert leaked_secrets(text, _profile()) == []


def test_email_in_a_free_text_answer_is_caught():
    assert "email" in leaked_secrets(
        "Свяжитесь со мной: bolatbek@example.com", _profile())


def test_phone_is_caught_despite_different_formatting():
    """The page asked for a phone; the model reformatted it. Still a leak."""
    assert "phone" in leaked_secrets("Мой номер 77001234567", _profile())


def test_phone_is_caught_when_written_with_separators():
    assert "phone" in leaked_secrets("тел. +7 700 123 45 67", _profile())


def test_linkedin_url_in_an_answer_is_caught():
    assert "linkedin" in leaked_secrets(
        "Профиль: linkedin.com/in/bolatbek", _profile())


def test_several_leaks_are_all_reported():
    text = "bolatbek@example.com, 77001234567"
    assert set(leaked_secrets(text, _profile())) == {"email", "phone"}


def test_an_empty_profile_field_never_matches():
    """A blank email must not make every answer look like a leak."""
    blank = ApplyProfile(email="", phone="", linkedin="")
    assert leaked_secrets("любой текст с @ и цифрами 12345678", blank) == []


def test_a_short_phone_is_not_matched():
    """Too few digits to be a real number — matching it would fire on any date."""
    short = ApplyProfile(email="", phone="12345", linkedin="")
    assert leaked_secrets("код 12345 и ещё 999", short) == []


def test_unrelated_digits_do_not_count_as_a_phone():
    assert leaked_secrets("Опыт: 5 лет, 2019-2024, зарплата 300000", _profile()) == []


def test_empty_text_leaks_nothing():
    assert leaked_secrets("", _profile()) == []


# --- routes seen live on 2026-07-20 (make apply_probe) ----------------------

def test_ats_vendor_behind_a_company_page_is_allowed():
    """superplay.co routes IFRAME_ATS into comeet.co — the form is the vendor's,
    so the check runs on the vendor host, which must pass."""
    assert host_allowed("https://www.comeet.co/jobs/superplay/28/26/apply")


def test_company_own_page_is_still_rejected():
    """ddrive.tech-style page: if it ever served a plain form we'd fill it blind."""
    assert not host_allowed("https://www.ddrive.tech/team/junior-software-developer")


def test_join_com_is_allowed():
    """join.com hosts the apply flow itself (live probe case 1)."""
    assert host_allowed("https://join.com/companies/lemvos/16426802-internship")


# --- вендор за собственным доменом компании (замеры 2026-08-24) -------------
#
# Подставной резолвер вместо сети: цепочки ниже сняты живьём `dig +short` и
# https://dns.google/resolve в тот же день, так что тест проверяет разбор ровно
# тех ответов, которые приходят в проде.

def _chain(*targets):
    """Резолвер, отдающий заранее снятую цепочку CNAME."""
    def resolve(host):
        return targets
    return resolve


class _ResolverCalled(BaseException):
    """Намеренно не Exception: проверка глушит любой сбой резолвера и уходит в
    ручной отклик, так что обычное исключение она бы съела и тест «прошёл» бы,
    не заметив лишнего похода в сеть."""


def _explodes(host):
    raise _ResolverCalled(f"DNS-запрос для {host} не должен был случиться")


def test_recruitee_behind_a_company_domain_is_allowed():
    """Живой прогон 2026-08-24 увёл jobs.profitap.com в ручной отклик «незнакомый
    сайт», хотя jobs.profitap.com CNAME secure.recruitee.com — форму рисует
    Recruitee, который в ALLOWED_APPLY_HOSTS с самого начала."""
    assert host_or_vendor_allowed(
        "https://jobs.profitap.com/o/qa-engineer-3",
        resolve=_chain("secure.recruitee.com"))


def test_teamtailor_behind_a_company_domain_is_allowed():
    """Тот же прогон, careers.bluethrone.io. Путь /jobs/<7-значный id>-<слаг>
    читался как Greenhouse — а CNAME ведёт в ext.teamtailor.com. Тест ловит
    попытку опознавать вендора по форме URL вместо цепочки CNAME."""
    assert host_or_vendor_allowed(
        "https://careers.bluethrone.io/jobs/8175038-senior-backend-engineer-golang",
        resolve=_chain("ext.teamtailor.com", "ext.teamtailor.com.c.section.io",
                       "3bbnb6yydwv4hm5t2ebiebv6ffmlet6a.e.ns1.sectionedge.com",
                       "lmn-stk-k1.ep.section.io"))


def test_a_per_tenant_vendor_subdomain_counts_as_the_vendor():
    """careers.voi.com CNAME 2zx972fqcl81m.ext.teamtailor.com — Teamtailor выдаёт
    части клиентов персональный хост. Точное сравнение с ext.teamtailor.com
    такую цепочку бы не узнало."""
    assert host_or_vendor_allowed(
        "https://careers.voi.com/jobs/1",
        resolve=_chain("2zx972fqcl81m.ext.teamtailor.com", "teamtailor.map.fastly.net"))


def test_a_vendor_we_do_not_know_stays_manual():
    """karriere.nect.com CNAME nect.career.softgarden.de (замерено 2026-08-24).
    softgarden не в списке — его вёрстку мы не разбирали, и делегирование домена
    вендору само по себе не повод заполнять форму."""
    assert not host_or_vendor_allowed(
        "https://karriere.nect.com/vacancies/1",
        resolve=_chain("nect.career.softgarden.de"))


def test_a_cname_target_that_only_looks_like_a_vendor_is_rejected():
    """Форма реального сбоя: у nect.com в зоне лежит битый CNAME на
    nect.career.softgarden.de.nect.com — имя вендора внутри чужого домена.
    Поиск подстрокой пропустил бы и злоумышленника с secure.recruitee.com.evil.tld."""
    assert not host_or_vendor_allowed(
        "https://careers.evil.tld/o/qa-engineer",
        resolve=_chain("secure.recruitee.com.evil.tld"))


def test_a_cdn_hop_named_after_the_vendor_is_not_the_vendor():
    """ext.teamtailor.com.c.section.io — настоящий хоп из цепочки Teamtailor, но
    живёт он под section.io. Без этого хопа цепочка в вендора не заходит, и
    засчитывать её нельзя: иначе чужой CDN с таким же именем хоста пройдёт."""
    assert not host_or_vendor_allowed(
        "https://careers.evil.tld/jobs/1",
        resolve=_chain("ext.teamtailor.com.c.section.io", "lmn-stk-k1.ep.section.io"))


def test_a_company_page_without_a_cname_stays_manual():
    """ddrive.tech отдаёт вакансию со своего сервера — заполнять её вслепую
    ровно то, от чего защищает список."""
    assert not host_or_vendor_allowed(
        "https://www.ddrive.tech/team/junior-software-developer", resolve=_chain())


def test_a_dns_failure_keeps_the_apply_manual():
    """Не дозвонились до резолвера — это «не доказано», а не «разрешено»."""
    def boom(host):
        raise TimeoutError("DoH не ответил")

    assert not host_or_vendor_allowed(
        "https://jobs.profitap.com/o/qa-engineer-3", resolve=boom)


def test_a_listed_ats_host_never_waits_on_dns():
    """Хост из списка обязан проходить без сети: иначе упавший резолвер уронит в
    ручной отклик и greenhouse.io, который и так разрешён."""
    assert host_or_vendor_allowed(
        "https://boards.greenhouse.io/acme/jobs/123", resolve=_explodes)


def test_a_garbage_url_never_reaches_the_resolver():
    for url in ("", "not-a-url", "https://", "mailto:hr@acme.com"):
        assert not host_or_vendor_allowed(url, resolve=_explodes), url


def test_the_chain_is_matched_case_insensitively_and_without_the_root_dot():
    """dns.google отдаёт цель с финальной точкой («secure.recruitee.com.»), а
    регистр в DNS незначащий. Без нормализации живой ответ не совпадёт."""
    assert host_or_vendor_allowed(
        "https://jobs.profitap.com/o/qa-engineer-3",
        resolve=_chain("Secure.Recruitee.COM."))


def test_a_lookalike_host_is_not_rescued_by_its_own_dns():
    """boards.greenhouse.io.evil.tld отбивает host_allowed. Свою зону
    злоумышленник пишет сам, так что проверка CNAME не должна давать второй шанс
    ничему, что не заходит в домен вендора."""
    assert not host_or_vendor_allowed(
        "https://boards.greenhouse.io.evil.tld/apply",
        resolve=_chain("origin.evil.tld"))


def test_vendor_behind_names_the_vendor_for_the_log():
    """Оператору в «ушло автоматом» нужно видеть, ЧЬЮ форму мы сочли знакомой."""
    assert vendor_behind("https://jobs.profitap.com/o/qa-engineer-3",
                         resolve=_chain("secure.recruitee.com")) == "recruitee.com"
    assert vendor_behind("https://careers.random-startup.xyz/apply",
                         resolve=_chain()) is None


# --- разбор ответа dns.google ----------------------------------------------
# Полезные нагрузки ниже сняты живьём 2026-08-24, сеть в тестах не нужна.

def test_cname_targets_are_read_in_resolution_order():
    payload = {"Status": 0, "Answer": [
        {"name": "careers.bluethrone.io.", "type": 5, "data": "ext.teamtailor.com."},
        {"name": "ext.teamtailor.com.", "type": 5, "data": "ext.teamtailor.com.c.section.io."},
        {"name": "lmn-stk-k1.ep.section.io.", "type": 1, "data": "207.120.36.204"},
    ]}
    assert cname_targets(payload) == ("ext.teamtailor.com", "ext.teamtailor.com.c.section.io")


def test_an_a_record_is_not_mistaken_for_a_cname():
    """type 1 — это IP. Приняв его за имя, мы бы сравнивали адрес со списком хостов."""
    payload = {"Status": 0, "Answer": [
        {"name": "jobs.channable.com.", "type": 1, "data": "35.242.209.60"}]}
    assert cname_targets(payload) == ()


def test_a_cname_in_a_failed_lookup_is_not_a_chain():
    """Снято живьём с career.nect.com 2026-08-24: Status 3 (NXDOMAIN), а запись
    CNAME в Answer всё равно лежит — у nect.com в зоне опечатка, цель никуда не
    разрешается. Имя, которое не разрешилось, не отдавало ту страницу, что мы
    только что открыли, так что доказательством такая цепочка быть не может.
    Тест ловит чтение Answer без проверки Status."""
    broken = {"Status": 3, "Answer": [
        {"name": "career.nect.com.", "type": 5, "TTL": 60,
         "data": "nect.career.softgarden.de.nect.com."}]}
    assert cname_targets(broken) == ()
    # То же, но цель — настоящий вендор: иначе тест прошёл бы просто потому, что
    # softgarden не в списке, и дыру в проверке Status не заметил бы.
    broken["Answer"][0]["data"] = "secure.recruitee.com."
    assert cname_targets(broken) == ()
    assert cname_targets({"Status": 2}) == ()


def test_a_shape_we_did_not_expect_yields_no_chain():
    """Резолвер сменил формат — падать посреди отклика нельзя, уходим в ручной."""
    for payload in (None, {}, {"Status": 0, "Answer": "нет"}, {"Status": 0, "Answer": [None]}):
        assert cname_targets(payload) == (), payload


@pytest.mark.live
def test_the_two_hosts_from_the_2026_08_24_run_resolve_into_their_vendors():
    """Сеть настоящая: страховка от того, что компания съедет с вендора или
    вендор сменит хост для клиентских доменов, и правило тихо перестанет работать."""
    assert vendor_behind("https://jobs.profitap.com/o/qa-engineer-3") == "recruitee.com"
    assert vendor_behind(
        "https://careers.bluethrone.io/jobs/8175038-senior-backend-engineer-golang"
    ) == "teamtailor.com"

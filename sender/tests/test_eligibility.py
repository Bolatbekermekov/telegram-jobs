"""Жёсткие требования вакансии, которые кандидат не может выполнить.

Право работать без спонсорства визы у кандидата есть только в Казахстане. На
вопрос формы «Are you legally authorized to work in X?» бот честно отвечает «No»
(`apply_profile.work_authorized_in`), а Greenhouse, Ashby и Lever держат такие
вопросы как knockout: заявку отклоняет сам ATS, человек её не видит. До этой
проверки прогон платил описанием, оценкой, письмом и браузером за отклик,
который отсеется автоматически.

Правило намеренно узкое: блокирует только ЯВНО написанное требование. Страна в
локации сама по себе не блокирует — релокация со спонсорством возможна, а
удалёнку могут оформить контрактом. Лучше пропустить невозможную вакансию, чем
выбросить подходящую.
"""
import pytest

from app.domain.eligibility import check_eligibility

HOME = "Kazakhstan"


def _blocked(text, location=""):
    v = check_eligibility(text, location=location, home_country=HOME)
    return not v.eligible


# --- явные требования, которые кандидат не выполняет ---

@pytest.mark.parametrize("text", [
    # Лид #1516, отправлен 2026-09-20 письмом — дословно из описания.
    "Salary is $200k to 300k depending on experience. Open exclusively to "
    "Pakistani candidates.",
    "Candidates must be authorized to work in the United States without visa "
    "sponsorship.",
    "You must be legally authorized to work in the UK.",
    "This role requires an active security clearance.",
    "Must be a U.S. citizen.",
    "Remote (US only).",
    "US-based candidates only.",
    "Applicants must be based in the EU.",
    "We are only considering candidates located in Canada.",
    "Must be located in the US or Canada.",
    # Wellfound: список стран найма без Казахстана и спонсорства нет.
    "Hires remotely in United States, Canada\nVisa sponsorship: Not Available",
    "Удалённая работа, только для граждан РФ.",
    "Требуется гражданство РФ.",
    "Работа только из России.",
])
def test_an_explicit_requirement_the_candidate_does_not_meet_blocks(text):
    assert _blocked(text)


def test_onsite_abroad_without_sponsorship_blocks():
    assert _blocked("We are unable to sponsor visas for this role.",
                    location="Berlin, Germany (On-site)")


def test_the_reason_names_the_requirement():
    """Причина уйдёт в «Заметку» — человек должен увидеть, что именно помешало."""
    v = check_eligibility("Open exclusively to Pakistani candidates.",
                          home_country=HOME)
    assert v.blocking_reasons
    assert "pakistan" in v.blocking_reasons[0].lower()


# --- то, что блокировать нельзя ---

@pytest.mark.parametrize("text", [
    "",
    # Удалёнка из любой страны: виза не нужна вовсе.
    "Fully remote, work from anywhere. We do not offer visa sponsorship.",
    # Работодатель сам предлагает визу — релокация возможна.
    "Visa sponsorship and relocation support available. Office in Berlin.",
    "Must be authorized to work in Kazakhstan.",
    "Удалённо, только резиденты РК.",
    # Лид #1018 — «вне РФ» это не «из РФ».
    "Удаленный формат работы (вне РФ, часовой пояс EET, Кипр).",
    # Не место, а формат работы.
    "You must be able to work in a fast-paced environment.",
    "Must be based in the office three days a week.",
    # Список, где есть регион кандидата.
    "Must be based in Europe or Central Asia.",
    # Мягкое пожелание — не требование.
    "Candidates based in the EU are preferred.",
    # Страна названа, но про визу и право на работу ни слова.
    "Senior Python Developer. Location: Germany, hybrid.",
])
def test_what_is_not_an_explicit_blocker_passes(text):
    assert not _blocked(text)


def test_a_country_in_the_location_alone_does_not_block():
    """Без слов про визу страна в локации — не приговор: релокация со
    спонсорством остаётся возможной (кандидат к ней готов)."""
    assert not _blocked("Python developer", location="Berlin, Germany (On-site)")


def test_a_negated_offer_is_not_an_offer():
    """«We do not offer visa sponsorship» содержит «offer visa sponsorship» —
    за предложение визы это считать нельзя."""
    assert _blocked("We do not offer visa sponsorship.",
                    location="Amsterdam, Netherlands (Hybrid)")


def test_remote_anywhere_without_sponsorship_is_a_warning_not_a_block():
    v = check_eligibility("Remote, worldwide. No visa sponsorship.",
                          home_country=HOME)
    assert v.eligible
    assert v.warnings


# --- длинный список стран Wellfound ---
#
# Живьём 2026-09-24: «Hires remotely in: Atlanta, Georgia • Austin, Texas •
# Australia • Baltimore, Maryland • …» — список идёт по алфавиту и длиннее окна
# в 70 символов. Страна кандидата, стоящая дальше в списке, окном не видна, и
# выполнимое требование читалось как невыполнимое.
_LONG_LIST = ("Hires remotely in: Atlanta, Georgia • Austin, Texas • Australia • "
              "Baltimore, Maryland • Boston, Massachusetts • California • Chicago, "
              "Illinois • Denver, Colorado • {extra}Toronto, Canada, Remote work "
              "policy, Remote only")


def test_the_home_country_late_in_a_long_hiring_list_is_seen():
    assert not _blocked(_LONG_LIST.format(extra="Kazakhstan • "))


def test_worldwide_late_in_a_long_hiring_list_is_seen():
    assert not _blocked(_LONG_LIST.format(extra="Worldwide • "))


def test_a_long_hiring_list_without_the_home_country_still_blocks():
    assert _blocked(_LONG_LIST.format(extra=""))


def test_the_hiring_list_ends_at_the_next_field():
    """Поля карточки Wellfound идут одной строкой через запятую: страны после
    «Remote work policy» списку найма уже не принадлежат."""
    text = ("Hires remotely in: United States, Remote work policy, Remote only, "
            "Company offices: Kazakhstan")
    assert _blocked(text)


# --- «only» про льготы, а не про найм ---

def test_benefits_for_us_candidates_only_is_not_a_hiring_restriction():
    """Живьём 2026-09-24 (Remotive, «Frontend Web Application Developer»): раздел
    льгот «Full Time Employee Benefits (U.S. candidates only): Health &
    Dental…» прочитан как «нанимаем только из США», и вакансия ушла в отказники
    без оценки. Льготы только для американцев — это не запрет нанимать
    остальных."""
    text = ("Full Time Employee Benefits (U.S. candidates only) : Health & Dental "
            "insurance, 401(k) match, paid time off.")
    assert not _blocked(text)


def test_a_real_restriction_next_to_a_benefits_section_still_blocks():
    text = ("Benefits: health insurance, PTO.\n"
            "This role is open to US-based candidates only.")
    assert _blocked(text)

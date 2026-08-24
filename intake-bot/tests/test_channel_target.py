"""Канал/группа — не адресат: писать туда нельзя, значит и брать в контакт нельзя.

Живой замер 2026-08-24 по таблице: шесть лидов (#73, #87, #379–#382) целились в
телеграм-КАНАЛ, и все шесть упали одинаково — «You can't write in this chat».
Пять из них принесла подпись самого агрегатора («IT Jobs в Telegram | VK | Max»
со ссылкой https://t.me/devs_it), которая стоит В КОНЦЕ поста, но выигрывает у
почты работодателя, потому что telegram — первое правило, а email третье.

Форма поста не даёт отличить канал от человека: и «@simbirsoft_dev», и
«@ivan_hr» — одинаково законные телеграм-ники. Отличить может только сам
Telegram, поэтому вопрос задаётся наружу (`telegram_writable`), а правило
остаётся чистым: без оракула поведение ровно прежнее.
"""
import pytest

from app.domain.contact import Contact, detect_contact

SIMBIRSOFT = """#intern #удаленка

SimbirSoft
React-разработчик (стажировка)

Контакты: hr@simbirsoft.com / Telegram @simbirsoft_dev

IT Jobs  в Telegram | в VK | в Max
https://t.me/devs_it
https://vk.com/job_for_programmers
https://max.ru/devs_it"""

# Лид #87: две ссылки на каналы подряд, почта работодателя — выше по тексту.
MIND_SOFTWARE = """Junior Golang Developer
Резюме направлять с темой "MIND: Молодой специалист"
Контакты:hr@mindsw.io

🔥 Подписаться на наши каналы / @best_itjob / @it_rab"""

CHANNELS = {"https://t.me/devs_it", "@simbirsoft_dev", "@best_itjob", "@it_rab"}


def only_people(target: str):
    """Оракул как у живого Telegram: канал — False, человек — True."""
    return target not in CHANNELS


def test_channel_in_footer_loses_to_employer_email():
    assert detect_contact(SIMBIRSOFT, telegram_writable=only_people) == Contact(
        "email", "hr@simbirsoft.com")


def test_every_channel_handle_is_skipped_not_just_the_first():
    assert detect_contact(MIND_SOFTWARE, telegram_writable=only_people) == Contact(
        "email", "hr@mindsw.io")


def test_person_still_beats_email():
    c = detect_contact("Резюме @ivan_hr или на boss@company.com",
                       telegram_writable=only_people)
    assert c == Contact("telegram", "@ivan_hr")


def test_person_after_channel_wins():
    c = detect_contact("Подписка @best_itjob, резюме шли @ivan_hr",
                       telegram_writable=only_people)
    assert c == Contact("telegram", "@ivan_hr")


def test_without_oracle_behaviour_is_unchanged():
    """Правило остаётся чистым: не спросили — не догадываемся."""
    assert detect_contact(SIMBIRSOFT) == Contact("telegram", "https://t.me/devs_it")


def test_unknown_target_is_accepted():
    """Bot API отвечает «chat not found» и человеку, и несуществующему нику —
    отличить их нельзя, поэтому неизвестность трактуется в пользу лида."""
    c = detect_contact("Пиши @ivan_hr", telegram_writable=lambda t: None)
    assert c == Contact("telegram", "@ivan_hr")


def test_oracle_failure_does_not_lose_the_lead():
    """Telegram недоступен — это не повод потерять контакт."""
    def broken(target):
        raise RuntimeError("api down")

    c = detect_contact("Пиши @ivan_hr", telegram_writable=broken)
    assert c == Contact("telegram", "@ivan_hr")


def test_oracle_is_not_asked_about_other_platforms():
    asked = []

    def spy(target):
        asked.append(target)
        return True

    detect_contact("Резюме на hr@acme.io", telegram_writable=spy)
    assert asked == []


def test_only_channels_and_no_other_contact_means_no_contact():
    """Лид #73: кроме канала в посте нет ничего. Честнее ответить «не нашёл»,
    чем записать адрес, в который заведомо нельзя писать."""
    assert detect_contact("Больше вакансий в Python: @forpython",
                          telegram_writable=lambda t: False) is None


# --- ник с кириллической буквой внутри ---------------------------------------
# Лид #289 упал так: «Nobody is using this username, or the username is
# unacceptable. If the latter, it must match r"[a-zA-Z][\w\d]{3,30}[a-zA-Z\d]"».
# Telegram сам назвал спецификацию — ник только ASCII. В посте стояло
# «надсилайте в особисті @andrеinikolenko» с кириллической «е» внутри, а двумя
# строками ниже — «Контакт: @andreinikolenko» латиницей, настоящий. `_HANDLE_RE`
# ловит `\w`, который в Python матчит и кириллицу, поэтому побеждала подделка.
#
# Отказ, а НЕ обрезка до ASCII-головы: у #289 голова — «andr», это чужой живой
# ник. Та же причина, по которой «@maria.hr» не превращается в «@maria».

def test_handle_with_a_cyrillic_letter_inside_is_refused():
    assert detect_contact("надсилайте @andrеinikolenko") is None


def test_the_real_latin_handle_after_it_wins():
    text = "надсилайте в особисті @andrеinikolenko\n———\nКонтакт: @andreinikolenko"
    assert detect_contact(text) == Contact("telegram", "@andreinikolenko")


def test_a_fully_cyrillic_handle_is_refused():
    assert detect_contact("пиши @Иван_Петров") is None


def test_an_ascii_handle_glued_to_cyrillic_prose_is_not_truncated():
    """«@ivan_hrПиши» — не «@ivan_hr»: обрезка выдумывает адресата."""
    assert detect_contact("пиши @ivan_hrПиши в личку") is None

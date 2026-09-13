"""Что говорит страница после «Submit»: код из письма и подтверждение словами.

Живьём 2026-09-13, прогон с 65 лидами.

Greenhouse (лид #1177, SumUp). После отправки форма осталась на месте, а внизу:
«A verification code was sent to …@gmail.com. To submit your application, enter
the 8-character code to confirm you're a human. Security code». Это проверка, что
за браузером человек: код приходит на почту владельца, и доставать его оттуда
автоматически — значит обходить её. Отчёт же говорил «ВОЗМОЖНО, ЗАЯВКА УЖЕ УШЛА»,
хотя точно известно, что не ушла и что нужно сделать.

Recruitee (лиды #1156, #1160). Успех там объявляется «All done! Your application
has been successfully submitted!», а шаблон знал «application submitted» подряд —
«has been successfully» между словами ломало совпадение. В тех двух дампах фраза
лежала в словаре переводов, а не на экране, поэтому их исход по-прежнему
неизвестен; но видимое сообщение обязано засчитываться.
"""
from app.infrastructure.channels.external_apply import _SUBMITTED_RE, asks_for_emailed_code

GREENHOUSE = ("Please review our Privacy Notice before submitting your application. Confirm "
              "A verification code was sent to someone@gmail.com. To submit your application, "
              "enter the 8-character code to confirm you're a human. Security code Submit application")


def test_the_emailed_code_prompt_is_recognised():
    assert asks_for_emailed_code(GREENHOUSE)


def test_an_ordinary_form_is_not_mistaken_for_it():
    assert not asks_for_emailed_code("Full name * Email * Phone * Resume/CV Submit application")
    assert not asks_for_emailed_code("We will send you a confirmation email after you apply.")


def test_a_visible_success_message_counts_as_submitted():
    assert _SUBMITTED_RE.search("All done! Your application has been successfully submitted!")

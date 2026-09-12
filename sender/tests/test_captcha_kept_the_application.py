"""Невидимая капча не пропустила отправку — сказать это, а не «возможно, ушла».

Живьём 2026-09-12, три отклика на формы Ashby (Polymath, Basis Research,
Blacksmith Agency). Анкета заполнена целиком, резюме приложено, обязательный
«Do you require visa sponsorship?*» отвечен («No» подсвечен на снимке),
«Submit Application» нажата — и пятнадцать секунд ожидания не принесли ни
подтверждения, ни перехода, ни ошибки. Замер сохранённой страницы:

    рамок recaptcha на экране: 256x60  (бейдж невидимой reCAPTCHA)
    textarea[name^=g-recaptcha]: 1     токенов в них: 0

Пустой токен при оставшейся на экране форме значит, что отправку не приняли:
площадка требует доказательства, что за браузером человек. Обходить это
нечем и не нужно — заявку подаёт человек.

Чинится здесь не отправка, а ОТЧЁТ. Он говорил «ВОЗМОЖНО, ЗАЯВКА УЖЕ УШЛА,
проверь почту прежде чем откликаться повторно»: неправда дважды — посылает
искать письмо, которого не будет, и отговаривает подать руками, то есть лид
тихо умирает. Вместо этого надо назвать причину.

Осторожность: «не знаю» в этой ветке появилось не зря — на Ashby бывало, что
подтверждения нет, а заявка ушла (лиды 119, 127, 128, 129). Поэтому причина
называется ТОЛЬКО при совпадении двух признаков: форма осталась на экране И
токен капчи пуст. Одного пустого токена мало: на многих формах капча
выполняется лишь в момент отправки и поле пустует всегда.
"""
import pytest

from app.infrastructure.channels.external_apply import captcha_held_the_form


class _Loc:
    def __init__(self, n): self._n = n
    def count(self): return self._n


class _Page:
    """Ровно то, что спрашивает проверка: поля капчи и наличие формы."""
    def __init__(self, token="", boxes=1, fields=1):
        self._token, self._boxes, self._fields = token, boxes, fields

    def evaluate(self, js, *a):
        if "g-recaptcha" in js or "captcha" in js.lower():
            return {"boxes": self._boxes, "tokens": 1 if self._token else 0}
        return None

    def locator(self, sel):
        return _Loc(self._fields)


def test_empty_token_on_a_form_still_standing_is_named():
    assert captcha_held_the_form(_Page(token="", boxes=1, fields=3))


def test_a_solved_captcha_is_not_blamed():
    """Токен есть — отправку задержало что-то другое, и врать про капчу нельзя."""
    assert not captcha_held_the_form(_Page(token="03AFcW…", boxes=1, fields=3))


def test_no_captcha_at_all_is_not_blamed():
    assert not captcha_held_the_form(_Page(token="", boxes=0, fields=3))


def test_a_form_that_is_gone_is_not_blamed():
    """Форма исчезла — заявка, похоже, ушла; пустой токен тут ничего не значит."""
    assert not captcha_held_the_form(_Page(token="", boxes=1, fields=0))


def test_a_page_that_cannot_be_asked_says_no():
    """Диагностика не имеет права ронять отклик или выдумывать причину."""
    class _Broken:
        def evaluate(self, *a, **k): raise RuntimeError("страница закрыта")
        def locator(self, *a, **k): raise RuntimeError("страница закрыта")
    assert not captcha_held_the_form(_Broken())

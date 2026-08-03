"""Живая ли сессия RemoteOK. Чистая логика, без похода в сеть.

Файл сессии, сохранённый до того, как вход завершён, выглядит точно так же,
как рабочий — и ломается позже, на отклике: RemoteOK уводит гостя с кнопки
Apply на /sign-up?user_type=worker вместо формы работодателя. Так что судить
надо по странице, а не по наличию файла (та же ловушка, что у LinkedIn и
Threads, см. infrastructure/linkedin_session.py).

Признак снят с живой страницы 2026-08-03: у разлогиненного в шапке
remoteok.com стоят href="/login" и href="/sign-up" (по 3 вхождения каждый),
а href="/logout" не встречается ни разу.
"""
import re

_LOGOUT = re.compile(r'href="/log-?out', re.I)
_LOGIN = re.compile(r'href="/login', re.I)

# Ниже этого страница не похожа на remoteok.com: пустой ответ, таймаут или
# страница ошибки. Судить по ней нельзя, а «не знаю» здесь обязано означать
# «не залогинен» — иначе мы сохраним сессию гостя и узнаем об этом на отклике.
_MIN_PAGE_CHARS = 500


def is_logged_in(page_html) -> bool:
    html = str(page_html or "")
    if len(html) < _MIN_PAGE_CHARS:
        return False
    if _LOGOUT.search(html):
        return True
    return not _LOGIN.search(html)

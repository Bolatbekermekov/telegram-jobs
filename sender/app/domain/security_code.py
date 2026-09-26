"""Код подтверждения из письма ATS «Security code for your application to X». Чистая логика.

Форма письма снята с живых писем Greenhouse 2026-09-24/26 (DoiT, Nakisa, Stripe,
DoorDash India): тело только в HTML, код — отдельной строкой сразу после «Copy
and paste this code into the security code field on your application:», 8 знаков,
буквы и цифры в любом регистре.
"""
import html
import re

# Код берётся ТОЛЬКО сразу за инструкцией: в подвале письма есть и другие
# «слова» из 8 знаков (адрес, «Greenhou…»), и угадывать среди них нельзя.
_AFTER_INSTRUCTION = re.compile(
    r"security\s+code\s+field[^:]{0,60}:\s*([A-Za-z0-9]{6,12})(?![A-Za-z0-9])", re.I)


def _text(body: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", body or "")
    return html.unescape(no_tags)


def extract_security_code(body: str) -> str:
    """Код из тела письма (HTML или текст), или "" — если письмо не о коде."""
    m = _AFTER_INSTRUCTION.search(_text(body))
    return m.group(1) if m else ""

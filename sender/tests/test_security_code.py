"""Код из письма Greenhouse «Security code for your application to X».

Форма письма снята с живых писем 2026-09-24/26 (DoiT, Nakisa, Stripe, DoorDash
India): тело только в HTML, код — отдельной строкой сразу после «Copy and paste
this code into the security code field on your application:». 8 знаков, буквы
и цифры в любом регистре (у DoorDash — одни буквы).
"""
from app.domain.security_code import extract_security_code

HTML = """<html><body><table><tr><td><p>Copy and paste this code into the security
code field on your application:</p><h1 style="letter-spacing:4px">Ab3dEf9h</h1>
<p>After you enter the code, resubmit your application.</p>
<p>&copy; 2026 Greenhouse<br>18 West 18th Street, 11th Floor, New York, NY 10011, USA</p>
</td></tr></table></body></html>"""


def test_the_code_after_the_instruction_is_found():
    assert extract_security_code(HTML) == "Ab3dEf9h"


def test_a_letters_only_code_is_found_too():
    assert extract_security_code(HTML.replace("Ab3dEf9h", "eVsmLxLU")) == "eVsmLxLU"


def test_the_address_and_footer_are_not_mistaken_for_a_code():
    body = HTML.replace("Ab3dEf9h", "")
    assert extract_security_code(body) == ""


def test_an_unrelated_email_has_no_code():
    assert extract_security_code("<p>Thank you for applying to Stripe!</p>") == ""

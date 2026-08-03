"""Сопроводительное письмо файлом: сборка LaTeX из текста письма.

Текстовое поле cover letter модель заполняла и раньше. А вот поле-ЗАГРУЗКА
(«Cover letter», type=file) намеренно пропускалось: прикладывать туда CV нельзя,
а другого файла не было. На обязательном поле это значит `manual` — заявка
парковалась, уже потратив генерацию письма и браузер.

Письмо у нас уже написано под вакансию; не хватало только PDF.
"""
from app.domain.cover_letter_tex import build_tex, escape_tex


def test_the_letter_text_ends_up_in_the_document():
    tex = build_tex("Здравствуйте! Меня заинтересовала ваша вакансия.")
    assert "Меня заинтересовала ваша вакансию." not in tex   # не искажаем
    assert "Меня заинтересовала ваша вакансия." in tex


def test_latex_specials_cannot_break_the_build():
    """Текст пишет модель по чужой вакансии: «C# & R&D, 50% remote_work»
    уронил бы сборку целиком, а с ней и отклик."""
    tex = build_tex("C# & R&D, 50% remote_work #1 {brace} $money$")
    for raw, escaped in [("&", r"\&"), ("%", r"\%"), ("_", r"\_"),
                         ("#", r"\#"), ("$", r"\$")]:
        assert escaped in tex, raw


def test_a_backslash_does_not_become_a_command():
    assert r"\textbackslash" in escape_tex(r"path\to\file")


def test_blank_lines_stay_paragraph_breaks():
    tex = build_tex("Первый абзац.\n\nВторой абзац.")
    assert "Первый абзац." in tex and "Второй абзац." in tex
    assert tex.count(r"\par") >= 1 or "\n\n" in tex


def test_cyrillic_needs_a_font_that_has_it():
    """Письмо может быть и русским. Собирает tectonic, то есть XeTeX, поэтому
    подход pdfTeX (T2A + inputenc) не годится — на нём сборка падает с
    «Font T2A/cmr/m/n not loadable» (проверено живьём)."""
    tex = build_tex("Здравствуйте!")
    assert "fontspec" in tex
    assert "T2A" not in tex


def test_an_empty_letter_is_not_a_document():
    """Пустой PDF хуже отсутствующего: он выглядит как приложенное письмо."""
    assert build_tex("") == ""
    assert build_tex("   \n  ") == ""

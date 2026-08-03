"""Что за резюме реально ушло — записью в «Заметке», а не догадкой.

Резюме выбирается под роль вакансии (восемь вариантов), но в листе от этого не
оставалось ни следа: колонка «Заметка» у отправленных строк пустая, и понять
задним числом, какой из восьми PDF получил рекрутёр, было неоткуда.

Отдельный случай — каналы, которые вложений не поддерживают вовсе (Wellfound
принимает только текст, Threads тоже). Там `attachment_path` заполнен, но файл
не уходит, и запись «CV: …pdf» была бы прямой неправдой.
"""
from app.domain.sent_note import cv_note


def test_the_note_names_the_file_that_went_out():
    got = cv_note("/home/b/cv/backend-go/Bolatbek_Yermekov_Backend_Go.pdf",
                  supported=True, enabled=True)
    assert got == "CV: Bolatbek_Yermekov_Backend_Go.pdf"


def test_only_the_file_name_is_kept_not_the_whole_path():
    """Путь тянет за собой имя пользователя и структуру диска, а лист общий."""
    got = cv_note("/Users/bolatbek/telegram-jobs/sender/cv/qa/Bolatbek_QA.pdf",
                  supported=True, enabled=True)
    assert "/" not in got and "bolatbek" not in got.lower().replace("bolatbek_qa", "")


def test_a_channel_without_attachments_says_so():
    """Wellfound принимает только текст. Написать «CV: …pdf» значило бы
    утверждать, что файл ушёл, — а он не уходил."""
    got = cv_note("/cv/qa/Bolatbek_QA.pdf", supported=False, enabled=True)
    assert "без CV" in got
    assert "Bolatbek_QA.pdf" not in got


def test_attachments_turned_off_is_a_different_reason():
    got = cv_note("/cv/qa/Bolatbek_QA.pdf", supported=True, enabled=False)
    assert "без CV" in got
    assert "ATTACH_CV" in got


def test_no_file_chosen_at_all():
    for path in ("", None):
        assert "без CV" in cv_note(path, supported=True, enabled=True)

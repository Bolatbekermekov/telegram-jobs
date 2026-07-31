"""Что уходит в запрос на контакт, а что в сообщение принявшему.

Лиды 156/160/161/172/177/179 ушли ПРЯМЫМИ сообщениями людям, которые уже приняли
заявку, и каждое было обрезано на полумысли около 290 символов: канал нёс один
`body_limit = 300`, рассчитанный на записку к приглашению. Записка и письмо это
два разных текста с двумя разными пределами, поэтому теперь они и едут отдельно.
"""
import pytest

from app.domain.channel import InvitePendingError, OutreachContent
from app.infrastructure.channels.linkedin import (
    SEL_INVITE_SEND,
    SEL_MENU_CONNECT,
    SEL_MORE_BTN,
    SEL_NOTE_BOX,
    SEL_PERSONALIZE,
    LinkedInChannel,
    _NOTE_LIMIT,
    _invite_note,
    message_or_connect,
)
from tests.test_linkedin_channel import _FakePage


def test_the_message_path_is_not_capped_at_note_length():
    """Принявшему контакту уходит письмо целиком; жёсткий предел только у записки."""
    assert LinkedInChannel.body_limit is None
    assert LinkedInChannel.note_limit == _NOTE_LIMIT


def test_the_note_comes_from_its_own_field():
    content = OutreachContent(body="Длинное письмо на несколько абзацев.",
                              note="Здравствуйте! Пишу по вакансии Backend.")
    assert _invite_note(content) == "Здравствуйте! Пишу по вакансии Backend."


def test_without_a_note_the_letter_is_shortened_at_a_sentence():
    letter = "Здравствуйте. " + "Пишу по вакансии Backend в вашей команде. " * 12
    out = _invite_note(OutreachContent(body=letter))
    assert len(out) <= _NOTE_LIMIT
    assert out.endswith(".")


def test_an_overlong_note_is_shortened_not_sliced():
    note = "Здравствуйте. " + "Очень подробная записка про опыт и стек. " * 12
    out = _invite_note(OutreachContent(body="письмо", note=note))
    assert len(out) <= _NOTE_LIMIT
    assert out.endswith(".")


def test_message_or_connect_fills_the_note_not_the_letter():
    page = _FakePage({SEL_MORE_BTN: 1, SEL_MENU_CONNECT: 1, SEL_PERSONALIZE: 1,
                      SEL_NOTE_BOX: 1, SEL_INVITE_SEND: 1})
    content = OutreachContent(body="ПИСЬМО целиком, много текста.",
                              note="ЗАПИСКА для приглашения.")
    with pytest.raises(InvitePendingError):
        message_or_connect(page, "https://linkedin.com/in/x", content)

    filled = next(a[2] for a in page.actions
                  if a[0] == "fill" and a[1] == SEL_NOTE_BOX)
    assert filled == "ЗАПИСКА для приглашения."

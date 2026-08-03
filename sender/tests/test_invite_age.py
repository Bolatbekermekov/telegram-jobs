"""Когда пора перестать проверять запрос на контакт в LinkedIn.

Приглашение без ответа не двигается ничем: написать человеку нельзя, пока он
не примет, а примет он или нет — его дело. Каждый прогон открывает его профиль
заново, и без срока давности это навсегда: замер листа 2026-08-03 показал лид
#79, который проверялся с 17 июля, то есть 17 дней подряд.

Отдельный случай — приглашение без записанной даты отправки. Такие в листе есть
(все 7 `invited` на 2026-08-03), потому что `invited_plain` вызывал
`mark_status`, а он колонку «Дата отправки» не трогает. Возраст такого
приглашения неизвестен, и взять его неоткуда: разрыв между добавлением лида и
реальным контактом по 116 отправленным лидам — медиана 37 часов, p90 295 часов,
максимум 636. То есть «Дата добавления» заменой не работает.
"""
from datetime import datetime

from app.domain.invite_age import EXPIRED_NOTE_PREFIX, expired_note, invite_expired

NOW = datetime(2026, 8, 3, 12, 0)
WEEK = 7


def test_an_invite_sent_yesterday_still_waits():
    assert invite_expired(datetime(2026, 8, 2, 12, 0), NOW, WEEK) is False


def test_an_invite_one_hour_short_of_the_week_still_waits():
    """Граница считается по времени, а не по календарным дням: приглашение,
    отправленное 27 июля в 13:00, на 3 августа в 12:00 висит 6 дней 23 часа."""
    assert invite_expired(datetime(2026, 7, 27, 13, 0), NOW, WEEK) is False


def test_an_invite_exactly_a_week_old_is_done():
    assert invite_expired(datetime(2026, 7, 27, 12, 0), NOW, WEEK) is True


def test_an_older_invite_is_done():
    assert invite_expired(datetime(2026, 7, 17, 22, 29), NOW, WEEK) is True


def test_an_invite_without_a_date_is_done():
    """Возраст неизвестен и вычислить его не из чего — держать такую строку
    в проверке значит держать её вечно."""
    assert invite_expired(None, NOW, WEEK) is True


def test_the_window_is_a_parameter_not_a_constant():
    sent = datetime(2026, 8, 1, 12, 0)
    assert invite_expired(sent, NOW, 3) is False
    assert invite_expired(sent, NOW, 2) is True


# --- заметка для человека ----------------------------------------------------

def test_the_note_says_how_long_it_hung_and_since_when():
    note = expired_note(datetime(2026, 7, 17, 22, 29), NOW, WEEK)
    assert note.startswith(EXPIRED_NOTE_PREFIX)
    assert "16" in note                      # дней висело
    assert "2026-07-17" in note


def test_the_note_admits_when_the_date_is_missing():
    """Не выдумывать срок: у этих строк даты отправки нет, и заметка обязана
    сказать именно это, а не «висит 0 дней»."""
    note = expired_note(None, NOW, WEEK)
    assert note.startswith(EXPIRED_NOTE_PREFIX)
    assert "не записана" in note


def test_every_note_carries_the_prefix_history_keys_on():
    """`record_to_sent` узнаёт такую строку по префиксу и оставляет её в истории
    отправок — иначе адрес, которому мы уже писали, снова станет нетронутым."""
    for sent in (datetime(2026, 7, 1), None):
        assert expired_note(sent, NOW, WEEK).startswith(EXPIRED_NOTE_PREFIX)

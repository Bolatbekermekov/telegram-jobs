"""What happens when the sheet write fails on a message that is already sent.

Lead #148: the Telegram message was delivered, `mark_sent` met a Sheets 502, and
the traceback ended the run with the row still `new` — so the next run would have
messaged the same person a second time. The write is retried now, but retries can
still be exhausted, and this is what must happen then.
"""
from app.domain.lead import STATUS_SENT
from app.interface.cli import _record_sent


class _Lead:
    lead_id = "148"
    row = 149
    target = "@Maha_zhuss"


class _OkRepo:
    def __init__(self):
        self.calls = []

    def mark_sent(self, lead, body, status, note=""):
        self.calls.append((lead, body, status, note))


class _BrokenRepo:
    def mark_sent(self, lead, body, status, note=""):
        raise RuntimeError("APIError: [-1]: <!DOCTYPE html> 502")


def test_a_successful_write_reports_true():
    repo = _OkRepo()
    assert _record_sent(repo, _Lead(), "тело", "telegram") is True
    (_, body, status, _note), = repo.calls
    assert (body, status) == ("тело", STATUS_SENT)


def test_the_questions_the_model_answered_end_up_in_the_note():
    """Вопросы в формах отклика отвечает LLM, и её ответы нигде не сохранялись:
    заявка уходила, а чем мы представились работодателю — неизвестно."""
    from app.interface.cli import _sent_note

    class _Chan:
        supports_attachment = True

    class _Log:
        pairs = [("Years of experience", "3"), ("Salary expectations", "4000 EUR")]

    _Chan.answer_log = _Log()
    note = _sent_note(_Chan(), "/cv/qa/Bolatbek_QA.pdf", attach_enabled=True)

    assert "CV: Bolatbek_QA.pdf" in note
    assert "Years of experience" in note and "3" in note
    assert "Salary expectations" in note and "4000 EUR" in note


def test_the_log_is_cleared_before_each_lead():
    """Канал живёт между лидами одной платформы (ChannelSwitcher), поэтому без
    очистки ответы предыдущего лида приклеились бы к заметке следующего — и
    выглядели бы как вопросы, которых работодатель не задавал."""
    from app.application.answer_log import AnswerLog
    from app.interface.cli import _reset_answer_log

    class _Chan:
        answer_log = AnswerLog()

    ch = _Chan()
    ch.answer_log.pairs = [("Прошлый вопрос", "прошлый ответ")]
    _reset_answer_log(ch)
    assert ch.answer_log.pairs == []


def test_resetting_a_channel_without_a_log_is_harmless():
    from app.interface.cli import _reset_answer_log
    _reset_answer_log(object())          # telegram, email — вопросов не задают


def test_a_send_without_questions_keeps_the_note_short():
    from app.interface.cli import _sent_note

    class _Chan:
        supports_attachment = True

    assert _sent_note(_Chan(), "/cv/qa/x.pdf", attach_enabled=True) == "CV: x.pdf"


def test_the_cv_that_went_out_is_written_into_the_note():
    """Резюме выбирается под роль, но в листе от этого не оставалось следа —
    какой из восьми PDF получил рекрутёр, узнать было неоткуда."""
    repo = _OkRepo()
    _record_sent(repo, _Lead(), "тело", "telegram",
                 note="CV: Bolatbek_Yermekov_Backend_Go.pdf")
    (_, _, _, note), = repo.calls
    assert note == "CV: Bolatbek_Yermekov_Backend_Go.pdf"


def test_a_failed_write_does_not_raise():
    """Raising here is what killed the run and left the lead `new`."""
    assert _record_sent(_BrokenRepo(), _Lead(), "тело", "telegram") is False


def test_a_failed_write_names_the_row_and_the_duplicate_risk(capsys):
    _record_sent(_BrokenRepo(), _Lead(), "тело", "telegram")
    out = capsys.readouterr().out

    assert "#148" in out
    assert "@Maha_zhuss" in out
    assert "149" in out                      # the row to fix by hand
    assert STATUS_SENT in out
    assert "повторно" in out                 # says why it matters

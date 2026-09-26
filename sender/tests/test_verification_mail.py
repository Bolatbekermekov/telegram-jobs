"""Чтение кода Greenhouse из Gmail по IMAP — только новое письмо и только чтение.

Код живёт недолго, а в ящике лежат коды прошлых попыток к тем же компаниям
(DoiT, Stripe — 24.09). Берётся письмо, пришедшее ПОСЛЕ нажатия «Отправить»
(`since`), самое новое. Ящик открывается readonly: письма не помечаются
прочитанными и не трогаются.
"""
import email.utils
import imaplib

from app.infrastructure.verification_mail import GmailCodeReader

SINCE = 1790400000.0      # момент нажатия «Отправить»


def _raw(code, when):
    date = email.utils.formatdate(when)
    body = (f"<p>Copy and paste this code into the security code field on your "
            f"application:</p><h1>{code}</h1><p>After you enter the code, resubmit.</p>")
    return (f"From: Greenhouse <no-reply@us.greenhouse-mail.io>\r\n"
            f"Subject: Security code for your application to Stripe\r\nDate: {date}\r\n"
            f"Content-Type: text/html; charset=utf-8\r\n\r\n{body}").encode()


class _Imap:
    """Ящик: [(uid, код, время прихода)]. Считает вызовы и режим открытия."""

    def __init__(self, mails, box):
        self.mails, self.box = mails, box

    def login(self, user, password):
        self.box["login"] = (user, password)
        return "OK", [b""]

    def select(self, mailbox, readonly=False):
        self.box["readonly"] = readonly
        return "OK", [b"1"]

    def search(self, charset, *criteria):
        self.box["criteria"] = " ".join(criteria)
        return "OK", [b" ".join(str(i).encode() for i, _, _ in self.mails)]

    def fetch(self, uid, parts):
        for i, code, when in self.mails:
            if str(i).encode() == uid:
                internal = imaplib.Time2Internaldate(when).encode()
                return "OK", [(b"%d (INTERNALDATE %s BODY[] {1}" % (i, internal), _raw(code, when)), b")"]
        return "NO", []

    def logout(self):
        pass


def _reader(mails, box, clock):
    return GmailCodeReader("me@gmail.com", "app-pass",
                           connect=lambda: _Imap(mails, box),
                           now=lambda: clock[0], sleep=lambda s: clock.__setitem__(0, clock[0] + s))


def test_the_newest_code_sent_after_the_submit_is_taken():
    box, clock = {}, [SINCE + 5]
    mails = [(1, "OLDold11", SINCE - 3600), (2, "NEWnew22", SINCE + 20)]
    assert _reader(mails, box, clock).code_since(SINCE) == "NEWnew22"
    assert box["readonly"] is True, "ящик открывается только на чтение"


def test_an_old_code_from_a_previous_attempt_is_never_used():
    box, clock = {}, [SINCE + 5]
    reader = _reader([(1, "OLDold11", SINCE - 3600)], box, clock)
    assert reader.code_since(SINCE, timeout_s=30, poll_s=10) == ""


def test_it_waits_for_the_mail_to_arrive():
    box, clock = {}, [SINCE]
    mails = []

    class _Late(_Imap):
        def search(self, charset, *criteria):
            if clock[0] >= SINCE + 20 and not mails:
                mails.append((3, "LATEla33", SINCE + 18))
            return super().search(charset, *criteria)

    reader = GmailCodeReader("me@gmail.com", "app-pass", connect=lambda: _Late(mails, box),
                             now=lambda: clock[0],
                             sleep=lambda s: clock.__setitem__(0, clock[0] + s))
    assert reader.code_since(SINCE, timeout_s=120, poll_s=10) == "LATEla33"


def test_a_mailbox_failure_is_no_code_not_a_crash():
    def broken():
        raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")
    reader = GmailCodeReader("me@gmail.com", "bad", connect=broken,
                             now=lambda: SINCE, sleep=lambda s: None)
    assert reader.code_since(SINCE, timeout_s=0) == ""

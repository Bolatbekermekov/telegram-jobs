"""Email channel: sends a personal email with CV attached via SMTP (STARTTLS)."""
import mimetypes
import smtplib
from email.message import EmailMessage
from pathlib import Path

from app.domain.channel import ChannelError, OutreachContent


def build_email(content: OutreachContent, to_addr: str, from_addr: str,
                from_name: str) -> EmailMessage:
    if not content.subject:
        raise ChannelError("email requires a subject")
    msg = EmailMessage()
    msg["From"] = f"{from_name} <{from_addr}>"
    msg["To"] = to_addr
    msg["Subject"] = content.subject
    msg.set_content(content.body)
    if content.attachment_path:
        path = Path(content.attachment_path)
        ctype, _ = mimetypes.guess_type(path.name)
        maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
        msg.add_attachment(path.read_bytes(), maintype=maintype,
                           subtype=subtype, filename=path.name)
    return msg


class EmailChannel:
    name = "email"
    body_limit = None
    needs_subject = True

    def __init__(self, host: str, port: int, user: str, password: str,
                 from_name: str, smtp_factory=smtplib.SMTP):
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._from_name = from_name
        self._smtp_factory = smtp_factory  # injectable for tests

    def start(self) -> None:  # SMTP connects per-send; nothing to do here
        pass

    def stop(self) -> None:
        pass

    def send(self, target: str, content: OutreachContent) -> None:
        msg = build_email(content, to_addr=target.strip(),
                          from_addr=self._user, from_name=self._from_name)
        with self._smtp_factory(self._host, self._port) as smtp:
            smtp.starttls()
            smtp.login(self._user, self._password)
            smtp.send_message(msg)

"""Adapt one generated body to a channel's limits and subject requirement."""
import re

from app.domain.channel import OutreachContent


def _drop_signature_lines(body: str, labels) -> str:
    """Убрать из подписи строки-контакты площадки, с которой и так пишем.

    Подпись это фиксированный блок «Label: значение» (см. sender/signature.txt),
    и в письме, которое читают в LinkedIn с профиля отправителя, строка
    «LinkedIn: ссылка на этот же профиль» лишняя.

    Режем ТОЛЬКО строку, начинающуюся с метки и двоеточия. Слово «LinkedIn»
    внутри предложения это текст письма («нашёл вакансию в LinkedIn»), а не
    контакт, и его трогать нельзя.
    """
    if not labels:
        return body
    pattern = re.compile(
        r"^\s*(?:" + "|".join(re.escape(str(x)) for x in labels) + r")\s*:", re.I)
    kept = [line for line in body.splitlines() if not pattern.match(line)]
    return "\n".join(kept).rstrip()


def _truncate(body: str, limit: int) -> str:
    if len(body) <= limit:
        return body
    window = body[:limit]
    cut = window.rfind(" ")
    if cut > 0:
        return window[:cut].rstrip()
    return window


def format_for_channel(channel, body: str, subject: str | None,
                       attachment_path: str | None, note: str = "") -> OutreachContent:
    # Сначала выбрасываем лишние строки подписи, потом меряем длину: канал с
    # пределом должен считать его по тому тексту, который реально уйдёт.
    # Проверка по атрибуту, как и `note_limit`: канал, который о нём не знает,
    # ничего у себя не правит.
    out_body = _drop_signature_lines(body, getattr(channel, "signature_drop", ()))
    if channel.body_limit is not None:
        out_body = _truncate(out_body, channel.body_limit)
    out_subject = subject if channel.needs_subject else None
    # `note` не режется здесь: её предел принадлежит каналу, а не письму, и канал
    # применяет его сам (см. LinkedInChannel.note_limit).
    return OutreachContent(body=out_body, subject=out_subject,
                           attachment_path=attachment_path, note=note)

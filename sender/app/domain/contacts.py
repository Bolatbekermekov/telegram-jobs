"""Один телеграм-ник и один LinkedIn на все площадки.

Контакты лежали в трёх местах и разошлись: в signature.txt был один ник, в
apply_profile.yml его переписали руками, а в CV, которое уходит модели, записан
третий вариант. В письмо попадал тот, который встретился по дороге, и в форму
отклика тоже — работодателю уезжал ник, по которому не отвечают, и ссылка на
чужой профиль. Проверить это глазами нельзя: письмо каждый раз новое.

Источник правды один — блок подписи (sender/signature.txt). Он и так
дописывается к каждому сообщению кодом, а не моделью, ровно для того, чтобы
ссылки в нём были верные. Отсюда контакты разбираются один раз и подменяют
собой ЛЮБОЙ другой ник и ЛЮБОЙ другой профиль в исходящем тексте, в полях формы
отклика и в ответах модели.

Замена сплошная, а не только в строках подписи, и это осознанно: исходящее
письмо адресовано работодателю, и телеграм-ник в нём может быть только нашим —
писать человеку его собственный контакт незачем (profile.md прямо запрещает
модели вставлять ссылки в тело письма). Поэтому любой найденный ник — это наш
ник, который откуда-то взялся неправильным, и его надо чинить, а не сохранять.
"""
import re
from dataclasses import dataclass

# Метки строк-контактов в подписи. Не «любое слово telegram», а именно начало
# строки с двоеточием: слово «LinkedIn» внутри предложения — это текст, а не
# контакт (та же логика, что в format_content._drop_signature_lines).
_TELEGRAM_LABEL_RE = re.compile(r"^\s*(?:telegram|tg|телеграм|телега)\s*:\s*(.+)$",
                                re.IGNORECASE)
_LINKEDIN_LABEL_RE = re.compile(r"^\s*linkedin\s*:\s*(.+)$", re.IGNORECASE)

# Ссылка на телеграм в любом виде: с протоколом и без, t.me и telegram.me.
_TME_LINK_RE = re.compile(
    r"(?P<pre>(?:https?://)?(?:www\.)?t(?:elegram)?\.me/(?:s/)?@?)"
    r"(?P<nick>[A-Za-z0-9_]{4,32})/?",
    re.IGNORECASE)
# Голый ник. Взгляд назад отсекает адреса почты (…50@gmail.com): там перед «@»
# стоит буква или цифра, а у ника — пробел, начало строки или знак препинания.
_HANDLE_RE = re.compile(r"(?<![\w./@-])@([A-Za-z0-9_]{4,32})\b")
# Профиль LinkedIn. Только /in/ — /jobs/ и /company/ это ссылки на вакансию и
# на работодателя, они к контактам отправителя отношения не имеют.
_LINKEDIN_URL_RE = re.compile(
    r"(?:https?://)?(?:[A-Za-z0-9-]+\.)*linkedin\.com/in/[A-Za-z0-9%\-_.]+/?",
    re.IGNORECASE)


@dataclass(frozen=True)
class Contacts:
    """Контакты отправителя в каноническом виде: '@nick' и полный https-адрес."""
    telegram: str = ""
    linkedin: str = ""

    def __bool__(self) -> bool:
        return bool(self.telegram or self.linkedin)


def normalize_handle(value) -> str:
    """'nick', '@nick', 't.me/nick', 'https://t.me/nick' -> '@nick'."""
    text = str(value or "").strip()
    if not text:
        return ""
    m = _TME_LINK_RE.search(text)
    if m:
        return "@" + m.group("nick")
    m = re.search(r"@?([A-Za-z0-9_]{4,32})", text)
    return "@" + m.group(1) if m else ""


def normalize_linkedin(value) -> str:
    """Ссылка на профиль с протоколом; мусор и не-профили отбрасываются."""
    text = str(value or "").strip()
    m = _LINKEDIN_URL_RE.search(text)
    if not m:
        return ""
    url = m.group(0)
    return url if url.lower().startswith("http") else f"https://{url}"


def parse_contacts(signature_text) -> Contacts:
    """Разобрать блок подписи в контакты.

    Отсутствующая строка даёт пустое значение, а пустое значение отключает
    подмену этого вида контакта: лучше оставить текст как есть, чем стереть
    ник ради «канона», которого нам никто не задал.
    """
    telegram = linkedin = ""
    for line in str(signature_text or "").splitlines():
        m = _TELEGRAM_LABEL_RE.match(line)
        if m and not telegram:
            telegram = normalize_handle(m.group(1))
            continue
        m = _LINKEDIN_LABEL_RE.match(line)
        if m and not linkedin:
            linkedin = normalize_linkedin(m.group(1))
    return Contacts(telegram=telegram, linkedin=linkedin)


def canonicalize(text, contacts: Contacts) -> str:
    """Заменить в тексте любой телеграм-ник и любой профиль LinkedIn на наши.

    Форма записи сохраняется: ссылка остаётся ссылкой (t.me/новый_ник), ник
    остаётся ником (@новый_ник). Иначе строка подписи «Telegram: @nick»
    превратилась бы в ссылку, а «пиши в t.me/nick» — в голый ник.
    """
    out = str(text or "")
    if not out or not contacts:
        return out
    if contacts.telegram:
        nick = contacts.telegram.lstrip("@")
        out = _TME_LINK_RE.sub(lambda m: m.group("pre") + nick, out)
        out = _HANDLE_RE.sub(lambda m: f"@{nick}", out)
    if contacts.linkedin:
        out = _LINKEDIN_URL_RE.sub(lambda m: contacts.linkedin, out)
    return out

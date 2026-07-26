"""The model as a FALLBACK contact detector: prompt building and answer vetting.

`contact.py` states the project's rule: platform detection is deterministic on
purpose, because it decides where a message is later sent. That rule is not
repealed here, it is narrowed — and this module is where the narrowing is
enforced:

  1. Rules decide first. This is reached only when `detect_contact` returned
     None, so every pre-existing lead keeps its deterministic path.
  2. Threads only. The caller is `resolve_threads_lead`; intake, hh, LinkedIn
     and wellfound never touch it.
  3. The model's answer is vetted, not trusted. `parse_contact_response` drops
     anything doubtful, and the load-bearing check is the fourth one: the target
     must actually occur in the thread, so an invented handle cannot become a
     recipient.

What made this necessary is a live post: its author typed "Telegram: @
skyluckwalker", with a space, and Threads stores it that way (its own payload
has linkified_in_app_url: null). No reader-side fix exists and a blanket `@\\s+`
rule was tried and reverted — it fabricates "@acme" out of "hr @ acme.com".

Scope of the anti-invention check, stated so it is not over-trusted: it defends
against the model inventing a contact that is not in the text. It does NOT
defend against contaminated text — a stranger's handle absorbed into the
author's block would BE in the source. That is why block scoping in
`threads_thread.py` is a safety property, not a formatting one.

The occurrence check compares the WHOLE target against the text, and it must stay
that way. It therefore rejects «почта name собака domain.ru», one of the sloppy
forms this fallback was partly meant to catch — that is an accepted cost, not an
oversight. Relaxing it to "each part occurs somewhere in the text" would gut the
guard: in a post of any length almost any plausible address can be assembled from
fragments, so a thread mentioning hr@acme.com and info@other.com would validate a
fabricated hr@other.com. A missed contact degrades to a DM to the author; a
fabricated one reaches a stranger.

Pure: no network, no client. The OpenAI call lives in
`infrastructure/openai_contact.py`.
"""
import json
import re

from app.domain.contact import Contact, canonical_hh_url

_CONTACT_SYSTEM = (
    "Ты извлекаешь контакт для отклика из текста поста Threads. "
    "Верни ТОЛЬКО JSON: "
    "{\"platform\": \"telegram|email|linkedin|hh|wellfound\", \"target\": \"<контакт>\"}. "
    "Если контакта для отклика в тексте нет — верни {\"platform\": null}. "
    "Ник телеграма верни как @nick, почту как name@domain.tld, остальное — ссылкой. "
    "Автор часто пишет контакт неаккуратно: «Telegram: @ nick», «телега nick», "
    "«почта name собака domain.ru» — такое распознавай. "
    "НЕ ВЫДУМЫВАЙ: собирай target только из того, что есть в тексте, "
    "не достраивай почту по названию компании и не угадывай ник. "
    "Имя автора поста в Threads — это НЕ ник в телеграме."
)

# Platforms build_channel can serve. Anything else would blow up the send loop.
# `threads` is absent on purpose: it is the fallback the resolver chooses itself
# when nothing was found, never a contact the model gets to "find".
_PLATFORMS = {"telegram", "email", "linkedin", "hh", "wellfound"}

_TG_HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{5,32}$")
_HH_HOST = r"(?:[\w.-]*\.)?hh\.(?:ru|kz|uz|by|kg|az|tj)"
# Shape per platform, anchored: "пиши в тг" must not pass as a Telegram target,
# and a URL must be on the host it claims — otherwise `linkedin` + evil.com would
# hand a browser channel an arbitrary page.
_SHAPES = {
    "email": re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]+$"),
    "linkedin": re.compile(r"^(?:https?://)?(?:[\w-]+\.)?linkedin\.com/\S+$", re.IGNORECASE),
    "hh": re.compile(rf"^(?:https?://)?{_HH_HOST}/\S+$", re.IGNORECASE),
    "wellfound": re.compile(
        r"^(?:https?://)?(?:www\.)?(?:wellfound\.com|angel\.co)/\S+$", re.IGNORECASE),
}

_TRAILING = ".,);]>\"'"
# Scheme, www., spaces and at-signs are noise for the occurrence check: the whole
# point is that "Telegram: @ skyluckwalker" and "@skyluckwalker" are the same
# thing, and that "hh.ru/vacancy/1" matches "https://hh.ru/vacancy/1".
_NOISE_RE = re.compile(r"https?://|www\.|[\s@]+", re.IGNORECASE)


def _squash(text: str) -> str:
    return _NOISE_RE.sub("", (text or "").lower())


def build_contact_prompt(thread_text: str) -> tuple[str, str]:
    """(system, user) for one thread. One call per lead, on the writing model."""
    user = f"=== ТЕКСТ ПОСТА ===\n{thread_text}\n\nВерни только JSON."
    return _CONTACT_SYSTEM, user


def parse_contact_response(raw: str, source_text: str, author: str) -> Contact | None:
    """A vetted `Contact` from the model's answer, or None if anything is off.

    `source_text` is the rendered thread and `author` the '@handle' from the post
    URL. Five checks, all mandatory — see the module docstring for why the
    occurrence one carries the most weight.
    """
    try:
        m = re.search(r"\{.*\}", raw or "", re.DOTALL)
        data = json.loads(m.group(0)) if m else {}
    except Exception:  # noqa: BLE001 — malformed model output → no contact
        return None
    if not isinstance(data, dict):
        return None

    platform, target = data.get("platform"), data.get("target")
    if not isinstance(platform, str) or not isinstance(target, str):
        return None
    platform = platform.strip().lower()
    target = target.strip().rstrip(_TRAILING)
    if platform not in _PLATFORMS or not target:
        return None

    if platform == "telegram":
        nick = target.lstrip("@").strip()
        if not _TG_HANDLE_RE.match(nick):
            return None
        target = "@" + nick
    elif not _SHAPES[platform].match(target):
        return None

    # Anti-invention. Checked BEFORE canonicalisation, so a regional hh link is
    # compared against the text as written, not against its hh.ru rewrite.
    if _squash(target) not in _squash(source_text):
        return None

    # The author's Threads name is not a Telegram username: DMing it on Telegram
    # reaches whoever holds that name there — a different person.
    if platform == "telegram" and author:
        if target.lstrip("@").lower() == author.strip().lstrip("@").lower():
            return None

    if platform == "hh":
        # Same treatment the rules give it: the saved hh session is hh.ru-only.
        target = canonical_hh_url(target)
    return Contact(platform, target)

"""Load ApplyProfile from a YAML file (sender/apply_profile.yml)."""
from dataclasses import fields
from pathlib import Path

import yaml

from app.domain.apply_profile import ApplyProfile
from app.domain.contacts import Contacts, canonicalize

_STR_FIELDS = {f.name for f in fields(ApplyProfile)
               if f.type == "str" or f.name not in ("needs_visa_sponsorship",
                                                     "open_to_relocation", "custom_answers")}
_KNOWN = {f.name for f in fields(ApplyProfile)}


def load_apply_profile(path: str, contacts: Contacts | None = None) -> ApplyProfile:
    """Профиль для автозаполнения форм.

    `contacts` (из подписи) главнее файла: телеграм-ник и LinkedIn в YAML — это
    копия, сделанная руками, и она уже расходилась с подписью. Форма отклика и
    письмо должны называть работодателю ОДИН контакт, поэтому здесь копия
    молча приводится к источнику правды, а не спорит с ним.
    """
    contacts = contacts or Contacts()
    p = Path(path)
    if not p.exists():
        return _with_contacts(ApplyProfile(), contacts)
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    known = {k: v for k, v in data.items() if k in _KNOWN}
    # Coerce str fields: null -> "".
    for name in _STR_FIELDS:
        if name in known and known[name] is None:
            known[name] = ""
    raw_ca = known.get("custom_answers") or {}
    known["custom_answers"] = {
        str(k).lower(): ("" if v is None else str(v)) for k, v in raw_ca.items()
    }
    return _with_contacts(ApplyProfile(**known), contacts)


def _with_contacts(profile: ApplyProfile, contacts: Contacts) -> ApplyProfile:
    """Подставить канонические контакты в профиль и в готовые ответы.

    Пустой канон ничего не трогает: если строки нет в подписи, значит канона
    нам не задали, и стирать то, что человек написал в YAML, не за что.
    """
    if contacts.linkedin:
        profile.linkedin = contacts.linkedin
    if contacts.telegram:
        profile.telegram = contacts.telegram
    profile.custom_answers = {k: canonicalize(v, contacts)
                              for k, v in profile.custom_answers.items()}
    return profile

"""Load ApplyProfile from a YAML file (sender/apply_profile.yml)."""
from dataclasses import fields
from pathlib import Path

import yaml

from app.domain.apply_profile import ApplyProfile

_STR_FIELDS = {f.name for f in fields(ApplyProfile)
               if f.type == "str" or f.name not in ("needs_visa_sponsorship",
                                                     "open_to_relocation", "custom_answers")}
_KNOWN = {f.name for f in fields(ApplyProfile)}


def load_apply_profile(path: str) -> ApplyProfile:
    p = Path(path)
    if not p.exists():
        return ApplyProfile()
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
    return ApplyProfile(**known)

"""Shared keyword matching for feed-style platforms (RemoteOK, Remotive).

Their public APIs return a fixed, all-category recent feed and ignore search /
category params, so we filter to relevant roles ourselves — on the TITLE, by
role word. Seniority words carry no role signal and are dropped; the AI scorer
does the precise relevance/level filtering on the full description afterwards.
"""
import re

_WORD_RE = re.compile(r"[a-z0-9+#]+")
# Seniority words carry no role signal — drop them so "junior backend developer"
# matches on its role words (backend / developer), not on the absent "junior".
_LEVEL_WORDS = {"junior", "jr", "intern", "internship", "senior", "sr",
                "mid", "entry", "level"}


def title_matches(title: str, keywords: list[str]) -> bool:
    """True when any role word of any keyword appears as a whole word in title."""
    title_words = set(_WORD_RE.findall((title or "").lower()))
    for kw in keywords:
        role_words = [w for w in _WORD_RE.findall(kw.lower())
                      if w not in _LEVEL_WORDS]
        if role_words and any(w in title_words for w in role_words):
            return True
    return False

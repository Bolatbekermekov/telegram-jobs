"""Re-capture the LinkedIn fixtures in this directory from the live site.

Run from the project root:

    sender/.venv/bin/python intake-bot/tests/fixtures/linkedin/capture.py

Captured 2026-08-13. Both fixtures are **verbatim byte prefixes of real HTTP
response bodies** — nothing distilled, hand-edited, or synthesised. What each is:

  post.html          A public post, fetched anonymously with the fetcher's browser
                     UA. Carries the post's WHOLE text in og:description, and that
                     text carries an `lnkd.in` link — the two live facts the post
                     reader and the shortener resolver are built on.
  lnkd_interstitial.html
                     What that `lnkd.in` link answers: not a 3xx, but HTTP 200 and
                     a small page whose only external <a> holds the real
                     destination. Kept whole (~5 KB).

Why this pair and not a hiring post: it is the mechanics that need pinning, and
this pair pins them end to end — full post text, an outbound link rewritten by
LinkedIn, and a `t.me` address recoverable from behind the rewrite. It is NOT a
vacancy, and its Telegram address is a bot rather than a recruiter, so it proves
nothing about summarising or about whom we would write to. Those live in unit
tests over the extracted text.

Truncation: post.html is the first _SLICE_BYTES (30 000) bytes of a ~128 KB
response, cut back to a UTF-8 character boundary. The asserts below check the
whole response first and the slice second, so "the og tag survived the cut" is
proven rather than assumed.

The asserts are the live-behaviour proof, not ceremony. If one fires, LinkedIn
changed how it serves these pages: stop and report it. Do not weaken an assert,
do not hand-edit a fixture, and do not fall back to synthetic markup.

Two failures that mean something specific:

* HTTP 404 on the post — the post was deleted. Every deleted post answers 404
  with the same ~320 KB generic shell for every User-Agent, including the social
  crawlers; anonymous post reading itself is fine (verified 2026-08-13 on live
  posts). Pick another live public post rather than concluding the feature broke.
* og:description missing while the status is 200 — the post is not public. Live,
  LinkedIn serves its generic members blurb in that case, which
  `_LI_POST_BOILERPLATE_RE` rejects on purpose.
"""
import html as _html
import pathlib
import re

import httpx

_HERE = pathlib.Path(__file__).parent
_SLICE_BYTES = 30_000

# The fetcher's own browser UA — the fixture must be what production receives.
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

_POST_URL = (
    "https://ru.linkedin.com/posts/evgeniy-evsyukov_telegram-"
    "%D0%B1%D0%BE%D1%82-%D0%BF%D0%BE%D0%B8%D1%81%D0%BA%D0%B0-it-"
    "%D0%B2%D0%B0%D0%BA%D0%B0%D0%BD%D1%81%D0%B8%D0%B9-%D0%B2%D1%81%D0%B5%D0%BC-"
    "activity-7091693103895449600-thjQ")

_OG_DESC_RE = re.compile(
    r'<meta[^>]+property="og:description"[^>]+content="([^"]*)"', re.IGNORECASE)
# The post's rendered body, used only here — to prove og:description is not a
# truncation of it. Production reads the meta tag, which keeps the line breaks
# this container's markup would cost us.
_COMMENTARY_RE = re.compile(
    r'data-test-id="main-feed-activity-card__commentary"[^>]*>(.*?)</p>', re.S)
_EXTERNAL_HREF_RE = re.compile(
    r'data-tracking-control-name="external_url_click"[^>]*href="([^"]+)"')


def _get(url: str) -> httpx.Response:
    return httpx.get(url, headers={"User-Agent": _UA}, timeout=30.0,
                     follow_redirects=True)


def _slice(body: bytes) -> bytes:
    """First _SLICE_BYTES bytes, cut back to a UTF-8 character boundary."""
    cut = body[:_SLICE_BYTES]
    while cut:
        try:
            cut.decode("utf-8")
        except UnicodeDecodeError:
            cut = cut[:-1]
            continue
        break
    return cut


def main() -> None:
    resp = _get(_POST_URL)
    assert resp.status_code == 200, (
        f"post answered {resp.status_code}; a 404 means this post was deleted — "
        "pick another live public post, see the module docstring")
    full = resp.text

    assert len(_OG_DESC_RE.findall(full)) == 1, (
        "expected exactly one og:description in the whole response; more than one "
        "means the extractor could pick a decoy")
    og = _html.unescape(_OG_DESC_RE.search(full).group(1))
    assert len(og) > 1000, f"og:description is only {len(og)} chars — pick a longer post"

    # The load-bearing claim of the whole feature: the meta tag is the FULL post,
    # not a preview of it. Measured 2026-08-13: og 1243 chars vs body 1232 (the
    # difference is the line breaks the tag keeps and the markup drops).
    body = _COMMENTARY_RE.search(full)
    assert body, "post body container not found — LinkedIn changed the post page"
    plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body.group(1))).strip()
    assert len(og) >= len(plain), (
        f"og:description ({len(og)}) is SHORTER than the rendered body "
        f"({len(plain)}) — LinkedIn now truncates it and the post reader must "
        "stop relying on the meta tag alone")

    # The reason resolve_lnkd_in exists: LinkedIn rewrites every outbound url in
    # post text, so a t.me link inside a post is invisible to contact detection.
    shortened = re.findall(r"https?://lnkd\.in/\S+", og)
    assert shortened, ("no lnkd.in link in the post text — this fixture also has to "
                       "demonstrate the rewrite, pick a post that links out")

    (_HERE / "post.html").write_bytes(_slice(resp.content))
    kept = _OG_DESC_RE.search((_HERE / "post.html").read_text(encoding="utf-8"))
    assert kept, "the 30 000-byte cut lost og:description — raise _SLICE_BYTES"

    interstitial = _get(shortened[0])
    assert interstitial.status_code == 200, (
        f"lnkd.in answered {interstitial.status_code}")
    assert not interstitial.history, (
        "lnkd.in now redirects (3xx) instead of serving an interstitial — "
        "resolve_lnkd_in can be replaced by following the redirect")
    dest = _EXTERNAL_HREF_RE.search(interstitial.text)
    assert dest, "no external_url_click href — LinkedIn changed the interstitial"
    assert dest.group(1).startswith("https://t.me/"), (
        f"destination is {dest.group(1)!r}, expected a t.me link: this fixture has "
        "to demonstrate a Telegram address recovered from behind the rewrite")
    (_HERE / "lnkd_interstitial.html").write_bytes(interstitial.content)

    print(f"post.html: {len(_slice(resp.content))} bytes of {len(resp.content)}; "
          f"og:description {len(og)} chars, body {len(plain)}")
    print(f"lnkd_interstitial.html: {len(interstitial.content)} bytes; "
          f"{shortened[0]} -> {dest.group(1)}")


if __name__ == "__main__":
    main()

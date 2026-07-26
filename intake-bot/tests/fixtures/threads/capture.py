"""Re-capture the Threads fixtures in this directory from the live site.

Run from the project root:

    sender/.venv/bin/python intake-bot/tests/fixtures/threads/capture.py

Captured 2026-07-26. Every fixture here is a **verbatim byte prefix of a real HTTP
response body** — nothing distilled, hand-edited, or synthesised. What each one is:

  post.html      /@lnkrnchk/post/DbL4LxBl6v9 fetched with a NON-browser User-Agent.
                 The only one of the three that carries og:* tags; its og:description
                 decodes to the 480-char root post. That tag sits at bytes ~2254-4815
                 of the response, so the truncation below keeps it whole.
  missing.html   A non-existent post id, non-browser UA. Comes back HTTP 200 with no
                 og tags at all — this is also how a deleted or private post looks.
  spa_shell.html The same real post fetched with a Chrome UA: a JS shell carrying no
                 og tags. This is the trap the whole Threads feature exists to avoid,
                 and the reason the fetcher must not send a browser UA to threads.com.

Truncation: each file is the first _SLICE_BYTES (30 000) bytes of the response, cut
back to a UTF-8 character boundary. The full responses are ~545 KB / ~259 KB / ~260 KB
and are mostly Meta's inline script payload — the first <script> lands at byte ~88-95 K
and </head> at ~104-116 K. 30 000 bytes keeps each response's real <head>, so the
extractor is exercised against a genuine document's worth of competing <meta>/<link>
tags, while holding all three fixtures to ~90 KB instead of ~1.1 MB.

One consequence worth knowing: the slices therefore contain no <script> payload. The
"no og tags" guarantee for missing.html and spa_shell.html is asserted below against
each FULL response, which is strictly stronger than asserting it against a slice — a
tag absent from the whole document cannot appear in a prefix of it. As measured on the
capture date, `og:description` occurs exactly once in the whole post response and zero
times in the whole missing and shell responses, so there is no og-shaped decoy hiding
in the script payload to defend against.

The asserts below are the live-behaviour proof, not ceremony. If one fires, Threads
changed how it serves these pages: stop and report it. Do not weaken an assert, do not
hand-edit a fixture, and do not fall back to synthetic markup.
"""
import codecs
import html as _html
import pathlib
import re
import urllib.request

OUT = pathlib.Path(__file__).parent
POST = "https://www.threads.com/@lnkrnchk/post/DbL4LxBl6v9"
MISSING = "https://www.threads.com/@lnkrnchk/post/ZZZZZZZZZZZ"
UA_BOT = "python-httpx/0.27.0"
UA_BROWSER = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
_SLICE_BYTES = 30_000
# The tag the extractor reads, and the one whose absence defines the other two cases.
_OG_DESC_RE = re.compile(
    r'<meta[^>]+property="og:description"[^>]+content="([^"]*)"', re.IGNORECASE)


def get(url, ua):
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read()


def slice_utf8(raw):
    """The first _SLICE_BYTES bytes of `raw`, backed off to a UTF-8 character
    boundary. Stays a verbatim prefix — a blind cut can split a multi-byte char and
    leave a file that no longer decodes."""
    text = codecs.getincrementaldecoder("utf-8")().decode(raw[:_SLICE_BYTES], final=False)
    out = text.encode("utf-8")
    assert raw.startswith(out), "slice is not a verbatim prefix of the response"
    return out


# A non-browser UA gets the server-rendered page that carries og:*.
raw = get(POST, UA_BOT).decode("utf-8", "replace")
metas = re.findall(
    r'<meta[^>]+(?:property|name)="(?:og:[a-z]+|description|twitter:description)"[^>]+>', raw)
assert metas, "og-тегов нет: Threads отдал скелет, проверь UA"
post = slice_utf8(get(POST, UA_BOT))
(OUT / "post.html").write_bytes(post)

# A deleted / non-existent post id: the page comes back 200 with NO og tags at all.
missing_raw = get(MISSING, UA_BOT)
assert not re.search(r'property="og:description"', missing_raw.decode("utf-8", "replace")), \
    "у отсутствующего поста появился og"
(OUT / "missing.html").write_bytes(slice_utf8(missing_raw))

# A browser UA gets a JS shell — the trap this whole feature has to avoid.
shell_raw = get(POST, UA_BROWSER)
assert not re.search(r'property="og:description"', shell_raw.decode("utf-8", "replace")), \
    "браузерный UA неожиданно отдал og"
(OUT / "spa_shell.html").write_bytes(slice_utf8(shell_raw))

# Truncating must not have changed what the fixtures prove: post.html still has to
# carry a whole og:description with the full 480-char root post, and the other two
# still have to carry none. Without this, a slice that clipped the tag would quietly
# turn every Threads test into a test of the empty string.
m = _OG_DESC_RE.search(post.decode("utf-8"))
assert m, "срез post.html потерял og:description — подними _SLICE_BYTES"
assert len(_html.unescape(m.group(1)).strip()) == 480, "текст поста в срезе изменился"
for name in ("missing.html", "spa_shell.html"):
    assert not _OG_DESC_RE.search((OUT / name).read_text(encoding="utf-8")), \
        f"в {name} появился og:description"

# The three fixtures must be genuinely different documents. They were once distilled
# down to the same 76-byte synthetic shell, which made two of the tests duplicates
# asserting nothing about the pages they claimed to cover.
blobs = {name: (OUT / name).read_bytes()
         for name in ("post.html", "missing.html", "spa_shell.html")}
assert len(set(blobs.values())) == 3, "фикстуры совпадают побайтово"

for f in sorted(OUT.glob("*.html")):
    print(f, f.stat().st_size, "bytes")

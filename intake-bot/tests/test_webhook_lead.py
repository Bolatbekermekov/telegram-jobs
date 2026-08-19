"""What the bot answers after saving a lead, and what the use case is wired with."""
import asyncio

import api.webhook as wh
from app.domain.lead import ExtractedLead


class _FakeRequest:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


def _run(monkeypatch, lead):
    """Feed one ordinary text message through the webhook, return the replies."""
    monkeypatch.setattr(wh.config, "TELEGRAM_WEBHOOK_SECRET", "", raising=False)
    replies = []
    monkeypatch.setattr(wh, "_reply", lambda chat_id, text: replies.append(text))
    monkeypatch.setattr(wh, "_build_use_case",
                        lambda: type("_UC", (), {"execute": lambda _s, _t: lead})())

    update = {"message": {"chat": {"id": 5}, "text": "Вот вакансия: https://x"}}
    asyncio.run(wh.telegram_webhook(_FakeRequest(update), ""))
    return replies


def test_the_reply_says_where_the_contact_came_from(monkeypatch):
    """A lead saved as `telegram / @acme_hr` from a message that named neither is
    the one case where the bot's answer is genuinely surprising. Saying nothing
    about it leaves no way to tell a handle read out of a post from one typed by
    hand — and no way to spot it reading the wrong one."""
    lead = ExtractedLead(
        platform="telegram", target="@acme_hr", vacancy_context="Junior Python Dev",
        raw_text="raw",
        note="контакт из LinkedIn-поста: https://www.linkedin.com/posts/x-activity-1-a/")

    replies = _run(monkeypatch, lead)

    assert replies and "@acme_hr" in replies[0]
    assert "контакт из LinkedIn-поста" in replies[0]


def test_an_ordinary_lead_reply_gains_no_extra_line(monkeypatch):
    lead = ExtractedLead(platform="telegram", target="@ivan_hr",
                         vacancy_context="Junior Python Dev", raw_text="raw")

    replies = _run(monkeypatch, lead)

    assert replies and "ℹ️" not in replies[0]


def test_the_use_case_is_wired_to_undo_linkedins_link_rewrite(monkeypatch):
    """A post's `t.me` link arrives rewritten as `lnkd.in`, and the use case can
    only see through it with a resolver injected here. Nothing else fails visibly
    if this wiring is dropped: leads simply stop finding Telegram contacts and
    quietly fall back to the post's author."""
    monkeypatch.setattr(wh, "_build_repo", lambda: object())
    monkeypatch.setattr(wh, "OpenAISummarizer", lambda *a, **k: object())

    uc = wh._build_use_case()

    assert uc._resolve_link is wh.resolve_lnkd_in
    assert uc._fetch is wh.fetch_vacancy_text


def test_a_link_that_is_only_a_hyperlink_reaches_the_use_case(monkeypatch):
    """A forwarded post whose LinkedIn url lives under the words «пост на
    LinkedIn» has no url in `message["text"]`. Reading that field alone is what
    made intake answer «Не нашёл контакт» to it."""
    monkeypatch.setattr(wh.config, "TELEGRAM_WEBHOOK_SECRET", "", raising=False)
    monkeypatch.setattr(wh, "_reply", lambda chat_id, text: None)
    seen = []
    lead = ExtractedLead(platform="linkedin", target="https://www.linkedin.com/posts/x/",
                         vacancy_context="Node.js", raw_text="raw")
    monkeypatch.setattr(
        wh, "_build_use_case",
        lambda: type("_UC", (), {"execute": lambda _s, t: (seen.append(t), lead)[1]})())

    update = {"message": {
        "chat": {"id": 5},
        "text": "PixelPlex ищет Node.js. Ищет Мария Кохович, её пост на LinkedIn.",
        "entities": [{"type": "text_link", "offset": 47, "length": 15,
                      "url": "https://www.linkedin.com/posts/maria_hiring-activity-7-abc/"}],
    }}
    asyncio.run(wh.telegram_webhook(_FakeRequest(update), ""))

    assert seen and "https://www.linkedin.com/posts/maria_hiring-activity-7-abc/" in seen[0]


def test_a_photo_with_a_caption_is_not_dropped(monkeypatch):
    """A hiring post forwarded with its picture has no `text` at all."""
    monkeypatch.setattr(wh.config, "TELEGRAM_WEBHOOK_SECRET", "", raising=False)
    monkeypatch.setattr(wh, "_reply", lambda chat_id, text: None)
    seen = []
    lead = ExtractedLead(platform="telegram", target="@acme_hr",
                         vacancy_context="Node.js", raw_text="raw")
    monkeypatch.setattr(
        wh, "_build_use_case",
        lambda: type("_UC", (), {"execute": lambda _s, t: (seen.append(t), lead)[1]})())

    update = {"message": {"chat": {"id": 5}, "photo": [{"file_id": "f"}],
                          "caption": "Ищем бэкендера, пиши @acme_hr"}}
    asyncio.run(wh.telegram_webhook(_FakeRequest(update), ""))

    assert seen and "@acme_hr" in seen[0]

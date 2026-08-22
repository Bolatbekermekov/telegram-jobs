# Intake architecture
- FastAPI Vercel webhook at intake-bot/api/webhook.py receives Telegram updates, commands, and candidate callbacks.
- Text/link intake detects the contact and platform deterministically, fetches supported vacancy pages when possible, asks OpenAI for a concise vacancy summary, then appends a `new` lead to the main Sheet.
- /start_search and per-platform search commands append requests to the Control tab. There is NO approval step: since 2026-08-22 the laptop's search writes every found job straight into the main leads tab as `new`, and /show_vacancies plus the ✅/❌ buttons were deleted. The Candidates tab is read-only history, kept only so once-rejected URLs stay deduped.
- TELEGRAM_WEBHOOK_SECRET is optional in config; when non-empty, the endpoint checks Telegram's secret-token header.
- Google credentials support a local service-account file or inline JSON for Vercel.
- Synchronous external calls are made from the async webhook handler; keep serverless latency and replay/idempotency in mind when changing the flow.

## Which page gets read
- `detect_contact`'s target is NOT the vacancy page: it ranks an address (t.me, @handle, email) above every url. The page to read is `contact.target` when that target is itself fetchable, else `pick_vacancy_url(raw_text)`. Preferring the target keeps `canonical_hh_url`'s normalisation; scanning first would refetch the raw shared string.
- LinkedIn `/posts/` and `/feed/update/` are read regardless of `is_link_only` — the post body is the only place an apply-to address exists. Every other page stays behind that gate: an hh page or LinkedIn job has no contact to find and a fetch bought for nothing risks the ~10s function budget.
- Message text and page text are summarised TOGETHER when the message carried words of its own; a link-only message summarises the page alone. A read that was attempted and came back empty still stores "" (see the `_vacancy_text` docstring — rows 121/141).

## Lead routing from a post
- Ladder: address in the MESSAGE (telegram/email, `post_contact.DIRECT_PLATFORMS`) → telegram/email inside the POST body → post author's profile url.
- Only telegram/email are accepted out of post text. An hh/LinkedIn url inside a post is a reference, not a recipient.
- An UNREAD post keeps the post url as target on purpose: an author profile cannot be re-read for a description, and the laptop's `needs_vacancy_refetch` + `is_fetchable_vacancy_url(target)` is what fills «Вакансия» later.
- The reason is recorded in `ExtractedLead.note` → «Заметка», and echoed in the bot reply as an `ℹ️` line.
- Contrast with Threads (`sender/app/application/resolve_threads_lead.py`), which resolves on the laptop because it needs a browser and distrusts bare @mentions. LinkedIn needs neither: the post is a plain anonymous GET, and LinkedIn renders mentions as display names, so a surviving `@token` in post text is literal contact info.

## LinkedIn live behaviour (verified 2026-08-13, pinned by intake-bot/tests/fixtures/linkedin/capture.py)
- Public posts answer 200 anonymously; og:description carries the WHOLE post text with line breaks. A DELETED post answers 404 with a ~320 KB generic shell to every User-Agent — never conclude the feature broke from a 404 alone.
- LinkedIn rewrites every outbound url in post text as `lnkd.in/<code>`, so a `t.me` link in a post is invisible until undone. `lnkd.in` does not redirect: 200 plus a ~5 KB interstitial whose `external_url_click` anchor holds the destination. `resolve_lnkd_in` refuses any non-`lnkd.in` url on purpose (the urls come from a stranger's post text) and the caller resolves at most 2, only when no plain @handle was found.

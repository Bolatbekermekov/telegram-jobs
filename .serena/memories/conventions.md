# Code conventions
- Clean-ish layers: domain dataclasses/pure functions; application orchestration/protocols; infrastructure APIs/browser/sheets; interface CLI/webhook.
- Prefer dependency injection at browser/model/repository seams; tests use small fakes rather than live services.
- Operational invariant: a transient failure should not lose a lead. Leave retryable work `new`; use `manual` for human-required actions; delivered work becomes `sent`; `skipped` is terminal; LinkedIn invite-without-letter becomes `invited`.
- Live delivery precedes the Sheets status write. Sender retries the write and stops with an explicit manual-repair warning if recording still fails, to reduce duplicate sends.
- Model/scraped text written to Sheets uses RAW input to prevent formula injection.
- Broad exception handling is intentional at unstable network/browser/model boundaries; comments should state why swallowing is safe.
- Preserve strict sheet order in the sender loop; ChannelSwitcher keeps only one external channel active.
- The two vacancy_text.py and vacancy_fetcher.py copies must remain byte-identical unless the mirror design/test is deliberately changed.
- Code uses type hints and dataclasses, but typing is partial. Comments/docstrings mix Russian operator context with English implementation notes.
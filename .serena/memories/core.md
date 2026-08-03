# Project map
- Personal job-search/outreach automation; Google Sheets is the shared state boundary between cloud intake and local sender.
- Cloud intake lives under `intake-bot/`; local search, review, and delivery live under `sender/`.
- Read `mem:intake/core` for webhook/intake flows and sheet writes.
- Read `mem:sender/core` for local worker, orchestration, channels, searchers, and status semantics.
- Read `mem:cv/core` for role-specific CV selection, generation, and attachment invariants.
- Shared vacancy page parsing/fetching is duplicated byte-for-byte in both services and guarded by sender/tests/test_vacancy_mirror.py.
- Design history and implementation plans live under docs/superpowers/specs and docs/superpowers/plans; README.md is the operator guide.
- Privacy boundary: .env, service_account.json, browser/Telegram sessions, sender/cv contents, signature.txt, and apply_profile.yml are gitignored.
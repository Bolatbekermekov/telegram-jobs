# Sender architecture
- Entry point sender/run.py dispatches commands into app/interface/cli.py.
- `run()` reads Sheets leads in strict row/id order, resolves Threads and stale vacancy text before opening a channel, generates role-tailored content, asks for explicit confirmation unless AUTO_SEND, delivers, then records status.
- Delivery platforms: Telegram and email direct send; LinkedIn profiles/posts/Easy Apply/external forms; HeadHunter response/chat; Wellfound; Threads DM fallback.
- Search platforms: LinkedIn, Wellfound, HeadHunter, RemoteOK, Remotive, We Work Remotely. Worker takes requests from the Control tab and writes findings via `SearchLeadsRepo` straight into the main leads tab as `new` (no approval since 2026-08-22); the Candidates tab is read only, for dedup against history.
- Browser automation is concentrated in large, selector-sensitive modules under app/infrastructure/channels and app/infrastructure/search.
- Google Sheets is the source of truth; no local database or queue exists.
- Read `mem:cv/core` before changing message generation, attachments, Easy Apply, or external forms.
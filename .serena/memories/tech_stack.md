# Tech stack
- Python application code; current local test interpreter is Python 3.14.
- Cloud intake: FastAPI on Vercel, httpx, OpenAI SDK, gspread/google-auth.
- Local sender: Telethon, OpenAI SDK, gspread/google-auth, Playwright, Patchright, httpx, pypdf, PyYAML.
- Persistence/coordination: Google Sheets tabs for leads, candidates, and control/heartbeat requests.
- CV sources are LaTeX; sender/build_cvs.sh uses Tectonic and pypdf page-count validation.
- Tests: pytest with a `live` marker; default sender config excludes live tests.
- Dependencies are exact top-level pins in requirements.txt, but there is no full transitive lockfile, formatter/linter config, static-type-checker config, or checked-in CI workflow.
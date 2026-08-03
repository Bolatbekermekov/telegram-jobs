# Completion checks
- Always run `make test-unit`.
- Run `PYTHONPATH=intake-bot sender/.venv/bin/python -m pytest intake-bot/tests -q` when intake/shared parsing is touched.
- Run `sender/.venv/bin/python -m compileall -q sender/app intake-bot/app intake-bot/api` for syntax/import compilation.
- Live tests are opt-in only; do not run `make apply_probe` unless real-site network activity is explicitly authorized.
- No formatter, linter, type checker, coverage gate, or CI gate is configured; do not claim they passed.
- If CV LaTeX or build logic changes, run `bash sender/build_cvs.sh`, require exactly one page per role, extract text to verify ATS readability, render every PDF page, and visually inspect links, clipping, spacing, and glyphs.
# Project shortcuts. Run from the project root (telegram-jobs/).
# Uses the sender's venv directly, so no activation needed.
# Override the interpreter if your venv is elsewhere: make test PYTHON=python
#
#   make dry   -> generate a message for a lead and just print it (no Telegram)
#   make test  -> send a TEST message to yourself (TO below); lead status is NOT changed
#   make run   -> real interactive run: approve / edit / send per lead
#   make login -> diagnose / complete the Telegram login (shows how the code is sent)

PYTHON ?= sender/.venv/Scripts/python.exe
TO ?= @bolatbekermeko_v

.PHONY: dry test run login

dry:
	$(PYTHON) sender/test_send.py --dry-run

test:
	$(PYTHON) sender/test_send.py --to "$(TO)"

run:
	$(PYTHON) sender/run.py

login:
	$(PYTHON) sender/login_debug.py

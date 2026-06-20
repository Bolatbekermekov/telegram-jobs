# Project shortcuts. Run from the project root (telegram-jobs/).
# Uses the sender's venv directly, so no activation needed.
# Override the interpreter if your venv is elsewhere: make test PYTHON=python
#
#   make dry            -> generate a message for a lead and just print it (no Telegram)
#   make test           -> send a TEST message to yourself (TO below); lead status is NOT changed
#   make run            -> real interactive run: approve / edit / send per lead
#   make worker         -> background vacancy-search loop (LinkedIn + Wellfound)
#   make login_telegram -> log in to Telegram by scanning a QR code (no SMS/app code needed)
#   make login_browser  -> open the LinkedIn login window, save the session (one-time)
#   make login_wellfound -> open your Chrome for a one-time Wellfound login (leave it open)
#   make search          -> one-shot vacancy search across all platforms
#   make search_linkedin -> one-shot LinkedIn search
#   make search_wellfound-> one-shot Wellfound search (needs make login_wellfound Chrome open)
#   make bot_menu        -> register the bot's command menu in Telegram (one-time)
#   make test-unit      -> run the sender test suite

PYTHON ?= sender/.venv/Scripts/python.exe
TO ?= @bolatbekermeko_v

.PHONY: dry test run worker login_telegram login_browser login_wellfound search search_linkedin search_wellfound bot_menu test-unit

dry:
	$(PYTHON) sender/test_send.py --dry-run

test:
	$(PYTHON) sender/test_send.py --to "$(TO)"

run:
	$(PYTHON) sender/run.py

worker:
	$(PYTHON) sender/run.py worker

login_telegram:
	$(PYTHON) sender/qr_login.py

login_browser:
	$(PYTHON) sender/run.py login_browser

login_wellfound:
	$(PYTHON) sender/run.py login_wellfound

search:
	$(PYTHON) sender/run.py search

search_linkedin:
	$(PYTHON) sender/run.py search_linkedin

search_wellfound:
	$(PYTHON) sender/run.py search_wellfound

bot_menu:
	$(PYTHON) sender/register_bot_menu.py

test-unit:
	$(PYTHON) -m pytest sender/tests -v

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
#   make login_hh        -> open the hh.ru login window, save the session (one-time)
#   make login_threads  -> open the Threads login window, save the session (one-time; use a burner Instagram)
#   make login           -> log in to ALL platforms in one go (skips ones with a session)
#   make search          -> one-shot vacancy search across all platforms
#   make search_linkedin -> one-shot LinkedIn search
#   make search_wellfound-> one-shot Wellfound search (needs make login_wellfound Chrome open)
#   make search_remoteok -> one-shot RemoteOK search
#   make search_remotive -> one-shot Remotive search
#   make search_wwr      -> one-shot We Work Remotely search (opens a visible Chrome)
#   make search_hh       -> one-shot HeadHunter search (needs make login_hh once)
#   make bot_menu        -> register the bot's command menu in Telegram (one-time)
#   make test-unit      -> run the sender test suite
#   make apply_probe    -> LIVE routing check on the 3 real external-apply URLs (network; no submit)

PYTHON ?= sender/.venv/bin/python
TO ?= @bolatbekermeko_v

.PHONY: dry test run worker login_telegram login_browser login_wellfound login_hh login_threads login search search_linkedin search_wellfound search_remoteok search_remotive search_wwr search_hh bot_menu test-unit apply_probe

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

search_remoteok:
	$(PYTHON) sender/run.py search_remoteok

search_remotive:
	$(PYTHON) sender/run.py search_remotive

search_wwr:
	$(PYTHON) sender/run.py search_wwr

login_hh:
	$(PYTHON) sender/run.py login_hh

login_threads:
	$(PYTHON) sender/run.py login_threads

login:
	$(PYTHON) sender/run.py login

search_hh:
	$(PYTHON) sender/run.py search_hh

bot_menu:
	$(PYTHON) sender/register_bot_menu.py

test-unit:
	$(PYTHON) -m pytest sender/tests -v -m "not live"

apply_probe:
	$(PYTHON) -m pytest sender/tests/test_apply_live.py -v -m live

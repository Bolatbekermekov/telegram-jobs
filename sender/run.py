"""Entry point for the local sender. Run from the `sender` folder: python run.py"""
import sys
from pathlib import Path

# Force UTF-8 stdout/stderr: the CLI prints Russian text and arrows, which crash
# with UnicodeEncodeError when output goes anywhere non-console (a log file, a
# pipe, cron) where Windows defaults to cp1251.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001 — older/odd streams without reconfigure
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.interface.cli import (  # noqa: E402
    run,
    run_login_all,
    run_login_browser,
    run_login_wellfound,
    run_login_hh,
    run_login_threads,
    run_search_once,
    run_worker,
)

if __name__ == "__main__":
    cmd = sys.argv[1:2]
    if cmd == ["worker"]:
        run_worker()
    elif cmd == ["login"]:
        run_login_all()
    elif cmd == ["login_browser"]:
        run_login_browser()
    elif cmd == ["login_wellfound"]:
        run_login_wellfound()
    elif cmd == ["login_hh"]:
        run_login_hh()
    elif cmd == ["login_threads"]:
        run_login_threads()
    elif cmd and cmd[0] in ("search", "search_linkedin", "search_wellfound",
                            "search_remoteok", "search_remotive", "search_wwr",
                            "search_hh"):
        from app.application.search_commands import platforms_arg
        run_search_once(platforms_arg(cmd[0]))
    else:
        run()

"""Entry point for the local sender. Run from the `sender` folder: python run.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.interface.cli import run, run_login_browser, run_worker  # noqa: E402

if __name__ == "__main__":
    if sys.argv[1:2] == ["worker"]:
        run_worker()
    elif sys.argv[1:2] == ["login_browser"]:
        run_login_browser()
    else:
        run()

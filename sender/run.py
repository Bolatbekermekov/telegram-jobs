"""Entry point for the local sender. Run from the `sender` folder: python run.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.interface.cli import run  # noqa: E402

if __name__ == "__main__":
    run()

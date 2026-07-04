#!/usr/bin/env python3
"""Run stockmonitor from the local virtual environment."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"


def _venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def main() -> int:
    py = _venv_python()
    if not py.exists():
        print("Le programme n'est pas encore installe.")
        if os.name == "nt":
            print("Lance d'abord: python install.py")
        else:
            print("Lance d'abord: python3 install.py")
        return 1

    proc = subprocess.run([str(py), "-m", "stockmonitor", *sys.argv[1:]], cwd=ROOT)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())

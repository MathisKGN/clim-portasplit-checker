#!/usr/bin/env python3
"""Install stockmonitor in a local virtual environment.

This script keeps the user-facing setup to one command:
    python install.py

It creates .venv, installs requirements, and downloads the Camoufox browser.
"""
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


def _run(cmd: list[str], *, step: str) -> None:
    print(f"\n==> {step}", flush=True)
    print(" ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def _check_python() -> None:
    if sys.version_info < (3, 9):
        version = ".".join(map(str, sys.version_info[:3]))
        raise SystemExit(
            f"Python {version} est trop ancien. Installe Python 3.10 ou plus "
            "depuis https://www.python.org/downloads/ puis relance cette commande."
        )


def main() -> int:
    _check_python()

    if not VENV_DIR.exists():
        _run([sys.executable, "-m", "venv", str(VENV_DIR)], step="Creation de .venv")
    else:
        print("==> .venv existe deja, je le reutilise", flush=True)

    py = _venv_python()
    if not py.exists():
        raise SystemExit(f"Installation incomplete: Python introuvable dans {py}")

    _run([str(py), "-m", "pip", "install", "--upgrade", "pip"], step="Mise a jour de pip")
    _run([str(py), "-m", "pip", "install", "-r", "requirements.txt"], step="Installation des dependances")
    _run([str(py), "-m", "camoufox", "fetch"], step="Installation du navigateur Camoufox")

    print("\nInstallation terminee.")
    print("Pour lancer le programme:")
    if os.name == "nt":
        print("  python run.py")
    else:
        print("  python3 run.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

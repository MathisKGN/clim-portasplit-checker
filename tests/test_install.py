from __future__ import annotations

from pathlib import Path

import install


class _Completed:
    returncode = 0
    stdout = ""
    stderr = ""


def test_geocode_https_check_uses_runtime_ssl_fallback(monkeypatch):
    calls = []

    def fake_run(cmd, *, cwd, text, capture_output):
        calls.append(cmd)
        return _Completed()

    monkeypatch.setattr(install.subprocess, "run", fake_run)

    install._check_geocode_https(Path("/tmp/python"))

    code = calls[0][2]
    assert "from stockmonitor.seeds_dynamic import _urlopen_with_ssl_fallback" in code
    assert "with _urlopen_with_ssl_fallback(req, timeout=10)" in code
    assert "urllib.request.urlopen(" not in code

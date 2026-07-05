from __future__ import annotations

import io
import json
import ssl
import urllib.error

import pytest

from stockmonitor import seeds_dynamic


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _response(payload):
    return FakeResponse(json.dumps(payload).encode("utf-8"))


def _url_of(req) -> str:
    return getattr(req, "full_url", str(req))


def test_geocode_cp_or_raise_reads_primary_geo_api(monkeypatch):
    def fake_urlopen(req, timeout, context=None):
        assert "geo.api.gouv.fr" in _url_of(req)
        return _response([
            {
                "nom": "Créteil",
                "centre": {"coordinates": [2.4523, 48.7845]},
                "population": 93397,
            }
        ])

    monkeypatch.setattr(seeds_dynamic.urllib.request, "urlopen", fake_urlopen)

    assert seeds_dynamic.geocode_cp_or_raise("94000") == (48.7845, 2.4523)


def test_geocode_cp_or_raise_uses_adresse_api_fallback(monkeypatch):
    def fake_urlopen(req, timeout, context=None):
        url = _url_of(req)
        if "geo.api.gouv.fr" in url:
            raise urllib.error.HTTPError(url, 503, "Service Unavailable", {}, None)
        assert "api-adresse.data.gouv.fr" in url
        return _response({
            "features": [
                {
                    "properties": {"postcode": "94000", "city": "Créteil"},
                    "geometry": {"coordinates": [2.452976, 48.784506]},
                }
            ]
        })

    monkeypatch.setattr(seeds_dynamic.urllib.request, "urlopen", fake_urlopen)

    assert seeds_dynamic.geocode_cp_or_raise("94000") == (48.784506, 2.452976)


def test_geocode_cp_or_raise_reports_unknown_postcode(monkeypatch):
    def fake_urlopen(req, timeout, context=None):
        if "geo.api.gouv.fr" in _url_of(req):
            return _response([])
        return _response({"features": []})

    monkeypatch.setattr(seeds_dynamic.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(seeds_dynamic.PostcodeNotFound, match="75000"):
        seeds_dynamic.geocode_cp_or_raise("75000")


def test_geocode_cp_or_raise_reports_ssl_error(monkeypatch):
    cert_error = ssl.SSLCertVerificationError("certificate verify failed")

    def fake_urlopen(req, timeout, context=None):
        raise urllib.error.URLError(cert_error)

    monkeypatch.setattr(seeds_dynamic.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(seeds_dynamic.GeocodeServiceError) as exc_info:
        seeds_dynamic.geocode_cp_or_raise("94000")

    assert "certificat HTTPS" in str(exc_info.value)
    if seeds_dynamic.sys.platform == "darwin":
        assert "Install Certificates.command" in (exc_info.value.hint or "")


def test_geocode_cp_keeps_none_compatibility(monkeypatch):
    def fake_urlopen(req, timeout, context=None):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(seeds_dynamic.urllib.request, "urlopen", fake_urlopen)

    assert seeds_dynamic.geocode_cp("94000") is None

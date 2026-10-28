import io
import zipfile
from datetime import UTC, date, datetime, timedelta

import pytest
import requests

from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.dataflows.vendors import gdelt_events as gdelt


def _row(quad="3", tone="-4.0", event_day="20231231", added="20240101"):
    row = [""] * 58
    row[0], row[1], row[29], row[34], row[56] = "1", event_day, quad, tone, added
    return "\t".join(row) + "\n"


def _zip(data, name="20240101.export.CSV"):
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, data)
    return target.getvalue()


class _Response:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload
        self.closed = False

    def iter_content(self, chunk_size):
        yield self.payload

    def close(self):
        self.closed = True


def test_realistic_file_is_aggregated_and_download_restricted(monkeypatch):
    response = _Response(_zip(_row() + _row("4", "2.0")))

    def get(url, **kwargs):
        assert url == "https://data.gdeltproject.org/events/20240101.export.CSV.zip"
        assert kwargs["stream"] and kwargs["allow_redirects"] is False
        return response

    monkeypatch.setattr(requests, "get", get)
    result = gdelt.fetch_gdelt_day(date(2024, 1, 1))
    assert result["records"] == 2
    assert result["average_tone"] == -1
    assert result["quadrant_records"]["verbal conflict"] == 1
    assert result["quadrant_records"]["material conflict"] == 1
    assert result["historical_availability"] == "not_verified"
    assert result["coverage"] == "unknown"
    assert response.closed


@pytest.mark.parametrize("content", [
    _row(added="20240102"), _row(event_day="20240102"),
    _row(tone="nan"), _row(quad="9"), "invalid\trow\n",
])
def test_rejects_invalid_or_future_records(monkeypatch, content):
    monkeypatch.setattr(gdelt, "_download", lambda day: _zip(content))
    with pytest.raises(VendorUnavailableError):
        gdelt.fetch_gdelt_day(date(2024, 1, 1))


def test_rejects_unexpected_zip_and_download_failure(monkeypatch):
    monkeypatch.setattr(gdelt, "_download", lambda day: _zip(_row(), "../evil.csv"))
    with pytest.raises(VendorUnavailableError):
        gdelt.fetch_gdelt_day(date(2024, 1, 1))
    monkeypatch.setattr(gdelt, "_download", lambda day: b"not a zip")
    with pytest.raises(VendorUnavailableError):
        gdelt.fetch_gdelt_day(date(2024, 1, 1))


def test_enforces_download_and_expanded_size_bounds(monkeypatch):
    response = _Response(b"x" * 11)
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: response)
    monkeypatch.setattr(gdelt, "_MAX_ARCHIVE_BYTES", 10)
    with pytest.raises(VendorUnavailableError, match="size limit"):
        gdelt.fetch_gdelt_day(date(2024, 1, 1))
    assert response.closed
    monkeypatch.setattr(gdelt, "_download", lambda day: _zip(_row()))
    monkeypatch.setattr(gdelt, "_MAX_EXPANDED_BYTES", 10)
    with pytest.raises(VendorUnavailableError, match="size"):
        gdelt.fetch_gdelt_day(date(2024, 1, 1))


def test_two_day_lag_uses_run_cache_and_discloses_uncertainty(monkeypatch):
    called = []

    def fetch(day):
        called.append(day)
        return {"records": 1, "quadrant_records": {"verbal conflict": 1},
                "average_tone": -1.0, "source_url": "https://example.com",
                "archive_sha256": "a" * 64}

    monkeypatch.setattr(gdelt, "fetch_gdelt_day", fetch)
    cache = {}
    one = gdelt.render_gdelt_events(datetime(2024, 1, 3, tzinfo=UTC), cache)
    assert "Event occurrence dates may be earlier" in one
    two = gdelt.render_gdelt_events(datetime(2024, 1, 3, 12, tzinfo=UTC), cache)
    assert called == [date(2024, 1, 1)]
    assert "2024-01-01" in one and "2024-01-01" in two
    assert "actual historical publication time not verified" in one
    with pytest.raises(ValueError, match="timezone"):
        gdelt.render_gdelt_events(datetime(2024, 1, 3), cache)
    # UTC determines which file is safe under the two-day assumption.
    later = datetime(2024, 1, 4, tzinfo=UTC) - timedelta(minutes=1)
    gdelt.render_gdelt_events(later, cache)
    assert called == [date(2024, 1, 1)]


def test_http_and_timeout_fail_closed(monkeypatch):
    response = _Response(b"")
    response.status_code = 429
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: response)
    with pytest.raises(VendorUnavailableError, match="429"):
        gdelt.fetch_gdelt_day(date(2024, 1, 1))
    assert response.closed

    def fail(*args, **kwargs):
        raise requests.Timeout("network failed")

    monkeypatch.setattr(requests, "get", fail)
    with pytest.raises(VendorUnavailableError, match="download failed"):
        gdelt.fetch_gdelt_day(date(2024, 1, 1))

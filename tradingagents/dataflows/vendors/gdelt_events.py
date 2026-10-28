"""Summarize GDELT's daily event files with explicit availability assumptions."""

from __future__ import annotations

import csv
import hashlib
import io
import math
import zipfile
from datetime import UTC, date, datetime, time, timedelta

import requests

from tradingagents.dataflows.errors import VendorUnavailableError

_BASE = "https://data.gdeltproject.org/events"
_MAX_ARCHIVE_BYTES = 25 * 1024 * 1024
_MAX_EXPANDED_BYTES = 128 * 1024 * 1024
_FIRST_DAILY_FILE = date(2013, 4, 1)
_GROUPS = {"1": "verbal cooperation", "2": "material cooperation",
           "3": "verbal conflict", "4": "material conflict"}


def _file_date(value: str) -> date:
    try:
        parsed = datetime.strptime(value, "%Y%m%d").date()
    except (TypeError, ValueError) as exc:
        raise ValueError("GDELT dates must use YYYYMMDD") from exc
    if parsed.strftime("%Y%m%d") != value:
        raise ValueError("GDELT dates must use YYYYMMDD")
    return parsed


def _download(day: date) -> bytes:
    name = day.strftime("%Y%m%d")
    try:
        response = requests.get(f"{_BASE}/{name}.export.CSV.zip", timeout=(10, 60),
                                stream=True, allow_redirects=False)
    except requests.RequestException:
        raise VendorUnavailableError("GDELT event download failed") from None
    try:
        if response.status_code != 200:
            raise VendorUnavailableError(f"GDELT event download returned HTTP {response.status_code}")
        chunks, size = [], 0
        for chunk in response.iter_content(chunk_size=65536):
            size += len(chunk)
            if size > _MAX_ARCHIVE_BYTES:
                raise VendorUnavailableError("GDELT event archive exceeds size limit")
            chunks.append(chunk)
        return b"".join(chunks)
    except requests.RequestException:
        raise VendorUnavailableError("GDELT event download interrupted") from None
    finally:
        response.close()


def fetch_gdelt_day(day: date) -> dict:
    """Summarize one daily file; retrieval alone does not prove historical availability."""
    if isinstance(day, datetime) or not isinstance(day, date) or day < _FIRST_DAILY_FILE:
        raise ValueError("GDELT daily files start on 2013-04-01")
    payload = _download(day)
    name = day.strftime("%Y%m%d")
    groups = dict.fromkeys(_GROUPS.values(), 0)
    count, tone_sum = 0, 0.0
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            members = archive.infolist()
            if (len(members) != 1 or members[0].filename != f"{name}.export.CSV"
                    or members[0].file_size > _MAX_EXPANDED_BYTES):
                raise VendorUnavailableError("GDELT archive has unexpected contents or size")
            with archive.open(members[0]) as raw, io.TextIOWrapper(raw, encoding="utf-8", newline="") as stream:
                for row in csv.reader(stream, delimiter="\t", quoting=csv.QUOTE_NONE):
                    if len(row) != 58 or not row[0].isdigit() or row[29] not in _GROUPS:
                        raise VendorUnavailableError("GDELT event record has invalid fields")
                    try:
                        occurred, added = _file_date(row[1]), _file_date(row[56])
                        tone = float(row[34])
                    except ValueError:
                        raise VendorUnavailableError("GDELT event record has invalid values") from None
                    if occurred > added or added > day or not math.isfinite(tone):
                        raise VendorUnavailableError("GDELT event record has invalid dates or tone")
                    groups[_GROUPS[row[29]]] += 1
                    count += 1
                    tone_sum += tone
    except (zipfile.BadZipFile, UnicodeError, csv.Error, OSError, RuntimeError):
        raise VendorUnavailableError("GDELT event archive could not be read") from None
    return {
        "source": "GDELT 1.0 daily events", "archive_date": day.isoformat(),
        "source_url": f"{_BASE}/{name}.export.CSV.zip",
        "archive_sha256": hashlib.sha256(payload).hexdigest(),
        "records": count, "quadrant_records": groups,
        "average_tone": tone_sum / count if count else None,
        "coverage": "unknown", "historical_availability": "not_verified",
    }


def render_gdelt_events(decision_time: datetime, cache: dict | None = None) -> str:
    """Return the D-2 daily summary, with a per-run cache supplied by the caller.

    Two days is a conservative assumption, not evidence of publication time.
    """
    if not isinstance(decision_time, datetime) or decision_time.utcoffset() is None:
        raise ValueError("decision_time must include a timezone")
    decision = decision_time.astimezone(UTC)
    # shortcut: publication time is unverified; use archived publication metadata when available.
    day = decision.date() - timedelta(days=2)
    available = datetime.combine(day + timedelta(days=2), time.min, tzinfo=UTC)
    if cache is None:
        cache = {}
    if day not in cache:
        cache[day] = fetch_gdelt_day(day)
    result = cache[day]
    tone = "unavailable" if result["average_tone"] is None else f"{result['average_tone']:.3f}"
    return (
        f"## GDELT 1.0 records added on {day.isoformat()}\n"
        "Event occurrence dates may be earlier than the archive date.\n"
        f"Assumed available: {available.isoformat()} (two-day lag; actual historical "
        "publication time not verified). Global archive coverage is unknown. "
        "Records are coded events, not a complete news archive.\n"
        f"Records: {result['records']}; "
        + "; ".join(f"{key}: {value}" for key, value in result["quadrant_records"].items())
        + f"; average tone: {tone}.\nSource: {result['source_url']}\n"
        f"Archive SHA256: {result['archive_sha256']}"
    )

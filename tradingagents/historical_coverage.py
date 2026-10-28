"""Audit timestamped inputs before using them in a historical decision.

All datetimes must include a timezone. The window is [start, decision_time):
price timestamps are candle opens, and events use their publication time.
The caller supplies actual records, including when each became available; a
record's presence alone cannot establish complete coverage of an event feed.
"""

from datetime import UTC, datetime, timedelta


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware datetimes")
    return value.astimezone(UTC)


def audit_coverage(start, decision_time, candle_interval, candles, sources):
    """Report missing candles and usable events without inferring feed completeness.

    ``candles`` contains mappings with ``open_time`` and ``available_at``.
    ``sources`` maps source names to event mappings with ``published_at`` and
    ``available_at``. A missing timestamp must be represented by None. Feed
    contents and availability timestamps need independent provenance; this
    function does not check prices and cannot prove a vendor archived all data.
    """
    start, decision = _utc(start), _utc(decision_time)
    if start >= decision:
        raise ValueError("start must precede decision_time")
    if not isinstance(candle_interval, timedelta) or candle_interval <= timedelta(0):
        raise ValueError("candle_interval must be positive")
    if (decision - start) % candle_interval:
        raise ValueError("window must contain a whole number of candles")

    expected = set()
    cursor = start
    while cursor < decision:
        expected.add(cursor)
        cursor += candle_interval

    seen, duplicates, rejected = set(), set(), 0
    for candle in candles:
        opened = _utc(candle["open_time"])
        available = _utc(candle["available_at"])
        if opened not in expected or available < opened + candle_interval or available > decision:
            rejected += 1
            continue
        if opened in seen:
            duplicates.add(opened)
        seen.add(opened)
    missing = sorted(expected - seen)
    prices = {
        "status": "timestamps_complete" if not (missing or duplicates or rejected) else "timestamps_incomplete",
        "expected": len(expected),
        "usable": len(seen),
        "missing": missing,
        "duplicates": sorted(duplicates),
        "rejected": rejected,
    }

    events = {}
    for name in dict.fromkeys(("news", "macro", "sentiment", *sources)):
        records = sources.get(name, ())
        usable = undated = outside_window = unavailable_at_decision = 0
        for record in records:
            published, available = record.get("published_at"), record.get("available_at")
            if published is None or available is None:
                undated += 1
                continue
            published, available = _utc(published), _utc(available)
            if available < published:
                raise ValueError(f"{name}: availability precedes publication")
            if not start <= published < decision:
                outside_window += 1
            elif available > decision:
                unavailable_at_decision += 1
            else:
                usable += 1
        events[name] = {
            "status": "observed" if usable else "no_usable_records",
            "coverage": "unknown",
            "usable": usable,
            "undated": undated,
            "outside_window": outside_window,
            "unavailable_at_decision": unavailable_at_decision,
        }
    # Observed events never establish that an external feed is exhaustive.
    status = "incomplete" if missing or duplicates or rejected or any(
        item["status"] == "no_usable_records" for item in events.values()
    ) else "unknown"
    return {"status": status, "prices": prices, "sources": events}

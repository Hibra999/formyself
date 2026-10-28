"""Audit timestamped inputs before using them in a historical decision.

All datetimes must include a timezone. The window is [start, decision_time):
price timestamps are candle opens, and events use their publication time.
The caller supplies actual records, including when each became available; a
record's presence alone cannot establish complete coverage of an event feed.
"""

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware datetimes")
    return value.astimezone(UTC)


def _timestamp(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("timestamps must be ISO 8601 datetimes") from exc
    return _utc(value)


def audit_alpaca_snapshot(snapshot, start, decision_time, *, expected_symbol):
    """Validate a paginated Alpaca News snapshot, not the provider's full archive.

    A successful empty query means only that this query returned no usable items.
    Input is untrusted; consistency checks alone do not authenticate the response
    or prove that a model consumed this exact snapshot.
    """
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot must be an object")
    start, decision = _timestamp(start), _timestamp(decision_time)
    if start >= decision:
        raise ValueError("start must precede decision_time")

    errors = []
    if snapshot.get("source") != "alpaca":
        errors.append("unexpected_provider")
    if "symbol" not in snapshot or snapshot["symbol"] != expected_symbol:
        errors.append("symbol_mismatch")
    try:
        query_start = _timestamp(snapshot.get("start"))
        query_end = _timestamp(snapshot.get("end_exclusive"))
        if query_start != start or query_end != decision or query_start >= query_end:
            errors.append("query_window_mismatch")
    except (TypeError, ValueError):
        query_start = query_end = None
        errors.append("invalid_query_window")

    pages, articles, discarded = (snapshot.get("page_chain"), snapshot.get("articles"),
                                  snapshot.get("discarded"))
    if (not isinstance(pages, list) or not pages or type(snapshot.get("pages")) is not int
            or snapshot.get("pages") != len(pages)):
        errors.append("missing_or_inconsistent_pages")
        pages = []
    if not isinstance(articles, list):
        errors.append("invalid_articles")
        articles = []
    if (not isinstance(discarded, dict)
            or set(discarded) != {"invalid_timestamp", "outside_window", "revised_after_cut", "duplicate"}
            or any(type(n) is not int or n < 0 for n in discarded.values())):
        errors.append("invalid_discarded_counts")
        discarded = {}

    previous, seen, total = None, set(), 0
    for index, page in enumerate(pages):
        if not isinstance(page, dict):
            errors.append("invalid_page")
            continue
        if not {"request_cursor_sha256", "next_cursor_sha256", "http_status", "count"} <= page.keys():
            errors.append("missing_page_fields")
        requested, following = page.get("request_cursor_sha256"), page.get("next_cursor_sha256")
        if requested != previous:
            errors.append("broken_cursor_chain")
        if following is None and index != len(pages) - 1:
            errors.append("early_pagination_end")
        if following is not None:
            if (not isinstance(following, str)
                    or not re.fullmatch(r"[0-9a-f]{64}", following)
                    or following in seen):
                errors.append("invalid_or_repeated_cursor")
            else:
                seen.add(following)
        if page.get("http_status") != 200:
            errors.append("page_request_failed")
        count = page.get("count")
        if type(count) is not int or count < 0:
            errors.append("invalid_page_count")
        else:
            total += count
        previous = following
    if pages and previous is not None:
        errors.append("pagination_not_exhausted")
    if total != len(articles) + sum(discarded.values()):
        errors.append("article_count_mismatch")

    identifiers = set()
    for article in articles:
        if not isinstance(article, dict):
            errors.append("invalid_article")
            continue
        identifier = article.get("id")
        if identifier is None or str(identifier) in identifiers:
            errors.append("missing_or_duplicate_article_id")
        else:
            identifiers.add(str(identifier))
        try:
            created, updated = _timestamp(article.get("created_at")), _timestamp(article.get("updated_at"))
            if (updated < created or updated >= decision or query_start is None or query_end is None
                    or not query_start <= created < query_end):
                errors.append("article_outside_usable_window")
        except (TypeError, ValueError):
            errors.append("invalid_article_timestamp")

    digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":"),
                                       ensure_ascii=False).encode("utf-8")).hexdigest()
    exclusions = sum(discarded.values())
    status = ("incomplete" if errors else "query_with_exclusions" if exclusions
              else "query_observed" if articles else "query_empty")
    return {"status": status, "coverage": "unknown" if errors else "pagination_consistent",
            "provider": snapshot.get("source"), "symbol": snapshot.get("symbol"),
            "usable": len(articles), "discarded": discarded,
            "snapshot_sha256": digest, "errors": sorted(set(errors))}


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

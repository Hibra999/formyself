"""Alternative.me's Bitcoin Fear & Greed index, with a conservative daily lag.

This index is a Bitcoin market proxy, not a record of Reddit or Stocktwits
posts. Its historical timestamp is not proof of publication time or vintage.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import requests

from tradingagents.dataflows.errors import VendorUnavailableError

SOURCE_URL = "https://alternative.me/crypto/fear-and-greed-index/"
API_URL = "https://api.alternative.me/fng/"
_CLASSIFICATIONS = frozenset({"Extreme Fear", "Fear", "Neutral", "Greed", "Extreme Greed"})


def fetch_fear_greed_history() -> dict[str, dict]:
    """Fetch and validate all currently published daily readings, keyed by UTC date.

    Call once for a run and pass the resulting history to ``fear_greed_as_of``.
    A response is a present-day download, not proof that old values were not revised.
    """
    try:
        response = requests.get(API_URL, params={"limit": 0, "format": "json"}, timeout=30)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise VendorUnavailableError("Alternative.me Fear & Greed data unavailable") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise VendorUnavailableError("Alternative.me returned an invalid index response")
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("error") or not payload["data"]:
        raise VendorUnavailableError("Alternative.me returned no usable index history")

    history = {}
    for item in payload["data"]:
        if not isinstance(item, dict):
            raise VendorUnavailableError("Alternative.me returned an invalid index reading")
        raw_timestamp, raw_value = item.get("timestamp"), item.get("value")
        classification = item.get("value_classification")
        if (not isinstance(raw_timestamp, str) or not raw_timestamp.isascii()
                or not raw_timestamp.isdigit() or not isinstance(raw_value, str)
                or not raw_value.isascii() or not raw_value.isdigit()
                or not isinstance(classification, str) or classification not in _CLASSIFICATIONS):
            raise VendorUnavailableError("Alternative.me returned an invalid index reading")
        try:
            observed = datetime.fromtimestamp(int(raw_timestamp), UTC)
            value = int(raw_value)
        except (ValueError, OverflowError, OSError) as exc:
            raise VendorUnavailableError("Alternative.me returned an invalid index reading") from exc
        if not 0 <= value <= 100:
            raise VendorUnavailableError("Alternative.me returned an out-of-range index value")
        day = observed.date().isoformat()
        if day in history:
            raise VendorUnavailableError("Alternative.me returned duplicate daily readings")
        history[day] = {
            "timestamp": observed.isoformat(),
            "value": value,
            "classification": classification,
        }
    return history


def fear_greed_as_of(history: dict[str, dict], trade_date: str) -> dict:
    """Return exactly the prior UTC day's reading; gaps are never filled silently."""
    try:
        day = date.fromisoformat(trade_date)
    except (TypeError, ValueError) as exc:
        raise ValueError("trade_date must be a date in YYYY-MM-DD format") from exc
    if day.isoformat() != trade_date:
        raise ValueError("trade_date must be a date in YYYY-MM-DD format")
    try:
        previous = (day - timedelta(days=1)).isoformat()
    except OverflowError as exc:
        raise ValueError("trade_date has no preceding day") from exc
    if previous not in history:
        raise VendorUnavailableError(f"Alternative.me has no reading for {previous}")
    reading = history[previous]
    return {"source": SOURCE_URL, "index": "Bitcoin Fear & Greed", "reading_date": previous,
            "available_assumption": day.isoformat(), "timestamp": reading["timestamp"],
            "value": reading["value"], "classification": reading["classification"]}


def render_fear_greed(history: dict[str, dict], trade_date: str) -> str:
    """Render a clearly attributed market-wide Bitcoin proxy for an analyst."""
    reading = fear_greed_as_of(history, trade_date)
    return (
        "## Bitcoin Fear & Greed — Alternative.me\n"
        f"Source: {SOURCE_URL}\n"
        f"Reading date (UTC): {reading['reading_date']}\n"
        f"Index: {reading['value']}/100 ({reading['classification']})\n"
        "The previous-day lag is a conservative assumption; historical publication "
        "time and revisions are not verified. This Bitcoin market proxy is not "
        "ETH/SOL-specific sentiment or historical Reddit/Stocktwits content."
    )

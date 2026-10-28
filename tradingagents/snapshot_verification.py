"""Inspect persisted Alpaca snapshots and references in generated reports.

Matching hashes prove byte integrity, not source authenticity, complete news
coverage, or that a model actually used every article.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from tradingagents.historical_coverage import audit_alpaca_snapshot

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_HEADING = re.compile(
    r"^## Alpaca/Benzinga news \(snapshot SHA256: ([0-9a-f]{64})\)[ \t]*\r?$",
    re.MULTILINE,
)


def load_alpaca_snapshot(directory: str | Path, digest: str) -> dict:
    """Read canonical bytes named by SHA256, failing on absence or tampering."""
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        raise ValueError("snapshot digest must be a lowercase SHA256")
    root = Path(directory).resolve()
    path = root / f"{digest}.json"
    if path.is_symlink() or path.resolve().parent != root:
        raise ValueError("snapshot must be a regular file in the snapshot directory")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("snapshot bytes do not match their digest")
    try:
        snapshot = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("snapshot is not valid UTF-8 JSON") from exc
    if not isinstance(snapshot, dict) or snapshot.get("source") != "alpaca":
        raise ValueError("snapshot must be an Alpaca news object")
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if raw != canonical:
        raise ValueError("snapshot bytes are not canonical JSON")
    return snapshot


def audit_stored_alpaca_snapshot(directory, digest, start, decision_time, *, expected_symbol):
    """Check stored bytes plus timestamp and pagination consistency for a scope."""
    snapshot = load_alpaca_snapshot(directory, digest)
    return audit_alpaca_snapshot(snapshot, start, decision_time, expected_symbol=expected_symbol)


def inspect_graph_report_snapshots(directory, final_state):
    """Find literal snapshot headings in graph news/sentiment report fields.

    ``verified`` means the referenced file's bytes match its name. The model's
    report can omit or invent a heading; this does not establish tool use.
    """
    references = {}
    for field in ("news_report", "sentiment_report"):
        text = final_state.get(field, "")
        if not isinstance(text, str):
            raise ValueError(f"{field} must be text")
        references[field] = sorted(set(_HEADING.findall(text)))

    verified, missing, invalid = [], [], []
    for digest in sorted(set(references["news_report"] + references["sentiment_report"])):
        try:
            load_alpaca_snapshot(directory, digest)
        except FileNotFoundError:
            missing.append(digest)
        except (OSError, ValueError):
            invalid.append(digest)
        else:
            verified.append(digest)
    return {"references": references, "verified": verified, "missing": missing, "invalid": invalid}

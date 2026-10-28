import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from tradingagents.dataflows import router
from tradingagents.dataflows.config import run_config
from tradingagents.dataflows.vendors import alpaca_news
from tradingagents.default_config import build_default_config

SNAPSHOT = {"source": "alpaca", "articles": [{"headline": "noticia histórica", "source": "test",
             "created_at": "2025-01-01T00:00:00Z", "updated_at": "2025-01-01T00:00:00Z",
             "id": "1", "summary": "", "url": ""}]}


def test_report_persists_exact_hash_named_bytes_only_when_enabled(tmp_path):
    with run_config({"results_dir": str(tmp_path), "alpaca_persist_news_snapshots": False}):
        alpaca_news._report(SNAPSHOT, 1)
    assert not list(tmp_path.iterdir())

    with run_config({"results_dir": str(tmp_path), "alpaca_persist_news_snapshots": True}):
        report = alpaca_news._report(SNAPSHOT, 1)
    digest = alpaca_news.snapshot_sha256(SNAPSHOT)
    path = tmp_path / "reports" / "alpaca_news_snapshots" / f"{digest}.json"
    contents = path.read_bytes()
    assert hashlib.sha256(contents).hexdigest() == digest
    assert json.loads(contents) == SNAPSHOT
    assert digest in report
    assert list(path.parent.iterdir()) == [path]


def test_concurrent_persistence_keeps_one_complete_snapshot(tmp_path):
    with ThreadPoolExecutor(max_workers=8) as pool:
        paths = list(pool.map(lambda _: alpaca_news._persist_snapshot(SNAPSHOT, tmp_path), range(24)))
    assert len(set(paths)) == 1
    path = paths[0]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == path.stem
    assert list(path.parent.iterdir()) == [path]


def test_corrupt_existing_snapshot_blocks_report_and_is_not_overwritten(tmp_path):
    path = alpaca_news._persist_snapshot(SNAPSHOT, tmp_path)
    path.write_text("corrupted", encoding="utf-8")
    with (run_config({"results_dir": str(tmp_path), "alpaca_persist_news_snapshots": True}),
          pytest.raises(alpaca_news.AlpacaSnapshotError, match="stored or verified")):
        alpaca_news._report(SNAPSHOT, 1)
    assert path.read_text(encoding="utf-8") == "corrupted"
    assert list(path.parent.iterdir()) == [path]


def test_write_failure_surfaces_and_removes_temporary_file(tmp_path, monkeypatch):
    def fail(*args):
        raise PermissionError("denied")
    monkeypatch.setattr(alpaca_news.os, "link", fail)
    with (run_config({"results_dir": str(tmp_path), "alpaca_persist_news_snapshots": True}),
          pytest.raises(alpaca_news.AlpacaSnapshotError, match="stored or verified")):
        alpaca_news._report(SNAPSHOT, 1)
    assert not list((tmp_path / "reports" / "alpaca_news_snapshots").iterdir())


def test_snapshot_environment_option_is_boolean(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_ALPACA_NEWS_SNAPSHOTS", "true")
    assert build_default_config()["alpaca_persist_news_snapshots"] is True
    monkeypatch.setenv("TRADINGAGENTS_ALPACA_NEWS_SNAPSHOTS", "invalid")
    with pytest.raises(ValueError, match="Invalid value"):
        build_default_config()


def test_failed_persistence_is_not_hidden_by_another_news_vendor(tmp_path, monkeypatch):
    monkeypatch.setattr(alpaca_news, "fetch_news", lambda *args: SNAPSHOT)
    monkeypatch.setattr(alpaca_news, "_persist_snapshot", lambda *args: (_ for _ in ()).throw(
        PermissionError("denied")))
    monkeypatch.setitem(router.VENDOR_METHODS["get_news"], "yfinance",
                        lambda *args: pytest.fail("must not fall back"))
    with (run_config({"results_dir": str(tmp_path), "alpaca_persist_news_snapshots": True,
                      "tool_vendors": {"get_news": "alpaca,yfinance"}}),
          pytest.raises(alpaca_news.AlpacaSnapshotError)):
        router.route_to_vendor("get_news", "BTC-USD", "2025-01-01", "2025-01-01")

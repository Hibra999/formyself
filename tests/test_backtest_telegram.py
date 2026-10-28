import logging

import pytest
import requests

from tradingagents.backtest_telegram import TelegramNotifications


def test_disabled_and_incomplete_configuration(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert not TelegramNotifications().message("test")
    with pytest.raises(ValueError):
        TelegramNotifications(token="token")


def test_notifications_do_not_expose_token_on_network_failure(monkeypatch, caplog):
    def fail(*args, **kwargs):
        raise requests.ConnectionError("https://api.telegram.org/bottopsecret/sendMessage")

    monkeypatch.setattr(requests, "post", fail)
    with caplog.at_level(logging.WARNING):
        assert not TelegramNotifications("topsecret", "123").message("test")
    assert "topsecret" not in caplog.text


def test_document_is_sent_as_file(monkeypatch, tmp_path):
    path = tmp_path / "report.html"
    path.write_text("report", encoding="utf-8")

    def post(url, **kwargs):
        assert url.endswith("/sendDocument")
        assert kwargs["data"]["chat_id"] == "123"
        assert kwargs["files"]["document"].read() == b"report"
        return type("Response", (), {"ok": True, "json": lambda self: {"ok": True}})()

    monkeypatch.setattr(requests, "post", post)
    assert TelegramNotifications("token", "123").document(path)

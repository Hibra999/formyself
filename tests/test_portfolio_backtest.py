from types import SimpleNamespace

import pandas as pd
import pytest

from tradingagents.portfolio_backtest import quantstats_html, simulate_portfolio


def _prices(data):
    return pd.DataFrame(data, index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]))


def test_buy_sell_next_close_and_both_fees():
    result = simulate_portfolio(_prices({"BTC": [50, 100, 200, 200]}), [
        {"date": "2024-01-01", "ticker": "BTC", "rating": "Buy"},
        {"date": "2024-01-03", "ticker": "BTC", "rating": "Sell"},
    ])
    purchase = 100 / (1 + 0.1 * 0.0036)
    assert result.trades.side.tolist() == ["buy", "sell"]
    assert result.trades.date.tolist() == list(pd.to_datetime(["2024-01-02", "2024-01-04"]))
    assert result.trades.fee.tolist() == pytest.approx([purchase * 0.0036, 2 * purchase * 0.0036])
    assert result.equity.tolist() == pytest.approx([
        1000, 1000 - purchase * 0.0036,
        1000 - purchase * 0.0036 + purchase,
        1000 - purchase * 0.0036 + purchase - 2 * purchase * 0.0036,
    ])
    assert result.trades.iloc[0].value / result.equity.iloc[1] == pytest.approx(0.1)
    assert (1 + result.returns).prod() == pytest.approx(result.equity.iloc[-1] / 1000)


def test_hold_does_nothing_and_last_signal_is_pending():
    result = simulate_portfolio(_prices({"BTC": [1, 1, 1, 1]}), [
        {"date": "2024-01-01", "ticker": "BTC", "rating": "Hold"},
        {"date": "2024-01-04", "ticker": "BTC", "rating": "Buy"},
    ])
    assert result.trades.empty
    assert result.equity.tolist() == [1000] * 4
    assert len(result.pending) == 1


def test_consecutive_buy_signals_respect_post_fee_cap():
    result = simulate_portfolio(_prices({"BTC": [1, 1, 1, 1], "ETH": [1, 1, 1, 1]}), [
        {"date": "2024-01-01", "ticker": "BTC", "rating": "Buy"},
        {"date": "2024-01-02", "ticker": "BTC", "rating": "Buy"},
        {"date": "2024-01-01", "ticker": "ETH", "rating": "Overweight"},
    ])
    assert result.trades.ticker.tolist() == ["BTC", "ETH"]
    assert result.trades.value.sum() <= 200
    assert result.equity.iloc[-1] < 1000


def test_rejects_bad_prices_and_ambiguous_signals():
    with pytest.raises(ValueError, match="finite and positive"):
        simulate_portfolio(_prices({"BTC": [1, float("nan"), 1, 1]}), [])
    with pytest.raises(ValueError, match="duplicate signal"):
        simulate_portfolio(_prices({"BTC": [1, 1, 1, 1]}), [
            {"date": "2024-01-01", "ticker": "BTC", "rating": "Buy"},
            {"date": "2024-01-01", "ticker": "BTC", "rating": "Sell"},
        ])
    with pytest.raises(ValueError, match="valid rating"):
        simulate_portfolio(_prices({"BTC": [1, 1, 1, 1]}), [
            {"date": "2024-01-01", "ticker": "BTC", "rating": "Review"},
        ])
    with pytest.raises(ValueError, match="predates"):
        simulate_portfolio(_prices({"BTC": [1, 1, 1, 1]}), [
            {"date": "2023-12-31", "ticker": "BTC", "rating": "Buy"},
        ])


def test_quantstats_receives_portfolio_returns(monkeypatch, tmp_path):
    result = simulate_portfolio(_prices({"BTC": [1, 1, 1, 1]}), [])
    calls = []
    monkeypatch.setitem(__import__("sys").modules, "quantstats", SimpleNamespace(
        reports=SimpleNamespace(html=lambda *args, **kwargs: calls.append((args, kwargs)))
    ))
    path = tmp_path / "report.html"
    quantstats_html(result, path)
    assert calls[0][0][0] is result.returns
    assert calls[0][1]["output"] == str(path)
    assert calls[0][1]["periods_per_year"] == 365
    assert "Sell/Underweight sell" in calls[0][1]["title"]


def test_rejects_missing_days_in_crypto_prices():
    prices = _prices({"BTC": [1, 1, 1, 1]}).drop(pd.Timestamp("2024-01-02"))
    with pytest.raises(ValueError, match="consecutive daily"):
        simulate_portfolio(prices, [])

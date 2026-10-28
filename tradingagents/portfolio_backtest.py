"""Simulate a long-only portfolio from dated signals and closing prices.

Prices are a DataFrame indexed by consecutive timezone-naive calendar dates, with a
column per ticker. Signals are dictionaries with date, ticker and rating. A
signal fills at the first supplied close strictly after its date. Caller must
supply prices and signals that were available on their respective dates.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass
class PortfolioResult:
    equity: pd.Series
    returns: pd.Series
    trades: pd.DataFrame
    pending: list[dict]


def simulate_portfolio(prices: pd.DataFrame, signals: list[dict]) -> PortfolioResult:
    """Apply Buy/Overweight, Hold, and Sell/Underweight with Bitso-style taker fees.

    Each purchase targets at most 10% of equity after its fee. An existing
    position can exceed 10% as prices move; it is not forcibly rebalanced.
    Prices model fills at close with no slippage or liquidity constraints.
    """
    if prices.empty or prices.columns.has_duplicates or not isinstance(prices.index, pd.DatetimeIndex):
        raise ValueError("prices require a nonempty date index and unique ticker columns")
    if (prices.index.tz is not None or prices.index.has_duplicates
            or not prices.index.is_monotonic_increasing
            or not (prices.index == prices.index.normalize()).all()):
        raise ValueError("price dates must be unique, sorted, timezone-naive calendar dates")
    if len(prices) > 1 and not (prices.index[1:] - prices.index[:-1] == pd.Timedelta(days=1)).all():
        raise ValueError("prices require consecutive daily observations for crypto")
    try:
        prices = prices.astype(float)
    except (ValueError, TypeError) as exc:
        raise ValueError("prices must be finite and positive") from exc
    if not prices.map(lambda value: pd.notna(value) and 0 < value < float("inf")).all().all():
        raise ValueError("prices must be finite and positive, with no missing observations")

    by_date: dict[pd.Timestamp, list[dict]] = {}
    pending = []
    seen = set()
    allowed = {"Buy", "Overweight", "Hold", "Underweight", "Sell"}
    for signal in signals:
        ticker, rating = signal.get("ticker"), signal.get("rating")
        try:
            date = pd.Timestamp(signal["date"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("signal date must be a calendar date") from exc
        if (pd.isna(date) or date.tz is not None or date != date.normalize()
                or ticker not in prices.columns or rating not in allowed):
            raise ValueError("signal must have a calendar date, known ticker and valid rating")
        if date < prices.index[0]:
            raise ValueError("signal predates the available portfolio price history")
        key = (date, ticker)
        if key in seen:
            raise ValueError("duplicate signal for ticker and date")
        seen.add(key)
        # A close is usable only after the date on which the signal was produced.
        index = prices.index.searchsorted(date, side="right")
        if index == len(prices.index):
            pending.append(signal.copy())
        else:
            by_date.setdefault(prices.index[index], []).append(signal)

    cash = 1000.0
    positions = dict.fromkeys(prices.columns, 0.0)
    history, trades = [], []
    fee_rate = 0.0036
    for date, row in prices.iterrows():
        events = by_date.get(date, [])
        # Process older signals first; for the same signal date, sell before buy.
        events = sorted(events, key=lambda s: (pd.Timestamp(s["date"]),
                        s["rating"] not in {"Sell", "Underweight"}, s["ticker"]))
        for signal in events:
            ticker, rating = signal["ticker"], signal["rating"]
            price, quantity = row[ticker], positions[ticker]
            equity = cash + sum(positions[name] * row[name] for name in prices.columns)
            value = 0.0
            if rating in {"Buy", "Overweight"}:
                value = max(0.0, min((0.1 * equity - quantity * price) / (1 + 0.1 * fee_rate),
                                     cash / (1 + fee_rate)))
                positions[ticker] += value / price
                cash -= value * (1 + fee_rate)
            elif rating in {"Sell", "Underweight"}:
                value = quantity * price
                positions[ticker] = 0.0
                cash += value * (1 - fee_rate)
            if value > 0:
                trades.append({"date": date, "signal_date": pd.Timestamp(signal["date"]),
                               "ticker": ticker, "side": "buy" if rating in {"Buy", "Overweight"} else "sell",
                               "price": price, "quantity": value / price, "value": value,
                               "fee": value * fee_rate})
        history.append(cash + sum(positions[name] * row[name] for name in prices.columns))

    equity = pd.Series(history, index=prices.index, name="equity")
    returns = equity.pct_change()
    returns.iloc[0] = equity.iloc[0] / 1000.0 - 1
    return PortfolioResult(equity, returns.rename("returns"), pd.DataFrame(trades, columns=[
        "date", "signal_date", "ticker", "side", "price", "quantity", "value", "fee",
    ]), pending)


def quantstats_html(result: PortfolioResult, output: str | Path) -> None:
    """Write a QuantStats HTML report from the simulated portfolio returns."""
    try:
        import quantstats as qs
    except ImportError as exc:
        raise ImportError("QuantStats is required: install the quantstats package") from exc
    qs.reports.html(result.returns, output=str(output),
                    title=("Simulated portfolio: 1,000 USD; 10% position cap; 0.36% fee per side; "
                           "next close; no slippage; Buy/Overweight buy, Sell/Underweight sell"),
                    periods_per_year=365)

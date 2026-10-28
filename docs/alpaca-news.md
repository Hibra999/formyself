# Alpaca historical news

Set `ALPACA_API_KEY`, `ALPACA_API_SECRET` and `TRADINGAGENTS_NEWS_VENDOR=alpaca`
in the local `.env`, which Git ignores. Never commit credentials or use this
integration to place orders. The environment setting changes the two news tools
only; insider transactions keep the category's existing provider. Alternatively,
select Alpaca programmatically without changing the other providers:

```python
from tradingagents.default_config import build_default_config
from tradingagents.graph.trading_graph import TradingAgentsGraph

config = build_default_config()
config["tool_vendors"] = {"get_news": "alpaca", "get_global_news": "alpaca"}
graph = TradingAgentsGraph(config=config)
```

Prices and indicators remain on yfinance and macro data on FRED unless they are
configured separately. BTC-USD, ETH-USD and SOL-USD map to Alpaca's BTCUSD,
ETHUSD and SOLUSD; stock tickers such as SPY pass through. Unsupported Yahoo
symbols, including forex tickers, fail rather than guessing an Alpaca symbol.

The data-only Alpaca News endpoint is paginated to its end, with a limit of
100 pages. HTTP errors (including 429), invalid responses, repeated cursors and
page-limit exhaustion fail explicitly; there is no automatic retry. Each news
item needs UTC-aware `created_at` and `updated_at`. Items published outside the
window or revised after its end are withheld. The inclusive end date is bounded
by the next UTC midnight, consistent with the native first-subsequent-close
scoring. Alpaca supplies current article versions, not necessarily earlier
versions; withheld items are not proof that nothing occurred.

`fetch_news(start_date, end_date, symbol=None)` returns the exact filtered
snapshot, page-chain hashes and discard counts without credentials or cursor
values. Set `TRADINGAGENTS_ALPACA_NEWS_SNAPSHOTS=true` to retain the exact
snapshot used by each analyst under `results_dir/reports/alpaca_news_snapshots/`.
The analyst report prints its SHA256. The snapshot is written atomically, its
file name is the hash of its canonical JSON bytes, and it contains no API
credentials or raw page cursors. Snapshot files contain third-party news and
are ignored by Git. A separate later fetch may differ. Alpaca supplies
Benzinga news, not an exhaustive archive of global events or historic Reddit,
StockTwits, prediction markets or all exogenous variables. This adapter does not
establish completeness or unlock the audited portfolio backtest.

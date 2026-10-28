from tradingagents.agents import tools
from tradingagents.dataflows.config import run_config


def test_research_macro_tool_uses_previous_vintage(monkeypatch):
    calls = []
    monkeypatch.setattr(tools, "route_to_vendor", lambda *args: calls.append(args) or "ok")
    with run_config({"research_macro_previous_day": True}):
        tools.get_macro_indicators.func("cpi", "2024-01-08", trade_date="2024-01-08")
        tools.get_macro_indicators.func("cpi", "2024-01-03", trade_date="2024-01-08")
    assert calls[0][2] == "2024-01-07"
    assert calls[1][2] == "2024-01-03"

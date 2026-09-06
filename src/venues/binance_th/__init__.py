"""Binance TH (Gulf / binance.th) venue adapters — paper/read-only first."""
from venues.binance_th.tape import (
    BINANCE_TH_API_BASE,
    BinanceTHError,
    DEFAULT_SYMBOL,
    fetch_book_ticker,
    fetch_public_ticker,
    fixture_ticker_row,
    ticker_to_tape_quote,
)
from venues.binance_th.paper import (
    LIVE_GATE_ENV,
    paper_fill_from_ticker,
    refuse_live,
    simulate_paper_order,
)

__all__ = [
    "BINANCE_TH_API_BASE",
    "BinanceTHError",
    "DEFAULT_SYMBOL",
    "LIVE_GATE_ENV",
    "fetch_book_ticker",
    "fetch_public_ticker",
    "fixture_ticker_row",
    "paper_fill_from_ticker",
    "refuse_live",
    "simulate_paper_order",
    "ticker_to_tape_quote",
]

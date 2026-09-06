"""Solana venue package — research quotes + paper fills (no custody, no swaps)."""
from __future__ import annotations

from venues.solana.desk_balance import (
    DEFAULT_DESK_PUBKEY,
    DeskBalanceError,
    DeskBalanceProbe,
    fetch_desk_balance,
)
from venues.solana.jupiter_quotes import (
    DEFAULT_TIMEOUT,
    JupiterQuoteError,
    SOL_MINT,
    USDC_MINT,
    fetch_jupiter_order_quote,
    fetch_jupiter_usd_price,
    fixture_sol_usdc_quote,
)
from venues.solana.paper import (
    VENUE as SOLANA_PAPER_VENUE,
    SolanaPaperError,
    paper_batch_fills,
    paper_fill_from_quote,
    refuse_live as refuse_solana_live,
    simulate_paper_fill,
)

__all__ = [
    "DEFAULT_DESK_PUBKEY",
    "DEFAULT_TIMEOUT",
    "DeskBalanceError",
    "DeskBalanceProbe",
    "JupiterQuoteError",
    "SOLANA_PAPER_VENUE",
    "SOL_MINT",
    "USDC_MINT",
    "SolanaPaperError",
    "fetch_desk_balance",
    "fetch_jupiter_order_quote",
    "fetch_jupiter_usd_price",
    "fixture_sol_usdc_quote",
    "paper_batch_fills",
    "paper_fill_from_quote",
    "refuse_solana_live",
    "simulate_paper_fill",
]

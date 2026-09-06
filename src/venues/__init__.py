"""Patpat-MakeMoney multi-venue data layer (Phase 1).

Public tape + research quotes only. No live order execution here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class TapeQuote:
    """Normalized venue quote for Ledger tape briefs."""

    venue: str
    symbol: str
    price: float
    ts: str  # ISO-8601 UTC
    source: str  # e.g. binance_public, bitkub_public, oneinch_spot, fixture

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = ["TapeQuote"]

"""DEX↔CEX arb scan helpers (paper/read-only)."""
from venues.arb.dex_cex import (
    ArbFeeConfig,
    ArbScanResult,
    detect_dex_cex_opportunity,
    simulate_paper_dual_leg,
)

__all__ = [
    "ArbFeeConfig",
    "ArbScanResult",
    "detect_dex_cex_opportunity",
    "simulate_paper_dual_leg",
]

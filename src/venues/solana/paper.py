"""Solana paper fill stub — Jupiter quote → paper fill (NO sign / NO broadcast).

Venue tag: solana_paper. Fee stack uses API feeBps only when present (labeled);
never invents PnL. Live execution is intentionally unimplemented and always refused.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional, Union

from venues.solana.jupiter_quotes import (
    DEFAULT_TIMEOUT,
    JupiterOrderQuote,
    JupiterQuoteError,
    SOL_MINT,
    USDC_MINT,
    fetch_jupiter_order_quote,
)

LIVE_GATE_ENV = "PMM_SOL_LIVE_OK"
VENUE = "solana_paper"
DEFAULT_AMOUNT = "1000000"  # 0.001 SOL smoke size (lamports)
DEFAULT_SIDE = "buy"  # buy output (USDC) paying input (SOL) along quote direction


class SolanaPaperError(RuntimeError):
    """Raised when Solana paper fill simulation fails or live is refused."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def refuse_live(*_args: Any, **_kwargs: Any) -> None:
    """Hard-refuse any live Solana swap / order path."""
    raise SolanaPaperError(
        f"Solana live swaps are not implemented; paper-only. "
        f"Future live path requires {LIVE_GATE_ENV}=1 (not honored here). "
        f"Never sign/send from this module."
    )


def live_order_stub(*_args: Any, **_kwargs: Any) -> None:
    """Live order stub — intentionally unimplemented; always raises."""
    refuse_live()


def _quote_to_dict(quote: Union[JupiterOrderQuote, dict[str, Any]]) -> dict[str, Any]:
    if isinstance(quote, JupiterOrderQuote):
        return quote.to_dict()
    if isinstance(quote, dict):
        return dict(quote)
    raise SolanaPaperError(f"quote must be JupiterOrderQuote or dict, got {type(quote)}")


def paper_fill_from_quote(
    quote: Union[JupiterOrderQuote, dict[str, Any]],
    *,
    side: str = DEFAULT_SIDE,
    leg: str = "single",
    round_trip_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Build a paper fill from a Jupiter order quote.

    side=buy  → along quote direction (pay input mint, receive output mint)
    side=sell → reverse economic label on the same quote mid (paper stub only;
                does not invent a reverse route; px still quote mid)

    Fee estimate: API fee_bps applied to output notional (out_ui) when present.
    Net fields are labeled estimates from that fee stack only — no invented PnL.
    """
    q = _quote_to_dict(quote)
    side_l = (side or DEFAULT_SIDE).strip().lower()
    if side_l not in ("buy", "sell"):
        raise SolanaPaperError(f"side must be buy|sell, got {side!r}")

    try:
        mid = float(q.get("mid"))
        in_ui = float(q.get("in_ui"))
        out_ui = float(q.get("out_ui"))
    except (TypeError, ValueError) as e:
        raise SolanaPaperError(f"quote missing numeric mid/in_ui/out_ui: {q!r}") from e
    if mid <= 0 or in_ui <= 0 or out_ui <= 0:
        raise SolanaPaperError(f"non-positive quote sizes/mid: mid={mid} in_ui={in_ui} out_ui={out_ui}")

    size_v = in_ui
    px = mid
    notional_out = out_ui

    fee_bps = q.get("fee_bps")
    fee_bps_f: Optional[float] = None
    fee_est: Optional[float] = None
    fee_label = "unavailable"
    if fee_bps is not None:
        try:
            fee_bps_f = float(fee_bps)
            fee_est = round(notional_out * fee_bps_f / 10_000.0, 8)
            fee_label = "API_feeBps"
        except (TypeError, ValueError):
            fee_bps_f = None
            fee_est = None
            fee_label = "unavailable_non_numeric"

    net_out = None
    if fee_est is not None:
        net_out = round(notional_out - fee_est, 8)
    net_mid = None
    if fee_bps_f is not None:
        net_mid = round(mid * (1.0 - fee_bps_f / 10_000.0), 8)

    prio = q.get("prioritization_fee_lamports")
    prio_label = q.get("prioritization_fee_label") or (
        "API_prioritizationFeeLamports_labeled_estimate"
        if prio is not None
        else "ESTIMATE_unavailable_no_field"
    )
    slip = q.get("slippage_bps")

    symbol = str(q.get("symbol") or "SOL/USDC")
    source = str(q.get("source") or "unknown")

    return {
        "venue": VENUE,
        "mode": "paper",
        "symbol": symbol,
        "side": side_l,
        "size": size_v,
        "px": px,
        "fill_price": px,
        "fee_estimate": fee_est,
        "fee_bps": fee_bps_f,
        "fee_bps_label": fee_label,
        "fee_rate": (fee_bps_f / 10_000.0) if fee_bps_f is not None else None,
        "notional_out_ui": round(notional_out, 8),
        "net_out_ui_after_fee_bps": net_out,
        "gross_mid": mid,
        "net_mid_after_fee_bps": net_mid,
        "in_amount": q.get("in_amount"),
        "out_amount": q.get("out_amount"),
        "in_ui": in_ui,
        "out_ui": out_ui,
        "input_mint": q.get("input_mint"),
        "output_mint": q.get("output_mint"),
        "price_impact_pct": q.get("price_impact_pct"),
        "slippage_bps": slip,
        "slippage_bps_label": "API_slippageBps" if slip is not None else "unavailable",
        "prioritization_fee_lamports": prio,
        "prioritization_fee_label": prio_label,
        "route_labels": q.get("route_labels") or [],
        "quote_source": source,
        "request_id": q.get("request_id"),
        "price_source": "jupiter_quote_mid",
        "ts": _utc_now_iso(),
        "leg": leg,
        "round_trip_id": round_trip_id,
        "live": False,
        "signed": False,
        "broadcast": False,
        "execution": "paper_fill_stub",
        "realized_pnl_thb": None,
        "pnl_basis": None,
        "note": (
            "paper fill from Jupiter quote — fee/net use API feeBps only when present; "
            "no invented PnL; never sign/send"
        ),
    }


def simulate_paper_fill(
    *,
    side: str = DEFAULT_SIDE,
    amount: str | int = DEFAULT_AMOUNT,
    input_mint: str = SOL_MINT,
    output_mint: str = USDC_MINT,
    slippage_bps: Optional[int] = None,
    timeout: float = DEFAULT_TIMEOUT,
    allow_fixture: bool = False,
    use_fixture: bool = False,
    quote: Optional[Union[JupiterOrderQuote, dict[str, Any]]] = None,
    leg: str = "single",
    round_trip_id: Optional[str] = None,
) -> dict[str, Any]:
    """Paper-simulate one Solana fill via Jupiter quote (or provided quote)."""
    if os.environ.get(LIVE_GATE_ENV, "").strip() in ("1", "true", "yes"):
        pass

    if quote is None:
        try:
            quote = fetch_jupiter_order_quote(
                input_mint=input_mint,
                output_mint=output_mint,
                amount=amount,
                slippage_bps=slippage_bps,
                timeout=timeout,
                allow_fixture=allow_fixture,
                use_fixture=use_fixture,
            )
        except JupiterQuoteError as e:
            raise SolanaPaperError(str(e)) from e

    return paper_fill_from_quote(
        quote,
        side=side,
        leg=leg,
        round_trip_id=round_trip_id,
    )


def paper_batch_fills(
    n: int = 5,
    *,
    side: str = DEFAULT_SIDE,
    amount: str | int = DEFAULT_AMOUNT,
    allow_fixture: bool = False,
    use_fixture: bool = False,
    timeout: float = DEFAULT_TIMEOUT,
    quote: Optional[Union[JupiterOrderQuote, dict[str, Any]]] = None,
    batch_id: Optional[str] = None,
) -> dict[str, Any]:
    """Produce N paper fills for edge_log / scorecard proof paths."""
    if n < 1:
        raise SolanaPaperError(f"n must be >= 1, got {n}")
    bid = batch_id or f"sol_paper_{uuid.uuid4().hex[:12]}"

    base_quote = quote
    if base_quote is None:
        try:
            base_quote = fetch_jupiter_order_quote(
                amount=amount,
                timeout=timeout,
                allow_fixture=allow_fixture,
                use_fixture=use_fixture,
            )
        except JupiterQuoteError as e:
            raise SolanaPaperError(str(e)) from e

    fills: list[dict[str, Any]] = []
    for i in range(n):
        fills.append(
            paper_fill_from_quote(
                base_quote,
                side=side if i % 2 == 0 else ("sell" if side == "buy" else "buy"),
                leg=f"batch_{i+1}",
                round_trip_id=f"{bid}_{i+1}",
            )
        )

    return {
        "ok": True,
        "mode": "paper",
        "live": False,
        "venue": VENUE,
        "batch_id": bid,
        "n": n,
        "fills": fills,
        "realized_pnl_thb": None,
        "pnl_basis": None,
        "note": (
            "paper batch from Jupiter quote — net/fee labeled from API feeBps only; "
            "no invented PnL; never sign/send"
        ),
    }


def paper_payload_for_edge_log(fill_or_batch: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize single fill or batch payload into fill dicts for edge_log."""
    if "fills" in fill_or_batch and isinstance(fill_or_batch["fills"], list):
        return [dict(f) for f in fill_or_batch["fills"] if isinstance(f, dict)]
    if "fill" in fill_or_batch and isinstance(fill_or_batch["fill"], dict):
        return [dict(fill_or_batch["fill"])]
    if fill_or_batch.get("side") and (
        fill_or_batch.get("px") is not None or fill_or_batch.get("fill_price") is not None
    ):
        return [dict(fill_or_batch)]
    raise SolanaPaperError("no paper fills found in payload")

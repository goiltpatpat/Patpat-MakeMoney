"""Binance TH thin paper stub — simulate fills WITHOUT sending orders.

Mirrors bitkub paper fill shape for edge_log venue tags: binance_th_paper.
Live execution is intentionally unimplemented and always refused.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Optional

from venues.binance_th.tape import (
    DEFAULT_SYMBOL,
    DEFAULT_TIMEOUT,
    BinanceTHError,
    _float_field,
    _normalize_symbol,
    fetch_public_ticker,
    ticker_to_tape_quote,
)

LIVE_GATE_ENV = "PMM_BINANCE_TH_LIVE_OK"
DEFAULT_FEE_RATE = 0.001  # documented paper taker-style estimate — not a live fee claim


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def refuse_live(*_args: Any, **_kwargs: Any) -> None:
    """Hard-refuse any live Binance TH order path."""
    raise BinanceTHError(
        f"Binance TH live orders are not implemented; paper/read-only only. "
        f"Future live path requires {LIVE_GATE_ENV}=1 (not honored here)."
    )


def derive_fill_px(row: dict[str, Any], side: str) -> tuple[float, str, Optional[float], Optional[float], Optional[float]]:
    side_l = (side or "buy").strip().lower()
    if side_l not in ("buy", "sell"):
        raise BinanceTHError(f"side must be buy|sell, got {side!r}")
    last = _float_field(row, "lastPrice", "price")
    ask = _float_field(row, "askPrice")
    bid = _float_field(row, "bidPrice")
    if side_l == "buy":
        fill_px = ask if ask and ask > 0 else last
        px_source = "ask" if ask and ask > 0 else "last"
    else:
        fill_px = bid if bid and bid > 0 else last
        px_source = "bid" if bid and bid > 0 else "last"
    if fill_px is None or fill_px <= 0:
        raise BinanceTHError(f"cannot derive paper fill from ticker: {row!r}")
    return float(fill_px), px_source, last, ask, bid


def paper_fill_from_ticker(
    row: dict[str, Any],
    *,
    side: str = "buy",
    symbol: str = DEFAULT_SYMBOL,
    size: Optional[float] = None,
    stake_thb: Optional[float] = None,
    fee_rate: float = DEFAULT_FEE_RATE,
    leg: str = "single",
    round_trip_id: Optional[str] = None,
) -> dict[str, Any]:
    """Paper fill from public ticker — no order sent. Venue tag: binance_th_paper."""
    sym = _normalize_symbol(symbol)
    side_l = (side or "buy").strip().lower()
    fill_px, px_source, last, ask, bid = derive_fill_px(row, side_l)

    if size is not None and stake_thb is not None:
        raise BinanceTHError("provide size OR stake_thb, not both")
    if size is None and stake_thb is None:
        size_v = None
        notional = None
        fee_est = None
    elif stake_thb is not None:
        if stake_thb <= 0:
            raise BinanceTHError(f"stake_thb must be > 0, got {stake_thb}")
        size_v = float(stake_thb) / fill_px
        notional = float(stake_thb)
        fee_est = round(notional * float(fee_rate), 6)
    else:
        assert size is not None
        if size <= 0:
            raise BinanceTHError(f"size must be > 0, got {size}")
        size_v = float(size)
        notional = size_v * fill_px
        fee_est = round(notional * float(fee_rate), 6)

    return {
        "venue": "binance_th_paper",
        "mode": "paper",
        "symbol": sym,
        "side": side_l,
        "size": size_v,
        "px": fill_px,
        "fill_price": fill_px,
        "fee_estimate": fee_est,
        "fee_rate": float(fee_rate) if fee_est is not None else None,
        "notional_thb": round(notional, 6) if notional is not None else None,
        "price_source": px_source,
        "last": last,
        "ask": ask,
        "bid": bid,
        "ts": _utc_now_iso(),
        "leg": leg,
        "round_trip_id": round_trip_id,
        "live": False,
        "note": "paper simulation only — no Binance TH order sent",
    }


def simulate_paper_order(
    *,
    side: str = "buy",
    symbol: str = DEFAULT_SYMBOL,
    timeout: float = DEFAULT_TIMEOUT,
    ticker_row: Optional[dict[str, Any]] = None,
    size: Optional[float] = None,
    stake_thb: Optional[float] = None,
    fee_rate: float = DEFAULT_FEE_RATE,
    leg: str = "single",
    round_trip_id: Optional[str] = None,
    use_fixture: Optional[bool] = None,
) -> dict[str, Any]:
    """Paper-simulate a Binance TH fill using public ticker. Never places orders."""
    if os.environ.get(LIVE_GATE_ENV, "").strip() in ("1", "true", "yes"):
        pass  # still paper-only

    row = (
        ticker_row
        if ticker_row is not None
        else fetch_public_ticker(symbol, timeout=timeout, use_fixture=use_fixture)
    )
    fill = paper_fill_from_ticker(
        row,
        side=side,
        symbol=symbol,
        size=size,
        stake_thb=stake_thb,
        fee_rate=fee_rate,
        leg=leg,
        round_trip_id=round_trip_id,
    )
    fill["tape"] = ticker_to_tape_quote(row, symbol=symbol).to_dict()
    return fill


def live_order_stub(*_args: Any, **_kwargs: Any) -> None:
    """Live order stub — always raises."""
    refuse_live()

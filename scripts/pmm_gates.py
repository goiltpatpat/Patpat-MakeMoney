#!/usr/bin/env python3
"""Patpat-MakeMoney impulse + skew gates (fail-closed). Feature flags default OFF."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

import requests

# Bucket-open BTC prints cached per market slug
_OPEN_PX: dict[str, float] = {}


@dataclass
class ImpulseResult:
    ok: bool
    status: str
    btc_open: Optional[float] = None
    btc_now: Optional[float] = None
    btc_move_usd: Optional[float] = None
    impulse_dir: Optional[str] = None  # UP | DOWN | FLAT
    flag_above_max_ref: bool = False
    detail: dict[str, Any] | None = None


@dataclass
class SkewResult:
    ok: bool
    status: str
    skew_side: Optional[str] = None  # UP | DOWN
    detail: dict[str, Any] | None = None


def fetch_binance_btcusdt(timeout: float = 5.0) -> tuple[float, float]:
    """Return (price, fetched_at_epoch). Fail raises."""
    r = requests.get(
        "https://api.binance.com/api/v3/ticker/price",
        params={"symbol": "BTCUSDT"},
        timeout=timeout,
    )
    r.raise_for_status()
    px = float(r.json()["price"])
    return px, time.time()


def bucket_open_ts_from_slug(slug: str) -> Optional[int]:
    # btc-updown-5m-<unix>
    try:
        return int(str(slug).rsplit("-", 1)[-1])
    except Exception:
        return None


def ensure_btc_open(slug: str, stale_sec: float = 8.0) -> float:
    """Return BTC open print for this slug; fetch/cache fail-closed via raise."""
    if slug in _OPEN_PX:
        return _OPEN_PX[slug]
    px, ts = fetch_binance_btcusdt()
    if time.time() - ts > stale_sec:
        raise RuntimeError("btc_print_stale_on_fetch")
    _OPEN_PX[slug] = px
    return px


def evaluate_impulse(
    slug: str,
    *,
    enabled: bool,
    btc_move_usd_min: float,
    btc_move_usd_max_reference: float = 100.0,
    stale_sec: float = 8.0,
) -> ImpulseResult:
    if not enabled:
        return ImpulseResult(ok=True, status="impulse_gate_disabled")

    try:
        btc_open = ensure_btc_open(slug, stale_sec=stale_sec)
        btc_now, fetched_at = fetch_binance_btcusdt()
        if time.time() - fetched_at > stale_sec:
            return ImpulseResult(ok=False, status="skip_impulse_feed_unavailable", detail={"reason": "stale"})
    except Exception as e:
        return ImpulseResult(
            ok=False,
            status="skip_impulse_feed_unavailable",
            detail={"error": str(e)},
        )

    move = float(btc_now) - float(btc_open)
    abs_move = abs(move)
    if abs_move < 1e-9:
        direction = "FLAT"
    elif move > 0:
        direction = "UP"
    else:
        direction = "DOWN"

    flag_max = abs_move > float(btc_move_usd_max_reference)

    if direction == "FLAT":
        return ImpulseResult(
            ok=False,
            status="skip_impulse_flat",
            btc_open=btc_open,
            btc_now=btc_now,
            btc_move_usd=move,
            impulse_dir=direction,
            flag_above_max_ref=flag_max,
        )

    if abs_move < float(btc_move_usd_min):
        return ImpulseResult(
            ok=False,
            status="skip_impulse_below_min",
            btc_open=btc_open,
            btc_now=btc_now,
            btc_move_usd=move,
            impulse_dir=direction,
            flag_above_max_ref=flag_max,
            detail={"btc_move_usd_min": btc_move_usd_min},
        )

    return ImpulseResult(
        ok=True,
        status="impulse_pass",
        btc_open=btc_open,
        btc_now=btc_now,
        btc_move_usd=move,
        impulse_dir=direction,
        flag_above_max_ref=flag_max,
    )


def evaluate_skew(
    up_ask: Optional[float],
    dn_ask: Optional[float],
    *,
    enabled: bool,
    impulse_dir: Optional[str],
    require_align: bool = True,
) -> SkewResult:
    if not enabled:
        return SkewResult(ok=True, status="skew_gate_disabled")

    if up_ask is None or dn_ask is None:
        return SkewResult(ok=False, status="skip_skew_ask_unavailable")

    up_v, dn_v = float(up_ask), float(dn_ask)
    if up_v == dn_v:
        return SkewResult(ok=False, status="skip_skew_tie", detail={"up_ask": up_v, "dn_ask": dn_v})

    skew_side = "UP" if up_v > dn_v else "DOWN"

    if require_align:
        if impulse_dir not in ("UP", "DOWN"):
            return SkewResult(
                ok=False,
                status="skip_skew_against_impulse",
                skew_side=skew_side,
                detail={"impulse_dir": impulse_dir},
            )
        if skew_side != impulse_dir:
            return SkewResult(
                ok=False,
                status="skip_skew_against_impulse",
                skew_side=skew_side,
                detail={"impulse_dir": impulse_dir, "up_ask": up_v, "dn_ask": dn_v},
            )

    return SkewResult(ok=True, status="skew_pass", skew_side=skew_side, detail={"up_ask": up_v, "dn_ask": dn_v})


def filter_candidates_by_impulse(
    candidates: list[tuple[str, float]],
    impulse_dir: Optional[str],
    *,
    enabled: bool,
) -> tuple[list[tuple[str, float]], Optional[str]]:
    """Return (filtered, skip_status_or_None)."""
    if not enabled or not impulse_dir:
        return candidates, None
    kept = [(s, p) for s, p in candidates if s == impulse_dir]
    if not kept and candidates:
        return [], "skip_threshold_anti_impulse_only"
    return kept, None

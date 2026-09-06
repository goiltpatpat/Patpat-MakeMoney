#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import time
import urllib.parse
import urllib.request
from typing import Any

from py_clob_client.client import ClobClient
from py_clob_client.constants import POLYGON
from py_clob_client.clob_types import ApiCreds

_LAST_POSITIONS_CACHE: dict[str, list[dict[str, Any]]] = {}


def _round_down(value: float, step: float) -> float:
    if step <= 0:
        return max(0.0, value)
    return max(0.0, (int(value / step)) * step)


def fetch_positions(user: str, limit: int = 500, retries: int = 4) -> list[dict[str, Any]]:
    url = "https://data-api.polymarket.com/positions?" + urllib.parse.urlencode(
        {"user": user, "sizeThreshold": 0, "limit": limit}
    )
    req = urllib.request.Request(url, headers={"User-Agent": "close-engine/1.1", "Accept": "application/json"})
    last_err = None
    for i in range(max(1, retries)):
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                arr = json.loads(resp.read().decode("utf-8"))
                if isinstance(arr, list):
                    _LAST_POSITIONS_CACHE[user] = arr
                    return arr
        except Exception as e:
            last_err = e
            time.sleep(0.5 * (2 ** i))
    if user in _LAST_POSITIONS_CACHE:
        return _LAST_POSITIONS_CACHE[user]
    if last_err:
        raise last_err
    return []


def get_token_size(user: str, token_id: str) -> float:
    arr = fetch_positions(user)
    for x in arr:
        if str(x.get("asset") or "") == str(token_id):
            try:
                return float(x.get("size") or 0.0)
            except Exception:
                return 0.0
    return 0.0


def build_client() -> ClobClient:
    c = ClobClient(
        host=os.getenv("PM_CLOB_BASE", "https://clob.polymarket.com"),
        chain_id=POLYGON,
        key=os.getenv("PM_PRIVATE_KEY"),
        signature_type=int(os.getenv("PM_SIGNATURE_TYPE", "2")),
        funder=os.getenv("PM_FUNDER"),
    )
    c.set_api_creds(
        ApiCreds(
            api_key=os.getenv("PM_API_KEY"),
            api_secret=os.getenv("PM_API_SECRET"),
            api_passphrase=os.getenv("PM_API_PASSPHRASE"),
        )
    )
    return c


def cancel_conflicting_orders(token_id: str) -> dict[str, Any]:
    try:
        c = build_client()
        resp = c.cancel_market_orders(asset_id=str(token_id))
        return {"ok": True, "response": resp}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def current_price_from_gamma(slug: str, side: str, fallback: float) -> float:
    try:
        url = "https://gamma-api.polymarket.com/markets?" + urllib.parse.urlencode({"slug": slug})
        arr = json.loads(urllib.request.urlopen(url, timeout=15).read().decode("utf-8"))
        if not arr:
            return fallback
        m = arr[0]
        outcomes = m.get("outcomes") or []
        prices = m.get("outcomePrices") or []
        if isinstance(outcomes, str):
            outcomes = json.loads(outcomes)
        if isinstance(prices, str):
            prices = json.loads(prices)
        idx = 0
        s = str(side).upper()
        for i, o in enumerate(outcomes):
            n = str(o).lower()
            if s == "UP" and ("up" in n or "yes" in n):
                idx = i
            if s == "DOWN" and ("down" in n or "no" in n):
                idx = i
        return float(prices[idx]) if idx < len(prices) else fallback
    except Exception:
        return fallback


def _market_readiness(token_id: str) -> dict[str, Any]:
    """Best-effort orderbook gate to avoid hard-failing unavailable books."""
    min_depth = float(os.getenv("PM_CLOSE_MIN_BOOK_DEPTH", "1"))
    max_spread = float(os.getenv("PM_CLOSE_MAX_SPREAD", "0.30"))
    try:
        pub = ClobClient(host=os.getenv("PM_CLOB_BASE", "https://clob.polymarket.com"), chain_id=POLYGON)
        book = pub.get_order_book(str(token_id))
        bids = getattr(book, "bids", []) or []
        asks = getattr(book, "asks", []) or []
        if not bids or not asks:
            return {"ready": False, "reason": "orderbook_empty", "bids": len(bids), "asks": len(asks)}
        best_bid = max(float(getattr(x, "price", 0) or 0) for x in bids)
        best_ask = min(float(getattr(x, "price", 0) or 0) for x in asks)
        best_bid_size = max(float(getattr(x, "size", 0) or 0) for x in bids if float(getattr(x, "price", 0) or 0) == best_bid)
        best_ask_size = max(float(getattr(x, "size", 0) or 0) for x in asks if float(getattr(x, "price", 0) or 0) == best_ask)
        spread = max(0.0, best_ask - best_bid)
        if best_bid_size <= 0 or best_ask_size <= 0 or (best_bid_size + best_ask_size) < min_depth:
            return {
                "ready": False,
                "reason": "insufficient_top_depth",
                "best_bid": best_bid,
                "best_ask": best_ask,
                "best_bid_size": best_bid_size,
                "best_ask_size": best_ask_size,
                "spread": spread,
            }
        if spread > max_spread:
            return {
                "ready": False,
                "reason": "spread_too_wide",
                "best_bid": best_bid,
                "best_ask": best_ask,
                "best_bid_size": best_bid_size,
                "best_ask_size": best_ask_size,
                "spread": spread,
            }
        return {
            "ready": True,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "best_bid_size": best_bid_size,
            "best_ask_size": best_ask_size,
            "spread": spread,
        }
    except Exception as e:
        emsg = str(e).lower()
        if "orderbook" in emsg and ("does not exist" in emsg or "no orderbook" in emsg):
            return {"ready": False, "reason": "orderbook_missing", "error": str(e)}
        if "no match" in emsg:
            return {"ready": False, "reason": "no_match", "error": str(e)}
        return {"ready": False, "reason": "orderbook_unavailable", "error": str(e)}


def try_close(repo: str, token_id: str, shares: float, limit_price: float | None, reason: str) -> tuple[bool, dict[str, Any] | None, str]:
    cmd = [
        ".venv/bin/python",
        "scripts/close_position_marketable.py",
        "--repo",
        ".",
        "--token-id",
        str(token_id),
        "--shares",
        str(shares),
        "--reason",
        str(reason),
        "--retries",
        "1",
    ]
    if limit_price is not None:
        cmd += ["--limit-price", str(limit_price)]
    p = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, env=os.environ.copy())
    out = (p.stdout or "").strip()
    if p.returncode != 0:
        return False, None, (p.stderr or out or "close_failed")[-2000:]
    if not out:
        return False, None, "empty_close_output"
    try:
        obj = json.loads(out)
    except Exception:
        return False, None, "invalid_close_json"
    ok = bool(obj.get("ok"))
    return ok, obj, ("" if ok else str(obj.get("last_error") or obj))


def run_close_engine(repo: str, user: str, token_id: str, slug: str, side: str, target_shares: float, ref_price: float, reason: str = "MANUAL") -> dict[str, Any]:
    target = max(0.0, float(target_shares))
    cancel_info = None
    if str(reason).upper() in ("SL", "STOP_LOSS", "TIME_EXIT"):
        cancel_info = cancel_conflicting_orders(token_id)

    min_close_shares = float(os.getenv("PM_MIN_CLOSE_SHARES", "0.001"))
    size_step = float(os.getenv("PM_CLOSE_SIZE_STEP", "0.0001"))
    probe_frac = min(0.8, max(0.1, float(os.getenv("PM_CLOSE_IOC_PROBE_FRAC", "0.30"))))

    before = get_token_size(user, token_id)
    if before <= 0:
        return {"ok": True, "reason": "already_flat", "before_size": before, "after_size": 0.0, "attempts": [], "position_snapshot_before": before, "position_snapshot_after": 0.0, "cancel_info": cancel_info}

    if before < min_close_shares:
        return {
            "ok": True,
            "reason": "closed_dust",
            "before_size": before,
            "after_size": before,
            "dust_threshold": min_close_shares,
            "attempts": [],
            "position_snapshot_before": before,
            "position_snapshot_after": before,
            "cancel_info": cancel_info,
        }

    to_close_raw = min(before, target if target > 0 else before)
    to_close = _round_down(to_close_raw, size_step)
    if to_close < min_close_shares:
        return {
            "ok": True,
            "reason": "close_skipped_zero_amount",
            "before_size": before,
            "after_size": before,
            "target_close": to_close,
            "target_close_raw": to_close_raw,
            "size_step": size_step,
            "dust_threshold": min_close_shares,
            "attempts": [],
            "position_snapshot_before": before,
            "position_snapshot_after": before,
            "cancel_info": cancel_info,
        }

    readiness = _market_readiness(token_id)
    if not readiness.get("ready"):
        base = max(5.0, float(os.getenv("PM_CLOSE_DEFER_BASE_SEC", "8")))
        max_delay = max(base, float(os.getenv("PM_CLOSE_DEFER_MAX_SEC", "60")))
        retry_after = min(max_delay, base + random.uniform(0.0, base))
        return {
            "ok": False,
            "deferred": True,
            "reason": "close_deferred_market_unavailable",
            "before_size": before,
            "after_size": before,
            "target_close": to_close,
            "market_readiness": readiness,
            "retry_after_sec": round(retry_after, 2),
            "cancel_info": cancel_info,
        }

    cur = current_price_from_gamma(slug, side, ref_price)
    ladder = [
        max(0.01, min(0.99, cur * 0.995)),
        max(0.01, min(0.99, cur * 0.98)),
        max(0.01, min(0.99, cur * 0.95)),
        max(0.01, min(0.99, cur * 0.90)),
    ]

    attempts: list[dict[str, Any]] = []
    remaining = to_close

    probe = _round_down(max(min_close_shares, to_close * probe_frac), size_step)
    if probe >= min_close_shares and probe < remaining:
        ok, obj, err = try_close(repo, token_id, probe, None, reason)
        time.sleep(0.8)
        after_size = get_token_size(user, token_id)
        reduced = max(0.0, before - after_size)
        remaining = max(0.0, _round_down(to_close - reduced, size_step))
        attempts.append(
            {
                "phase": "probe_ioc",
                "close_shares": probe,
                "limit_price": None,
                "ok": ok,
                "error": err,
                "reported": obj,
                "after_size": after_size,
                "remaining": remaining,
            }
        )

    for px in ladder:
        if remaining <= max(1e-6, min_close_shares / 5):
            break
        leg = _round_down(remaining, size_step)
        if leg < min_close_shares:
            break
        ok, obj, err = try_close(repo, token_id, leg, px, reason)
        time.sleep(0.8)
        after_size = get_token_size(user, token_id)
        reduced = max(0.0, before - after_size)
        remaining = max(0.0, _round_down(to_close - reduced, size_step))
        attempts.append(
            {
                "phase": "limit_ladder",
                "close_shares": leg,
                "limit_price": px,
                "ok": ok,
                "error": err,
                "reported": obj,
                "after_size": after_size,
                "remaining": remaining,
            }
        )

    if remaining >= min_close_shares:
        ok, obj, err = try_close(repo, token_id, remaining, None, reason)
        time.sleep(0.8)
        after_size = get_token_size(user, token_id)
        remaining = max(0.0, _round_down(after_size, size_step))
        attempts.append({
            "phase": "final_ioc",
            "close_shares": remaining,
            "limit_price": None,
            "ok": ok,
            "error": err,
            "reported": obj,
            "after_size": after_size,
            "remaining": remaining,
        })

    final_size = get_token_size(user, token_id)
    return {
        "ok": final_size <= max(1e-6, before - to_close + 1e-6),
        "before_size": before,
        "target_close": to_close,
        "target_close_raw": to_close_raw,
        "size_step": size_step,
        "after_size": final_size,
        "position_snapshot_before": before,
        "position_snapshot_after": final_size,
        "attempts": attempts,
        "cancel_info": cancel_info,
        "exit_reason": reason,
        "market_readiness": readiness,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--user", default=os.getenv("PM_FUNDER") or os.getenv("PM_ADDRESS") or "")
    ap.add_argument("--token-id", required=True)
    ap.add_argument("--market-slug", required=True)
    ap.add_argument("--side", required=True)
    ap.add_argument("--shares", type=float, required=True)
    ap.add_argument("--ref-price", type=float, default=0.5)
    ap.add_argument("--reason", default="MANUAL")
    args = ap.parse_args()

    if not args.user:
        raise SystemExit("Missing --user (or PM_FUNDER/PM_ADDRESS)")

    out = run_close_engine(args.repo, args.user, args.token_id, args.market_slug, args.side, args.shares, args.ref_price, args.reason)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import urllib.parse
import urllib.request
import os


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def fetch_json(url: str, params: dict[str, Any] | None = None, timeout: int = 10):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "pm-live-exit-manager/1.2"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_jsonish(v):
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return [x.strip() for x in v.split(",") if x.strip()]
    return []


def get_token_size(user: str, token_id: str) -> float | None:
    if not user or not token_id:
        return None
    try:
        arr = fetch_json("https://data-api.polymarket.com/positions", {"user": user, "sizeThreshold": 0, "limit": 500})
        if isinstance(arr, list):
            for x in arr:
                if str(x.get("asset") or "") == str(token_id):
                    return float(x.get("size") or 0.0)
        return 0.0
    except Exception:
        return None


def current_price_for_side(market: dict, side: str) -> float:
    outcomes = parse_jsonish(market.get("outcomes") or [])
    prices = parse_jsonish(market.get("outcomePrices") or [])
    if len(prices) < 2:
        raise RuntimeError("Missing outcome prices")

    idx = 0
    side_u = str(side).upper()
    for i, o in enumerate(outcomes):
        name = str(o).lower()
        if side_u == "UP" and ("up" in name or "yes" in name):
            idx = i
            break
        if side_u == "DOWN" and ("down" in name or "no" in name):
            idx = i
            break
    return float(prices[idx])


def append_jsonl(path: str, payload: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def close_with_retries(repo: str, user: str, token_id: str, market_slug: str, side: str, shares: float, reason: str, retries: int, backoff_sec: float, ref_price: float):
    """Delegates close execution to close_engine (API inventory sync + readiness gate + two-phase close)."""
    last_err = None
    deferred_obj = None
    for attempt in range(1, retries + 1):
        cmd = [
            ".venv/bin/python",
            "scripts/close_engine.py",
            "--repo", repo,
            "--user", user,
            "--token-id", str(token_id),
            "--market-slug", str(market_slug),
            "--side", str(side),
            "--shares", str(shares),
            "--ref-price", str(ref_price),
            "--reason", str(reason),
        ]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0:
            last_err = (p.stderr or p.stdout or "close_engine_failed")[-2000:]
        else:
            try:
                obj = json.loads((p.stdout or "").strip() or "{}")
            except Exception:
                obj = {"ok": False, "error": "invalid_close_engine_json", "stdout": (p.stdout or "")[-1000:]}
            if obj.get("ok") is True:
                return {"close_engine": obj, "order_post_result": {"status": "matched", "success": True}}, attempt, None, False
            if obj.get("reason") == "already_flat":
                return {"close_engine": obj, "order_post_result": {"status": "matched", "success": True}}, attempt, None, False
            if obj.get("deferred") is True or obj.get("reason") == "close_deferred_market_unavailable":
                deferred_obj = obj
                last_err = str(obj.get("market_readiness") or obj.get("reason") or obj)
                break
            last_err = str(obj.get("error") or obj.get("reason") or obj)
        if attempt < retries:
            sleep_for = backoff_sec * (2 ** (attempt - 1)) + random.uniform(0.0, 0.5)
            time.sleep(sleep_for)
    if deferred_obj is not None:
        return {"close_engine": deferred_obj, "deferred": True}, 1, last_err, True
    return None, retries, last_err, False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default="runtime/pm_open_position.json")
    ap.add_argument("--gamma-base", default="https://gamma-api.polymarket.com")
    ap.add_argument("--sl-pct", type=float, default=0.35)
    ap.add_argument("--tp-pct", type=float, default=0.25)
    ap.add_argument("--trail-arm-pct", type=float, default=0.15)
    ap.add_argument("--trail-giveback-pct", type=float, default=0.08)
    ap.add_argument("--time-exit-sec", type=int, default=90)
    ap.add_argument("--log", default="runtime/pm_live_exits.log")
    ap.add_argument("--error-log", default="runtime/pm_live_exits_errors.log")
    ap.add_argument("--close-retries", type=int, default=3)
    ap.add_argument("--close-backoff-sec", type=float, default=1.5)
    ap.add_argument("--force-close", action="store_true")
    ap.add_argument("--expiry-clear-sec", type=int, default=300)
    ap.add_argument("--user", default=os.getenv("PM_FUNDER") or os.getenv("PM_ADDRESS") or "")
    args = ap.parse_args()

    sp = Path(args.state)
    if not sp.exists():
        print(json.dumps({"action": "noop", "reason": "no_open_position"}))
        return

    st = json.loads(sp.read_text(encoding="utf-8"))
    market_slug = st.get("market_slug")
    token_id = st.get("token_id")
    shares = float(st.get("shares") or 0.0)
    entry_price = float(st.get("entry_price") or 0.0)
    side = str(st.get("side") or "")
    expiry_ts = int(st.get("expiry_ts") or 0)

    if not market_slug or not token_id or shares <= 0 or entry_price <= 0:
        print(json.dumps({"action": "noop", "reason": "invalid_state"}))
        return

    sl_pct = float(st.get("sl_pct", args.sl_pct))
    tp_pct = float(st.get("tp_pct", args.tp_pct))
    trail_arm_pct = float(st.get("trail_arm_pct", args.trail_arm_pct))
    trail_giveback_pct = float(st.get("trail_giveback_pct", args.trail_giveback_pct))
    time_exit_sec = int(st.get("time_exit_sec", args.time_exit_sec))

    now_ts = int(now_utc().timestamp())
    time_left = max(0, expiry_ts - now_ts) if expiry_ts > 0 else 999999

    if expiry_ts > 0 and now_ts >= expiry_ts:
        event = {
            "ts": now_utc().isoformat().replace("+00:00", "Z"),
            "action": "expired_market_redeem_required",
            "market_slug": market_slug,
            "token_id": token_id,
            "shares": shares,
            "expiry_ts": expiry_ts,
            "expired_ago_sec": max(0, now_ts - expiry_ts),
        }
        append_jsonl(args.log, event)
        sp.unlink(missing_ok=True)
        print(json.dumps(event, ensure_ascii=False))
        return

    if expiry_ts > 0 and (now_ts - expiry_ts) > max(0, int(args.expiry_clear_sec)):
        event = {
            "ts": now_utc().isoformat().replace("+00:00", "Z"),
            "action": "expired_state_cleared",
            "market_slug": market_slug,
            "token_id": token_id,
            "shares": shares,
            "expiry_ts": expiry_ts,
            "expired_ago_sec": (now_ts - expiry_ts),
        }
        append_jsonl(args.log, event)
        sp.unlink(missing_ok=True)
        print(json.dumps(event, ensure_ascii=False))
        return

    market_data_ok = False
    market_data_error = None
    cur = None
    peak = float(st.get("peak_price") or entry_price)
    pnl_pct = None

    try:
        arr = fetch_json(f"{args.gamma_base.rstrip('/')}/markets", {"slug": market_slug})
        if isinstance(arr, list) and arr:
            market = arr[0]
            cur = current_price_for_side(market, side)
            market_data_ok = True
            if cur > peak:
                peak = cur
                st["peak_price"] = peak
                sp.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
            pnl_pct = (cur - entry_price) / entry_price
        else:
            market_data_error = "market_not_found"
    except Exception as e:
        market_data_error = str(e)

    reason = None
    if args.force_close:
        reason = "force_close"
    elif time_left <= max(1, int(time_exit_sec)):
        reason = "time_exit"
    elif market_data_ok and pnl_pct is not None:
        if pnl_pct <= -abs(sl_pct):
            reason = "stop_loss"
        elif pnl_pct >= abs(tp_pct):
            reason = "take_profit"
        elif peak >= entry_price * (1 + abs(trail_arm_pct)) and cur <= peak * (1 - abs(trail_giveback_pct)):
            reason = "trailing_stop"
    else:
        reason = "close_degraded_mode"

    if not reason:
        print(
            json.dumps(
                {
                    "action": "hold",
                    "market_slug": market_slug,
                    "entry_price": entry_price,
                    "current_price": cur,
                    "peak_price": peak,
                    "pnl_pct": pnl_pct,
                    "time_left_sec": time_left,
                },
                ensure_ascii=False,
            )
        )
        return

    band_pct = float(st.get("close_price_band_pct", 0.03))
    fallback_limit_price = None
    if cur is not None:
        fallback_limit_price = max(0.01, min(0.99, float(cur) * (1.0 - abs(band_pct))))
    elif entry_price > 0:
        fallback_limit_price = max(0.01, min(0.99, float(entry_price) * (1.0 - abs(band_pct) * 2.0)))

    api_token_size = get_token_size(args.user, token_id) if args.user else None
    if args.user and (api_token_size is not None and api_token_size <= 1e-6):
        checks = [api_token_size]
        for _ in range(4):
            time.sleep(0.8)
            checks.append(get_token_size(args.user, token_id))
        if all((v is not None and v <= 1e-6) for v in checks):
            event = {
                "ts": now_utc().isoformat().replace("+00:00", "Z"),
                "action": "onchain_position_not_found",
                "market_slug": market_slug,
                "token_id": token_id,
                "local_shares": shares,
                "api_token_size": api_token_size,
                "api_zero_checks": checks,
            }
            append_jsonl(args.log, event)
            sp.unlink(missing_ok=True)
            print(json.dumps(event, ensure_ascii=False))
            return
        nz = [v for v in checks if isinstance(v, (int, float)) and v > 1e-6]
        if nz:
            api_token_size = nz[-1]

    size_step = float(os.getenv("PM_CLOSE_SIZE_STEP", "0.0001"))
    min_close_shares = float(os.getenv("PM_MIN_CLOSE_SHARES", "0.001"))
    shares_base = min(shares, api_token_size) if (api_token_size is not None and api_token_size > 0) else shares
    shares_to_close = max(0.0, int(shares_base / size_step) * size_step)

    if shares_to_close < min_close_shares:
        event = {
            "ts": now_utc().isoformat().replace("+00:00", "Z"),
            "action": "close_skipped_zero_amount",
            "reason": reason,
            "market_slug": market_slug,
            "token_id": token_id,
            "shares": shares,
            "shares_to_close": shares_to_close,
            "api_token_size": api_token_size,
            "size_step": size_step,
            "min_close_shares": min_close_shares,
        }
        append_jsonl(args.log, event)
        print(json.dumps(event, ensure_ascii=False))
        return

    next_retry_ts = int(st.get("close_next_retry_ts") or 0)
    if not args.force_close and next_retry_ts > now_ts:
        print(json.dumps({
            "action": "close_deferred_market_unavailable",
            "market_slug": market_slug,
            "token_id": token_id,
            "retry_in_sec": max(0, next_retry_ts - now_ts),
        }, ensure_ascii=False))
        return

    close_res, attempts_used, close_error, was_deferred = close_with_retries(
        repo=".",
        user=args.user,
        token_id=token_id,
        market_slug=market_slug,
        side=side,
        shares=shares_to_close,
        reason=str(reason).upper(),
        retries=max(1, int(args.close_retries)),
        backoff_sec=max(0.1, float(args.close_backoff_sec)),
        ref_price=(cur if cur is not None else entry_price),
    )

    if was_deferred:
        engine = (close_res or {}).get("close_engine") or {}
        retry_after = float(engine.get("retry_after_sec") or random.uniform(8.0, 18.0))
        st["close_next_retry_ts"] = int(now_ts + max(2, retry_after))
        sp.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
        event = {
            "ts": now_utc().isoformat().replace("+00:00", "Z"),
            "action": "close_deferred_market_unavailable",
            "reason": reason,
            "market_slug": market_slug,
            "token_id": token_id,
            "shares": shares,
            "shares_to_close": shares_to_close,
            "api_token_size": api_token_size,
            "close_attempts": attempts_used,
            "close_error": close_error,
            "close_result": close_res,
            "retry_after_sec": retry_after,
            "degraded_mode": (not market_data_ok),
            "market_data_error": market_data_error,
        }
        append_jsonl(args.log, event)
        print(json.dumps(event, ensure_ascii=False))
        return

    post = (close_res or {}).get("order_post_result") or {}
    close_ok = close_res is not None and (str(post.get("status", "")).lower() == "matched" and post.get("success") is True)

    size_after_close = None
    if close_ok and args.user:
        for _ in range(3):
            size_after_close = get_token_size(args.user, token_id)
            if size_after_close is None:
                break
            if size_after_close <= 1e-6:
                break
            time.sleep(0.8)

    event = {
        "ts": now_utc().isoformat().replace("+00:00", "Z"),
        "action": "close" if close_ok else "close_failed",
        "reason": reason,
        "market_slug": market_slug,
        "token_id": token_id,
        "shares": shares,
        "shares_to_close": shares_to_close,
        "api_token_size": api_token_size,
        "entry_price": entry_price,
        "current_price": cur,
        "peak_price": peak,
        "pnl_pct_at_close_signal": pnl_pct,
        "sl_pct": sl_pct,
        "tp_pct": tp_pct,
        "trail_arm_pct": trail_arm_pct,
        "trail_giveback_pct": trail_giveback_pct,
        "time_exit_sec": time_exit_sec,
        "time_left_sec": time_left,
        "degraded_mode": (not market_data_ok),
        "market_data_error": market_data_error,
        "close_ok": close_ok,
        "close_attempts": attempts_used,
        "fallback_limit_price": fallback_limit_price,
        "close_price_band_pct": band_pct,
        "reduce_only_template": True,
        "post_only": False,
        "close_error": close_error,
        "close_result": close_res,
        "postcheck_user": args.user if args.user else None,
        "postcheck_token_size_after_close": size_after_close,
    }

    append_jsonl(args.log, event)

    if not close_ok:
        append_jsonl(
            args.error_log,
            {
                "ts": event["ts"],
                "market_slug": market_slug,
                "token_id": token_id,
                "shares": shares,
                "shares_to_close": shares_to_close,
                "api_token_size": api_token_size,
                "reason": reason,
                "market_data_error": market_data_error,
                "close_error": close_error,
                "close_attempts": attempts_used,
            },
        )
        fail_cnt = int(st.get("close_fail_count") or 0) + 1
        st["close_fail_count"] = fail_cnt
        debounce_sec = int(os.getenv("PM_MANUAL_ESCALATION_DEBOUNCE_SEC", "900"))
        last_escalated = str(st.get("manual_escalated_at") or "")
        last_escalated_ts = 0
        if last_escalated:
            try:
                last_escalated_ts = int(datetime.fromisoformat(last_escalated.replace("Z", "+00:00")).timestamp())
            except Exception:
                last_escalated_ts = 0
        should_escalate = (
            fail_cnt >= int(os.getenv("PM_MANUAL_ESCALATION_FAILS", "3"))
            and (now_ts - last_escalated_ts) >= debounce_sec
        )
        if should_escalate:
            st["manual_escalated_at"] = now_utc().isoformat().replace("+00:00", "Z")
            append_jsonl(
                args.error_log,
                {
                    "ts": event["ts"],
                    "action": "manual_intervention_required",
                    "market_slug": market_slug,
                    "token_id": token_id,
                    "time_left_sec": time_left,
                    "close_error": close_error,
                    "close_fail_count": fail_cnt,
                },
            )
        sp.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")

    if close_ok:
        sp.unlink(missing_ok=True)

    print(json.dumps(event, ensure_ascii=False))


if __name__ == "__main__":
    main()

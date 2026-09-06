#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
import time


def clamp(x: float, a: float, b: float) -> float:
    return max(a, min(b, x))


def main():
    raw = sys.stdin.read().strip()
    if not raw:
        raise SystemExit("empty exec payload")
    obj = json.loads(raw)

    slug = str(obj.get("market_slug") or "")
    m = re.search(r"(\d+)$", slug)
    bucket = int(m.group(1)) if m else int(time.time())
    expiry = bucket + 900

    side = str((obj.get("signal") or {}).get("side") or "").upper()
    entry = float((obj.get("pm_prices") or {}).get("up" if side == "UP" else "down") or 0)
    post = (obj.get("order_post_result") or {})
    shares = float(post.get("takingAmount") or 0)
    cost = float(post.get("makingAmount") or 0)
    vol = float((obj.get("signal") or {}).get("hl_volatility") or 0.0)

    sl = clamp(float(os.getenv("PM_SL_BASE", "0.30")) + float(os.getenv("PM_SL_VOL_MULT", "220")) * vol,
               float(os.getenv("PM_SL_MIN", "0.20")), float(os.getenv("PM_SL_MAX", "0.50")))
    tp = clamp(float(os.getenv("PM_TP_BASE", "0.20")) + float(os.getenv("PM_TP_VOL_MULT", "180")) * vol,
               float(os.getenv("PM_TP_MIN", "0.12")), float(os.getenv("PM_TP_MAX", "0.45")))
    tr_arm = clamp(float(os.getenv("PM_TRAIL_ARM_BASE", "0.12")) + float(os.getenv("PM_TRAIL_ARM_VOL_MULT", "120")) * vol,
                   float(os.getenv("PM_TRAIL_ARM_MIN", "0.08")), float(os.getenv("PM_TRAIL_ARM_MAX", "0.35")))
    tr_gb = clamp(float(os.getenv("PM_TRAIL_GIVEBACK_BASE", "0.06")) + float(os.getenv("PM_TRAIL_GIVEBACK_VOL_MULT", "70")) * vol,
                  float(os.getenv("PM_TRAIL_GIVEBACK_MIN", "0.04")), float(os.getenv("PM_TRAIL_GIVEBACK_MAX", "0.20")))

    state = {
        "opened_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "market_slug": slug,
        "token_id": obj.get("token_id"),
        "side": side,
        "entry_price": entry,
        "peak_price": entry,
        "shares": shares,
        "cost_usd": cost,
        "expiry_ts": expiry,
        "hl_volatility": vol,
        "sl_pct": round(sl, 6),
        "tp_pct": round(tp, 6),
        "trail_arm_pct": round(tr_arm, 6),
        "trail_giveback_pct": round(tr_gb, 6),
        "time_exit_sec": int(os.getenv("PM_TIME_EXIT_SEC", "90")),
        "close_price_band_pct": float(os.getenv("PM_CLOSE_PRICE_BAND_PCT", "0.03")),
    }
    print(json.dumps(state, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path


def run_close(repo: Path, token_id: str, shares: float, limit_price: float | None):
    cmd = ["./scripts/run_pm_live_trade.sh", "close", "--close-token-id", str(token_id), "--close-shares", str(shares)]
    if limit_price is not None:
        cmd += ["--close-limit-price", str(limit_price)]
    p = subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True, env=os.environ.copy())
    out = (p.stdout or "").strip()
    if p.returncode != 0:
        return False, {"error": (p.stderr or out or "close_failed")[-2000:]}
    if not out:
        return False, {"error": "empty_close_output"}
    try:
        obj = json.loads(out)
    except Exception:
        return False, {"error": "invalid_close_json", "stdout_tail": out[-1200:]}
    post = obj.get("order_post_result") or {}
    ok = str(post.get("status", "")).lower() == "matched" and post.get("success") is True
    return ok, obj


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--token-id", required=True)
    ap.add_argument("--shares", type=float, required=True)
    ap.add_argument("--reason", default="MANUAL")
    ap.add_argument("--limit-price", type=float, default=0.0)
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--backoff-sec", type=float, default=0.8)
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    retries = max(1, int(args.retries))
    min_close_shares = float(os.getenv("PM_MIN_CLOSE_SHARES", "0.001"))
    size_step = float(os.getenv("PM_CLOSE_SIZE_STEP", "0.0001"))
    shares_eff = max(0.0, int(float(args.shares) / size_step) * size_step)
    if shares_eff < min_close_shares:
        print(json.dumps({
            "ok": True,
            "reason": "close_skipped_zero_amount",
            "requested_shares": float(args.shares),
            "shares_effective": shares_eff,
            "size_step": size_step,
            "min_close_shares": min_close_shares,
            "attempts": [],
        }, ensure_ascii=False, indent=2))
        return

    attempts = []
    last = None
    for i in range(1, retries + 1):
        ok, obj = run_close(repo, args.token_id, shares_eff, args.limit_price if args.limit_price > 0 else None)
        attempts.append({"attempt": i, "ok": ok, "result": obj})
        if ok:
            print(json.dumps({"ok": True, "reason": args.reason, "attempts": attempts}, ensure_ascii=False, indent=2))
            return
        last = obj
        if i < retries:
            time.sleep(args.backoff_sec * (2 ** (i - 1)))

    print(json.dumps({"ok": False, "reason": args.reason, "attempts": attempts, "last_error": last}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

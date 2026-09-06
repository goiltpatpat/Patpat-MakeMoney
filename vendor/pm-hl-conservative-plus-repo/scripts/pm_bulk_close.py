#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Position:
    asset: str
    slug: str
    title: str
    outcome: str
    size: float
    cur_price: float
    redeemable: bool


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        k = k.strip()
        v = v.strip()
        if k and k not in os.environ:
            os.environ[k] = v


def fetch_positions(user: str, size_threshold: float = 0.0, limit: int = 500) -> list[Position]:
    params = {
        "user": user,
        "sizeThreshold": size_threshold,
        "limit": max(1, min(500, int(limit))),
        "offset": 0,
    }
    url = "https://data-api.polymarket.com/positions?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "pm-bulk-close/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        arr = json.loads(resp.read().decode("utf-8"))

    out: list[Position] = []
    for x in arr:
        out.append(
            Position(
                asset=str(x.get("asset") or ""),
                slug=str(x.get("slug") or ""),
                title=str(x.get("title") or ""),
                outcome=str(x.get("outcome") or ""),
                size=float(x.get("size") or 0.0),
                cur_price=float(x.get("curPrice") or 0.0),
                redeemable=bool(x.get("redeemable") or False),
            )
        )
    return out


def close_one(repo: Path, token_id: str, shares: float, limit_price: float | None) -> dict[str, Any]:
    cmd = [
        str(repo / ".venv/bin/python"),
        str(repo / "src/live/pm_live_trade_runner.py"),
        "--execute",
        "--close-token-id",
        token_id,
        "--close-shares",
        f"{shares:.6f}",
    ]
    if limit_price and limit_price > 0:
        cmd += ["--close-limit-price", f"{limit_price:.6f}"]

    p = subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True)
    if p.returncode != 0:
        return {"ok": False, "error": (p.stderr or p.stdout or "command_failed").strip()[-1500:]}

    try:
        obj = json.loads(p.stdout)
    except Exception:
        return {"ok": False, "error": "invalid_json", "stdout": p.stdout[-1200:]}

    post = (obj.get("order_post_result") or {})
    ok = (str(post.get("status", "")).lower() == "matched" and post.get("success") is True)
    return {"ok": ok, "result": obj}


def main() -> None:
    ap = argparse.ArgumentParser(description="Bulk close Polymarket positions via CLOB API")
    ap.add_argument("--repo", default=".", help="Path to pm-hl-conservative-plus-repo")
    ap.add_argument("--user", default="", help="Polymarket wallet/proxy address (default: PM_FUNDER or PM_ADDRESS)")
    ap.add_argument("--max", type=int, default=20, help="Max positions to process")
    ap.add_argument("--min-size", type=float, default=0.01, help="Skip positions smaller than this")
    ap.add_argument("--include-redeemable", action="store_true", help="Also try to close redeemable positions")
    ap.add_argument("--band-pct", type=float, default=0.03, help="Limit close price band (curPrice * (1-band))")
    ap.add_argument("--execute", action="store_true", help="Actually submit close orders")
    ap.add_argument("--json-out", default="runtime/pm_bulk_close_report.json")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    _load_dotenv(repo / ".env")

    user = args.user.strip() or _env("PM_FUNDER") or _env("PM_ADDRESS")
    if not user:
        raise SystemExit("Missing user address. Provide --user or set PM_FUNDER/PM_ADDRESS in .env")

    positions = fetch_positions(user=user, size_threshold=0.0, limit=500)
    candidates: list[Position] = []
    for p in positions:
        if p.size < args.min_size:
            continue
        if (not args.include_redeemable) and p.redeemable:
            continue
        if not p.asset:
            continue
        candidates.append(p)

    candidates = candidates[: max(0, int(args.max))]

    actions = []
    for p in candidates:
        limit_price = max(0.01, min(0.99, p.cur_price * (1.0 - abs(args.band_pct)))) if p.cur_price > 0 else None
        row = {
            "slug": p.slug,
            "title": p.title,
            "outcome": p.outcome,
            "token_id": p.asset,
            "shares": p.size,
            "cur_price": p.cur_price,
            "redeemable": p.redeemable,
            "limit_price": limit_price,
            "mode": "execute" if args.execute else "dry",
        }
        if args.execute:
            row["close"] = close_one(repo=repo, token_id=p.asset, shares=p.size, limit_price=limit_price)
        actions.append(row)

    report = {
        "user": user,
        "positions_total": len(positions),
        "candidates": len(candidates),
        "executed": bool(args.execute),
        "actions": actions,
    }

    out_path = repo / args.json_out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

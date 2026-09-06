#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

from py_clob_client.client import ClobClient
from py_clob_client.constants import POLYGON
from py_clob_client.clob_types import ApiCreds, OpenOrderParams, BalanceAllowanceParams, AssetType


def load_env(dotenv: Path) -> None:
    if not dotenv.exists():
        return
    for ln in dotenv.read_text(encoding="utf-8", errors="replace").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        if k and k not in os.environ:
            os.environ[k] = v


def fetch_positions(user: str, retries: int = 4) -> list[dict]:
    url = "https://data-api.polymarket.com/positions?" + urllib.parse.urlencode({"user": user, "sizeThreshold": 0, "limit": 500})
    req = urllib.request.Request(url, headers={"User-Agent": "pm-reconcile/1.0", "Accept": "application/json"})
    last = None
    for i in range(max(1, retries)):
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                arr = json.loads(resp.read().decode("utf-8"))
                return arr if isinstance(arr, list) else []
        except Exception as e:
            last = str(e)
            time.sleep(0.6 * (2 ** i))
    raise RuntimeError(last or "positions_fetch_failed")


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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--write", default="runtime/pm_reconcile_report.json")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    load_env(repo / ".env")

    user = os.getenv("PM_FUNDER") or os.getenv("PM_ADDRESS") or ""
    if not user:
        raise SystemExit("Missing PM_FUNDER/PM_ADDRESS")

    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    out = {"ts": ts, "user": user}

    # API truth: positions
    try:
        positions = fetch_positions(user)
        out["positions_count"] = len(positions)
        out["positions_open"] = sum(1 for x in positions if not x.get("redeemable"))
        out["positions_redeemable"] = sum(1 for x in positions if x.get("redeemable"))
        out["positions_open_value"] = round(sum(float(x.get("currentValue") or 0) for x in positions if not x.get("redeemable")), 6)
        out["positions_redeemable_value"] = round(sum(float(x.get("currentValue") or 0) for x in positions if x.get("redeemable")), 6)
    except Exception as e:
        out["positions_error"] = str(e)
        positions = []

    c = build_client()

    # Open orders
    try:
        oo = c.get_orders(OpenOrderParams())
        if isinstance(oo, dict):
            rows = oo.get("data") or oo.get("orders") or []
        else:
            rows = oo or []
        out["open_orders_count"] = len(rows)
    except Exception as e:
        out["open_orders_error"] = str(e)

    # Allowance overview: collateral + open token ids
    allow = {"collateral": None, "conditional": []}
    try:
        p = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=int(os.getenv("PM_SIGNATURE_TYPE", "2")))
        allow["collateral"] = c.get_balance_allowance(p)
    except Exception as e:
        allow["collateral_error"] = str(e)

    token_ids = []
    for x in positions:
        if x.get("redeemable"):
            continue
        t = str(x.get("asset") or "")
        if t:
            token_ids.append(t)
    token_ids = list(dict.fromkeys(token_ids))[:30]

    for t in token_ids:
        rec = {"token_id": t}
        try:
            p = BalanceAllowanceParams(asset_type=AssetType.CONDITIONAL, token_id=t, signature_type=int(os.getenv("PM_SIGNATURE_TYPE", "2")))
            rec["value"] = c.get_balance_allowance(p)
        except Exception as e:
            rec["error"] = str(e)
        allow["conditional"].append(rec)

    out["allowance"] = allow

    path = repo / args.write
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # append line log for monitoring
    line_path = repo / "runtime/pm_reconcile.log"
    with line_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(out, ensure_ascii=False) + "\n")

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

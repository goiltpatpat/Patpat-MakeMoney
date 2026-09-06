#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
import urllib.parse
import urllib.request

TS_RE = re.compile(r"^\[(?P<ts>[^\]]+)\]\s+(?P<msg>.*)$")


@dataclass
class ExecAttempt:
    ts: datetime
    market: str


@dataclass
class FillTrade:
    ts: datetime
    market: str
    side: str
    shares: float
    cost: float
    order_id: str


@dataclass
class FailedEvent:
    ts: datetime
    market: str
    reason: str


def parse_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def fetch_json(url: str, params: dict[str, Any] | None = None, timeout: int = 10):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "pm-exec-summary/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_log(log_path: Path):
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()

    attempts: list[ExecAttempt] = []
    failed_events: list[FailedEvent] = []
    fills: list[FillTrade] = []

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        m = TS_RE.match(line)
        if not m:
            i += 1
            continue

        ts_raw = m.group("ts")
        msg = m.group("msg")
        try:
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            i += 1
            continue

        if msg.startswith("execute market="):
            market = msg.split("market=", 1)[1].strip()
            attempts.append(ExecAttempt(ts=ts, market=market))

            # Optional JSON block with order_post_result on success
            j = i + 1
            while j < n and not lines[j].strip():
                j += 1
            if j < n and lines[j].lstrip().startswith("{"):
                brace = 0
                buf: list[str] = []
                k = j
                while k < n:
                    part = lines[k]
                    brace += part.count("{")
                    brace -= part.count("}")
                    buf.append(part)
                    if brace == 0:
                        break
                    k += 1
                if brace == 0:
                    try:
                        obj = json.loads("\n".join(buf))
                        post = obj.get("order_post_result") or {}
                        if str(post.get("status", "")).lower() == "matched" and post.get("success") is True:
                            fills.append(
                                FillTrade(
                                    ts=ts,
                                    market=str(obj.get("market_slug") or market),
                                    side=str((obj.get("signal") or {}).get("side") or "").upper(),
                                    shares=parse_float(post.get("takingAmount")),
                                    cost=parse_float(post.get("makingAmount")),
                                    order_id=str(post.get("orderID") or ""),
                                )
                            )
                    except Exception:
                        pass
                    i = k

        elif msg.startswith("execute_failed market="):
            market = msg.split("market=", 1)[1].strip()
            prev_window = "\n".join(lines[max(0, i - 40):i]).lower()
            reason = "other"
            if "no orders found to match" in prev_window or "no match" in prev_window:
                reason = "no_liquidity_match"
            elif "not enough balance / allowance" in prev_window:
                reason = "balance_or_allowance"
            elif "request exception" in prev_window or "connecttimeout" in prev_window or "handshake operation timed out" in prev_window:
                reason = "network_or_timeout"
            elif "service not ready" in prev_window:
                reason = "service_not_ready"
            failed_events.append(FailedEvent(ts=ts, market=market, reason=reason))

        i += 1

    return attempts, fills, failed_events


def summarize_day(log_path: Path, tz_name: str, gamma_base: str):
    tz = ZoneInfo(tz_name)
    now_local = datetime.now(tz)
    attempts, fills, failed_events = parse_log(log_path)

    # Filter by local day
    def in_today(dt_utc: datetime) -> bool:
        d = dt_utc.astimezone(tz)
        return d.date() == now_local.date()

    attempts_d = [a for a in attempts if in_today(a.ts)]
    fills_d = [f for f in fills if in_today(f.ts)]
    failed_d = [e for e in failed_events if in_today(e.ts)]
    fail_reasons: dict[str, int] = {}
    for e in failed_d:
        fail_reasons[e.reason] = fail_reasons.get(e.reason, 0) + 1

    # Build market resolution cache
    resolved_pnl = 0.0
    resolved_count = 0
    unresolved_count = 0
    unresolved_cost = 0.0
    per_trade = []
    market_cache: dict[str, dict[str, Any]] = {}

    for tr in fills_d:
        payload = market_cache.get(tr.market)
        if payload is None:
            try:
                arr = fetch_json(f"{gamma_base.rstrip('/')}/markets", {"slug": tr.market})
                payload = arr[0] if isinstance(arr, list) and arr else {}
            except Exception:
                payload = {}
            market_cache[tr.market] = payload

        outcomes = payload.get("outcomes") or []
        prices = payload.get("outcomePrices") or []
        if isinstance(outcomes, str):
            try:
                outcomes = json.loads(outcomes)
            except Exception:
                outcomes = []
        if isinstance(prices, str):
            try:
                prices = json.loads(prices)
            except Exception:
                prices = []

        winner_idx = None
        for idx, p in enumerate(prices):
            try:
                if float(p) >= 0.999:
                    winner_idx = idx
                    break
            except Exception:
                pass

        if winner_idx is None:
            unresolved_count += 1
            unresolved_cost += tr.cost
            per_trade.append({
                "market": tr.market,
                "side": tr.side,
                "cost": tr.cost,
                "shares": tr.shares,
                "status": "unresolved",
                "realized_pnl": None,
            })
            continue

        winner = str(outcomes[winner_idx]).upper() if winner_idx < len(outcomes) else ""
        win = ("UP" in winner and tr.side == "UP") or (("DOWN" in winner or "NO" in winner) and tr.side == "DOWN")
        payout = tr.shares if win else 0.0
        pnl = payout - tr.cost
        resolved_pnl += pnl
        resolved_count += 1
        per_trade.append({
            "market": tr.market,
            "side": tr.side,
            "cost": tr.cost,
            "shares": tr.shares,
            "status": "resolved",
            "winner": winner,
            "realized_pnl": round(pnl, 6),
        })

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "timezone": tz_name,
        "date": str(now_local.date()),
        "attempts": len(attempts_d),
        "filled": len(fills_d),
        "not_filled": max(0, len(attempts_d) - len(fills_d)),
        "failed_markets_count": len(failed_d),
        "failure_reasons": fail_reasons,
        "resolved_fills": resolved_count,
        "unresolved_fills": unresolved_count,
        "realized_pnl_estimate_usd": round(resolved_pnl, 6),
        "capital_in_unresolved_usd": round(unresolved_cost, 6),
        "fills": per_trade,
    }
    return summary


def to_markdown(s: dict[str, Any]) -> str:
    lines = []
    lines.append(f"# PM execution auto-summary ({s['date']} {s['timezone']})")
    lines.append("")
    lines.append(f"- attempts: **{s['attempts']}**")
    lines.append(f"- filled: **{s['filled']}**")
    lines.append(f"- not filled: **{s['not_filled']}**")
    lines.append(f"- realized PnL estimate (resolved only): **{s['realized_pnl_estimate_usd']:.4f} USD**")
    lines.append(f"- unresolved fills: **{s['unresolved_fills']}** (capital: {s['capital_in_unresolved_usd']:.4f} USD)")
    if s.get("failure_reasons"):
        fr = ", ".join(f"{k}={v}" for k, v in sorted(s["failure_reasons"].items()))
        lines.append(f"- failure reasons: {fr}")
    lines.append("")
    lines.append(f"_generated: {s['generated_at_utc']}_")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Daily execution summary from pm_live_worker.log")
    ap.add_argument("--log", default="runtime/pm_live_worker.log")
    ap.add_argument("--tz", default="Europe/Moscow")
    ap.add_argument("--gamma-base", default="https://gamma-api.polymarket.com")
    ap.add_argument("--write-json", default="")
    ap.add_argument("--write-md", default="")
    args = ap.parse_args()

    summary = summarize_day(Path(args.log), args.tz, args.gamma_base)

    if args.write_json:
        p = Path(args.write_json)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.write_md:
        p = Path(args.write_md)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(to_markdown(summary), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

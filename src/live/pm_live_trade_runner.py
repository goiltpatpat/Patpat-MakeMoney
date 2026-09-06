#!/usr/bin/env python3
"""
Patpat-MakeMoney live trade runner (guarded).

Derived from Novals83/polymarket-hl-strategy; owned and developed in this repo.

- Uses Gamma API to resolve active BTC 15m market + token ids.
- Builds direction signal from Hyperliquid short momentum.
- Places a capped BUY market order through py-clob-client.

Safety defaults:
- max notional hard cap = $15 unless explicitly changed
- dry-run by default
- optional --execute to actually submit

Auth modes supported:
1) API creds mode (L2): PM_API_KEY + PM_API_SECRET + PM_API_PASSPHRASE
2) Private key mode (derive creds): PM_PRIVATE_KEY (+ optional PM_SIGNATURE_TYPE, PM_FUNDER)

Required from user for real execution:
- either full API creds (key+secret+passphrase), or private key.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Tuple

import time
import urllib.parse
import urllib.request
from urllib.error import URLError
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, MarketOrderArgs, OrderType, OrderArgs, BalanceAllowanceParams, AssetType
from py_clob_client.constants import POLYGON


def _get_json(url: str, params: dict | None = None, timeout: int = 25, retries: int = 3):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    last_err = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            last_err = e
            if i < retries - 1:
                time.sleep(1.2 * (i + 1))
    raise RuntimeError(f"GET failed: {url} :: {last_err}")


def _post_json(url: str, payload: dict, timeout: int = 25, retries: int = 3):
    body = json.dumps(payload).encode("utf-8")
    last_err = None
    for i in range(retries):
        try:
            req = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            last_err = e
            if i < retries - 1:
                time.sleep(1.2 * (i + 1))
    raise RuntimeError(f"POST failed: {url} :: {last_err}")


def parse_jsonish(v):
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return [x.strip() for x in v.split(",") if x.strip()]
    return []


def _extract_balance_and_min_allowance(raw: dict | None) -> tuple[float | None, float | None]:
    if not isinstance(raw, dict):
        return None, None
    bal = None
    try:
        if raw.get("balance") is not None:
            bal = float(raw.get("balance"))
    except Exception:
        bal = None
    min_allow = None
    allows = raw.get("allowances")
    if isinstance(allows, dict) and allows:
        vals = []
        for v in allows.values():
            try:
                vals.append(float(v))
            except Exception:
                pass
        if vals:
            min_allow = min(vals)
    return bal, min_allow


def _deep_find_number(obj, keys: tuple[str, ...]) -> float | None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            lk = str(k).lower()
            if any(t in lk for t in keys):
                try:
                    return float(v)
                except Exception:
                    pass
            got = _deep_find_number(v, keys)
            if got is not None:
                return got
    elif isinstance(obj, list):
        for it in obj:
            got = _deep_find_number(it, keys)
            if got is not None:
                return got
    return None


def get_gamma_market(gamma_base: str, slug: Optional[str] = None) -> dict | None:
    gamma_base = gamma_base.rstrip("/")
    if slug:
        arr = _get_json(f"{gamma_base}/markets", params={"slug": slug}, timeout=25, retries=4)
        return arr[0] if isinstance(arr, list) and arr else None

    now = int(datetime.now(timezone.utc).timestamp())
    bucket = (now // 900) * 900
    for ts in [bucket, bucket - 900, bucket + 900]:
        s = f"btc-updown-15m-{ts}"
        arr = _get_json(f"{gamma_base}/markets", params={"slug": s}, timeout=25, retries=4)
        if isinstance(arr, list) and arr:
            return arr[0]
    return None


def extract_market_tokens(market: dict) -> Tuple[float, float, str, str]:
    outcomes = parse_jsonish(market.get("outcomes") or [])
    prices = parse_jsonish(market.get("outcomePrices") or [])
    token_ids = parse_jsonish(market.get("clobTokenIds") or [])

    if not outcomes or len(prices) < 2 or len(token_ids) < 2:
        raise RuntimeError("Gamma market payload missing outcomes/prices/clobTokenIds")

    up = down = None
    up_token = down_token = None
    for i, n in enumerate(outcomes):
        nm = str(n).lower()
        p = float(prices[i]) if i < len(prices) else None
        tid = str(token_ids[i]) if i < len(token_ids) else None
        if p is None or not tid:
            continue
        if ("up" in nm or "yes" in nm) and up is None:
            up = p
            up_token = tid
        if ("down" in nm or "no" in nm) and down is None:
            down = p
            down_token = tid

    if up is None or down is None:
        # fallback by index
        up, down = float(prices[0]), float(prices[1])
        up_token, down_token = str(token_ids[0]), str(token_ids[1])

    return up, down, up_token, down_token


def hl_signal(symbol: str = "BTC", lookback_sec: int = 180) -> Tuple[str, float, float, float, float]:
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = now_ms - lookback_sec * 1000
    payload = {
        "type": "candleSnapshot",
        "req": {
            "coin": symbol.upper(),
            "interval": "1m",
            "startTime": start_ms,
            "endTime": now_ms,
        },
    }
    candles = _post_json("https://api.hyperliquid.xyz/info", payload, timeout=20, retries=4) or []
    if len(candles) < 2:
        raise RuntimeError("Not enough HL candles for signal")

    mids = [((float(c["o"]) + float(c["c"])) / 2.0) for c in candles]
    start_mid = mids[0]
    end_mid = mids[-1]
    mom = (end_mid - start_mid) / start_mid if start_mid else 0.0
    rets = []
    for i in range(1, len(mids)):
        prev = mids[i - 1]
        cur = mids[i]
        rets.append((cur - prev) / prev if prev else 0.0)
    if rets:
        mu = sum(rets) / len(rets)
        var = sum((r - mu) ** 2 for r in rets) / len(rets)
        vol = var ** 0.5
    else:
        vol = 0.0
    side = "UP" if mom >= 0 else "DOWN"
    return side, mom, start_mid, end_mid, vol


@dataclass
class TradeConfig:
    gamma_base: str
    clob_base: str
    market_slug: str
    symbol: str

    start_equity: float
    risk_frac: float
    max_notional_usd: float

    pm_api_key: str
    pm_api_secret: str
    pm_api_passphrase: str
    pm_private_key: str
    pm_funder: str
    pm_signature_type: int

    execute: bool


def _best_bid_ask(book) -> Tuple[float | None, float | None, float, float]:
    bids = getattr(book, "bids", []) or []
    asks = getattr(book, "asks", []) or []

    best_bid = None
    best_bid_size = 0.0
    for b in bids:
        p = float(getattr(b, "price", 0) or 0)
        s = float(getattr(b, "size", 0) or 0)
        if best_bid is None or p > best_bid:
            best_bid = p
            best_bid_size = s

    best_ask = None
    best_ask_size = 0.0
    for a in asks:
        p = float(getattr(a, "price", 0) or 0)
        s = float(getattr(a, "size", 0) or 0)
        if best_ask is None or p < best_ask:
            best_ask = p
            best_ask_size = s

    return best_bid, best_ask, best_bid_size, best_ask_size


def build_client(cfg: TradeConfig) -> Tuple[ClobClient, str]:
    # API creds mode (L2 without private key for order signing is often insufficient,
    # but supported if user already has credentials + key mode in environment)
    if cfg.pm_private_key:
        client = ClobClient(
            host=cfg.clob_base,
            chain_id=POLYGON,
            key=cfg.pm_private_key,
            signature_type=cfg.pm_signature_type,
            funder=(cfg.pm_funder or None),
        )
        if cfg.pm_api_key and cfg.pm_api_secret and cfg.pm_api_passphrase:
            creds = ApiCreds(
                api_key=cfg.pm_api_key,
                api_secret=cfg.pm_api_secret,
                api_passphrase=cfg.pm_api_passphrase,
            )
        else:
            creds = client.create_or_derive_api_creds()
        client.set_api_creds(creds)
        return client, "private_key"

    if cfg.pm_api_key and cfg.pm_api_secret and cfg.pm_api_passphrase:
        creds = ApiCreds(
            api_key=cfg.pm_api_key,
            api_secret=cfg.pm_api_secret,
            api_passphrase=cfg.pm_api_passphrase,
        )
        client = ClobClient(host=cfg.clob_base, chain_id=POLYGON, creds=creds)
        return client, "api_creds_only"

    raise RuntimeError(
        "Missing auth. Provide PM_PRIVATE_KEY or full PM_API_KEY+PM_API_SECRET+PM_API_PASSPHRASE"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gamma-base", default=os.getenv("GAMMA_BASE_URL", "https://gamma-api.polymarket.com"))
    ap.add_argument("--clob-base", default=os.getenv("PM_CLOB_BASE", "https://clob.polymarket.com"))
    ap.add_argument("--market-slug", default=os.getenv("PM_MARKET_SLUG", ""))
    ap.add_argument("--symbol", default=os.getenv("SYMBOL", "BTC"))

    ap.add_argument("--start-equity", type=float, default=float(os.getenv("START_EQUITY", "1000")))
    ap.add_argument("--risk-frac", type=float, default=float(os.getenv("BASE_RISK_FRAC", "0.03")))
    ap.add_argument("--max-notional-usd", type=float, default=float(os.getenv("PM_MAX_NOTIONAL_USD", "15")))

    ap.add_argument("--pm-api-key", default=os.getenv("PM_API_KEY", ""))
    ap.add_argument("--pm-api-secret", default=os.getenv("PM_API_SECRET", ""))
    ap.add_argument("--pm-api-passphrase", default=os.getenv("PM_API_PASSPHRASE", ""))
    ap.add_argument("--pm-private-key", default=os.getenv("PM_PRIVATE_KEY", ""))
    ap.add_argument("--pm-funder", default=os.getenv("PM_FUNDER", os.getenv("PM_ADDRESS", "")))
    ap.add_argument("--pm-signature-type", type=int, default=int(os.getenv("PM_SIGNATURE_TYPE", "1")))

    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--force-side", choices=["UP", "DOWN", "up", "down"], default="")
    ap.add_argument("--close-token-id", default="")
    ap.add_argument("--close-shares", type=float, default=0.0)
    ap.add_argument("--close-limit-price", type=float, default=0.0)
    args = ap.parse_args()

    cfg = TradeConfig(
        gamma_base=args.gamma_base,
        clob_base=args.clob_base,
        market_slug=args.market_slug,
        symbol=args.symbol,
        start_equity=args.start_equity,
        risk_frac=args.risk_frac,
        max_notional_usd=args.max_notional_usd,
        pm_api_key=args.pm_api_key,
        pm_api_secret=args.pm_api_secret,
        pm_api_passphrase=args.pm_api_passphrase,
        pm_private_key=args.pm_private_key,
        pm_funder=args.pm_funder,
        pm_signature_type=args.pm_signature_type,
        execute=args.execute,
    )

    if args.close_token_id and args.close_shares > 0:
        result = {
            "mode": "close_execute" if cfg.execute else "close_dry_run",
            "token_id": args.close_token_id,
            "close_shares": float(args.close_shares),
            "close_side": "SELL",
            "close_path": "limit" if (args.close_limit_price and args.close_limit_price > 0) else "market",
        }
        if not cfg.execute:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return

        client, auth_mode = build_client(cfg)
        ot = os.getenv('PM_CLOSE_ORDER_TYPE', os.getenv('PM_ORDER_TYPE', 'FAK')).upper()
        order_type = OrderType.FOK if ot == 'FOK' else (OrderType.FAK if ot == 'FAK' else OrderType.GTC)

        close_shares_eff = float(args.close_shares)
        # pre-check and optional auto-restore allowance for conditional token on SELL close path
        try:
            sig_type = int(cfg.pm_signature_type)
            ba = BalanceAllowanceParams(asset_type=AssetType.CONDITIONAL, token_id=args.close_token_id, signature_type=sig_type)
            before = client.get_balance_allowance(ba)
            bal_before_raw, allow_before_raw = _extract_balance_and_min_allowance(before)
            need_shares = float(args.close_shares)
            # Polymarket conditional balances are 1e6 precision integer values
            need_raw = need_shares * 1_000_000.0
            auto_restore = str(os.getenv("PM_AUTO_RESTORE_ALLOWANCE", "1")).lower() not in ("0", "false", "no")
            restored = None
            if auto_restore and (allow_before_raw is None or allow_before_raw + 1e-6 < need_raw):
                restored = client.update_balance_allowance(ba)
            after = client.get_balance_allowance(ba)
            bal_after_raw, allow_after_raw = _extract_balance_and_min_allowance(after)
            result["allowance_precheck"] = {
                "needed_shares": need_shares,
                "needed_raw": need_raw,
                "before": before,
                "after": after,
                "balance_before_raw": bal_before_raw,
                "allowance_before_raw": allow_before_raw,
                "balance_after_raw": bal_after_raw,
                "allowance_after_raw": allow_after_raw,
                "auto_restore": auto_restore,
                "restored": restored,
            }
            # If on-chain token balance is lower than requested shares, downsize close request to available size.
            if bal_after_raw is not None and bal_after_raw + 1e-6 < need_raw:
                close_shares_eff = max(0.0, bal_after_raw / 1_000_000.0)
                result["close_shares_adjusted_by_balance"] = close_shares_eff
            if allow_after_raw is not None and allow_after_raw + 1e-6 < (close_shares_eff * 1_000_000.0):
                raise RuntimeError(f"insufficient token allowance for close: allowance_raw={allow_after_raw} need_raw={close_shares_eff * 1_000_000.0}")
        except Exception as e:
            result["allowance_precheck_error"] = str(e)
            strict_allow = str(os.getenv("PM_CLOSE_REQUIRE_ALLOWANCE_OK", "0")).lower() not in ("0", "false", "no")
            if strict_allow:
                print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
                return

        if close_shares_eff <= 1e-8:
            result["close_skipped"] = "zero_effective_shares"
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return

        if args.close_limit_price and args.close_limit_price > 0:
            px = max(0.01, min(0.99, float(args.close_limit_price)))
            # size is shares for a limit SELL
            order_args = OrderArgs(
                token_id=args.close_token_id,
                price=px,
                size=float(close_shares_eff),
                side="SELL",
            )
            signed = client.create_order(order_args)
            try:
                posted = client.post_order(signed, order_type)
            except Exception as e:
                # auto-restore conditional allowance and retry once on close path
                if "not enough balance / allowance" in str(e).lower():
                    ba2 = BalanceAllowanceParams(asset_type=AssetType.CONDITIONAL, token_id=args.close_token_id, signature_type=int(cfg.pm_signature_type))
                    client.update_balance_allowance(ba2)
                    posted = client.post_order(signed, order_type)
                else:
                    raise
        else:
            # market close path
            order_args = MarketOrderArgs(
                token_id=args.close_token_id,
                amount=float(close_shares_eff),
                side="SELL",
            )
            signed = client.create_market_order(order_args)
            try:
                posted = client.post_order(signed, order_type)
            except Exception as e:
                if "not enough balance / allowance" in str(e).lower():
                    ba2 = BalanceAllowanceParams(asset_type=AssetType.CONDITIONAL, token_id=args.close_token_id, signature_type=int(cfg.pm_signature_type))
                    client.update_balance_allowance(ba2)
                    posted = client.post_order(signed, order_type)
                else:
                    raise
        result["auth_mode"] = auth_mode
        result["order_post_result"] = posted
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return

    market = get_gamma_market(cfg.gamma_base, cfg.market_slug or None)
    if not market:
        raise SystemExit("No active market found")

    up, down, up_token, down_token = extract_market_tokens(market)
    force_side = str(getattr(args, "force_side", "") or "").upper()
    mom = hl_start = hl_now = hl_vol = None
    side = None
    try:
        side, mom, hl_start, hl_now, hl_vol = hl_signal(cfg.symbol)
    except Exception as e:
        # Desk force-side may proceed without HL; otherwise open cannot choose a side.
        if force_side not in ("UP", "DOWN"):
            raise
        result_hl_error = str(e)
    else:
        result_hl_error = None
    # Patpat-MakeMoney desk: when --force-side is set, caller owns entry side.
    if force_side in ("UP", "DOWN"):
        side = force_side
    if side not in ("UP", "DOWN"):
        raise RuntimeError("entry side unresolved")

    desired_notional = cfg.start_equity * cfg.risk_frac
    stake_usd = min(desired_notional, cfg.max_notional_usd)
    # hard fail-safe
    stake_usd = min(stake_usd, 15.0)

    token_id = up_token if side == "UP" else down_token
    entry_price = up if side == "UP" else down

    # blacklist / entry-quality filters
    min_price = float(os.getenv("PM_ENTRY_PRICE_MIN", "0.03"))
    max_price = float(os.getenv("PM_ENTRY_PRICE_MAX", "0.97"))
    max_spread = float(os.getenv("PM_MAX_SPREAD", "0.03"))
    min_top_ask_notional = float(os.getenv("PM_MIN_TOP_ASK_NOTIONAL_USD", "20"))

    filter_blocked = False
    filter_reasons = []
    book_info = {}

    if entry_price < min_price or entry_price > max_price:
        filter_blocked = True
        filter_reasons.append("price_extreme")

    # public book check (liquidity/spread)
    try:
        pub_client = ClobClient(host=cfg.clob_base, chain_id=POLYGON)
        book = pub_client.get_order_book(token_id)
        best_bid, best_ask, best_bid_size, best_ask_size = _best_bid_ask(book)
        spread = (best_ask - best_bid) if (best_ask is not None and best_bid is not None) else None
        top_ask_notional = (best_ask or 0.0) * (best_ask_size or 0.0)
        book_info = {
            "best_bid": best_bid,
            "best_ask": best_ask,
            "best_bid_size": best_bid_size,
            "best_ask_size": best_ask_size,
            "spread": spread,
            "top_ask_notional": top_ask_notional,
        }
        if spread is None or spread > max_spread:
            filter_blocked = True
            filter_reasons.append("wide_spread")
        if top_ask_notional < min_top_ask_notional:
            filter_blocked = True
            filter_reasons.append("thin_top_of_book")
    except Exception as e:
        filter_blocked = True
        filter_reasons.append(f"orderbook_unavailable:{e}")

    result = {
        "mode": "execute" if cfg.execute else "dry_run",
        "market_slug": market.get("slug"),
        "market_id": market.get("id"),
        "question": market.get("question"),
        "signal": {"side": side, "hl_momentum": mom, "hl_start_mid": hl_start, "hl_now_mid": hl_now, "hl_volatility": hl_vol, "force_side": force_side or None, "hl_error": result_hl_error},
        "pm_prices": {"up": up, "down": down},
        "entry_price": entry_price,
        "token_id": token_id,
        "stake_usd": stake_usd,
        "max_notional_guard": 15.0,
        "entry_filters": {
            "blocked": filter_blocked,
            "reasons": filter_reasons,
            "price_min": min_price,
            "price_max": max_price,
            "max_spread": max_spread,
            "min_top_ask_notional_usd": min_top_ask_notional,
            "book": book_info,
        },
    }

    if not cfg.execute:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if filter_blocked:
        result["blocked"] = True
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    client, auth_mode = build_client(cfg)
    order_args = MarketOrderArgs(
        token_id=token_id,
        amount=float(stake_usd),
        side="BUY",
    )
    signed = client.create_market_order(order_args)
    ot = os.getenv('PM_ORDER_TYPE', 'FOK').upper()
    order_type = OrderType.FOK if ot == 'FOK' else (OrderType.FAK if ot == 'FAK' else OrderType.GTC)
    posted = client.post_order(signed, order_type)

    result["auth_mode"] = auth_mode
    result["order_post_result"] = posted
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()

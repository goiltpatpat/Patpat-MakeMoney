"""Bitkub paper-first adapter skeleton (public ticker only — NO live orders)."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Optional

from venues import TapeQuote

# Public market data (v3). Live trading endpoints are intentionally NOT wired.
BITKUB_TICKER_URL = "https://api.bitkub.com/api/v3/market/ticker"
DEFAULT_SYMBOL = "BTC_THB"
DEFAULT_TIMEOUT = 8.0
USER_AGENT = "Patpat-MakeMoney/venues-bitkub-paper"

# Live gate documented for a future adapter — never honored by this module.
LIVE_GATE_ENV = "PMM_BITKUB_LIVE_OK"


class BitkubPaperError(RuntimeError):
    """Raised when Bitkub public ticker / paper simulation fails."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_json(url: str, params: Optional[dict] = None, timeout: float = DEFAULT_TIMEOUT) -> Any:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise BitkubPaperError(f"HTTP {e.code} from {url}") from e
    except urllib.error.URLError as e:
        raise BitkubPaperError(f"network error fetching {url}: {e.reason}") from e
    except TimeoutError as e:
        raise BitkubPaperError(f"timeout fetching {url}") from e
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise BitkubPaperError(f"invalid JSON from {url}") from e


def _normalize_symbol(symbol: str) -> str:
    s = (symbol or DEFAULT_SYMBOL).strip().upper().replace("-", "_")
    # Accept THB_BTC legacy form → BTC_THB (v3 uses base_quote like btc_thb)
    if s.startswith("THB_"):
        base = s.split("_", 1)[1]
        s = f"{base}_THB"
    return s


def fetch_public_ticker(
    symbol: str = DEFAULT_SYMBOL,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """
    Fetch Bitkub public ticker for one symbol (api/v3/market/ticker?sym=...).

    Returns the raw ticker object (dict) for the symbol.
    """
    sym = _normalize_symbol(symbol)
    data = _get_json(BITKUB_TICKER_URL, params={"sym": sym.lower()}, timeout=timeout)

    row: Optional[dict] = None
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            item_sym = str(item.get("symbol") or item.get("sym") or "").upper()
            if item_sym == sym or item_sym.replace("-", "_") == sym:
                row = item
                break
        if row is None and len(data) == 1 and isinstance(data[0], dict):
            row = data[0]
    elif isinstance(data, dict):
        # Some deployments return { "BTC_THB": {...} } or a single object
        if "last" in data or "lowest_ask" in data or "lowestAsk" in data:
            row = data
        else:
            for k, v in data.items():
                if not isinstance(v, dict):
                    continue
                key = str(k).upper().replace("-", "_")
                if key == sym or key == f"THB_{sym.split('_')[0]}" or key.endswith(sym.split("_")[0]):
                    row = v
                    row = {**v, "symbol": v.get("symbol", k)}
                    break
            if row is None:
                # first dict value fallback when sym filtered server-side
                for v in data.values():
                    if isinstance(v, dict) and ("last" in v or "lowestAsk" in v or "lowest_ask" in v):
                        row = dict(v)
                        break

    if not isinstance(row, dict):
        raise BitkubPaperError(f"ticker not found for {sym}: payload={data!r}")
    return row


def ticker_to_tape_quote(row: dict[str, Any], symbol: str = DEFAULT_SYMBOL) -> TapeQuote:
    """Map a Bitkub ticker row to TapeQuote using last price."""
    sym = _normalize_symbol(symbol)
    try:
        last = float(row.get("last") or row.get("lastPrice") or 0)
    except (TypeError, ValueError) as e:
        raise BitkubPaperError(f"bad last in ticker: {row!r}") from e
    if last <= 0:
        raise BitkubPaperError(f"non-positive last for {sym}: {last}")
    return TapeQuote(
        venue="bitkub_public",
        symbol=sym,
        price=last,
        ts=_utc_now_iso(),
        source="bitkub_v3_market_ticker",
    )


def paper_fill_from_ticker(
    row: dict[str, Any],
    *,
    side: str = "buy",
    symbol: str = DEFAULT_SYMBOL,
) -> dict[str, Any]:
    """
    Compute a paper fill from public ticker.

    buy → fill at lowest ask (or last); sell → fill at highest bid (or last).
    """
    sym = _normalize_symbol(symbol)
    side_l = (side or "buy").strip().lower()
    if side_l not in ("buy", "sell"):
        raise BitkubPaperError(f"side must be buy|sell, got {side!r}")

    def _f(*keys: str) -> Optional[float]:
        for k in keys:
            if k in row and row[k] is not None:
                try:
                    return float(row[k])
                except (TypeError, ValueError):
                    continue
        return None

    last = _f("last", "lastPrice")
    ask = _f("lowest_ask", "lowestAsk", "ask")
    bid = _f("highest_bid", "highestBid", "bid")
    if side_l == "buy":
        fill_px = ask if ask and ask > 0 else last
        px_source = "ask" if ask and ask > 0 else "last"
    else:
        fill_px = bid if bid and bid > 0 else last
        px_source = "bid" if bid and bid > 0 else "last"
    if fill_px is None or fill_px <= 0:
        raise BitkubPaperError(f"cannot derive paper fill from ticker: {row!r}")

    return {
        "venue": "bitkub",
        "mode": "paper",
        "symbol": sym,
        "side": side_l,
        "fill_price": fill_px,
        "price_source": px_source,
        "last": last,
        "ask": ask,
        "bid": bid,
        "ts": _utc_now_iso(),
        "live": False,
        "note": "paper simulation only — no order sent",
    }


def simulate_paper_order(
    *,
    side: str = "buy",
    symbol: str = DEFAULT_SYMBOL,
    timeout: float = DEFAULT_TIMEOUT,
    ticker_row: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Paper-simulate a Bitkub fill using the public ticker.

    Refuses live: if PMM_BITKUB_LIVE_OK is set, still does NOT place orders;
    live execution is a future stub gated by that env (documented only).
    """
    # Explicit live refusal — skeleton only.
    if os.environ.get(LIVE_GATE_ENV, "").strip() in ("1", "true", "yes"):
        # Documented gate present, but this module never routes to live.
        pass

    row = ticker_row if ticker_row is not None else fetch_public_ticker(symbol, timeout=timeout)
    fill = paper_fill_from_ticker(row, side=side, symbol=symbol)
    # JSON-log shape for Ledger / runtime observers
    fill["tape"] = ticker_to_tape_quote(row, symbol=symbol).to_dict()
    return fill


def live_order_stub(*_args: Any, **_kwargs: Any) -> None:
    """
    Live order stub — intentionally unimplemented.

    Future live adapter MUST require env PMM_BITKUB_LIVE_OK=1 plus BITKUB_API_KEY /
    BITKUB_API_SECRET and must never be the default. This function always raises.
    """
    raise BitkubPaperError(
        f"Bitkub live orders are not implemented; paper-only. "
        f"Future live path requires {LIVE_GATE_ENV}=1 (not honored here)."
    )

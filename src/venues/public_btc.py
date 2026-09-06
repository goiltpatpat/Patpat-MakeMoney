"""Public BTC spot tape (read-only)."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Optional

from venues import TapeQuote

BINANCE_TICKER_URL = "https://api.binance.com/api/v3/ticker/price"
BINANCE_MARK_URL = "https://api.binance.com/api/v3/premiumIndex"
DEFAULT_TIMEOUT = 8.0
USER_AGENT = "Patpat-MakeMoney/venues-public-btc"


class PublicBtcError(RuntimeError):
    """Raised when the public BTC feed cannot be read."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_json(url: str, params: Optional[dict] = None, timeout: float = DEFAULT_TIMEOUT) -> dict:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise PublicBtcError(f"HTTP {e.code} from {url}") from e
    except urllib.error.URLError as e:
        raise PublicBtcError(f"network error fetching {url}: {e.reason}") from e
    except TimeoutError as e:
        raise PublicBtcError(f"timeout fetching {url}") from e
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise PublicBtcError(f"invalid JSON from {url}") from e
    if not isinstance(data, dict):
        raise PublicBtcError(f"unexpected payload type from {url}: {type(data).__name__}")
    return data


def fetch_btc_usdt_last(*, timeout: float = DEFAULT_TIMEOUT) -> TapeQuote:
    """Fetch BTCUSDT last price from Binance public ticker API."""
    data = _get_json(BINANCE_TICKER_URL, params={"symbol": "BTCUSDT"}, timeout=timeout)
    try:
        price = float(data["price"])
    except (KeyError, TypeError, ValueError) as e:
        raise PublicBtcError(f"malformed Binance ticker payload: {data!r}") from e
    if price <= 0:
        raise PublicBtcError(f"non-positive BTCUSDT last: {price}")
    return TapeQuote(
        venue="binance_public",
        symbol="BTCUSDT",
        price=price,
        ts=_utc_now_iso(),
        source="binance_ticker_price",
    )


def fetch_btc_usdt_mark(*, timeout: float = DEFAULT_TIMEOUT) -> TapeQuote:
    """Fetch BTCUSDT mark price from Binance public premiumIndex (futures mark)."""
    data = _get_json(BINANCE_MARK_URL, params={"symbol": "BTCUSDT"}, timeout=timeout)
    try:
        # spot-adjacent mark; field is markPrice on USDT-M futures premiumIndex
        price = float(data.get("markPrice") or data.get("price"))
    except (TypeError, ValueError) as e:
        raise PublicBtcError(f"malformed Binance mark payload: {data!r}") from e
    if price <= 0:
        raise PublicBtcError(f"non-positive BTCUSDT mark: {price}")
    return TapeQuote(
        venue="binance_public",
        symbol="BTCUSDT",
        price=price,
        ts=_utc_now_iso(),
        source="binance_premium_index_mark",
    )


def fetch_public_btc(*, prefer: str = "last", timeout: float = DEFAULT_TIMEOUT) -> TapeQuote:
    """Return a public BTCUSDT TapeQuote. prefer: last|mark."""
    prefer = (prefer or "last").strip().lower()
    if prefer == "mark":
        return fetch_btc_usdt_mark(timeout=timeout)
    return fetch_btc_usdt_last(timeout=timeout)

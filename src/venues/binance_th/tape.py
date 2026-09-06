"""Binance TH public ticker/tape helper (api.binance.th ONLY — never api.binance.com).

Official docs: https://www.binance.th/api-docs/en/
Base: https://api.binance.th
Public market data used here:
  GET /api/v1/ticker/price?symbol=BTCTHB
  GET /api/v1/ticker/bookTicker?symbol=BTCTHB
  GET /api/v1/ticker/24hr?symbol=BTCTHB

Paper/read-only. No live orders. No silent fallback to Binance.com global.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Optional

from venues import TapeQuote

# CRITICAL: Thai-licensed Gulf Binance only — NEVER api.binance.com
BINANCE_TH_API_BASE = "https://api.binance.th"
DOCS_URL = "https://www.binance.th/api-docs/en/"
TICKER_PRICE_PATH = "/api/v1/ticker/price"
BOOK_TICKER_PATH = "/api/v1/ticker/bookTicker"
TICKER_24HR_PATH = "/api/v1/ticker/24hr"

DEFAULT_SYMBOL = "BTCTHB"
DEFAULT_TIMEOUT = 8.0
USER_AGENT = "Patpat-MakeMoney/venues-binance-th-tape"

# Fixture mode for offline tests (explicit, never silent global fallback)
FIXTURE_ENV = "PMM_BINANCE_TH_FIXTURE"
FIXTURE_BTCTHB = {
    "symbol": "BTCTHB",
    "price": "2600000.00",
    "bidPrice": "2599900.00",
    "bidQty": "0.10",
    "askPrice": "2600100.00",
    "askQty": "0.10",
    "lastPrice": "2600000.00",
}


class BinanceTHError(RuntimeError):
    """Raised when Binance TH public market data fails."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_symbol(symbol: str) -> str:
    """Normalize to Binance TH form BTCTHB (no underscore)."""
    s = (symbol or DEFAULT_SYMBOL).strip().upper().replace("-", "").replace("_", "")
    if not s:
        return DEFAULT_SYMBOL
    return s


def fixture_ticker_row(symbol: str = DEFAULT_SYMBOL) -> dict[str, Any]:
    """Deterministic fixture row for tests / offline dry-runs."""
    sym = _normalize_symbol(symbol)
    row = dict(FIXTURE_BTCTHB)
    row["symbol"] = sym
    return row


def _assert_th_host(url: str) -> None:
    """Refuse any call that is not api.binance.th (geo/product rule)."""
    if "api.binance.th" not in url:
        raise BinanceTHError(
            f"refusing non-TH host in Binance TH adapter: {url!r} "
            f"(must use {BINANCE_TH_API_BASE}; never api.binance.com). Docs: {DOCS_URL}"
        )
    if "api.binance.com" in url:
        raise BinanceTHError(
            "refusing api.binance.com — Binance TH is Gulf/binance.th only"
        )


def _get_json(url: str, params: Optional[dict] = None, timeout: float = DEFAULT_TIMEOUT) -> Any:
    _assert_th_host(url)
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    _assert_th_host(url)
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise BinanceTHError(f"HTTP {e.code} from {url}") from e
    except urllib.error.URLError as e:
        raise BinanceTHError(f"network error fetching {url}: {e.reason}") from e
    except TimeoutError as e:
        raise BinanceTHError(f"timeout fetching {url}") from e
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise BinanceTHError(f"invalid JSON from {url}") from e


def _float_field(row: dict[str, Any], *keys: str) -> Optional[float]:
    for k in keys:
        if k in row and row[k] is not None:
            try:
                return float(row[k])
            except (TypeError, ValueError):
                continue
    return None


def fetch_public_ticker(
    symbol: str = DEFAULT_SYMBOL,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    use_fixture: Optional[bool] = None,
) -> dict[str, Any]:
    """
    Fetch Binance TH public mid via GET /api/v1/ticker/price (+ bookTicker when available).

    Returns a merged dict with symbol, price/lastPrice, bidPrice, askPrice when present.
    Fixture mode: PMM_BINANCE_TH_FIXTURE=1 or use_fixture=True.
    """
    sym = _normalize_symbol(symbol)
    if use_fixture is None:
        use_fixture = os.environ.get(FIXTURE_ENV, "").strip().lower() in ("1", "true", "yes")
    if use_fixture:
        return fixture_ticker_row(sym)

    price_url = f"{BINANCE_TH_API_BASE}{TICKER_PRICE_PATH}"
    data = _get_json(price_url, params={"symbol": sym}, timeout=timeout)
    if not isinstance(data, dict):
        raise BinanceTHError(f"unexpected ticker/price payload for {sym}: {data!r}")

    row: dict[str, Any] = dict(data)
    row["symbol"] = str(row.get("symbol") or sym).upper()
    px = _float_field(row, "price", "lastPrice")
    if px is None or px <= 0:
        raise BinanceTHError(f"non-positive price for {sym}: {row!r}")
    row["lastPrice"] = px
    row["price"] = px

    # Best-effort book ticker for bid/ask (same host only)
    try:
        book_url = f"{BINANCE_TH_API_BASE}{BOOK_TICKER_PATH}"
        book = _get_json(book_url, params={"symbol": sym}, timeout=timeout)
        if isinstance(book, dict):
            for k in ("bidPrice", "bidQty", "askPrice", "askQty"):
                if k in book:
                    row[k] = book[k]
    except BinanceTHError:
        pass  # price alone is enough for mid

    row["_source_host"] = "api.binance.th"
    row["_docs"] = DOCS_URL
    return row


def fetch_book_ticker(
    symbol: str = DEFAULT_SYMBOL,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    use_fixture: Optional[bool] = None,
) -> dict[str, Any]:
    """Fetch GET /api/v1/ticker/bookTicker from api.binance.th only."""
    sym = _normalize_symbol(symbol)
    if use_fixture is None:
        use_fixture = os.environ.get(FIXTURE_ENV, "").strip().lower() in ("1", "true", "yes")
    if use_fixture:
        return fixture_ticker_row(sym)

    url = f"{BINANCE_TH_API_BASE}{BOOK_TICKER_PATH}"
    data = _get_json(url, params={"symbol": sym}, timeout=timeout)
    if not isinstance(data, dict):
        raise BinanceTHError(f"unexpected bookTicker payload for {sym}: {data!r}")
    bid = _float_field(data, "bidPrice")
    ask = _float_field(data, "askPrice")
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        raise BinanceTHError(f"bad bookTicker for {sym}: {data!r}")
    data["symbol"] = str(data.get("symbol") or sym).upper()
    data["_source_host"] = "api.binance.th"
    return data


def ticker_to_tape_quote(row: dict[str, Any], symbol: str = DEFAULT_SYMBOL) -> TapeQuote:
    """Map a Binance TH ticker row to TapeQuote using last/mid price."""
    sym = _normalize_symbol(symbol or str(row.get("symbol") or DEFAULT_SYMBOL))
    last = _float_field(row, "lastPrice", "price")
    bid = _float_field(row, "bidPrice")
    ask = _float_field(row, "askPrice")
    if last is None or last <= 0:
        if bid and ask and bid > 0 and ask > 0:
            last = (bid + ask) / 2.0
        else:
            raise BinanceTHError(f"cannot derive mid from ticker: {row!r}")
    return TapeQuote(
        venue="binance_th",
        symbol=sym,
        price=float(last),
        ts=_utc_now_iso(),
        source="binance_th_ticker_price",
    )


def unavailable_status(*, reason: str = "public API unreachable") -> dict[str, Any]:
    """Explicit unavailable payload (never silent Binance.com fallback)."""
    return {
        "status": "unavailable",
        "venue": "binance_th",
        "host": BINANCE_TH_API_BASE,
        "docs": DOCS_URL,
        "reason": reason,
        "todo": (
            f"Verify public market data at {DOCS_URL}; "
            "use fixture mode (PMM_BINANCE_TH_FIXTURE=1) for offline tests; "
            "NEVER call api.binance.com and label it Binance TH."
        ),
        "ts": _utc_now_iso(),
    }

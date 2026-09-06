"""1inch read-only spot/price quote helper (research only — NO swaps)."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Optional

from venues import TapeQuote

# Documented Spot Price API (Bearer optional via ONEINCH_API_KEY).
# Read-only price endpoint — this module never calls swap/quote execution paths.
ONEINCH_PRICE_BASE = "https://api.1inch.dev/price/v1.1"
ETH_CHAIN_ID = 1
# Native ETH sentinel used by 1inch price API
ETH_NATIVE = "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
WBTC_ETH = "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599"
DEFAULT_TIMEOUT = 8.0
USER_AGENT = "Patpat-MakeMoney/venues-oneinch-quotes"

# Deterministic fixture used when network is unavailable / tests / no key.
FIXTURE_WBTC_USD = 95000.0


class OneInchQuoteError(RuntimeError):
    """Raised when a 1inch read-only price cannot be obtained (non-fixture)."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fixture_wbtc_usd_quote(*, price: float = FIXTURE_WBTC_USD) -> TapeQuote:
    """Offline/fixture TapeQuote for CI and keyless research dry runs."""
    return TapeQuote(
        venue="oneinch",
        symbol="WBTC-USD",
        price=float(price),
        ts=_utc_now_iso(),
        source="fixture",
    )


def _get_json(
    url: str,
    *,
    api_key: Optional[str],
    timeout: float = DEFAULT_TIMEOUT,
) -> Any:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise OneInchQuoteError(f"HTTP {e.code} from {url}") from e
    except urllib.error.URLError as e:
        raise OneInchQuoteError(f"network error fetching {url}: {e.reason}") from e
    except TimeoutError as e:
        raise OneInchQuoteError(f"timeout fetching {url}") from e
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise OneInchQuoteError(f"invalid JSON from {url}") from e


def fetch_token_usd_price(
    token_address: str,
    *,
    chain_id: int = ETH_CHAIN_ID,
    api_key: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT,
    allow_fixture: bool = True,
) -> TapeQuote:
    """
    Read-only USD spot price for a token via 1inch Spot Price API.

    If ONEINCH_API_KEY (or api_key) is missing and allow_fixture=True, returns fixture.
    Never executes swaps.
    """
    key = api_key if api_key is not None else os.environ.get("ONEINCH_API_KEY", "").strip()
    token = (token_address or "").strip().lower()
    if not token.startswith("0x"):
        raise OneInchQuoteError(f"invalid token address: {token_address!r}")

    if not key:
        if allow_fixture:
            q = fixture_wbtc_usd_quote()
            # preserve requested symbol hint when WBTC
            if token == WBTC_ETH.lower():
                return q
            return TapeQuote(
                venue="oneinch",
                symbol=f"{token[:10]}-USD",
                price=q.price,
                ts=q.ts,
                source="fixture",
            )
        raise OneInchQuoteError(
            "ONEINCH_API_KEY not set; pass allow_fixture=True for offline fixture mode"
        )

    url = (
        f"{ONEINCH_PRICE_BASE}/{int(chain_id)}/{token}"
        f"?{urllib.parse.urlencode({'currency': 'USD'})}"
    )
    data = _get_json(url, api_key=key, timeout=timeout)
    # Response shapes vary: bare number string, or {address: price}
    price: Optional[float] = None
    if isinstance(data, (int, float, str)):
        try:
            price = float(data)
        except ValueError:
            price = None
    elif isinstance(data, dict):
        for k, v in data.items():
            if str(k).lower() == token or len(data) == 1:
                try:
                    price = float(v)
                    break
                except (TypeError, ValueError):
                    continue
    if price is None or price <= 0:
        raise OneInchQuoteError(f"could not parse 1inch price payload: {data!r}")

    symbol = "WBTC-USD" if token == WBTC_ETH.lower() else f"{token[:10]}-USD"
    return TapeQuote(
        venue="oneinch",
        symbol=symbol,
        price=price,
        ts=_utc_now_iso(),
        source="oneinch_spot_price_v1.1",
    )


def fetch_wbtc_usd_quote(
    *,
    api_key: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT,
    allow_fixture: bool = True,
) -> TapeQuote:
    """Convenience: WBTC USD spot (research). Fixture if no key."""
    return fetch_token_usd_price(
        WBTC_ETH,
        chain_id=ETH_CHAIN_ID,
        api_key=api_key,
        timeout=timeout,
        allow_fixture=allow_fixture,
    )

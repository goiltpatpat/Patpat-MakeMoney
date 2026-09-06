"""Jupiter Solana read-only quote client (research / dry-run — NEVER sign or send).

API (public docs):
  - Quote: GET https://api.jup.ag/swap/v2/order WITHOUT taker → quote only (transaction=null)
    Docs: https://developers.jup.ag/docs/swap/order-and-execute
  - Price: GET https://api.jup.ag/price/v3?ids={mints}
    Docs: https://developers.jup.ag/docs/price

Auth: optional x-api-key via JUPITER_API_KEY (Portal). Keyless allowed at low RPS.
Fixture mode ONLY with explicit use_fixture+allow_fixture — fail closed, no silent fixture.
No private keys. No /execute. No Raydium compute in this slice (optional later).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from venues import TapeQuote

JUPITER_API_BASE = "https://api.jup.ag"
JUPITER_ORDER_PATH = "/swap/v2/order"
JUPITER_PRICE_PATH = "/price/v3"
DOCS_ORDER = "https://developers.jup.ag/docs/swap/order-and-execute"
DOCS_PRICE = "https://developers.jup.ag/docs/price"
DOCS_PORTAL = "https://developers.jup.ag/portal"

SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
MSOL_MINT = "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So"
JITOSOL_MINT = "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn"
KNOWN_DECIMALS: dict[str, int] = {
    SOL_MINT: 9,
    USDC_MINT: 6,
    MSOL_MINT: 9,
    JITOSOL_MINT: 9,
}

DEFAULT_TIMEOUT = 10.0
USER_AGENT = "Patpat-MakeMoney/venues-solana-jupiter-quotes"
FIXTURE_SOL_USDC_MID = 150.0
FIXTURE_IN_AMOUNT = "100000000"  # 0.1 SOL


class JupiterQuoteError(RuntimeError):
    """Raised when a Jupiter read-only quote/price cannot be obtained (non-fixture)."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _api_key(explicit: Optional[str] = None) -> Optional[str]:
    if explicit is not None:
        k = explicit.strip()
        return k or None
    return os.environ.get("JUPITER_API_KEY", "").strip() or None


def _headers(api_key: Optional[str]) -> dict[str, str]:
    h = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if api_key:
        h["x-api-key"] = api_key
    return h


def _get_json(url: str, *, api_key: Optional[str], timeout: float) -> Any:
    req = urllib.request.Request(url, headers=_headers(api_key))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        raise JupiterQuoteError(f"HTTP {e.code} from {url}: {body}") from e
    except urllib.error.URLError as e:
        raise JupiterQuoteError(f"network error fetching {url}: {e.reason}") from e
    except TimeoutError as e:
        raise JupiterQuoteError(f"timeout fetching {url}") from e
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise JupiterQuoteError(f"invalid JSON from {url}") from e


def mint_decimals(mint: str, override: Optional[int] = None) -> int:
    if override is not None:
        return int(override)
    m = (mint or "").strip()
    if m in KNOWN_DECIMALS:
        return KNOWN_DECIMALS[m]
    raise JupiterQuoteError(
        f"unknown mint decimals for {mint!r}; pass input_decimals/output_decimals explicitly"
    )


def _ui_amount(raw: str | int | float, decimals: int) -> float:
    return float(raw) / (10 ** int(decimals))


@dataclass
class JupiterOrderQuote:
    """Normalized Jupiter /swap/v2/order quote-only brief (Ledger-friendly)."""

    venue: str
    symbol: str
    input_mint: str
    output_mint: str
    in_amount: str
    out_amount: str
    mid: float
    in_ui: float
    out_ui: float
    price_impact_pct: Optional[float]
    slippage_bps: Optional[int]
    fee_bps: Optional[float]
    prioritization_fee_lamports: Optional[int]
    prioritization_fee_label: str
    route_labels: list[str]
    router: Optional[str]
    mode: Optional[str]
    request_id: Optional[str]
    ts: str
    source: str
    docs: str = DOCS_ORDER
    note: str = ""
    raw_keys: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["live"] = False
        d["signed"] = False
        d["execution"] = "quote_only"
        return d

    def to_tape_quote(self) -> TapeQuote:
        return TapeQuote(
            venue=self.venue,
            symbol=self.symbol,
            price=float(self.mid),
            ts=self.ts,
            source=self.source,
        )


def fixture_sol_usdc_quote(
    *,
    mid: float = FIXTURE_SOL_USDC_MID,
    in_amount: str = FIXTURE_IN_AMOUNT,
) -> JupiterOrderQuote:
    """Offline fixture SOL→USDC quote — explicit flag only; never silent."""
    in_ui = _ui_amount(in_amount, 9)
    out_ui = in_ui * float(mid)
    out_raw = str(int(round(out_ui * 1_000_000)))
    return JupiterOrderQuote(
        venue="jupiter_solana",
        symbol="SOL/USDC",
        input_mint=SOL_MINT,
        output_mint=USDC_MINT,
        in_amount=str(in_amount),
        out_amount=out_raw,
        mid=float(mid),
        in_ui=in_ui,
        out_ui=out_ui,
        price_impact_pct=0.0,
        slippage_bps=50,
        fee_bps=2.0,
        prioritization_fee_lamports=None,
        prioritization_fee_label="ESTIMATE_unavailable_fixture",
        route_labels=["fixture"],
        router="fixture",
        mode="fixture",
        request_id=None,
        ts=_utc_now_iso(),
        source="fixture",
        note=(
            "FIXTURE — not a live Jupiter quote; money-path must kill unless allow_fixture. "
            "Never sign/send."
        ),
        raw_keys=[],
    )


def _route_labels(route_plan: Any) -> list[str]:
    labels: list[str] = []
    if not isinstance(route_plan, list):
        return labels
    for step in route_plan:
        if not isinstance(step, dict):
            continue
        info = step.get("swapInfo") if isinstance(step.get("swapInfo"), dict) else step
        lab = info.get("label") if isinstance(info, dict) else None
        if lab:
            labels.append(str(lab))
    return labels


def _parse_order_payload(
    data: dict[str, Any],
    *,
    input_mint: str,
    output_mint: str,
    input_decimals: int,
    output_decimals: int,
    source: str,
) -> JupiterOrderQuote:
    if not isinstance(data, dict):
        raise JupiterQuoteError(f"unexpected order payload type: {type(data)}")
    in_amount = data.get("inAmount")
    out_amount = data.get("outAmount")
    if in_amount is None or out_amount is None:
        raise JupiterQuoteError(
            f"order payload missing inAmount/outAmount (see {DOCS_ORDER}): "
            f"keys={sorted(data.keys())}"
        )
    in_ui = _ui_amount(in_amount, input_decimals)
    out_ui = _ui_amount(out_amount, output_decimals)
    if in_ui <= 0:
        raise JupiterQuoteError(f"non-positive in_ui from quote: inAmount={in_amount!r}")
    mid = out_ui / in_ui

    impact: Optional[float] = None
    for key in ("priceImpactPct", "priceImpact"):
        if data.get(key) is not None:
            try:
                impact = float(data[key])
                break
            except (TypeError, ValueError):
                continue

    slip: Optional[int] = None
    if data.get("slippageBps") is not None:
        try:
            slip = int(data["slippageBps"])
        except (TypeError, ValueError):
            slip = None

    fee_bps: Optional[float] = None
    if data.get("feeBps") is not None:
        try:
            fee_bps = float(data["feeBps"])
        except (TypeError, ValueError):
            fee_bps = None

    prio: Optional[int] = None
    if data.get("prioritizationFeeLamports") is not None:
        try:
            prio = int(data["prioritizationFeeLamports"])
        except (TypeError, ValueError):
            prio = None
    if prio is None:
        prio_label = "ESTIMATE_unavailable_no_field"
    else:
        prio_label = "API_prioritizationFeeLamports_labeled_estimate"

    in_sym = "SOL" if input_mint == SOL_MINT else input_mint[:6]
    out_sym = "USDC" if output_mint == USDC_MINT else output_mint[:6]
    return JupiterOrderQuote(
        venue="jupiter_solana",
        symbol=f"{in_sym}/{out_sym}",
        input_mint=input_mint,
        output_mint=output_mint,
        in_amount=str(in_amount),
        out_amount=str(out_amount),
        mid=float(mid),
        in_ui=float(in_ui),
        out_ui=float(out_ui),
        price_impact_pct=impact,
        slippage_bps=slip,
        fee_bps=fee_bps,
        prioritization_fee_lamports=prio,
        prioritization_fee_label=prio_label,
        route_labels=_route_labels(data.get("routePlan")),
        router=str(data["router"]) if data.get("router") is not None else None,
        mode=str(data["mode"]) if data.get("mode") is not None else None,
        request_id=str(data["requestId"]) if data.get("requestId") is not None else None,
        ts=_utc_now_iso(),
        source=source,
        note=(
            "quote-only: GET /swap/v2/order WITHOUT taker; never sign/send; "
            "fee/slippage/priority-fee fields are API-reported or labeled ESTIMATE; "
            f"docs={DOCS_ORDER}"
        ),
        raw_keys=sorted(str(k) for k in data.keys()),
    )


def fetch_jupiter_order_quote(
    *,
    input_mint: str = SOL_MINT,
    output_mint: str = USDC_MINT,
    amount: str | int = "100000000",
    slippage_bps: Optional[int] = None,
    input_decimals: Optional[int] = None,
    output_decimals: Optional[int] = None,
    api_key: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT,
    allow_fixture: bool = False,
    use_fixture: bool = False,
) -> JupiterOrderQuote:
    """
    Read-only Jupiter Swap API V2 order quote (NO taker → no transaction to sign).

    Fail closed: HTTP failure raises (no silent fixture).
    Fixture only when use_fixture=True AND allow_fixture=True.
    """
    if use_fixture:
        if not allow_fixture:
            raise JupiterQuoteError(
                "use_fixture=True requires allow_fixture=True (no silent fixture on money path)"
            )
        if input_mint == SOL_MINT and output_mint == USDC_MINT:
            return fixture_sol_usdc_quote(in_amount=str(amount))
        raise JupiterQuoteError("fixture currently only supports SOL→USDC")

    in_dec = mint_decimals(input_mint, input_decimals)
    out_dec = mint_decimals(output_mint, output_decimals)
    key = _api_key(api_key)

    params: dict[str, str] = {
        "inputMint": input_mint,
        "outputMint": output_mint,
        "amount": str(amount),
    }
    # Intentionally omit taker → quote only (transaction=null).
    if slippage_bps is not None:
        params["slippageBps"] = str(int(slippage_bps))

    url = f"{JUPITER_API_BASE}{JUPITER_ORDER_PATH}?{urllib.parse.urlencode(params)}"
    data = _get_json(url, api_key=key, timeout=timeout)
    if not isinstance(data, dict):
        raise JupiterQuoteError(f"unexpected JSON type from order: {type(data)}")

    return _parse_order_payload(
        data,
        input_mint=input_mint,
        output_mint=output_mint,
        input_decimals=in_dec,
        output_decimals=out_dec,
        source="jupiter_swap_v2_order",
    )


def fetch_jupiter_usd_price(
    mint: str = SOL_MINT,
    *,
    api_key: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT,
    allow_fixture: bool = False,
    use_fixture: bool = False,
) -> TapeQuote:
    """Read-only Jupiter Price API V3 USD price for a mint."""
    if use_fixture:
        if not allow_fixture:
            raise JupiterQuoteError(
                "use_fixture=True requires allow_fixture=True (no silent fixture)"
            )
        return TapeQuote(
            venue="jupiter_price_v3",
            symbol="SOL-USD" if mint == SOL_MINT else f"{mint[:8]}-USD",
            price=float(FIXTURE_SOL_USDC_MID),
            ts=_utc_now_iso(),
            source="fixture",
        )

    key = _api_key(api_key)
    url = (
        f"{JUPITER_API_BASE}{JUPITER_PRICE_PATH}?"
        + urllib.parse.urlencode({"ids": mint})
    )
    data = _get_json(url, api_key=key, timeout=timeout)
    if not isinstance(data, dict):
        raise JupiterQuoteError(f"unexpected price payload: {type(data)}")
    row = data.get(mint)
    if not isinstance(row, dict) or row.get("usdPrice") is None:
        raise JupiterQuoteError(f"price v3 missing usdPrice for {mint}: {data!r}")
    try:
        px = float(row["usdPrice"])
    except (TypeError, ValueError) as e:
        raise JupiterQuoteError(f"invalid usdPrice: {row.get('usdPrice')!r}") from e
    if px <= 0:
        raise JupiterQuoteError(f"non-positive usdPrice: {px}")
    symbol = "SOL-USD" if mint == SOL_MINT else f"{mint[:8]}-USD"
    return TapeQuote(
        venue="jupiter_price_v3",
        symbol=symbol,
        price=px,
        ts=_utc_now_iso(),
        source="jupiter_price_v3",
    )

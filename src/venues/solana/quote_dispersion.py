"""Jupiter quote-dispersion logger (T1-plus) — multi-size + optional pool RO mids.

Paper / research only. Compares Jupiter /swap/v2/order quote-only mids across a
size ladder (dispersion) and, when available, public Raydium/Orca/Meteora RO
pool mids. Logs fee+slip stack from API fields (labeled ESTIMATE when absent).

Fail-closed: empty / rate-limit / HTTP errors -> no invented mids.
Fixture-kill default. --live refused at CLI. No tips / secrets / auto-trade.

Pool mids: best-effort public RO probes; if blocked or unsupported -> status
deferred/unavailable (documented); Jupiter size-ladder remains the MVP SoT.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from venues.solana import jupiter_quotes as jup

# --- Size ladder (SOL -> USDC default; raw lamports for 9-dp SOL) ---
# 0.001, 0.01, 0.05, 0.1, 0.5, 1.0 SOL
DEFAULT_SIZE_LADDER_LAMPORTS: tuple[str, ...] = (
    "1000000",
    "10000000",
    "50000000",
    "100000000",
    "500000000",
    "1000000000",
)

DEFAULT_TIMEOUT = 10.0
DEFAULT_SLIPPAGE_BPS_ESTIMATE = 50
DEFAULT_FEE_BPS_ESTIMATE = 5.0
USER_AGENT = "Patpat-MakeMoney/venues-solana-quote-dispersion"

ORCA_WHIRLPOOL_SOL_USDC = "7qbRF6YsyGuLUVs6Y1q64bdVrfe4ZcUUz1JRdoVNUJnm"

RAYDIUM_API_V3_BASE = "https://api-v3.raydium.io"
ORCA_API_BASE = "https://api.mainnet.orca.so/v1"
METEORA_API_BASE = "https://dlmm-api.meteora.ag"

DOCS_JUPITER = jup.DOCS_ORDER


class DispersionError(RuntimeError):
    """Raised when dispersion cannot be computed without inventing mids."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _leg_is_fixture(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    if obj.get("fixture") is True:
        return True
    src = str(obj.get("source") or "").lower()
    return src in ("fixture", "fixtures", "test_fixture")


@dataclass
class FeeSlipStack:
    """Fee + slip stack — API when present, else labeled ESTIMATE."""

    fee_bps: Optional[float] = None
    fee_bps_label: str = "ESTIMATE"
    slippage_bps: Optional[int] = None
    slippage_bps_label: str = "ESTIMATE"
    price_impact_pct: Optional[float] = None
    prioritization_fee_lamports: Optional[int] = None
    prioritization_fee_label: str = "ESTIMATE_unavailable"
    fee_floor_bps: float = DEFAULT_FEE_BPS_ESTIMATE
    note: str = (
        "fee/slip from Jupiter API when present; else ESTIMATE defaults — not a tipster"
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def fee_slip_from_quote(
    q: dict[str, Any],
    *,
    default_fee_bps: float = DEFAULT_FEE_BPS_ESTIMATE,
    default_slip_bps: int = DEFAULT_SLIPPAGE_BPS_ESTIMATE,
) -> FeeSlipStack:
    fee = q.get("fee_bps")
    fee_label = "API_feeBps"
    if fee is None:
        fee = float(default_fee_bps)
        fee_label = "ESTIMATE"
    else:
        try:
            fee = float(fee)
        except (TypeError, ValueError):
            fee = float(default_fee_bps)
            fee_label = "ESTIMATE"

    slip = q.get("slippage_bps")
    slip_label = "API_slippageBps"
    if slip is None:
        slip = int(default_slip_bps)
        slip_label = "ESTIMATE"
    else:
        try:
            slip = int(slip)
        except (TypeError, ValueError):
            slip = int(default_slip_bps)
            slip_label = "ESTIMATE"

    prio = q.get("prioritization_fee_lamports")
    prio_label = q.get("prioritization_fee_label") or (
        "API_prioritizationFeeLamports_labeled_estimate"
        if prio is not None
        else "ESTIMATE_unavailable"
    )
    impact = q.get("price_impact_pct")
    try:
        impact_f = float(impact) if impact is not None else None
    except (TypeError, ValueError):
        impact_f = None

    prio_out: Optional[int] = None
    if prio is not None:
        try:
            prio_out = int(prio)
        except (TypeError, ValueError):
            prio_out = None

    return FeeSlipStack(
        fee_bps=fee,
        fee_bps_label=fee_label,
        slippage_bps=slip,
        slippage_bps_label=slip_label,
        price_impact_pct=impact_f,
        prioritization_fee_lamports=prio_out,
        prioritization_fee_label=str(prio_label),
        fee_floor_bps=float(fee),
    )


def _http_get_json(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    headers: Optional[dict[str, str]] = None,
) -> Any:
    h = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        if e.code == 429:
            raise DispersionError(f"rate_limit HTTP 429 from {url}: {body}") from e
        raise DispersionError(f"HTTP {e.code} from {url}: {body}") from e
    except urllib.error.URLError as e:
        raise DispersionError(f"network error {url}: {e.reason}") from e
    except TimeoutError as e:
        raise DispersionError(f"timeout {url}") from e
    if not raw or not raw.strip():
        raise DispersionError(f"empty response from {url}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise DispersionError(f"invalid JSON from {url}") from e


def fetch_jupiter_size_quote(
    amount: str,
    *,
    input_mint: str = jup.SOL_MINT,
    output_mint: str = jup.USDC_MINT,
    timeout: float = DEFAULT_TIMEOUT,
    allow_fixture: bool = False,
    use_fixture: bool = False,
    api_key: Optional[str] = None,
    quote_fn: Optional[Callable[..., Any]] = None,
) -> dict[str, Any]:
    """One Jupiter quote-only mid for a size. Fail-closed; no invented mid."""
    if use_fixture:
        if not allow_fixture:
            raise DispersionError(
                "use_fixture=True requires allow_fixture=True "
                "(no silent fixture on money path)"
            )
        base = float(jup.FIXTURE_SOL_USDC_MID)
        try:
            lamports = int(amount)
        except ValueError as e:
            raise DispersionError(f"bad fixture amount: {amount!r}") from e
        # tiny synthetic impact: +0.5 bps per 0.1 SOL — labeled fixture
        impact_bps = (lamports / 100_000_000.0) * 0.5
        mid = base * (1.0 - impact_bps / 1e4)
        in_ui = lamports / 1e9
        out_ui = in_ui * mid
        return {
            "venue": "jupiter_solana",
            "symbol": "SOL/USDC",
            "input_mint": input_mint,
            "output_mint": output_mint,
            "in_amount": str(amount),
            "out_amount": str(int(round(out_ui * 1_000_000))),
            "mid": float(mid),
            "in_ui": float(in_ui),
            "out_ui": float(out_ui),
            "price_impact_pct": impact_bps / 100.0,
            "slippage_bps": 50,
            "fee_bps": 2.0,
            "prioritization_fee_lamports": None,
            "prioritization_fee_label": "ESTIMATE_unavailable_fixture",
            "route_labels": ["fixture"],
            "router": "fixture",
            "ts": _utc_now_iso(),
            "source": "fixture",
            "fixture": True,
            "status": "ok",
            "note": "FIXTURE Jupiter size quote — tests only; never sign/send",
        }

    fn = quote_fn or jup.fetch_jupiter_order_quote
    try:
        q = fn(
            input_mint=input_mint,
            output_mint=output_mint,
            amount=amount,
            input_decimals=9 if input_mint == jup.SOL_MINT else None,
            output_decimals=6 if output_mint == jup.USDC_MINT else None,
            timeout=timeout,
            allow_fixture=False,
            use_fixture=False,
            api_key=api_key,
        )
    except jup.JupiterQuoteError as e:
        msg = str(e)
        status = "empty_or_error"
        if "429" in msg or "rate_limit" in msg.lower():
            status = "rate_limit"
        return {
            "venue": "jupiter_solana",
            "symbol": "SOL/USDC",
            "input_mint": input_mint,
            "output_mint": output_mint,
            "in_amount": str(amount),
            "mid": None,
            "ts": _utc_now_iso(),
            "source": "jupiter_swap_v2_order",
            "fixture": False,
            "status": status,
            "error": msg,
            "note": "fail-closed: no invented mid",
        }

    if hasattr(q, "to_dict"):
        d = q.to_dict()
    elif isinstance(q, dict):
        d = dict(q)
    else:
        raise DispersionError(f"unexpected quote type: {type(q)}")

    mid = d.get("mid")
    if mid is None or float(mid) <= 0:
        return {
            "venue": d.get("venue") or "jupiter_solana",
            "symbol": d.get("symbol") or "SOL/USDC",
            "input_mint": d.get("input_mint") or input_mint,
            "output_mint": d.get("output_mint") or output_mint,
            "in_amount": str(amount),
            "mid": None,
            "ts": d.get("ts") or _utc_now_iso(),
            "source": d.get("source") or "jupiter_swap_v2_order",
            "fixture": False,
            "status": "empty",
            "error": "non-positive or missing mid",
            "note": "fail-closed: no invented mid",
        }

    return {
        "venue": d.get("venue") or "jupiter_solana",
        "symbol": d.get("symbol") or "SOL/USDC",
        "input_mint": d.get("input_mint") or input_mint,
        "output_mint": d.get("output_mint") or output_mint,
        "in_amount": str(d.get("in_amount") or amount),
        "out_amount": d.get("out_amount"),
        "mid": float(mid),
        "in_ui": d.get("in_ui"),
        "out_ui": d.get("out_ui"),
        "price_impact_pct": d.get("price_impact_pct"),
        "slippage_bps": d.get("slippage_bps"),
        "fee_bps": d.get("fee_bps"),
        "prioritization_fee_lamports": d.get("prioritization_fee_lamports"),
        "prioritization_fee_label": d.get("prioritization_fee_label"),
        "route_labels": list(d.get("route_labels") or []),
        "router": d.get("router"),
        "ts": d.get("ts") or _utc_now_iso(),
        "source": d.get("source") or "jupiter_swap_v2_order",
        "fixture": False,
        "status": "ok",
        "note": "Jupiter quote-only size mid — never sign/send",
        "docs": DOCS_JUPITER,
    }


def compute_size_dispersion(quotes: list[dict[str, Any]]) -> dict[str, Any]:
    """Dispersion across successful Jupiter size-ladder mids."""
    ok_rows = [q for q in quotes if q.get("status") == "ok" and q.get("mid") is not None]
    if not ok_rows:
        return {
            "status": "empty",
            "kill": True,
            "kill_reason": "no_valid_mids",
            "n_ok": 0,
            "n_total": len(quotes),
            "dispersion_bps": None,
            "spread_max_min_bps": None,
            "note": "fail-closed: no invented dispersion",
        }
    mids = [float(q["mid"]) for q in ok_rows]
    mx, mn = max(mids), min(mids)
    mid_avg = sum(mids) / len(mids)
    if mid_avg <= 0:
        return {
            "status": "bad_mid",
            "kill": True,
            "kill_reason": "bad_mid",
            "n_ok": len(ok_rows),
            "n_total": len(quotes),
            "dispersion_bps": None,
            "note": "fail-closed: non-positive average mid",
        }
    spread_bps = ((mx - mn) / mid_avg) * 1e4
    adjacent: list[dict[str, Any]] = []
    sorted_rows = sorted(ok_rows, key=lambda r: int(r.get("in_amount") or 0))
    for a, b in zip(sorted_rows, sorted_rows[1:]):
        ma, mb = float(a["mid"]), float(b["mid"])
        m = (ma + mb) / 2.0
        adj = ((mb - ma) / m) * 1e4 if m > 0 else None
        adjacent.append(
            {
                "from_amount": a.get("in_amount"),
                "to_amount": b.get("in_amount"),
                "from_mid": ma,
                "to_mid": mb,
                "adj_spread_bps": adj,
            }
        )
    return {
        "status": "ok",
        "kill": False,
        "kill_reason": None,
        "n_ok": len(ok_rows),
        "n_total": len(quotes),
        "min_mid": mn,
        "max_mid": mx,
        "avg_mid": mid_avg,
        "dispersion_bps": spread_bps,
        "spread_max_min_bps": spread_bps,
        "adjacent": adjacent,
        "note": (
            "Jupiter multi-size dispersion: (max_mid-min_mid)/avg_mid * 1e4; "
            "size ladder quote-only; research tape"
        ),
    }


def fetch_pool_mid_raydium(
    *,
    timeout: float = DEFAULT_TIMEOUT,
    allow_fixture: bool = False,
    use_fixture: bool = False,
) -> dict[str, Any]:
    """Best-effort Raydium RO mid for SOL/USDC. Fail -> deferred (no invent)."""
    if use_fixture:
        if not allow_fixture:
            return {
                "venue": "raydium",
                "status": "kill",
                "kill": True,
                "kill_reason": "money_leg_source_fixture",
                "mid": None,
                "fixture": True,
                "ts": _utc_now_iso(),
                "note": "fixture killed unless allow_fixture",
            }
        return {
            "venue": "raydium",
            "status": "ok",
            "mid": 149.8,
            "symbol": "SOL/USDC",
            "source": "fixture",
            "fixture": True,
            "ts": _utc_now_iso(),
            "note": "FIXTURE Raydium mid — tests only",
        }
    url = (
        f"{RAYDIUM_API_V3_BASE}/mint/price?"
        + urllib.parse.urlencode({"mints": jup.SOL_MINT})
    )
    try:
        data = _http_get_json(url, timeout=timeout)
    except DispersionError as e:
        msg = str(e)
        status = "rate_limit" if ("rate_limit" in msg or "429" in msg) else "deferred"
        return {
            "venue": "raydium",
            "status": status,
            "mid": None,
            "error": msg,
            "ts": _utc_now_iso(),
            "source": "raydium_api_v3_mint_price",
            "fixture": False,
            "note": "Raydium pool/mint mid deferred — no invented mid",
            "docs": "https://api-v3.raydium.io/",
        }
    mid = None
    if isinstance(data, dict):
        payload = data.get("data") if isinstance(data.get("data"), dict) else data
        if isinstance(payload, dict):
            raw = payload.get(jup.SOL_MINT) or payload.get("price") or payload.get("value")
            try:
                if isinstance(raw, dict):
                    raw = raw.get("price") or raw.get("value")
                mid = float(raw) if raw is not None else None
            except (TypeError, ValueError):
                mid = None
    if mid is None or mid <= 0:
        return {
            "venue": "raydium",
            "status": "deferred",
            "mid": None,
            "raw_keys": sorted(str(k) for k in (data.keys() if isinstance(data, dict) else [])),
            "ts": _utc_now_iso(),
            "source": "raydium_api_v3_mint_price",
            "fixture": False,
            "note": "Raydium response lacked usable SOL mid — deferred; no invent",
        }
    return {
        "venue": "raydium",
        "status": "ok",
        "mid": float(mid),
        "symbol": "SOL/USDC",
        "ts": _utc_now_iso(),
        "source": "raydium_api_v3_mint_price",
        "fixture": False,
        "note": "Raydium public mint price (RO) — research only",
    }


def fetch_pool_mid_orca(
    *,
    timeout: float = DEFAULT_TIMEOUT,
    allow_fixture: bool = False,
    use_fixture: bool = False,
) -> dict[str, Any]:
    """Best-effort Orca RO mid. Default deferred if API unavailable."""
    if use_fixture:
        if not allow_fixture:
            return {
                "venue": "orca",
                "status": "kill",
                "kill": True,
                "kill_reason": "money_leg_source_fixture",
                "mid": None,
                "fixture": True,
                "ts": _utc_now_iso(),
                "note": "fixture killed unless allow_fixture",
            }
        return {
            "venue": "orca",
            "status": "ok",
            "mid": 149.9,
            "symbol": "SOL/USDC",
            "source": "fixture",
            "fixture": True,
            "ts": _utc_now_iso(),
            "note": "FIXTURE Orca mid — tests only",
        }
    url = f"{ORCA_API_BASE}/whirlpool/{ORCA_WHIRLPOOL_SOL_USDC}"
    try:
        data = _http_get_json(url, timeout=timeout)
    except DispersionError as e:
        msg = str(e)
        status = "rate_limit" if ("rate_limit" in msg or "429" in msg) else "deferred"
        return {
            "venue": "orca",
            "status": status,
            "mid": None,
            "error": msg,
            "pool": ORCA_WHIRLPOOL_SOL_USDC,
            "ts": _utc_now_iso(),
            "source": "orca_whirlpool_api",
            "fixture": False,
            "note": "Orca pool mid deferred — no invented mid",
        }
    mid = None
    if isinstance(data, dict):
        for key in ("price", "tokenAPrice", "whirlpoolPrice", "currentPrice"):
            if data.get(key) is not None:
                try:
                    mid = float(data[key])
                    break
                except (TypeError, ValueError):
                    continue
    if mid is None or mid <= 0:
        return {
            "venue": "orca",
            "status": "deferred",
            "mid": None,
            "pool": ORCA_WHIRLPOOL_SOL_USDC,
            "ts": _utc_now_iso(),
            "source": "orca_whirlpool_api",
            "fixture": False,
            "note": "Orca response lacked usable mid — deferred; no invent",
        }
    return {
        "venue": "orca",
        "status": "ok",
        "mid": float(mid),
        "symbol": "SOL/USDC",
        "pool": ORCA_WHIRLPOOL_SOL_USDC,
        "ts": _utc_now_iso(),
        "source": "orca_whirlpool_api",
        "fixture": False,
        "note": "Orca public whirlpool mid (RO) — research only",
    }


def fetch_pool_mid_meteora(
    *,
    timeout: float = DEFAULT_TIMEOUT,
    allow_fixture: bool = False,
    use_fixture: bool = False,
) -> dict[str, Any]:
    """Best-effort Meteora RO mid. Default deferred if API unavailable."""
    if use_fixture:
        if not allow_fixture:
            return {
                "venue": "meteora",
                "status": "kill",
                "kill": True,
                "kill_reason": "money_leg_source_fixture",
                "mid": None,
                "fixture": True,
                "ts": _utc_now_iso(),
                "note": "fixture killed unless allow_fixture",
            }
        return {
            "venue": "meteora",
            "status": "ok",
            "mid": 149.7,
            "symbol": "SOL/USDC",
            "source": "fixture",
            "fixture": True,
            "ts": _utc_now_iso(),
            "note": "FIXTURE Meteora mid — tests only",
        }
    url = f"{METEORA_API_BASE}/pair/all_by_groups"
    try:
        data = _http_get_json(url, timeout=min(timeout, 5.0))
    except DispersionError as e:
        msg = str(e)
        status = "rate_limit" if ("rate_limit" in msg or "429" in msg) else "deferred"
        return {
            "venue": "meteora",
            "status": status,
            "mid": None,
            "error": msg,
            "ts": _utc_now_iso(),
            "source": "meteora_dlmm_api",
            "fixture": False,
            "note": "Meteora pool mid deferred — no invented mid",
            "docs": "https://dlmm-api.meteora.ag/",
        }
    _ = data  # probed reachable; mid extraction deferred this slice
    return {
        "venue": "meteora",
        "status": "deferred",
        "mid": None,
        "ts": _utc_now_iso(),
        "source": "meteora_dlmm_api",
        "fixture": False,
        "note": (
            "Meteora SOL/USDC pool mid extraction deferred this slice — "
            "no invented mid; Jupiter size-ladder is SoT"
        ),
        "docs": "https://dlmm-api.meteora.ag/",
    }


def compare_jupiter_vs_pools(
    jupiter_avg_mid: Optional[float],
    pools: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Compare Jupiter avg mid vs available pool RO mids. Skip missing."""
    rows: dict[str, Any] = {}
    if jupiter_avg_mid is None or jupiter_avg_mid <= 0:
        return {
            "status": "empty",
            "comparisons": {},
            "note": "no Jupiter mid for pool compare — fail-closed",
        }
    any_ok = False
    for name, leg in pools.items():
        if not isinstance(leg, dict):
            continue
        mid = leg.get("mid")
        if leg.get("status") != "ok" or mid is None:
            rows[name] = {
                "status": leg.get("status") or "unavailable",
                "dispersion_bps": None,
                "pool_mid": None,
                "note": leg.get("note") or "pool mid unavailable",
            }
            continue
        try:
            pm = float(mid)
        except (TypeError, ValueError):
            rows[name] = {"status": "bad_mid", "dispersion_bps": None, "pool_mid": None}
            continue
        if pm <= 0:
            rows[name] = {"status": "bad_mid", "dispersion_bps": None, "pool_mid": None}
            continue
        m = (float(jupiter_avg_mid) + pm) / 2.0
        bps = ((float(jupiter_avg_mid) - pm) / m) * 1e4
        rows[name] = {
            "status": "ok",
            "jupiter_mid": float(jupiter_avg_mid),
            "pool_mid": pm,
            "dispersion_bps": bps,
            "sign_convention": (
                "(jupiter_avg - pool_mid) / mid * 1e4; positive = Jupiter richer than pool"
            ),
        }
        any_ok = True
    return {
        "status": "ok" if any_ok else "deferred",
        "comparisons": rows,
        "note": (
            "Jupiter vs pool RO mids where available; "
            "deferred venues omitted from edge claims"
        ),
    }


def scan_quote_dispersion(
    *,
    sizes: Optional[list[str]] = None,
    timeout: float = DEFAULT_TIMEOUT,
    allow_fixture: bool = False,
    use_fixture: bool = False,
    probe_pools: bool = True,
    api_key: Optional[str] = None,
    quote_fn: Optional[Callable[..., Any]] = None,
    default_fee_bps: float = DEFAULT_FEE_BPS_ESTIMATE,
    default_slip_bps: int = DEFAULT_SLIPPAGE_BPS_ESTIMATE,
    snaps: int = 1,
) -> dict[str, Any]:
    """
    Run size-ladder Jupiter quotes (+ optional pool probes) -> Ledger JSON.

    snaps: number of full ladder passes to record (thesis >=20 path in tests).
    Fail-closed on empty/rate-limit; fixture-kill unless allow_fixture.
    """
    ladder = [str(x) for x in (sizes or list(DEFAULT_SIZE_LADDER_LAMPORTS))]
    if snaps < 1:
        snaps = 1

    snap_rows: list[dict[str, Any]] = []
    soft_flags: list[str] = []

    for i in range(int(snaps)):
        quotes: list[dict[str, Any]] = []
        for amt in ladder:
            q = fetch_jupiter_size_quote(
                amt,
                timeout=timeout,
                allow_fixture=allow_fixture,
                use_fixture=use_fixture,
                api_key=api_key,
                quote_fn=quote_fn,
            )
            quotes.append(q)

        if any(_leg_is_fixture(q) for q in quotes) and not allow_fixture:
            disp = {
                "status": "kill",
                "kill": True,
                "kill_reason": "money_leg_source_fixture",
                "n_ok": 0,
                "n_total": len(quotes),
                "dispersion_bps": None,
                "note": "fixture money-path killed unless allow_fixture",
            }
            fee_stack = FeeSlipStack().to_dict()
        else:
            disp = compute_size_dispersion(quotes)
            ok_q = next((q for q in quotes if q.get("status") == "ok"), {})
            fee_stack = fee_slip_from_quote(
                ok_q, default_fee_bps=default_fee_bps, default_slip_bps=default_slip_bps
            ).to_dict()

        if any(q.get("status") == "rate_limit" for q in quotes):
            soft_flags.append("rate_limit")
            if disp.get("n_ok", 0) == 0:
                disp = {
                    "status": "rate_limit",
                    "kill": True,
                    "kill_reason": "rate_limit",
                    "n_ok": 0,
                    "n_total": len(quotes),
                    "dispersion_bps": None,
                    "note": "fail-closed on rate_limit — no invented mids",
                }
        if disp.get("n_ok", 0) == 0 and disp.get("kill_reason") != "money_leg_source_fixture":
            if any(q.get("status") in ("empty", "empty_or_error") for q in quotes):
                soft_flags.append("empty")
                disp = {
                    "status": "empty",
                    "kill": True,
                    "kill_reason": "empty",
                    "n_ok": 0,
                    "n_total": len(quotes),
                    "dispersion_bps": None,
                    "note": "fail-closed on empty quotes — no invented mids",
                }

        if probe_pools:
            pools = {
                "raydium": fetch_pool_mid_raydium(
                    timeout=timeout, allow_fixture=allow_fixture, use_fixture=use_fixture
                ),
                "orca": fetch_pool_mid_orca(
                    timeout=timeout, allow_fixture=allow_fixture, use_fixture=use_fixture
                ),
                "meteora": fetch_pool_mid_meteora(
                    timeout=timeout, allow_fixture=allow_fixture, use_fixture=use_fixture
                ),
            }
            if not allow_fixture:
                for k, leg in list(pools.items()):
                    if _leg_is_fixture(leg):
                        pools[k] = {
                            **leg,
                            "status": "kill",
                            "kill": True,
                            "kill_reason": "money_leg_source_fixture",
                            "mid": None,
                            "note": "fixture pool mid killed unless allow_fixture",
                        }
        else:
            pools = {
                "raydium": {"venue": "raydium", "status": "skipped", "mid": None},
                "orca": {"venue": "orca", "status": "skipped", "mid": None},
                "meteora": {"venue": "meteora", "status": "skipped", "mid": None},
            }

        pool_cmp = compare_jupiter_vs_pools(disp.get("avg_mid"), pools)

        snap_rows.append(
            {
                "snap": i + 1,
                "ts": _utc_now_iso(),
                "quotes": quotes,
                "size_dispersion": disp,
                "fee_slip_stack": fee_stack,
                "pools": pools,
                "jupiter_vs_pools": pool_cmp,
                "kill": bool(disp.get("kill")),
                "kill_reason": disp.get("kill_reason"),
            }
        )

    n_alive = sum(1 for s in snap_rows if not s.get("kill"))
    kill = n_alive == 0
    first_kill = next((s.get("kill_reason") for s in snap_rows if s.get("kill")), None)
    last = snap_rows[-1] if snap_rows else {}

    return {
        "status": "ok" if not kill else (first_kill or "kill"),
        "kill": kill,
        "kill_reason": None if not kill else (first_kill or "lane_kill"),
        "lane": "jupiter_quote_dispersion",
        "mode": "paper",
        "live": False,
        "execution": "scan_only",
        "pair": "SOL/USDC",
        "input_mint": jup.SOL_MINT,
        "output_mint": jup.USDC_MINT,
        "size_ladder_lamports": ladder,
        "snaps": len(snap_rows),
        "snaps_ok": n_alive,
        "samples": snap_rows,
        "latest": last,
        "soft_flags": soft_flags,
        "pool_mids_policy": (
            "Raydium/Orca/Meteora RO mids best-effort; deferred when blocked/unparsed; "
            "never invent; Jupiter multi-size dispersion is MVP SoT"
        ),
        "ts": _utc_now_iso(),
        "thesis": (
            "T1-plus Jupiter quote-dispersion: size-ladder mids + fee/slip stack; "
            "optional pool RO compare; fixture-kill; --live refuse; no tips/auto-trade"
        ),
        "note": (
            "Research/dry-run only. Fail-closed on empty/rate-limit. "
            "Pool mids may be deferred — see pool_mids_policy."
        ),
    }


__all__ = [
    "DEFAULT_SIZE_LADDER_LAMPORTS",
    "DispersionError",
    "FeeSlipStack",
    "compare_jupiter_vs_pools",
    "compute_size_dispersion",
    "fee_slip_from_quote",
    "fetch_jupiter_size_quote",
    "fetch_pool_mid_meteora",
    "fetch_pool_mid_orca",
    "fetch_pool_mid_raydium",
    "scan_quote_dispersion",
]

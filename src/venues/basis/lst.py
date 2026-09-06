"""LST fair-rate vs Jupiter LST↔SOL quotes (paper / RO SCAN).

Compares protocol fair exchange rates to Jupiter aggregator quotes:

1. **Marinade mSOL:** fair rate from ``GET https://api.marinade.finance/msol/price_sol``
   (SOL per 1 mSOL; public RO; no APY tipster fields used).
2. **jitoSOL:** fair rate = totalLamports / poolTokenSupply from SPL stake-pool
   account ``Jito4APyf642JPZPx3hGc6WWJ8zPKtRbRs4P815Awbb`` via public RPC
   ``getAccountInfo`` (RO decode; no SDK; no stake/unstake).

Jupiter leg: ``GET /swap/v2/order`` WITHOUT taker (quote-only) for LST→SOL.
Sign: gross_basis_bps = (jupiter_sol_per_lst - fair_sol_per_lst) / mid * 1e4
  positive = Jupiter richer than fair (DEX premium vs protocol).
  negative = Jupiter discount vs fair.

Fee haircuts labeled ESTIMATE. --live never here (CLI refuses). Fixture-kill
default. Never invent rates; fail closed on HTTP/RPC errors. No tips / APY
marketing / auto-trade.
"""
from __future__ import annotations

import base64
import json
import struct
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from venues.basis.bitkub_bnth import (
    BasisError,
    _age_sec,
    _leg_is_fixture,
    _utc_now,
    _utc_now_iso,
)
from venues.solana import jupiter_quotes as jup
from venues.solana.desk_balance import DEFAULT_RPC_URL, resolve_rpc_url

# --- Known mints / pool ---
SOL_MINT = jup.SOL_MINT
MSOL_MINT = "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So"
JITOSOL_MINT = "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn"
JITO_STAKE_POOL = "Jito4APyf642JPZPx3hGc6WWJ8zPKtRbRs4P815Awbb"

# SPL StakePool: total_lamports @ 258, pool_token_supply @ 266 (u64 LE each)
_STAKE_POOL_TOTAL_LAMPORTS_OFF = 258
_STAKE_POOL_TOKEN_SUPPLY_OFF = 266

MARINADE_MSOL_PRICE_SOL_URL = "https://api.marinade.finance/msol/price_sol"
MARINADE_DOCS = "https://docs.marinade.finance/marinade-protocol/protocol-overview/marinade-liquid/msol-token"
JITO_STAKE_DOCS = "https://www.jito.network/docs/jitosol/jitosol-liquid-staking/for-developers/staking-integration/"

DEFAULT_TIMEOUT = 10.0
DEFAULT_MAX_AGE_SEC = 60.0
DEFAULT_LST_AMOUNT = "100000000"  # 0.1 LST (9 dp)
USER_AGENT = "Patpat-MakeMoney/venues-basis-lst"

# Labeled ESTIMATE Jupiter fee haircut when API feeBps absent
DEFAULT_JUPITER_FEE_BPS = 5.0
DEFAULT_MIN_NET_BPS = 0.0

# Fixture fair rates (offline tests only)
FIXTURE_MSOL_FAIR = 1.40
FIXTURE_JITOSOL_FAIR = 1.20
FIXTURE_JUP_MSOL_MID = 1.402  # slight premium vs fair
FIXTURE_JUP_JITO_MID = 1.195  # slight discount vs fair


@dataclass
class LstFeeConfig:
    """Configurable fee haircuts — labeled ESTIMATE for paper falsify."""

    jupiter_fee_bps: float = DEFAULT_JUPITER_FEE_BPS
    min_net_bps: float = DEFAULT_MIN_NET_BPS

    def fee_floor_bps(self, api_fee_bps: Optional[float] = None) -> float:
        if api_fee_bps is not None:
            return float(api_fee_bps)
        return float(self.jupiter_fee_bps)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["fee_floor_bps_default"] = self.fee_floor_bps()
        d["label"] = "ESTIMATE"
        d["note"] = (
            "jupiter_fee_bps is ESTIMATE when API feeBps absent; "
            "prefer API feeBps when present — not a tipster / APY claim"
        )
        return d


def _http_get_text(url: str, *, timeout: float = DEFAULT_TIMEOUT) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8").strip()
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        raise BasisError(f"HTTP {e.code} from {url}: {body}") from e
    except urllib.error.URLError as e:
        raise BasisError(f"network error {url}: {e.reason}") from e
    except TimeoutError as e:
        raise BasisError(f"timeout {url}") from e


def _rpc_get_account_data(
    pubkey: str,
    *,
    rpc_url: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> bytes:
    url = resolve_rpc_url(rpc_url)
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getAccountInfo",
            "params": [pubkey, {"encoding": "base64"}],
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        raise BasisError(f"RPC HTTP {e.code} from {url}: {detail}") from e
    except urllib.error.URLError as e:
        raise BasisError(f"RPC network error {url}: {e.reason}") from e
    except TimeoutError as e:
        raise BasisError(f"RPC timeout {url}") from e
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        raise BasisError(f"invalid JSON from RPC {url}") from e
    if not isinstance(payload, dict):
        raise BasisError(f"unexpected RPC payload type: {type(payload)}")
    if payload.get("error"):
        raise BasisError(f"RPC error: {payload['error']!r}")
    result = payload.get("result")
    if not isinstance(result, dict) or result.get("value") is None:
        raise BasisError(f"stake pool account missing: {pubkey}")
    value = result["value"]
    if not isinstance(value, dict) or not value.get("data"):
        raise BasisError(f"stake pool account empty data: {pubkey}")
    data_field = value["data"]
    if isinstance(data_field, list) and data_field:
        b64 = data_field[0]
    elif isinstance(data_field, str):
        b64 = data_field
    else:
        raise BasisError(f"unexpected account data encoding: {type(data_field)}")
    try:
        return base64.b64decode(b64)
    except Exception as e:
        raise BasisError(f"base64 decode failed for {pubkey}") from e


def decode_stake_pool_ratio(data: bytes) -> dict[str, Any]:
    """Decode SPL StakePool totalLamports / poolTokenSupply → SOL per 1 pool token."""
    need = _STAKE_POOL_TOKEN_SUPPLY_OFF + 8
    if len(data) < need:
        raise BasisError(
            f"stake pool account too short: len={len(data)} need>={need}"
        )
    total_lamports = struct.unpack_from(
        "<Q", data, _STAKE_POOL_TOTAL_LAMPORTS_OFF
    )[0]
    pool_token_supply = struct.unpack_from(
        "<Q", data, _STAKE_POOL_TOKEN_SUPPLY_OFF
    )[0]
    if pool_token_supply <= 0:
        raise BasisError(f"non-positive pool_token_supply: {pool_token_supply}")
    if total_lamports <= 0:
        raise BasisError(f"non-positive total_lamports: {total_lamports}")
    # Both are 1e9-scaled (lamports vs 9-dp pool tokens) → ratio is SOL per 1 LST
    ratio = float(total_lamports) / float(pool_token_supply)
    return {
        "total_lamports": int(total_lamports),
        "pool_token_supply": int(pool_token_supply),
        "sol_per_lst": ratio,
    }


def fetch_msol_fair_rate(
    *,
    timeout: float = DEFAULT_TIMEOUT,
    allow_fixture: bool = False,
    use_fixture: bool = False,
    injected: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Marinade mSOL fair rate (SOL per 1 mSOL). Public RO; no APY fields."""
    if injected is not None:
        px = float(injected["price"])
        if px <= 0:
            raise BasisError(f"bad injected mSOL fair: {injected!r}")
        return {
            "lst": "mSOL",
            "mint": MSOL_MINT,
            "sol_per_lst": px,
            "ts": injected.get("ts") or _utc_now_iso(),
            "source": injected.get("source") or "injected",
            "fixture": _leg_is_fixture(injected),
            "docs": MARINADE_DOCS,
            "note": "Marinade fair mSOL/SOL — protocol true price; not DEX mid; no APY",
        }
    if use_fixture:
        if not allow_fixture:
            raise BasisError(
                "use_fixture=True requires allow_fixture=True (no silent fixture)"
            )
        return {
            "lst": "mSOL",
            "mint": MSOL_MINT,
            "sol_per_lst": float(FIXTURE_MSOL_FAIR),
            "ts": _utc_now_iso(),
            "source": "fixture",
            "fixture": True,
            "docs": MARINADE_DOCS,
            "note": "FIXTURE Marinade fair — tests only; no APY",
        }
    text = _http_get_text(MARINADE_MSOL_PRICE_SOL_URL, timeout=timeout)
    try:
        px = float(text)
    except ValueError as e:
        raise BasisError(f"Marinade msol/price_sol not a float: {text!r}") from e
    if px <= 0:
        raise BasisError(f"non-positive Marinade mSOL fair: {px}")
    return {
        "lst": "mSOL",
        "mint": MSOL_MINT,
        "sol_per_lst": px,
        "ts": _utc_now_iso(),
        "source": "marinade_msol_price_sol",
        "fixture": False,
        "url": MARINADE_MSOL_PRICE_SOL_URL,
        "docs": MARINADE_DOCS,
        "note": (
            "Marinade fair mSOL/SOL from api.marinade.finance/msol/price_sol "
            "(protocol true price); APY endpoints intentionally unused"
        ),
    }


def fetch_jitosol_fair_rate(
    *,
    timeout: float = DEFAULT_TIMEOUT,
    rpc_url: Optional[str] = None,
    allow_fixture: bool = False,
    use_fixture: bool = False,
    injected: Optional[dict[str, Any]] = None,
    account_data: Optional[bytes] = None,
) -> dict[str, Any]:
    """jitoSOL fair rate from SPL stake-pool ratio (public RPC RO)."""
    if injected is not None:
        px = float(injected["price"])
        if px <= 0:
            raise BasisError(f"bad injected jitoSOL fair: {injected!r}")
        return {
            "lst": "jitoSOL",
            "mint": JITOSOL_MINT,
            "pool": JITO_STAKE_POOL,
            "sol_per_lst": px,
            "ts": injected.get("ts") or _utc_now_iso(),
            "source": injected.get("source") or "injected",
            "fixture": _leg_is_fixture(injected),
            "docs": JITO_STAKE_DOCS,
            "note": "jitoSOL fair = totalLamports/poolTokenSupply — not DEX mid; no APY",
        }
    if use_fixture:
        if not allow_fixture:
            raise BasisError(
                "use_fixture=True requires allow_fixture=True (no silent fixture)"
            )
        return {
            "lst": "jitoSOL",
            "mint": JITOSOL_MINT,
            "pool": JITO_STAKE_POOL,
            "sol_per_lst": float(FIXTURE_JITOSOL_FAIR),
            "ts": _utc_now_iso(),
            "source": "fixture",
            "fixture": True,
            "docs": JITO_STAKE_DOCS,
            "note": "FIXTURE jitoSOL fair — tests only; no APY",
        }
    data = account_data if account_data is not None else _rpc_get_account_data(
        JITO_STAKE_POOL, rpc_url=rpc_url, timeout=timeout
    )
    decoded = decode_stake_pool_ratio(data)
    return {
        "lst": "jitoSOL",
        "mint": JITOSOL_MINT,
        "pool": JITO_STAKE_POOL,
        "sol_per_lst": float(decoded["sol_per_lst"]),
        "total_lamports": decoded["total_lamports"],
        "pool_token_supply": decoded["pool_token_supply"],
        "ts": _utc_now_iso(),
        "source": "jito_spl_stake_pool_rpc",
        "rpc_url": resolve_rpc_url(rpc_url),
        "fixture": False,
        "docs": JITO_STAKE_DOCS,
        "note": (
            "jitoSOL fair = totalLamports/poolTokenSupply from SPL stake pool "
            f"{JITO_STAKE_POOL} via public RPC getAccountInfo; no APY / tips"
        ),
    }


def fetch_jupiter_lst_sol_leg(
    *,
    lst: str,
    timeout: float = DEFAULT_TIMEOUT,
    allow_fixture: bool = False,
    use_fixture: bool = False,
    amount: str = DEFAULT_LST_AMOUNT,
    quote: Optional[dict[str, Any]] = None,
    api_key: Optional[str] = None,
) -> dict[str, Any]:
    """Jupiter LST→SOL mid as sol_per_lst (quote-only; no taker)."""
    lst_u = lst.strip()
    if lst_u not in ("mSOL", "jitoSOL"):
        raise BasisError(f"unsupported LST for Jupiter leg: {lst!r}")
    mint = MSOL_MINT if lst_u == "mSOL" else JITOSOL_MINT
    fixture_mid = (
        FIXTURE_JUP_MSOL_MID if lst_u == "mSOL" else FIXTURE_JUP_JITO_MID
    )

    if quote is not None:
        mid = quote.get("mid", quote.get("price"))
        if mid is None:
            raise BasisError(f"jupiter LST quote missing mid/price: {quote!r}")
        return {
            "venue": quote.get("venue") or "jupiter_solana",
            "symbol": str(quote.get("symbol") or f"{lst_u}/SOL"),
            "lst": lst_u,
            "mint": mint,
            "sol_per_lst": float(mid),
            "ts": quote.get("ts") or _utc_now_iso(),
            "source": quote.get("source") or "jupiter_swap_v2_order",
            "fixture": _leg_is_fixture(quote),
            "fee_bps_api": quote.get("fee_bps"),
            "route_labels": list(quote.get("route_labels") or []),
            "router": quote.get("router"),
            "price_impact_pct": quote.get("price_impact_pct"),
            "note": "Jupiter LST→SOL research mid — quote-only; never sign/send",
        }

    if use_fixture:
        if not allow_fixture:
            raise BasisError(
                "use_fixture=True requires allow_fixture=True (no silent fixture)"
            )
        return {
            "venue": "jupiter_solana",
            "symbol": f"{lst_u}/SOL",
            "lst": lst_u,
            "mint": mint,
            "sol_per_lst": float(fixture_mid),
            "ts": _utc_now_iso(),
            "source": "fixture",
            "fixture": True,
            "fee_bps_api": 2.0,
            "route_labels": ["fixture"],
            "router": "fixture",
            "price_impact_pct": 0.0,
            "note": "FIXTURE Jupiter LST→SOL — tests only; never sign/send",
        }

    # Ensure decimals known for LST mints
    jq = jup.fetch_jupiter_order_quote(
        input_mint=mint,
        output_mint=SOL_MINT,
        amount=amount,
        input_decimals=9,
        output_decimals=9,
        timeout=timeout,
        allow_fixture=False,
        use_fixture=False,
        api_key=api_key,
    )
    d = jq.to_dict()
    return {
        "venue": d["venue"],
        "symbol": d["symbol"],
        "lst": lst_u,
        "mint": mint,
        "sol_per_lst": float(d["mid"]),
        "ts": d["ts"],
        "source": d["source"],
        "fixture": False,
        "fee_bps_api": d.get("fee_bps"),
        "route_labels": list(d.get("route_labels") or []),
        "router": d.get("router"),
        "price_impact_pct": d.get("price_impact_pct"),
        "in_amount": d.get("in_amount"),
        "out_amount": d.get("out_amount"),
        "note": "Jupiter LST→SOL research mid — quote-only; never sign/send",
    }


def compute_lst_basis_bps(fair_sol_per_lst: float, jupiter_sol_per_lst: float) -> dict[str, Any]:
    """
    LST basis in SOL units.

    Sign: gross_basis_bps = (jupiter - fair) / mid * 1e4
    mid = (jupiter + fair) / 2
    positive = Jupiter richer than protocol fair (DEX premium).
    """
    if fair_sol_per_lst <= 0 or jupiter_sol_per_lst <= 0:
        raise BasisError(
            f"non-positive rates: fair={fair_sol_per_lst} jup={jupiter_sol_per_lst}"
        )
    mid = (float(fair_sol_per_lst) + float(jupiter_sol_per_lst)) / 2.0
    spread = float(jupiter_sol_per_lst) - float(fair_sol_per_lst)
    basis_bps = (spread / mid) * 1e4
    return {
        "fair_sol_per_lst": float(fair_sol_per_lst),
        "jupiter_sol_per_lst": float(jupiter_sol_per_lst),
        "mid": mid,
        "abs_spread_sol": spread,
        "gross_basis_bps": basis_bps,
        "basis_bps": basis_bps,
        "sign_convention": (
            "gross_basis_bps = (jupiter_sol_per_lst - fair_sol_per_lst) / mid * 1e4; "
            "positive = Jupiter richer than protocol fair (DEX premium)"
        ),
    }


def detect_lst_basis(
    fair: dict[str, Any],
    jupiter: dict[str, Any],
    *,
    fees: Optional[LstFeeConfig] = None,
    allow_fixture: bool = False,
    max_age_sec: float = DEFAULT_MAX_AGE_SEC,
    now: Optional[datetime] = None,
    soft_flags: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Compare one LST fair rate vs Jupiter LST→SOL mid."""
    fees = fees or LstFeeConfig()
    fee_dict = fees.to_dict()
    now = now or _utc_now()
    flags = list(soft_flags or [])
    lst = str(fair.get("lst") or jupiter.get("lst") or "")
    legs = {"fair": dict(fair), "jupiter": dict(jupiter)}
    base_note = (
        f"{lst} LST basis SCAN (protocol fair vs Jupiter LST→SOL) — "
        "paper/RO; labeled bps; no APY tipster; no live; fees=ESTIMATE"
    )

    if fair.get("lst") and jupiter.get("lst") and fair["lst"] != jupiter["lst"]:
        return {
            "status": "unit_mismatch",
            "kill": True,
            "kill_reason": "unit_mismatch",
            "lane": "lst_fair_vs_jupiter",
            "lst": lst,
            "unit": "SOL_per_LST",
            "legs": legs,
            "estimated_fees": fee_dict,
            "soft_flags": flags,
            "comparable": False,
            "opportunity": False,
            "ts": _utc_now_iso(),
            "mode": "paper",
            "live": False,
            "execution": "scan_only",
            "note": base_note + f"; LST mismatch fair={fair.get('lst')} jup={jupiter.get('lst')}",
        }

    if _leg_is_fixture(fair) or _leg_is_fixture(jupiter):
        if not allow_fixture:
            return {
                "status": "kill",
                "kill": True,
                "kill_reason": "money_leg_source_fixture",
                "lane": "lst_fair_vs_jupiter",
                "lst": lst,
                "unit": "SOL_per_LST",
                "legs": legs,
                "estimated_fees": fee_dict,
                "soft_flags": flags,
                "comparable": False,
                "opportunity": False,
                "ts": _utc_now_iso(),
                "mode": "paper",
                "live": False,
                "execution": "scan_only",
                "note": base_note + "; fixture money-path killed unless allow_fixture",
            }
        flags.append("fixture_allowed")

    ages = {
        "fair": _age_sec(fair.get("ts"), now=now),
        "jupiter": _age_sec(jupiter.get("ts"), now=now),
    }
    stale = False
    for k, age in ages.items():
        if age is not None and age > max_age_sec:
            stale = True
            flags.append(f"stale_{k}")
    if stale:
        return {
            "status": "stale",
            "kill": True,
            "kill_reason": "stale",
            "lane": "lst_fair_vs_jupiter",
            "lst": lst,
            "unit": "SOL_per_LST",
            "legs": legs,
            "ages_sec": ages,
            "max_age_sec": max_age_sec,
            "estimated_fees": fee_dict,
            "soft_flags": flags,
            "comparable": False,
            "opportunity": False,
            "ts": _utc_now_iso(),
            "mode": "paper",
            "live": False,
            "execution": "scan_only",
            "note": base_note + "; quote age exceeded max_age_sec",
        }

    try:
        calc = compute_lst_basis_bps(
            float(fair["sol_per_lst"]), float(jupiter["sol_per_lst"])
        )
    except (KeyError, TypeError, ValueError, BasisError) as e:
        return {
            "status": "bad_mid",
            "kill": True,
            "kill_reason": "bad_mid",
            "lane": "lst_fair_vs_jupiter",
            "lst": lst,
            "unit": "SOL_per_LST",
            "legs": legs,
            "errors": {"compute": str(e)},
            "estimated_fees": fee_dict,
            "soft_flags": flags,
            "comparable": False,
            "opportunity": False,
            "ts": _utc_now_iso(),
            "mode": "paper",
            "live": False,
            "execution": "scan_only",
            "note": base_note + f"; compute failed: {e}",
        }

    api_fee = jupiter.get("fee_bps_api")
    try:
        api_fee_f = float(api_fee) if api_fee is not None else None
    except (TypeError, ValueError):
        api_fee_f = None
    floor = fees.fee_floor_bps(api_fee_f)
    gross = float(calc["gross_basis_bps"])
    net = abs(gross) - float(floor)
    direction = (
        "jupiter_rich"
        if gross > 0
        else ("fair_rich" if gross < 0 else "flat")
    )
    opp = bool(net >= float(fees.min_net_bps) and abs(gross) > 0)

    # Route-label dispersion hint (not a separate DEX mid — labeled)
    route_labels = list(jupiter.get("route_labels") or [])
    dispersion_hint = {
        "route_labels": route_labels,
        "router": jupiter.get("router"),
        "price_impact_pct": jupiter.get("price_impact_pct"),
        "note": (
            "Jupiter routePlan labels only (Raydium/Orca/Meteora when present) — "
            "not independent DEX mids; primary lane is fair vs Jupiter"
        ),
    }

    return {
        "status": "ok",
        "kill": False,
        "kill_reason": None,
        "lane": "lst_fair_vs_jupiter",
        "lst": lst,
        "unit": "SOL_per_LST",
        "legs": legs,
        "ages_sec": ages,
        "max_age_sec": max_age_sec,
        "gross_basis_bps": gross,
        "net_basis_bps": net,
        "net_basis_bps_label": "ESTIMATE",
        "fee_floor_bps": floor,
        "fee_floor_source": "API_feeBps" if api_fee_f is not None else "ESTIMATE",
        "direction": direction,
        "comparable": True,
        "opportunity": opp,
        "dispersion_hint": dispersion_hint,
        "estimated_fees": fee_dict,
        "soft_flags": flags,
        "calc": calc,
        "ts": _utc_now_iso(),
        "mode": "paper",
        "live": False,
        "execution": "scan_only",
        "note": base_note,
    }


def _lane_fetch_failed(
    lst: str,
    *,
    fair: Optional[dict[str, Any]],
    jupiter: Optional[dict[str, Any]],
    errors: dict[str, str],
    flags: list[str],
    fees: LstFeeConfig,
) -> dict[str, Any]:
    return {
        "status": "fetch_failed",
        "kill": True,
        "kill_reason": "fetch_failed",
        "lane": "lst_fair_vs_jupiter",
        "lst": lst,
        "unit": "SOL_per_LST",
        "legs": {"fair": fair, "jupiter": jupiter},
        "errors": dict(errors),
        "estimated_fees": fees.to_dict(),
        "soft_flags": flags or ["out_of_sync"],
        "comparable": False,
        "opportunity": False,
        "ts": _utc_now_iso(),
        "mode": "paper",
        "live": False,
        "execution": "scan_only",
        "note": (
            f"{lst} LST basis — one or both legs failed; no invented rates; "
            "no APY tipster; no live"
        ),
    }


def scan_lst_basis(
    *,
    lsts: Optional[list[str]] = None,
    timeout: float = DEFAULT_TIMEOUT,
    fees: Optional[LstFeeConfig] = None,
    allow_fixture: bool = False,
    use_fixture: bool = False,
    max_age_sec: float = DEFAULT_MAX_AGE_SEC,
    amount: str = DEFAULT_LST_AMOUNT,
    rpc_url: Optional[str] = None,
    api_key: Optional[str] = None,
    msol_fair: Optional[dict[str, Any]] = None,
    jitosol_fair: Optional[dict[str, Any]] = None,
    msol_jupiter: Optional[dict[str, Any]] = None,
    jitosol_jupiter: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Fetch fair rates + Jupiter LST→SOL quotes; return Ledger JSON.

    Fail closed: HTTP/RPC errors → kill fetch_failed; never invent rates.
    Fixture money path killed unless allow_fixture.
    """
    fees = fees or LstFeeConfig()
    want = [x.strip() for x in (lsts or ["mSOL", "jitoSOL"]) if x and str(x).strip()]
    if not want:
        want = ["mSOL", "jitoSOL"]
    for x in want:
        if x not in ("mSOL", "jitoSOL"):
            raise BasisError(f"unsupported LST in scan: {x!r}")

    flags: list[str] = []
    errors: dict[str, str] = {}
    lanes: dict[str, Any] = {}

    for lst in want:
        fair: Optional[dict[str, Any]] = None
        jup_leg: Optional[dict[str, Any]] = None
        lane_errors: dict[str, str] = {}

        try:
            if lst == "mSOL":
                fair = fetch_msol_fair_rate(
                    timeout=timeout,
                    allow_fixture=allow_fixture,
                    use_fixture=use_fixture,
                    injected=msol_fair,
                )
            else:
                fair = fetch_jitosol_fair_rate(
                    timeout=timeout,
                    rpc_url=rpc_url,
                    allow_fixture=allow_fixture,
                    use_fixture=use_fixture,
                    injected=jitosol_fair,
                )
        except BasisError as e:
            flags.append("out_of_sync")
            lane_errors["fair"] = str(e)
            errors[f"{lst}_fair"] = str(e)

        try:
            inj = msol_jupiter if lst == "mSOL" else jitosol_jupiter
            jup_leg = fetch_jupiter_lst_sol_leg(
                lst=lst,
                timeout=timeout,
                allow_fixture=allow_fixture,
                use_fixture=use_fixture,
                amount=amount,
                quote=inj,
                api_key=api_key,
            )
        except (BasisError, jup.JupiterQuoteError) as e:
            if "out_of_sync" not in flags:
                flags.append("out_of_sync")
            lane_errors["jupiter"] = str(e)
            errors[f"{lst}_jupiter"] = str(e)

        if fair is None or jup_leg is None:
            lanes[lst] = _lane_fetch_failed(
                lst,
                fair=fair,
                jupiter=jup_leg,
                errors=lane_errors,
                flags=list(flags),
                fees=fees,
            )
        else:
            lanes[lst] = detect_lst_basis(
                fair,
                jup_leg,
                fees=fees,
                allow_fixture=allow_fixture,
                max_age_sec=max_age_sec,
                soft_flags=list(flags),
            )

    any_alive = any(not (lanes[k] or {}).get("kill") for k in lanes)
    any_opp = any(
        bool((lanes[k] or {}).get("opportunity")) and not (lanes[k] or {}).get("kill")
        for k in lanes
    )
    kill = not any_alive
    first_kill = next(
        (
            (lanes[k] or {}).get("kill_reason")
            for k in lanes
            if (lanes[k] or {}).get("kill")
        ),
        None,
    )

    return {
        "status": "ok" if not kill else (first_kill or "kill"),
        "kill": kill,
        "kill_reason": None if not kill else (first_kill or "lane_kill"),
        "asset": "LST",
        "mode": "paper",
        "live": False,
        "execution": "scan_only",
        "ts": _utc_now_iso(),
        "estimated_fees": fees.to_dict(),
        "lanes": lanes,
        "msol": lanes.get("mSOL"),
        "jitosol": lanes.get("jitoSOL"),
        "opportunity": any_opp and not kill,
        "soft_flags": flags,
        "errors": errors or None,
        "sources": [
            "api.marinade.finance/msol/price_sol",
            "jito_spl_stake_pool_rpc",
            "jupiter_swap_v2_order",
        ],
        "note": (
            "LST paper/RO basis tape: Marinade mSOL fair and/or jitoSOL stake-pool "
            "ratio vs Jupiter LST→SOL quotes; net_basis_bps labeled ESTIMATE; "
            "fixture-kill default; --live refuse at CLI; no APY tipster; no seeds; "
            "no auto-trade"
        ),
    }


__all__ = [
    "LstFeeConfig",
    "MSOL_MINT",
    "JITOSOL_MINT",
    "JITO_STAKE_POOL",
    "SOL_MINT",
    "DEFAULT_LST_AMOUNT",
    "fetch_msol_fair_rate",
    "fetch_jitosol_fair_rate",
    "fetch_jupiter_lst_sol_leg",
    "decode_stake_pool_ratio",
    "compute_lst_basis_bps",
    "detect_lst_basis",
    "scan_lst_basis",
    "BasisError",
]

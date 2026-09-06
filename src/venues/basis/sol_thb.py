"""Bitkub + BNTH SOL–THB mids vs Jupiter SOL/USDC with labeled FX (paper / RO SCAN).

Extends Bitkub↔BNTH same-ccy THB basis patterns (see bitkub_bnth.py) for SOL:

1. **Same-ccy THB rail (preferred):** Bitkub SOL_THB vs BNTH SOLTHB — no FX.
2. **Jupiter cross-check:** Jupiter SOL/USDC (or SOL stable) mid × labeled
   USDTTHB from api.binance.th public ticker → THB-equivalent mid vs CEX THB mid.

Fee haircuts are labeled ESTIMATE. --live never here (CLI refuses). Fixture-kill
default. Never invent prices/FX; fail closed on HTTP errors.

Sign convention (same_ccy / vs_jupiter):
  basis_bps = (leg_b - leg_a) / mid * 1e4
  mid = (leg_a + leg_b) / 2
  For same_ccy: leg_a=bitkub, leg_b=bnth (positive = BNTH richer).
  For jupiter_fx: leg_a=cex_thb_mid, leg_b=jupiter_thb_equiv
    (positive = Jupiter THB-equiv richer than CEX THB mid).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from venues.basis.bitkub_bnth import (
    BasisError,
    BasisFeeConfig,
    compute_basis_bps,
    mid_from_tape,
    opportunity_persisted,
    _age_sec,
    _assert_thb_quote,
    _leg_is_fixture,
    _utc_now,
    _utc_now_iso,
)
from venues.binance_th import tape as bnth_tape
from venues.bitkub import paper as bitkub_paper
from venues.solana import jupiter_quotes as jup

DEFAULT_BITKUB_SYMBOL = "SOL_THB"
DEFAULT_BNTH_SYMBOL = "SOLTHB"
DEFAULT_TIMEOUT = 8.0
DEFAULT_MAX_AGE_SEC = 30.0

# Labeled ESTIMATE taker haircuts (bps of notional) — paper falsify, not live schedule.
DEFAULT_BITKUB_TAKER_BPS = 25.0
DEFAULT_BNTH_TAKER_BPS = 10.0
DEFAULT_JUPITER_FEE_BPS = 5.0  # ESTIMATE placeholder when API feeBps absent
DEFAULT_FX_SLIP_BPS = 2.0  # ESTIMATE haircut on USDTTHB leg when used


@dataclass
class SolThbFeeConfig:
    """Configurable fee haircuts — all labeled ESTIMATE for paper falsify."""

    bitkub_taker_bps: float = DEFAULT_BITKUB_TAKER_BPS
    bnth_taker_bps: float = DEFAULT_BNTH_TAKER_BPS
    jupiter_fee_bps: float = DEFAULT_JUPITER_FEE_BPS
    fx_slip_bps: float = DEFAULT_FX_SLIP_BPS
    min_net_bps: float = 0.0

    def same_ccy_fee_floor_bps(self) -> float:
        return float(self.bitkub_taker_bps) + float(self.bnth_taker_bps)

    def jupiter_fx_fee_floor_bps(self) -> float:
        # CEX taker (prefer BNTH) + Jupiter fee ESTIMATE + FX slip ESTIMATE
        return (
            float(self.bnth_taker_bps)
            + float(self.jupiter_fee_bps)
            + float(self.fx_slip_bps)
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["same_ccy_fee_floor_bps"] = self.same_ccy_fee_floor_bps()
        d["jupiter_fx_fee_floor_bps"] = self.jupiter_fx_fee_floor_bps()
        d["label"] = "ESTIMATE"
        d["note"] = (
            "All taker/jupiter/fx_slip bps are labeled ESTIMATE for paper falsify — "
            "not live venue fee schedules"
        )
        return d


def fetch_bitkub_sol_leg(
    symbol: str = DEFAULT_BITKUB_SYMBOL,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    ticker_row: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    row = (
        ticker_row
        if ticker_row is not None
        else bitkub_paper.fetch_public_ticker(symbol, timeout=timeout)
    )
    q = bitkub_paper.ticker_to_tape_quote(row, symbol=symbol).to_dict()
    return mid_from_tape(q)


def fetch_bnth_sol_leg(
    symbol: str = DEFAULT_BNTH_SYMBOL,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    use_fixture: Optional[bool] = None,
    ticker_row: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    if ticker_row is not None:
        q = bnth_tape.ticker_to_tape_quote(ticker_row, symbol=symbol).to_dict()
        q["fixture"] = _leg_is_fixture(ticker_row) or _leg_is_fixture(q)
        return mid_from_tape(q)
    row = bnth_tape.fetch_public_ticker(symbol, timeout=timeout, use_fixture=use_fixture)
    host = str(row.get("_source_host") or "")
    if host and "api.binance.th" not in host and not row.get("_fixture"):
        raise BasisError(f"refusing non-TH BNTH host: {host!r}")
    q = bnth_tape.ticker_to_tape_quote(row, symbol=symbol).to_dict()
    q["fixture"] = _leg_is_fixture(row) or _leg_is_fixture(q)
    q["_source_host"] = row.get("_source_host", "api.binance.th")
    return mid_from_tape(q)


def fetch_jupiter_sol_leg(
    *,
    timeout: float = DEFAULT_TIMEOUT,
    allow_fixture: bool = False,
    use_fixture: bool = False,
    amount: str = "100000000",
    quote: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Jupiter SOL/USDC mid as a tape-like leg (quote_ccy = USDC/USD-stable)."""
    if quote is not None:
        mid = quote.get("mid", quote.get("price"))
        if mid is None:
            raise BasisError(f"jupiter quote missing mid/price: {quote!r}")
        return {
            "venue": quote.get("venue") or "jupiter_solana",
            "symbol": str(quote.get("symbol") or "SOL/USDC"),
            "price": float(mid),
            "ts": quote.get("ts") or _utc_now_iso(),
            "source": quote.get("source") or "jupiter_swap_v2_order",
            "fixture": _leg_is_fixture(quote),
            "quote_ccy": "USDC",
            "fee_bps_api": quote.get("fee_bps"),
            "note": "Jupiter SOL/USDC research mid — not THB; needs labeled FX for THB compare",
        }
    jq = jup.fetch_jupiter_order_quote(
        timeout=timeout,
        allow_fixture=allow_fixture,
        use_fixture=use_fixture,
        amount=amount,
    )
    d = jq.to_dict()
    return {
        "venue": d["venue"],
        "symbol": d["symbol"],
        "price": float(d["mid"]),
        "ts": d["ts"],
        "source": d["source"],
        "fixture": _leg_is_fixture(d),
        "quote_ccy": "USDC",
        "fee_bps_api": d.get("fee_bps"),
        "note": "Jupiter SOL/USDC research mid — not THB; needs labeled FX for THB compare",
    }


def fetch_usdtthb_labeled(
    *,
    timeout: float = DEFAULT_TIMEOUT,
    use_fixture: Optional[bool] = None,
    fx_row: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Labeled USDTTHB from BNTH public — never invent."""
    if fx_row is not None:
        px = float(fx_row["price"])
        if px <= 0:
            raise BasisError(f"bad USDTTHB price: {fx_row!r}")
        return {
            "price": px,
            "pair": "USDTTHB",
            "symbol": str(fx_row.get("symbol") or "USDTTHB"),
            "source": fx_row.get("source") or "injected",
            "ts": fx_row.get("ts") or _utc_now_iso(),
            "fixture": _leg_is_fixture(fx_row),
            "note": fx_row.get("note")
            or "labeled USDTTHB — not invented",
        }
    return bnth_tape.fetch_usdtthb_fx(timeout=timeout, use_fixture=use_fixture)


def jupiter_to_thb_equiv(
    jupiter_leg: dict[str, Any],
    fx: dict[str, Any],
) -> dict[str, Any]:
    """SOL/USDC mid × labeled USDTTHB → THB-equivalent mid (USDC≈USDT labeled)."""
    jup_mid = float(jupiter_leg["price"])
    fx_px = float(fx["price"])
    if jup_mid <= 0 or fx_px <= 0:
        raise BasisError(f"non-positive jupiter/fx: jup={jup_mid} fx={fx_px}")
    thb_equiv = jup_mid * fx_px
    return {
        "venue": "jupiter_thb_equiv",
        "symbol": "SOL_THB_equiv",
        "price": thb_equiv,
        "ts": jupiter_leg.get("ts") or fx.get("ts") or _utc_now_iso(),
        "source": "jupiter_usdc_x_bnth_usdtthb",
        "fixture": bool(_leg_is_fixture(jupiter_leg) or _leg_is_fixture(fx)),
        "quote_ccy": "THB",
        "components": {
            "jupiter_mid_usdc": jup_mid,
            "jupiter_symbol": jupiter_leg.get("symbol"),
            "jupiter_source": jupiter_leg.get("source"),
            "fx_usdtthb": fx_px,
            "fx_source": fx.get("source"),
            "fx_pair": fx.get("pair") or "USDTTHB",
            "stable_label": "USDC≈USDT labeled (explicit; not silent invent)",
        },
        "note": (
            "THB-equivalent = Jupiter SOL/USDC mid × labeled BNTH USDTTHB; "
            "USDC≈USDT is an EXPLICIT desk label"
        ),
    }


def _ledger(
    *,
    status: str,
    kill: bool,
    kill_reason: Optional[str],
    fees: dict[str, Any],
    legs: dict[str, Any],
    flags: list[str],
    note: str,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "status": status,
        "kill": kill,
        "kill_reason": kill_reason,
        "estimated_fees": fees,
        "legs": legs,
        "soft_flags": flags,
        "ts": _utc_now_iso(),
        "mode": "paper",
        "live": False,
        "execution": "scan_only",
        "asset": "SOL",
        "note": note,
    }
    if extra:
        out.update(extra)
    return out


def detect_same_ccy_sol_thb(
    bitkub: dict[str, Any],
    bnth: dict[str, Any],
    *,
    fees: Optional[SolThbFeeConfig] = None,
    allow_fixture: bool = False,
    max_age_sec: float = DEFAULT_MAX_AGE_SEC,
    now: Optional[datetime] = None,
    soft_flags: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Bitkub SOL_THB vs BNTH SOLTHB — same-ccy THB (extend BTC basis pattern)."""
    fees = fees or SolThbFeeConfig()
    fee_dict = fees.to_dict()
    now = now or _utc_now()
    flags = list(soft_flags or [])

    a = mid_from_tape(bitkub)
    b = mid_from_tape(bnth)
    a["role"] = "bitkub"
    b["role"] = "bnth"
    legs = {"bitkub": a, "bnth": b}
    base_note = (
        "SOL same-ccy THB basis SCAN (Bitkub SOL_THB ↔ BNTH SOLTHB) — "
        "paper/RO; no FX; api.binance.th only; no live orders; fees=ESTIMATE"
    )

    err_a = _assert_thb_quote(a["symbol"], "bitkub")
    err_b = _assert_thb_quote(b["symbol"], "bnth")
    if err_a or err_b:
        return _ledger(
            status="unit_mismatch",
            kill=True,
            kill_reason="unit_mismatch",
            fees=fee_dict,
            legs=legs,
            flags=flags,
            note=base_note + f"; {err_a or err_b}; refuse inventing FX",
            extra={"lane": "same_ccy", "unit": None, "comparable": False},
        )

    if not allow_fixture:
        fixture_legs = []
        if _leg_is_fixture(a):
            fixture_legs.append("bitkub")
        if _leg_is_fixture(b):
            fixture_legs.append("bnth")
        if fixture_legs:
            legs["fixture_legs"] = fixture_legs
            out = _ledger(
                status="fixture_mid",
                kill=True,
                kill_reason="money_leg_source_fixture",
                fees=fee_dict,
                legs=legs,
                flags=flags,
                note=(
                    base_note
                    + "; KILL fixture mid on money path — pass allow_fixture for offline tests only"
                ),
                extra={
                    "lane": "same_ccy",
                    "fixture_legs": fixture_legs,
                    "allow_fixture": False,
                    "comparable": False,
                },
            )
            return out

    age_bk = _age_sec(a.get("ts"), now=now)
    age_bn = _age_sec(b.get("ts"), now=now)
    legs["bitkub"]["age_sec"] = age_bk
    legs["bnth"]["age_sec"] = age_bn
    stale_legs = []
    if age_bk is not None and age_bk > float(max_age_sec):
        stale_legs.append("bitkub")
    if age_bn is not None and age_bn > float(max_age_sec):
        stale_legs.append("bnth")
    if stale_legs:
        flags.append("stale")
        legs["stale_legs"] = stale_legs
    if age_bk is not None and age_bn is not None and abs(age_bk - age_bn) > float(max_age_sec):
        if "out_of_sync" not in flags:
            flags.append("out_of_sync")

    try:
        calc = compute_basis_bps(a["price"], b["price"])
    except BasisError as e:
        return _ledger(
            status="bad_mid",
            kill=True,
            kill_reason="bad_mid",
            fees=fee_dict,
            legs=legs,
            flags=flags,
            note=base_note + f"; {e}",
            extra={"lane": "same_ccy", "comparable": False},
        )

    fee_floor = fees.same_ccy_fee_floor_bps()
    gross = float(calc["gross_basis_bps"])
    net = abs(gross) - fee_floor
    if gross > 0:
        direction = "bnth_rich"
    elif gross < 0:
        direction = "bitkub_rich"
    else:
        direction = "flat"

    kill = False
    kill_reason = None
    status = "ok"
    if "stale" in flags:
        kill = True
        kill_reason = "stale"
        status = "stale"
    elif net < float(fees.min_net_bps):
        status = "below_fee_floor" if net < 0 else "ok"

    opportunity = (not kill) and (net >= float(fees.min_net_bps)) and abs(gross) > 0

    return _ledger(
        status=status,
        kill=kill,
        kill_reason=kill_reason,
        fees=fee_dict,
        legs=legs,
        flags=flags,
        note=base_note,
        extra={
            "lane": "same_ccy",
            "unit": "THB",
            "comparable": True,
            "direction": direction,
            "gross_basis_bps": round(gross, 6),
            "basis_bps": round(gross, 6),
            "abs_spread_thb": round(float(calc["abs_spread_thb"]), 6),
            "mid_thb": round(float(calc["mid"]), 6),
            "fee_floor_bps": round(fee_floor, 6),
            "fee_floor_label": "ESTIMATE",
            "net_basis_bps": round(net, 6),
            "net_basis_bps_label": "ESTIMATE",
            "opportunity": opportunity,
            "sign_convention": calc["sign_convention"],
            "max_age_sec": float(max_age_sec),
            "allow_fixture": bool(allow_fixture),
            "sources": ["bitkub", "api.binance.th"],
        },
    )


def detect_jupiter_vs_cex_thb(
    cex_thb: dict[str, Any],
    jupiter_thb_equiv: dict[str, Any],
    fx: dict[str, Any],
    *,
    fees: Optional[SolThbFeeConfig] = None,
    allow_fixture: bool = False,
    max_age_sec: float = DEFAULT_MAX_AGE_SEC,
    now: Optional[datetime] = None,
    soft_flags: Optional[list[str]] = None,
    jupiter_fee_bps_override: Optional[float] = None,
) -> dict[str, Any]:
    """CEX SOL–THB mid vs Jupiter THB-equiv (USDC×labeled USDTTHB)."""
    fees = fees or SolThbFeeConfig()
    if jupiter_fee_bps_override is not None:
        fees = SolThbFeeConfig(
            bitkub_taker_bps=fees.bitkub_taker_bps,
            bnth_taker_bps=fees.bnth_taker_bps,
            jupiter_fee_bps=float(jupiter_fee_bps_override),
            fx_slip_bps=fees.fx_slip_bps,
            min_net_bps=fees.min_net_bps,
        )
    fee_dict = fees.to_dict()
    now = now or _utc_now()
    flags = list(soft_flags or [])

    a = mid_from_tape(cex_thb)
    b = mid_from_tape(jupiter_thb_equiv)
    a["role"] = "cex_thb"
    b["role"] = "jupiter_thb_equiv"
    legs = {
        "cex_thb": a,
        "jupiter_thb_equiv": b,
        "fx": {
            "pair": fx.get("pair") or "USDTTHB",
            "price": fx.get("price"),
            "source": fx.get("source"),
            "ts": fx.get("ts"),
            "fixture": _leg_is_fixture(fx),
            "note": fx.get("note"),
            "label": "labeled_public_USDTTHB",
        },
    }
    base_note = (
        "SOL Jupiter vs CEX THB basis SCAN — Jupiter SOL/USDC × labeled BNTH USDTTHB "
        "vs CEX SOL–THB mid; fees=ESTIMATE; paper/RO; no live"
    )

    err = _assert_thb_quote(a["symbol"], "cex_thb")
    if err:
        # Accept SOL_THB_equiv on jupiter side; cex must be THB symbol
        return _ledger(
            status="unit_mismatch",
            kill=True,
            kill_reason="unit_mismatch",
            fees=fee_dict,
            legs=legs,
            flags=flags,
            note=base_note + f"; {err}",
            extra={"lane": "jupiter_fx", "comparable": False},
        )

    if not allow_fixture:
        fixture_legs = []
        if _leg_is_fixture(a):
            fixture_legs.append("cex_thb")
        if _leg_is_fixture(b):
            fixture_legs.append("jupiter_thb_equiv")
        if _leg_is_fixture(fx):
            fixture_legs.append("fx")
        if fixture_legs:
            legs["fixture_legs"] = fixture_legs
            return _ledger(
                status="fixture_mid",
                kill=True,
                kill_reason="money_leg_source_fixture",
                fees=fee_dict,
                legs=legs,
                flags=flags,
                note=(
                    base_note
                    + "; KILL fixture mid on money path — pass allow_fixture for offline tests only"
                ),
                extra={
                    "lane": "jupiter_fx",
                    "fixture_legs": fixture_legs,
                    "allow_fixture": False,
                    "comparable": False,
                },
            )

    age_a = _age_sec(a.get("ts"), now=now)
    age_b = _age_sec(b.get("ts"), now=now)
    legs["cex_thb"]["age_sec"] = age_a
    legs["jupiter_thb_equiv"]["age_sec"] = age_b
    stale_legs = []
    if age_a is not None and age_a > float(max_age_sec):
        stale_legs.append("cex_thb")
    if age_b is not None and age_b > float(max_age_sec):
        stale_legs.append("jupiter_thb_equiv")
    if stale_legs:
        flags.append("stale")
        legs["stale_legs"] = stale_legs

    try:
        # Reuse compute: (bnth-like - bitkub-like) → here (jupiter - cex)
        calc = compute_basis_bps(a["price"], b["price"])
    except BasisError as e:
        return _ledger(
            status="bad_mid",
            kill=True,
            kill_reason="bad_mid",
            fees=fee_dict,
            legs=legs,
            flags=flags,
            note=base_note + f"; {e}",
            extra={"lane": "jupiter_fx", "comparable": False},
        )

    fee_floor = fees.jupiter_fx_fee_floor_bps()
    gross = float(calc["gross_basis_bps"])
    net = abs(gross) - fee_floor
    if gross > 0:
        direction = "jupiter_rich"
    elif gross < 0:
        direction = "cex_rich"
    else:
        direction = "flat"

    kill = False
    kill_reason = None
    status = "ok"
    if "stale" in flags:
        kill = True
        kill_reason = "stale"
        status = "stale"
    elif net < float(fees.min_net_bps):
        status = "below_fee_floor" if net < 0 else "ok"

    opportunity = (not kill) and (net >= float(fees.min_net_bps)) and abs(gross) > 0

    return _ledger(
        status=status,
        kill=kill,
        kill_reason=kill_reason,
        fees=fee_dict,
        legs=legs,
        flags=flags,
        note=base_note,
        extra={
            "lane": "jupiter_fx",
            "unit": "THB",
            "comparable": True,
            "direction": direction,
            "gross_basis_bps": round(gross, 6),
            "basis_bps": round(gross, 6),
            "abs_spread_thb": round(float(calc["abs_spread_thb"]), 6),
            "mid_thb": round(float(calc["mid"]), 6),
            "fee_floor_bps": round(fee_floor, 6),
            "fee_floor_label": "ESTIMATE",
            "net_basis_bps": round(net, 6),
            "net_basis_bps_label": "ESTIMATE",
            "opportunity": opportunity,
            "sign_convention": (
                "basis_bps = (jupiter_thb_equiv - cex_thb_mid) / mid * 1e4; "
                "positive = Jupiter THB-equiv richer than CEX"
            ),
            "fx_label": "USDTTHB from api.binance.th public (labeled; USDC≈USDT explicit)",
            "max_age_sec": float(max_age_sec),
            "allow_fixture": bool(allow_fixture),
            "sources": ["cex_thb", "jupiter", "api.binance.th/USDTTHB"],
        },
    )


def scan_sol_thb_basis(
    *,
    bitkub_symbol: str = DEFAULT_BITKUB_SYMBOL,
    bnth_symbol: str = DEFAULT_BNTH_SYMBOL,
    timeout: float = DEFAULT_TIMEOUT,
    fees: Optional[SolThbFeeConfig] = None,
    allow_fixture: bool = False,
    use_fixture: bool = False,
    max_age_sec: float = DEFAULT_MAX_AGE_SEC,
    include_jupiter: bool = True,
    cex_prefer: str = "bnth",  # bnth | bitkub | mid
    bitkub_row: Optional[dict[str, Any]] = None,
    bnth_row: Optional[dict[str, Any]] = None,
    jupiter_quote: Optional[dict[str, Any]] = None,
    fx_row: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Fetch public SOL–THB mids (+ optional Jupiter×FX) and return Ledger JSON.

    Fail closed: HTTP errors → kill fetch_failed; never invent mids/FX.
    Fixture money path killed unless allow_fixture.
    """
    fees = fees or SolThbFeeConfig()
    flags: list[str] = []
    errors: dict[str, str] = {}
    bitkub_leg: Optional[dict[str, Any]] = None
    bnth_leg: Optional[dict[str, Any]] = None

    try:
        if use_fixture and bitkub_row is None:
            bitkub_leg = mid_from_tape(
                {
                    "venue": "bitkub_public",
                    "symbol": bitkub_symbol,
                    "price": 5400.0,
                    "ts": _utc_now_iso(),
                    "source": "fixture",
                    "fixture": True,
                }
            )
        else:
            bitkub_leg = fetch_bitkub_sol_leg(
                bitkub_symbol, timeout=timeout, ticker_row=bitkub_row
            )
    except (bitkub_paper.BitkubPaperError, BasisError) as e:
        flags.append("out_of_sync")
        errors["bitkub"] = str(e)

    try:
        if use_fixture and bnth_row is None:
            bnth_leg = mid_from_tape(
                {
                    "venue": "binance_th",
                    "symbol": bnth_symbol,
                    "price": 5410.0,
                    "ts": _utc_now_iso(),
                    "source": "fixture",
                    "fixture": True,
                }
            )
        else:
            bnth_leg = fetch_bnth_sol_leg(
                bnth_symbol,
                timeout=timeout,
                use_fixture=True if use_fixture else None,
                ticker_row=bnth_row,
            )
    except (bnth_tape.BinanceTHError, BasisError) as e:
        if "out_of_sync" not in flags:
            flags.append("out_of_sync")
        errors["bnth"] = str(e)

    same_ccy: Optional[dict[str, Any]] = None
    if bitkub_leg is None or bnth_leg is None:
        same_ccy = {
            "status": "fetch_failed",
            "kill": True,
            "kill_reason": "fetch_failed",
            "lane": "same_ccy",
            "legs": {"bitkub": bitkub_leg, "bnth": bnth_leg},
            "errors": dict(errors),
            "soft_flags": flags or ["out_of_sync"],
            "comparable": False,
            "opportunity": False,
            "note": (
                "SOL same-ccy THB basis — one or both public fetches failed; "
                "no invented mids; no live"
            ),
        }
    else:
        same_ccy = detect_same_ccy_sol_thb(
            bitkub_leg,
            bnth_leg,
            fees=fees,
            allow_fixture=allow_fixture,
            max_age_sec=max_age_sec,
            soft_flags=list(flags),
        )

    jupiter_fx: Optional[dict[str, Any]] = None
    if include_jupiter:
        jup_leg: Optional[dict[str, Any]] = None
        fx: Optional[dict[str, Any]] = None
        try:
            if use_fixture and jupiter_quote is None:
                jq = jup.fixture_sol_usdc_quote()
                jup_leg = fetch_jupiter_sol_leg(quote=jq.to_dict())
            else:
                jup_leg = fetch_jupiter_sol_leg(
                    timeout=timeout,
                    allow_fixture=allow_fixture,
                    use_fixture=use_fixture,
                    quote=jupiter_quote,
                )
        except (jup.JupiterQuoteError, BasisError) as e:
            if "out_of_sync" not in flags:
                flags.append("out_of_sync")
            errors["jupiter"] = str(e)

        try:
            if use_fixture and fx_row is None:
                fx = {
                    "price": 36.0,
                    "pair": "USDTTHB",
                    "symbol": "USDTTHB",
                    "source": "fixture",
                    "ts": _utc_now_iso(),
                    "fixture": True,
                    "note": "FIXTURE labeled USDTTHB — tests only",
                }
            else:
                fx = fetch_usdtthb_labeled(
                    timeout=timeout,
                    use_fixture=True if use_fixture else None,
                    fx_row=fx_row,
                )
        except (bnth_tape.BinanceTHError, BasisError) as e:
            if "out_of_sync" not in flags:
                flags.append("out_of_sync")
            errors["fx"] = str(e)

        # Pick CEX THB mid for Jupiter compare
        cex_leg: Optional[dict[str, Any]] = None
        if cex_prefer == "bitkub" and bitkub_leg is not None:
            cex_leg = dict(bitkub_leg)
            cex_leg["role"] = "cex_thb"
        elif cex_prefer == "mid" and bitkub_leg is not None and bnth_leg is not None:
            mid_px = (float(bitkub_leg["price"]) + float(bnth_leg["price"])) / 2.0
            cex_leg = {
                "venue": "cex_thb_mid",
                "symbol": bnth_symbol if bnth_leg else bitkub_symbol,
                "price": mid_px,
                "ts": bnth_leg.get("ts") or bitkub_leg.get("ts"),
                "source": "bitkub_bnth_avg",
                "fixture": bool(
                    _leg_is_fixture(bitkub_leg) or _leg_is_fixture(bnth_leg)
                ),
                "role": "cex_thb",
            }
        elif bnth_leg is not None:
            cex_leg = dict(bnth_leg)
            cex_leg["role"] = "cex_thb"
        elif bitkub_leg is not None:
            cex_leg = dict(bitkub_leg)
            cex_leg["role"] = "cex_thb"

        if jup_leg is None or fx is None or cex_leg is None:
            jupiter_fx = {
                "status": "fetch_failed",
                "kill": True,
                "kill_reason": "fetch_failed",
                "lane": "jupiter_fx",
                "legs": {
                    "cex_thb": cex_leg,
                    "jupiter": jup_leg,
                    "fx": fx,
                },
                "errors": {k: errors[k] for k in ("jupiter", "fx", "bitkub", "bnth") if k in errors},
                "soft_flags": flags or ["out_of_sync"],
                "comparable": False,
                "opportunity": False,
                "note": (
                    "SOL Jupiter×FX vs CEX THB — missing leg(s); "
                    "no invented mids/FX; no live"
                ),
            }
        else:
            try:
                thb_equiv = jupiter_to_thb_equiv(jup_leg, fx)
                jup_fee = jup_leg.get("fee_bps_api")
                override = float(jup_fee) if jup_fee is not None else None
                jupiter_fx = detect_jupiter_vs_cex_thb(
                    cex_leg,
                    thb_equiv,
                    fx,
                    fees=fees,
                    allow_fixture=allow_fixture,
                    max_age_sec=max_age_sec,
                    soft_flags=list(flags),
                    jupiter_fee_bps_override=override,
                )
                jupiter_fx["jupiter_raw"] = {
                    "mid_usdc": jup_leg.get("price"),
                    "symbol": jup_leg.get("symbol"),
                    "source": jup_leg.get("source"),
                    "fee_bps_api": jup_leg.get("fee_bps_api"),
                }
            except BasisError as e:
                jupiter_fx = {
                    "status": "bad_mid",
                    "kill": True,
                    "kill_reason": "bad_mid",
                    "lane": "jupiter_fx",
                    "errors": {"compute": str(e)},
                    "comparable": False,
                    "opportunity": False,
                    "note": f"SOL Jupiter×FX compute failed: {e}",
                }

    # Top-level kill if both lanes killed / missing
    lanes_kill = True
    if same_ccy and not same_ccy.get("kill"):
        lanes_kill = False
    if jupiter_fx and not jupiter_fx.get("kill"):
        lanes_kill = False
    if not include_jupiter:
        lanes_kill = bool(same_ccy and same_ccy.get("kill"))

    any_opp = bool(
        (same_ccy or {}).get("opportunity")
        or (jupiter_fx or {}).get("opportunity")
    )

    return {
        "status": "ok" if not lanes_kill else (
            (same_ccy or {}).get("status")
            or (jupiter_fx or {}).get("status")
            or "kill"
        ),
        "kill": lanes_kill,
        "kill_reason": None
        if not lanes_kill
        else (
            (same_ccy or {}).get("kill_reason")
            or (jupiter_fx or {}).get("kill_reason")
            or "lane_kill"
        ),
        "asset": "SOL",
        "mode": "paper",
        "live": False,
        "execution": "scan_only",
        "ts": _utc_now_iso(),
        "estimated_fees": fees.to_dict(),
        "same_ccy": same_ccy,
        "jupiter_fx": jupiter_fx,
        "opportunity": any_opp and not lanes_kill,
        "soft_flags": flags,
        "errors": errors or None,
        "sources": [
            "bitkub",
            "api.binance.th",
            "jupiter",
            "api.binance.th/USDTTHB",
        ],
        "note": (
            "SOL–THB paper/RO basis tape: same-ccy Bitkub↔BNTH + optional Jupiter×labeled FX; "
            "net_basis_bps labeled ESTIMATE; fixture-kill default; --live refuse at CLI; "
            "no seeds/tips/live orders"
        ),
    }


# Re-export for CLI convenience
__all__ = [
    "SolThbFeeConfig",
    "DEFAULT_BITKUB_SYMBOL",
    "DEFAULT_BNTH_SYMBOL",
    "fetch_bitkub_sol_leg",
    "fetch_bnth_sol_leg",
    "fetch_jupiter_sol_leg",
    "fetch_usdtthb_labeled",
    "jupiter_to_thb_equiv",
    "detect_same_ccy_sol_thb",
    "detect_jupiter_vs_cex_thb",
    "scan_sol_thb_basis",
    "opportunity_persisted",
    "BasisError",
]

"""Bitkub ↔ Binance TH same-currency THB basis monitor (paper / read-only SCAN).

Compares BTC_THB (Bitkub public ticker) vs BTCTHB (api.binance.th only).
No FX conversion. No live orders. No tipster claims.

Sign convention (gross_basis_bps / basis_bps):
  basis_bps = (bnth_mid - bitkub_mid) / mid * 1e4
  where mid = (bnth_mid + bitkub_mid) / 2
  Positive → BNTH richer than Bitkub (BNTH mid above Bitkub).
  Negative → Bitkub richer than BNTH.

net_basis_bps = abs(gross_basis_bps) - fee_floor_bps
  fee_floor_bps = bitkub_taker_bps + bnth_taker_bps (labeled ESTIMATES, not live schedule).

Kill hard: unit_mismatch, money-leg fixture (unless allow_fixture), binance.com host.
Soft flags: stale / out_of_sync when a fetch fails or quote age exceeds max_age_sec.

OSS inspiration (shape only — no vendoring):
  - barbotine-shaped same-ccy basis screen
  - unicorn-style sync / persist flag (duration filter) as optional gate only
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from venues.binance_th import tape as bnth_tape
from venues.bitkub import paper as bitkub_paper
from venues.divergence import quote_currency

DEFAULT_BITKUB_SYMBOL = "BTC_THB"
DEFAULT_BNTH_SYMBOL = "BTCTHB"
DEFAULT_TIMEOUT = 8.0

# Labeled taker fee estimates (bps of notional) — paper falsify haircuts, not live facts.
DEFAULT_BITKUB_TAKER_BPS = 25.0  # ~0.25% Bitkub paper default
DEFAULT_BNTH_TAKER_BPS = 10.0

DEFAULT_MAX_AGE_SEC = 30.0
DEFAULT_MIN_NET_BPS = 0.0


class BasisError(RuntimeError):
    """Raised when same-ccy THB basis scan cannot proceed."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(ts: Any) -> Optional[datetime]:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    s = str(ts).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _age_sec(ts: Any, *, now: Optional[datetime] = None) -> Optional[float]:
    dt = _parse_ts(ts)
    if dt is None:
        return None
    now = now or _utc_now()
    return max(0.0, (now - dt).total_seconds())


def _leg_is_fixture(q: dict[str, Any]) -> bool:
    if q.get("fixture") is True or q.get("_fixture") is True:
        return True
    src = str(q.get("source") or "").strip().lower()
    return src == "fixture"


def _assert_thb_quote(symbol: str, venue_label: str) -> Optional[str]:
    ccy = quote_currency(symbol)
    if ccy != "THB":
        return f"{venue_label} symbol {symbol!r} quote={ccy!r} (need THB)"
    return None


@dataclass
class BasisFeeConfig:
    """Configurable taker fee haircuts — ESTIMATES for paper falsify."""

    bitkub_taker_bps: float = DEFAULT_BITKUB_TAKER_BPS
    bnth_taker_bps: float = DEFAULT_BNTH_TAKER_BPS
    min_net_bps: float = DEFAULT_MIN_NET_BPS

    def fee_floor_bps(self) -> float:
        return float(self.bitkub_taker_bps) + float(self.bnth_taker_bps)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["fee_floor_bps"] = self.fee_floor_bps()
        d["note"] = (
            "bitkub_taker_bps + bnth_taker_bps are labeled ESTIMATES for paper falsify — "
            "not live venue fee schedules"
        )
        return d


@dataclass
class PersistState:
    """Duration filter: opportunity only after |net| >= threshold for N consecutive samples."""

    consecutive: int = 0
    last_ok: bool = False
    samples: list[dict[str, Any]] = field(default_factory=list)

    def observe(
        self,
        *,
        net_basis_bps: Optional[float],
        threshold_bps: float,
        kill: bool,
    ) -> dict[str, Any]:
        ok = (
            not kill
            and net_basis_bps is not None
            and abs(float(net_basis_bps)) >= float(threshold_bps)
        )
        if ok:
            self.consecutive += 1
            self.last_ok = True
        else:
            self.consecutive = 0
            self.last_ok = False
        snap = {
            "ok": ok,
            "consecutive": self.consecutive,
            "threshold_bps": float(threshold_bps),
            "net_basis_bps": net_basis_bps,
        }
        self.samples.append(snap)
        return snap


def mid_from_tape(q: dict[str, Any]) -> dict[str, Any]:
    if "price" not in q or q["price"] is None:
        raise BasisError(f"quote missing price: {q!r}")
    return {
        "venue": q.get("venue"),
        "symbol": str(q.get("symbol") or ""),
        "price": float(q["price"]),
        "ts": q.get("ts"),
        "source": q.get("source"),
        "fixture": _leg_is_fixture(q),
    }


def compute_basis_bps(bitkub_mid: float, bnth_mid: float) -> dict[str, Any]:
    """
    Same-ccy THB basis.

    Sign: basis_bps = (bnth - bitkub) / mid * 1e4
    mid = (bnth + bitkub) / 2
    """
    if bitkub_mid <= 0 or bnth_mid <= 0:
        raise BasisError(f"non-positive mids: bitkub={bitkub_mid} bnth={bnth_mid}")
    mid = (float(bitkub_mid) + float(bnth_mid)) / 2.0
    abs_spread = float(bnth_mid) - float(bitkub_mid)
    basis_bps = (abs_spread / mid) * 1e4
    return {
        "bitkub_mid": float(bitkub_mid),
        "bnth_mid": float(bnth_mid),
        "mid": mid,
        "abs_spread_thb": abs_spread,
        "gross_basis_bps": basis_bps,
        "basis_bps": basis_bps,
        "sign_convention": (
            "basis_bps = (bnth_mid - bitkub_mid) / mid * 1e4; "
            "positive = BNTH richer than Bitkub"
        ),
    }


def fetch_bitkub_leg(
    symbol: str = DEFAULT_BITKUB_SYMBOL,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    ticker_row: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    row = ticker_row if ticker_row is not None else bitkub_paper.fetch_public_ticker(symbol, timeout=timeout)
    q = bitkub_paper.ticker_to_tape_quote(row, symbol=symbol).to_dict()
    return mid_from_tape(q)


def fetch_bnth_leg(
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
    # Hard refuse if somehow a non-TH host leaked into the row
    host = str(row.get("_source_host") or "")
    if host and "api.binance.th" not in host and not row.get("_fixture"):
        raise BasisError(f"refusing non-TH BNTH host: {host!r}")
    q = bnth_tape.ticker_to_tape_quote(row, symbol=symbol).to_dict()
    q["fixture"] = _leg_is_fixture(row) or _leg_is_fixture(q)
    q["_source_host"] = row.get("_source_host", "api.binance.th")
    return mid_from_tape(q)


def detect_bitkub_bnth_basis(
    bitkub: dict[str, Any],
    bnth: dict[str, Any],
    *,
    fees: Optional[BasisFeeConfig] = None,
    allow_fixture: bool = False,
    max_age_sec: float = DEFAULT_MAX_AGE_SEC,
    now: Optional[datetime] = None,
    soft_flags: Optional[list[str]] = None,
) -> dict[str, Any]:
    """
    Build Ledger JSON for Bitkub↔BNTH same-ccy THB basis.

    Hard kill: unit_mismatch, fixture (unless allow_fixture).
    Soft: stale / out_of_sync via soft_flags + age checks.
    """
    fees = fees or BasisFeeConfig()
    fee_dict = fees.to_dict()
    now = now or _utc_now()
    flags = list(soft_flags or [])

    a = mid_from_tape(bitkub)
    b = mid_from_tape(bnth)
    a["role"] = "bitkub"
    b["role"] = "bnth"

    legs = {"bitkub": a, "bnth": b}
    base_note = (
        "Bitkub↔BNTH same-ccy THB basis SCAN — paper/read-only; "
        "no FX; api.binance.th only; no live orders"
    )

    # Unit check — THB only, no FX path
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
            )
            out["fixture_legs"] = fixture_legs
            out["allow_fixture"] = False
            return out

    # Stale / age soft (and hard-kill if both missing absurdly old when ages known)
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
        )

    fee_floor = fees.fee_floor_bps()
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
        # Not a hard kill for monitoring — opportunity=false; still report
        status = "below_fee_floor" if net < 0 else "ok"

    opportunity = (not kill) and (net >= float(fees.min_net_bps)) and abs(gross) > 0

    out = _ledger(
        status=status,
        kill=kill,
        kill_reason=kill_reason,
        fees=fee_dict,
        legs=legs,
        flags=flags,
        note=base_note,
        extra={
            "unit": "THB",
            "comparable": True,
            "direction": direction,
            "gross_basis_bps": round(gross, 6),
            "basis_bps": round(gross, 6),
            "abs_spread_thb": round(float(calc["abs_spread_thb"]), 6),
            "mid_thb": round(float(calc["mid"]), 6),
            "fee_floor_bps": round(fee_floor, 6),
            "net_basis_bps": round(net, 6),
            "opportunity": opportunity,
            "sign_convention": calc["sign_convention"],
            "max_age_sec": float(max_age_sec),
            "allow_fixture": bool(allow_fixture),
            "sources": ["bitkub", "api.binance.th"],
            "oss_inspiration": {
                "barbotine_shaped_same_ccy": True,
                "unicorn_sync_flag_only": True,
                "vendored": False,
            },
        },
    )
    return out


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
        "unit": "THB" if (extra or {}).get("comparable") else None,
        "comparable": bool((extra or {}).get("comparable", False)),
        "note": note,
    }
    if extra:
        out.update(extra)
    return out


def scan_bitkub_bnth_basis(
    *,
    bitkub_symbol: str = DEFAULT_BITKUB_SYMBOL,
    bnth_symbol: str = DEFAULT_BNTH_SYMBOL,
    timeout: float = DEFAULT_TIMEOUT,
    fees: Optional[BasisFeeConfig] = None,
    allow_fixture: bool = False,
    use_fixture: bool = False,
    max_age_sec: float = DEFAULT_MAX_AGE_SEC,
    bitkub_row: Optional[dict[str, Any]] = None,
    bnth_row: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Fetch both public tickers and return Ledger JSON.

    Fetch failures → soft out_of_sync / stale flags; may still kill if a leg missing.
    """
    fees = fees or BasisFeeConfig()
    flags: list[str] = []
    bitkub_leg: Optional[dict[str, Any]] = None
    bnth_leg: Optional[dict[str, Any]] = None
    errors: dict[str, str] = {}

    try:
        if use_fixture and bitkub_row is None:
            # Deterministic offline Bitkub mid (labeled fixture) for tests only
            bitkub_leg = mid_from_tape(
                {
                    "venue": "bitkub_public",
                    "symbol": bitkub_symbol,
                    "price": 2599000.0,
                    "ts": _utc_now_iso(),
                    "source": "fixture",
                    "fixture": True,
                }
            )
        else:
            bitkub_leg = fetch_bitkub_leg(
                bitkub_symbol, timeout=timeout, ticker_row=bitkub_row
            )
    except (bitkub_paper.BitkubPaperError, BasisError) as e:
        flags.append("out_of_sync")
        errors["bitkub"] = str(e)

    try:
        bnth_leg = fetch_bnth_leg(
            bnth_symbol,
            timeout=timeout,
            use_fixture=True if use_fixture else None,
            ticker_row=bnth_row,
        )
    except (bnth_tape.BinanceTHError, BasisError) as e:
        if "out_of_sync" not in flags:
            flags.append("out_of_sync")
        errors["bnth"] = str(e)

    if bitkub_leg is None or bnth_leg is None:
        return {
            "status": "fetch_failed",
            "kill": True,
            "kill_reason": "fetch_failed",
            "estimated_fees": fees.to_dict(),
            "legs": {"bitkub": bitkub_leg, "bnth": bnth_leg},
            "soft_flags": flags or ["out_of_sync"],
            "errors": errors,
            "ts": _utc_now_iso(),
            "mode": "paper",
            "live": False,
            "execution": "scan_only",
            "comparable": False,
            "unit": None,
            "opportunity": False,
            "sources": ["bitkub", "api.binance.th"],
            "note": (
                "Bitkub↔BNTH basis SCAN — one or both public fetches failed; "
                "no invented mids; no FX; no live"
            ),
        }

    return detect_bitkub_bnth_basis(
        bitkub_leg,
        bnth_leg,
        fees=fees,
        allow_fixture=allow_fixture,
        max_age_sec=max_age_sec,
        soft_flags=flags,
    )


def opportunity_persisted(
    history: list[dict[str, Any]],
    *,
    min_samples: int,
    threshold_bps: float,
) -> dict[str, Any]:
    """
    Duration filter: True only if the last min_samples scans all have
    opportunity-worthy |net_basis_bps| >= threshold and not killed.
    """
    if min_samples <= 0:
        return {"persisted": False, "reason": "min_samples<=0", "count": 0}
    if len(history) < min_samples:
        return {
            "persisted": False,
            "reason": "insufficient_samples",
            "count": len(history),
            "need": min_samples,
        }
    window = history[-min_samples:]
    ok = True
    for h in window:
        if h.get("kill"):
            ok = False
            break
        net = h.get("net_basis_bps")
        if net is None or abs(float(net)) < float(threshold_bps):
            ok = False
            break
    return {
        "persisted": ok,
        "count": min_samples if ok else 0,
        "need": min_samples,
        "threshold_bps": float(threshold_bps),
        "window_nets": [h.get("net_basis_bps") for h in window],
    }

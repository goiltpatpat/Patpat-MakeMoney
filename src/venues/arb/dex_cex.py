"""DEX→CEX arb opportunity detector (paper/read-only scan — no auto-transfer).

Inputs: DEX mid (1inch read-only / fixture) + CEX mid (Binance TH preferred, Bitkub secondary).
Output Ledger JSON: gross spread, estimated fees, transfer_time_penalty_bps (labeled estimate),
travel_rule_buffer_bps (labeled estimate), net_edge_bps after costs.
Kill if net<=0, unit_mismatch, or money-leg source=fixture (unless allow_fixture). Refuse inventing USDTHB unless labeled FX quote provided.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from venues.divergence import pair_divergence, quote_currency


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class ArbFeeConfig:
    """Configurable fee / friction stack — estimates for paper falsify, not live facts."""

    dex_fee_bps: float = 30.0  # swap / gas / aggregator estimate
    cex_fee_bps: float = 10.0  # CEX taker-style estimate
    withdraw_fee_bps: float = 5.0  # network withdraw estimate in bps of notional
    transfer_time_penalty_bps: float = 15.0  # labeled estimate — deposit latency buffer
    travel_rule_buffer_bps: float = 10.0  # labeled estimate — Travel Rule / KYC friction
    min_net_edge_bps: float = 0.0  # kill when net_edge_bps <= this

    def total_cost_bps(self) -> float:
        return (
            float(self.dex_fee_bps)
            + float(self.cex_fee_bps)
            + float(self.withdraw_fee_bps)
            + float(self.transfer_time_penalty_bps)
            + float(self.travel_rule_buffer_bps)
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["total_cost_bps"] = self.total_cost_bps()
        d["note"] = (
            "fee/latency/Travel Rule figures are configurable ESTIMATES for paper falsify — "
            "not live schedule facts; transfer_time_penalty_bps and travel_rule_buffer_bps "
            "are labeled buffers, not measured latency"
        )
        return d


@dataclass
class ArbScanResult:
    status: str
    kill: bool
    kill_reason: Optional[str] = None
    direction: Optional[str] = None
    gross_spread_bps: Optional[float] = None
    net_edge_bps: Optional[float] = None
    fee_stack: dict[str, Any] = field(default_factory=dict)
    legs: dict[str, Any] = field(default_factory=dict)
    comparable: bool = False
    unit: Optional[str] = None
    ts: str = field(default_factory=_utc_now_iso)
    note: str = ""

    def to_ledger_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "kill": self.kill,
            "kill_reason": self.kill_reason,
            "direction": self.direction,
            "gross_spread_bps": self.gross_spread_bps,
            "net_edge_bps": self.net_edge_bps,
            "estimated_fees": self.fee_stack,
            "transfer_time_penalty_bps": (self.fee_stack or {}).get("transfer_time_penalty_bps"),
            "travel_rule_buffer_bps": (self.fee_stack or {}).get("travel_rule_buffer_bps"),
            "legs": self.legs,
            "comparable": self.comparable,
            "unit": self.unit,
            "ts": self.ts,
            "mode": "paper",
            "live": False,
            "execution": "scan_only",
            "note": self.note
            or (
                "DEX→CEX arb SCAN only — no live orders, no auto-transfer; "
                "gross vs net after fee stack + latency + Travel Rule buffers"
            ),
        }


def _mid_from_quote(q: dict[str, Any]) -> dict[str, Any]:
    """Normalize a TapeQuote-like dict."""
    if "price" not in q or q["price"] is None:
        raise ValueError(f"quote missing price: {q!r}")
    return {
        "venue": q.get("venue"),
        "symbol": str(q.get("symbol") or ""),
        "price": float(q["price"]),
        "ts": q.get("ts"),
        "source": q.get("source"),
    }


def _leg_is_fixture(q: dict[str, Any]) -> bool:
    """True when a money-leg mid is explicitly fixture-sourced."""
    if q.get("fixture") is True:
        return True
    src = str(q.get("source") or "").strip().lower()
    return src == "fixture"


def detect_dex_cex_opportunity(
    dex: dict[str, Any],
    cex: dict[str, Any],
    *,
    fees: Optional[ArbFeeConfig] = None,
    usdthb: Optional[dict[str, Any]] = None,
    prefer_direction: Optional[str] = None,
    allow_fixture: bool = False,
) -> dict[str, Any]:
    """
    Detect DEX↔CEX arb opportunity and return Ledger JSON.

    - unit_mismatch (no labeled FX) → kill
    - net_edge_bps <= min_net_edge_bps → kill
    - money leg source=fixture → kill unless allow_fixture (offline tests only)
    - Never invents USDTHB; reuse divergence helpers for FX-adjusted compare
    - Never report net>0 from fixture on the default money-path (allow_fixture=False)
    """
    fees = fees or ArbFeeConfig()
    fee_dict = fees.to_dict()
    a = _mid_from_quote(dex)
    b = _mid_from_quote(cex)
    a["role"] = "dex"
    b["role"] = "cex"

    if not allow_fixture:
        fixture_legs: list[str] = []
        if _leg_is_fixture(a):
            fixture_legs.append("dex")
        if _leg_is_fixture(b):
            fixture_legs.append("cex")
        if usdthb and _leg_is_fixture(usdthb):
            fixture_legs.append("usdthb")
        if fixture_legs:
            legs = {"dex": a, "cex": b, "fixture_legs": fixture_legs}
            result = ArbScanResult(
                status="fixture_mid",
                kill=True,
                kill_reason="money_leg_source_fixture",
                fee_stack=fee_dict,
                legs=legs,
                comparable=False,
                unit=None,
                note=(
                    "KILL: fixture mid on money path — never claim net>0 from fixture. "
                    "Pass allow_fixture=True / --allow-fixture for offline tests only."
                ),
            )
            out = result.to_ledger_json()
            out["allow_fixture"] = False
            out["fixture_legs"] = fixture_legs
            return out

    div = pair_divergence(a, b, usdthb=usdthb)

    legs = {"dex": a, "cex": b, "divergence": div}
    base_note = (
        "paper/read-only SCAN — no auto-transfer arb execution; "
        "transfer_time_penalty_bps and travel_rule_buffer_bps are labeled ESTIMATES"
    )

    if not div.get("comparable"):
        result = ArbScanResult(
            status="unit_mismatch",
            kill=True,
            kill_reason="unit_mismatch",
            fee_stack=fee_dict,
            legs=legs,
            comparable=False,
            unit=None,
            note=base_note + "; refuse inventing FX — supply labeled USDTHB for cross-currency",
        )
        return result.to_ledger_json()

    # Working prices in comparable unit
    unit = div.get("unit")
    # Prefer using fx-adjusted absolute prices via ratio on original when same unit;
    # when fx_adjusted, reconstruct USD-equivalent from abs_diff + ratio.
    a_px = a["price"]
    b_px = b["price"]
    if div.get("status") == "fx_adjusted" and usdthb and usdthb.get("price"):
        fx = float(usdthb["price"])
        a_ccy = div.get("a_quote_ccy")
        b_ccy = div.get("b_quote_ccy")

        def to_usd(px: float, ccy: Optional[str]) -> float:
            if ccy == "USD":
                return px
            if ccy == "THB":
                return px / fx
            raise ValueError(f"unexpected ccy {ccy}")

        a_work = to_usd(a_px, a_ccy)
        b_work = to_usd(b_px, b_ccy)
    else:
        a_work = a_px
        b_work = b_px

    if a_work <= 0 or b_work <= 0:
        result = ArbScanResult(
            status="bad_price",
            kill=True,
            kill_reason="non_positive_price",
            fee_stack=fee_dict,
            legs=legs,
            comparable=False,
            unit=unit,
            note=base_note,
        )
        return result.to_ledger_json()

    # Directions:
    # buy_dex_sell_cex: buy cheap on DEX, sell rich on CEX → gross = (cex - dex) / dex
    # buy_cex_sell_dex: buy cheap on CEX, sell rich on DEX → gross = (dex - cex) / cex
    gross_buy_dex = (b_work - a_work) / a_work * 10_000.0
    gross_buy_cex = (a_work - b_work) / b_work * 10_000.0

    candidates = [
        ("buy_dex_sell_cex", gross_buy_dex),
        ("buy_cex_sell_dex", gross_buy_cex),
    ]
    if prefer_direction in ("buy_dex_sell_cex", "buy_cex_sell_dex"):
        candidates = [c for c in candidates if c[0] == prefer_direction]

    direction, gross = max(candidates, key=lambda x: x[1])
    cost = fees.total_cost_bps()
    net = round(gross - cost, 6)
    gross_r = round(gross, 6)

    kill = False
    kill_reason = None
    status = "opportunity" if net > fees.min_net_edge_bps else "no_edge"
    if net <= fees.min_net_edge_bps:
        kill = True
        kill_reason = "net_edge_bps<=0" if fees.min_net_edge_bps == 0 else f"net_edge_bps<={fees.min_net_edge_bps}"

    result = ArbScanResult(
        status=status,
        kill=kill,
        kill_reason=kill_reason,
        direction=direction,
        gross_spread_bps=gross_r,
        net_edge_bps=net,
        fee_stack=fee_dict,
        legs=legs,
        comparable=True,
        unit=unit,
        note=base_note,
    )
    out = result.to_ledger_json()
    out["gross_vs_net"] = {
        "gross_spread_bps": gross_r,
        "total_cost_bps": cost,
        "net_edge_bps": net,
        "components_bps": {
            "dex_fee_bps": fees.dex_fee_bps,
            "cex_fee_bps": fees.cex_fee_bps,
            "withdraw_fee_bps": fees.withdraw_fee_bps,
            "transfer_time_penalty_bps": fees.transfer_time_penalty_bps,
            "travel_rule_buffer_bps": fees.travel_rule_buffer_bps,
        },
    }
    return out


def simulate_paper_dual_leg(
    opportunity: dict[str, Any],
    *,
    size: float = 0.001,
    dex_fee_rate: Optional[float] = None,
    cex_fee_rate: Optional[float] = None,
) -> dict[str, Any]:
    """
    Thin paper stub: simulate fills on both legs WITHOUT sending orders.

    Logs-ready fill shapes with venue tags dex_paper / binance_th_paper (or bitkub).
    """
    if opportunity.get("kill") or not opportunity.get("comparable"):
        return {
            "ok": False,
            "mode": "paper",
            "live": False,
            "error": "refusing paper dual-leg on killed/non-comparable opportunity",
            "opportunity_status": opportunity.get("status"),
            "kill_reason": opportunity.get("kill_reason"),
        }

    legs = opportunity.get("legs") or {}
    dex = legs.get("dex") or {}
    cex = legs.get("cex") or {}
    direction = opportunity.get("direction") or "buy_dex_sell_cex"
    fee_stack = opportunity.get("estimated_fees") or {}

    if dex_fee_rate is None:
        dex_fee_rate = float(fee_stack.get("dex_fee_bps", 30.0)) / 10_000.0
    if cex_fee_rate is None:
        cex_fee_rate = float(fee_stack.get("cex_fee_bps", 10.0)) / 10_000.0

    dex_px = float(dex["price"])
    cex_px = float(cex["price"])
    rt_id = f"arb-{_utc_now_iso().replace(':', '').replace('-', '')}"

    if direction == "buy_dex_sell_cex":
        dex_side, cex_side = "buy", "sell"
    else:
        dex_side, cex_side = "sell", "buy"

    cex_venue = str(cex.get("venue") or "binance_th")
    if cex_venue.startswith("binance_th"):
        cex_tag = "binance_th_paper"
    elif "bitkub" in cex_venue:
        cex_tag = "bitkub_paper"
    else:
        cex_tag = f"{cex_venue}_paper"

    dex_notional = size * dex_px
    cex_notional = size * cex_px
    dex_fill = {
        "venue": "dex_paper",
        "mode": "paper",
        "symbol": dex.get("symbol"),
        "side": dex_side,
        "size": size,
        "px": dex_px,
        "fill_price": dex_px,
        "fee_estimate": round(dex_notional * dex_fee_rate, 6),
        "fee_rate": dex_fee_rate,
        "ts": _utc_now_iso(),
        "leg": "dex",
        "round_trip_id": rt_id,
        "live": False,
        "note": "paper dual-leg — no DEX swap sent",
    }
    cex_fill = {
        "venue": cex_tag,
        "mode": "paper",
        "symbol": cex.get("symbol"),
        "side": cex_side,
        "size": size,
        "px": cex_px,
        "fill_price": cex_px,
        "fee_estimate": round(cex_notional * cex_fee_rate, 6),
        "fee_rate": cex_fee_rate,
        "ts": _utc_now_iso(),
        "leg": "cex",
        "round_trip_id": rt_id,
        "live": False,
        "note": "paper dual-leg — no CEX order sent",
    }

    return {
        "ok": True,
        "mode": "paper",
        "live": False,
        "round_trip_id": rt_id,
        "direction": direction,
        "open": dex_fill if dex_side == "buy" else cex_fill,
        "close": cex_fill if dex_side == "buy" else dex_fill,
        "dex": dex_fill,
        "cex": cex_fill,
        "net_edge_bps": opportunity.get("net_edge_bps"),
        "gross_spread_bps": opportunity.get("gross_spread_bps"),
        "note": "simulated fills both legs — no orders / no auto-transfer; edge_log venue tags dex_paper + CEX_paper",
    }


__all__ = [
    "ArbFeeConfig",
    "ArbScanResult",
    "_leg_is_fixture",
    "detect_dex_cex_opportunity",
    "simulate_paper_dual_leg",
    "quote_currency",
]

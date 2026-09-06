"""Triple-tape divergence helpers (read-only; no invented FX).

Same-currency pairs get numeric px ratios / abs diffs.
Cross-currency (e.g. BTCUSDT vs BTC_THB) is labeled unit_mismatch unless a
separately fetched, source-tagged USDTHB quote is supplied.
"""
from __future__ import annotations

from typing import Any, Optional


# Quote quote-currency hints from symbol strings used in this repo
_USD_LIKE = {"USDT", "USD", "USDC"}
_THB_LIKE = {"THB"}


def quote_currency(symbol: str) -> Optional[str]:
    """Best-effort quote currency from symbols like BTCUSDT, WBTC-USD, BTC_THB."""
    s = (symbol or "").strip().upper().replace("-", "_")
    if not s:
        return None
    if s.endswith("USDT"):
        return "USDT"
    if s.endswith("USDC"):
        return "USDC"
    if s.endswith("USD"):
        return "USD"
    if "_" in s:
        return s.rsplit("_", 1)[-1]
    return None


def _normalize_usd_bucket(ccy: Optional[str]) -> Optional[str]:
    if ccy is None:
        return None
    if ccy in _USD_LIKE:
        return "USD"
    if ccy in _THB_LIKE:
        return "THB"
    return ccy


def same_currency_pair(a_symbol: str, b_symbol: str) -> bool:
    return _normalize_usd_bucket(quote_currency(a_symbol)) == _normalize_usd_bucket(
        quote_currency(b_symbol)
    ) and _normalize_usd_bucket(quote_currency(a_symbol)) is not None


def pair_divergence(
    a: dict[str, Any],
    b: dict[str, Any],
    *,
    usdthb: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Compare two mid quotes.

    a/b expected keys: venue, symbol, price, ts, source (TapeQuote.to_dict shape).
    If currencies mismatch and usdthb is provided with keys price+source,
    Bitkub THB may be converted to USD-equivalent ONLY with that labeled FX.
    """
    a_sym = str(a.get("symbol") or "")
    b_sym = str(b.get("symbol") or "")
    a_px = float(a["price"])
    b_px = float(b["price"])
    a_ccy = _normalize_usd_bucket(quote_currency(a_sym))
    b_ccy = _normalize_usd_bucket(quote_currency(b_sym))
    label = f"{a.get('venue')}:{a_sym} vs {b.get('venue')}:{b_sym}"

    base: dict[str, Any] = {
        "pair": label,
        "a": {"venue": a.get("venue"), "symbol": a_sym, "price": a_px, "ts": a.get("ts"), "source": a.get("source")},
        "b": {"venue": b.get("venue"), "symbol": b_sym, "price": b_px, "ts": b.get("ts"), "source": b.get("source")},
        "a_quote_ccy": a_ccy,
        "b_quote_ccy": b_ccy,
    }

    if a_ccy and b_ccy and a_ccy == b_ccy:
        ratio = round(a_px / b_px, 8) if b_px else None
        abs_diff = round(a_px - b_px, 8)
        base.update(
            {
                "status": "ok",
                "comparable": True,
                "px_ratio_a_over_b": ratio,
                "abs_diff": abs_diff,
                "unit": a_ccy,
            }
        )
        return base

    # Cross-currency: optional labeled FX conversion (never invent FX)
    if usdthb and isinstance(usdthb, dict) and usdthb.get("price") is not None:
        try:
            fx = float(usdthb["price"])
        except (TypeError, ValueError):
            fx = 0.0
        fx_source = usdthb.get("source") or "unlabeled"
        if fx > 0 and a_ccy and b_ccy:
            # Convert THB leg to USD-equivalent using USDTHB (THB per 1 USD)
            def to_usd(px: float, ccy: str) -> Optional[float]:
                if ccy == "USD":
                    return px
                if ccy == "THB":
                    return px / fx
                return None

            a_usd = to_usd(a_px, a_ccy)
            b_usd = to_usd(b_px, b_ccy)
            if a_usd is not None and b_usd is not None and b_usd != 0:
                base.update(
                    {
                        "status": "fx_adjusted",
                        "comparable": True,
                        "px_ratio_a_over_b": round(a_usd / b_usd, 8),
                        "abs_diff": round(a_usd - b_usd, 8),
                        "unit": "USD_equivalent",
                        "fx": {
                            "pair": "USDTHB",
                            "price": fx,
                            "source": fx_source,
                            "ts": usdthb.get("ts"),
                            "note": "THB/USD via labeled public FX — not invented",
                        },
                    }
                )
                return base

    base.update(
        {
            "status": "unit_mismatch",
            "comparable": False,
            "px_ratio_a_over_b": None,
            "abs_diff": None,
            "unit": None,
            "note": (
                "cross-currency abs/ratio skipped — refuse inventing FX; "
                "supply labeled public USDTHB to enable fx_adjusted compare"
            ),
        }
    )
    return base


def compute_triple_tape_divergence(
    tape: list[dict[str, Any]],
    *,
    usdthb: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    From a tape list of mid quotes, emit per-mid summary + pairwise divergence.

    Prefer reporting each mid separately; numeric divergence only for same-currency
    (or fx_adjusted when usdthb provided).
    """
    mids = []
    for q in tape:
        if not isinstance(q, dict):
            continue
        if q.get("price") is None:
            continue
        mids.append(
            {
                "venue": q.get("venue"),
                "symbol": q.get("symbol"),
                "price": float(q["price"]),
                "ts": q.get("ts"),
                "source": q.get("source"),
                "quote_ccy": _normalize_usd_bucket(quote_currency(str(q.get("symbol") or ""))),
            }
        )

    pairs: list[dict[str, Any]] = []
    for i in range(len(mids)):
        for j in range(i + 1, len(mids)):
            pairs.append(pair_divergence(mids[i], mids[j], usdthb=usdthb))

    return {
        "mids": mids,
        "pairs": pairs,
        "n_mids": len(mids),
        "n_comparable_pairs": sum(1 for p in pairs if p.get("comparable")),
        "n_unit_mismatch_pairs": sum(1 for p in pairs if p.get("status") == "unit_mismatch"),
        "usdthb": usdthb,
        "note": (
            "Each mid reported separately; numeric divergence for same-currency only; "
            "cross-currency=unit_mismatch unless labeled USDTHB supplied"
        ),
    }


__all__ = [
    "quote_currency",
    "same_currency_pair",
    "pair_divergence",
    "compute_triple_tape_divergence",
]

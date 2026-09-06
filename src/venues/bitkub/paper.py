"""Bitkub paper-first adapter (public ticker only — NO live orders).

Supports open+close paper round-trips with parseable fill JSON for Thesis/edge_log.
Live execution is intentionally unimplemented and always refused.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from venues import TapeQuote

# Public market data (v3). Live trading endpoints are intentionally NOT wired.
BITKUB_TICKER_URL = "https://api.bitkub.com/api/v3/market/ticker"
DEFAULT_SYMBOL = "BTC_THB"
DEFAULT_TIMEOUT = 8.0
USER_AGENT = "Patpat-MakeMoney/venues-bitkub-paper"

# Live gate documented for a future adapter — never honored by this module.
LIVE_GATE_ENV = "PMM_BITKUB_LIVE_OK"

# Documented paper fee estimate (taker-style). Not a live fee schedule claim.
DEFAULT_FEE_RATE = 0.0025  # 0.25% of notional

# Day-cap defaults (falsifiable desk limits; configurable via caps file)
DEFAULT_MAX_TRADES_PER_DAY = 8
DEFAULT_MAX_LOSS_THB = 500.0
DEFAULT_STAKE_THB = 100.0

CAPS_FILENAME = "bitkub_paper_day_caps.json"
STATE_FILENAME = "bitkub_paper_day_state.json"


class BitkubPaperError(RuntimeError):
    """Raised when Bitkub public ticker / paper simulation fails."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc_day() -> str:
    return _utc_now().strftime("%Y-%m-%d")


def _get_json(url: str, params: Optional[dict] = None, timeout: float = DEFAULT_TIMEOUT) -> Any:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise BitkubPaperError(f"HTTP {e.code} from {url}") from e
    except urllib.error.URLError as e:
        raise BitkubPaperError(f"network error fetching {url}: {e.reason}") from e
    except TimeoutError as e:
        raise BitkubPaperError(f"timeout fetching {url}") from e
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise BitkubPaperError(f"invalid JSON from {url}") from e


def _normalize_symbol(symbol: str) -> str:
    s = (symbol or DEFAULT_SYMBOL).strip().upper().replace("-", "_")
    # Accept THB_BTC legacy form → BTC_THB (v3 uses base_quote like btc_thb)
    if s.startswith("THB_"):
        base = s.split("_", 1)[1]
        s = f"{base}_THB"
    return s


def fetch_public_ticker(
    symbol: str = DEFAULT_SYMBOL,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """
    Fetch Bitkub public ticker for one symbol (api/v3/market/ticker?sym=...).

    Returns the raw ticker object (dict) for the symbol.
    """
    sym = _normalize_symbol(symbol)
    data = _get_json(BITKUB_TICKER_URL, params={"sym": sym.lower()}, timeout=timeout)

    row: Optional[dict] = None
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            item_sym = str(item.get("symbol") or item.get("sym") or "").upper()
            if item_sym == sym or item_sym.replace("-", "_") == sym:
                row = item
                break
        if row is None and len(data) == 1 and isinstance(data[0], dict):
            row = data[0]
    elif isinstance(data, dict):
        # Some deployments return { "BTC_THB": {...} } or a single object
        if "last" in data or "lowest_ask" in data or "lowestAsk" in data:
            row = data
        else:
            for k, v in data.items():
                if not isinstance(v, dict):
                    continue
                key = str(k).upper().replace("-", "_")
                if key == sym or key == f"THB_{sym.split('_')[0]}" or key.endswith(sym.split("_")[0]):
                    row = {**v, "symbol": v.get("symbol", k)}
                    break
            if row is None:
                # first dict value fallback when sym filtered server-side
                for v in data.values():
                    if isinstance(v, dict) and ("last" in v or "lowestAsk" in v or "lowest_ask" in v):
                        row = dict(v)
                        break

    if not isinstance(row, dict):
        raise BitkubPaperError(f"ticker not found for {sym}: payload={data!r}")
    return row


def ticker_to_tape_quote(row: dict[str, Any], symbol: str = DEFAULT_SYMBOL) -> TapeQuote:
    """Map a Bitkub ticker row to TapeQuote using last price."""
    sym = _normalize_symbol(symbol)
    try:
        last = float(row.get("last") or row.get("lastPrice") or 0)
    except (TypeError, ValueError) as e:
        raise BitkubPaperError(f"bad last in ticker: {row!r}") from e
    if last <= 0:
        raise BitkubPaperError(f"non-positive last for {sym}: {last}")
    return TapeQuote(
        venue="bitkub_public",
        symbol=sym,
        price=last,
        ts=_utc_now_iso(),
        source="bitkub_v3_market_ticker",
    )


def _float_field(row: dict[str, Any], *keys: str) -> Optional[float]:
    for k in keys:
        if k in row and row[k] is not None:
            try:
                return float(row[k])
            except (TypeError, ValueError):
                continue
    return None


def derive_fill_px(row: dict[str, Any], side: str) -> tuple[float, str, Optional[float], Optional[float], Optional[float]]:
    """Return (fill_px, price_source, last, ask, bid) for side buy|sell."""
    side_l = (side or "buy").strip().lower()
    if side_l not in ("buy", "sell"):
        raise BitkubPaperError(f"side must be buy|sell, got {side!r}")
    last = _float_field(row, "last", "lastPrice")
    ask = _float_field(row, "lowest_ask", "lowestAsk", "ask")
    bid = _float_field(row, "highest_bid", "highestBid", "bid")
    if side_l == "buy":
        fill_px = ask if ask and ask > 0 else last
        px_source = "ask" if ask and ask > 0 else "last"
    else:
        fill_px = bid if bid and bid > 0 else last
        px_source = "bid" if bid and bid > 0 else "last"
    if fill_px is None or fill_px <= 0:
        raise BitkubPaperError(f"cannot derive paper fill from ticker: {row!r}")
    return float(fill_px), px_source, last, ask, bid


def paper_fill_from_ticker(
    row: dict[str, Any],
    *,
    side: str = "buy",
    symbol: str = DEFAULT_SYMBOL,
    size: Optional[float] = None,
    stake_thb: Optional[float] = None,
    fee_rate: float = DEFAULT_FEE_RATE,
    leg: str = "single",
    round_trip_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Compute a paper fill from public ticker.

    buy → fill at lowest ask (or last); sell → fill at highest bid (or last).
    Provide either size (base units) or stake_thb (quote notional for buy / sell proceeds estimate).

    Fill JSON keys (parseable): side, size, px, fee_estimate, ts (+ venue/mode/symbol).
    """
    sym = _normalize_symbol(symbol)
    side_l = (side or "buy").strip().lower()
    fill_px, px_source, last, ask, bid = derive_fill_px(row, side_l)

    if size is not None and stake_thb is not None:
        raise BitkubPaperError("provide size OR stake_thb, not both")
    if size is None and stake_thb is None:
        # Legacy single-tick fill without size (tape probe shape)
        size_v = None
        notional = None
        fee_est = None
    elif stake_thb is not None:
        if stake_thb <= 0:
            raise BitkubPaperError(f"stake_thb must be > 0, got {stake_thb}")
        size_v = float(stake_thb) / fill_px
        notional = float(stake_thb)
        fee_est = round(notional * float(fee_rate), 6)
    else:
        assert size is not None
        if size <= 0:
            raise BitkubPaperError(f"size must be > 0, got {size}")
        size_v = float(size)
        notional = size_v * fill_px
        fee_est = round(notional * float(fee_rate), 6)

    fill: dict[str, Any] = {
        "venue": "bitkub",
        "mode": "paper",
        "symbol": sym,
        "side": side_l,
        "size": size_v,
        "px": fill_px,
        "fill_price": fill_px,  # alias for older tape consumers
        "fee_estimate": fee_est,
        "fee_rate": float(fee_rate) if fee_est is not None else None,
        "notional_thb": round(notional, 6) if notional is not None else None,
        "price_source": px_source,
        "last": last,
        "ask": ask,
        "bid": bid,
        "ts": _utc_now_iso(),
        "leg": leg,
        "round_trip_id": round_trip_id,
        "live": False,
        "note": "paper simulation only — no order sent",
    }
    return fill


def simulate_paper_order(
    *,
    side: str = "buy",
    symbol: str = DEFAULT_SYMBOL,
    timeout: float = DEFAULT_TIMEOUT,
    ticker_row: Optional[dict[str, Any]] = None,
    size: Optional[float] = None,
    stake_thb: Optional[float] = None,
    fee_rate: float = DEFAULT_FEE_RATE,
    leg: str = "single",
    round_trip_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Paper-simulate a Bitkub fill using the public ticker.

    Refuses live: if PMM_BITKUB_LIVE_OK is set, still does NOT place orders;
    live execution is a future stub gated by that env (documented only).
    """
    # Explicit live refusal — this module never routes to live.
    if os.environ.get(LIVE_GATE_ENV, "").strip() in ("1", "true", "yes"):
        pass

    row = ticker_row if ticker_row is not None else fetch_public_ticker(symbol, timeout=timeout)
    fill = paper_fill_from_ticker(
        row,
        side=side,
        symbol=symbol,
        size=size,
        stake_thb=stake_thb,
        fee_rate=fee_rate,
        leg=leg,
        round_trip_id=round_trip_id,
    )
    fill["tape"] = ticker_to_tape_quote(row, symbol=symbol).to_dict()
    return fill


def default_runtime_dir(repo_root: Optional[Path] = None) -> Path:
    root = repo_root if repo_root is not None else Path(__file__).resolve().parents[3]
    return root / "runtime"


def load_day_caps(runtime_dir: Path) -> dict[str, Any]:
    """Load or create day-cap config under runtime/."""
    runtime_dir.mkdir(parents=True, exist_ok=True)
    path = runtime_dir / CAPS_FILENAME
    defaults = {
        "max_trades_per_day": DEFAULT_MAX_TRADES_PER_DAY,
        "max_loss_thb": DEFAULT_MAX_LOSS_THB,
        "fee_rate": DEFAULT_FEE_RATE,
        "note": "Bitkub paper day caps — editable; enforced by pmm_bitkub_paper.py",
    }
    if not path.exists():
        path.write_text(json.dumps(defaults, indent=2) + "\n", encoding="utf-8")
        return dict(defaults)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise BitkubPaperError(f"bad day caps file {path}: {e}") from e
    if not isinstance(data, dict):
        raise BitkubPaperError(f"day caps must be a JSON object: {path}")
    out = dict(defaults)
    out.update(data)
    return out


def _load_day_state(runtime_dir: Path) -> dict[str, Any]:
    path = runtime_dir / STATE_FILENAME
    day = _utc_day()
    empty = {"day": day, "trades": 0, "realized_pnl_thb": 0.0, "stopped": False, "stop_reason": None}
    if not path.exists():
        return empty
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return empty
    if not isinstance(data, dict) or data.get("day") != day:
        return empty
    return {
        "day": day,
        "trades": int(data.get("trades") or 0),
        "realized_pnl_thb": float(data.get("realized_pnl_thb") or 0.0),
        "stopped": bool(data.get("stopped")),
        "stop_reason": data.get("stop_reason"),
    }


def _save_day_state(runtime_dir: Path, state: dict[str, Any]) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    path = runtime_dir / STATE_FILENAME
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def check_day_caps(runtime_dir: Path, caps: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Return ok/state/caps; raises BitkubPaperError if day stop tripped."""
    caps = caps if caps is not None else load_day_caps(runtime_dir)
    state = _load_day_state(runtime_dir)
    max_trades = int(caps.get("max_trades_per_day", DEFAULT_MAX_TRADES_PER_DAY))
    max_loss = float(caps.get("max_loss_thb", DEFAULT_MAX_LOSS_THB))
    if state.get("stopped"):
        raise BitkubPaperError(f"day stop active: {state.get('stop_reason')}")
    if state["trades"] >= max_trades:
        raise BitkubPaperError(
            f"day trade cap reached: {state['trades']}>={max_trades} (see {CAPS_FILENAME})"
        )
    if state["realized_pnl_thb"] <= -abs(max_loss):
        raise BitkubPaperError(
            f"day loss stop: realized_pnl_thb={state['realized_pnl_thb']} <= -{max_loss}"
        )
    return {"ok": True, "state": state, "caps": caps}


def record_round_trip_result(
    runtime_dir: Path,
    *,
    realized_pnl_thb: float,
    caps: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Increment day trade count and accumulate realized paper PnL from fills only."""
    caps = caps if caps is not None else load_day_caps(runtime_dir)
    state = _load_day_state(runtime_dir)
    state["trades"] = int(state.get("trades") or 0) + 1
    state["realized_pnl_thb"] = round(float(state.get("realized_pnl_thb") or 0.0) + float(realized_pnl_thb), 6)
    max_trades = int(caps.get("max_trades_per_day", DEFAULT_MAX_TRADES_PER_DAY))
    max_loss = float(caps.get("max_loss_thb", DEFAULT_MAX_LOSS_THB))
    if state["trades"] >= max_trades:
        state["stopped"] = True
        state["stop_reason"] = f"max_trades_per_day={max_trades}"
    if state["realized_pnl_thb"] <= -abs(max_loss):
        state["stopped"] = True
        state["stop_reason"] = f"max_loss_thb={max_loss}"
    _save_day_state(runtime_dir, state)
    return state


def paper_round_trip(
    *,
    symbol: str = DEFAULT_SYMBOL,
    stake_thb: float = DEFAULT_STAKE_THB,
    timeout: float = DEFAULT_TIMEOUT,
    fee_rate: float = DEFAULT_FEE_RATE,
    open_row: Optional[dict[str, Any]] = None,
    close_row: Optional[dict[str, Any]] = None,
    runtime_dir: Optional[Path] = None,
    enforce_caps: bool = True,
    record: bool = True,
) -> dict[str, Any]:
    """
    Paper open (buy) + close (sell) round-trip using public ticker only.

    PnL is derived strictly from the two paper fills (not invented).
    """
    if stake_thb <= 0:
        raise BitkubPaperError(f"stake_thb must be > 0, got {stake_thb}")

    rt_dir = runtime_dir if runtime_dir is not None else default_runtime_dir()
    caps = load_day_caps(rt_dir) if enforce_caps or record else None
    if enforce_caps:
        assert caps is not None
        fee_rate = float(caps.get("fee_rate", fee_rate))
        check_day_caps(rt_dir, caps)

    sym = _normalize_symbol(symbol)
    rt_id = f"bkrt-{_utc_now().strftime('%Y%m%dT%H%M%S%f')}"

    o_row = open_row if open_row is not None else fetch_public_ticker(sym, timeout=timeout)
    open_fill = paper_fill_from_ticker(
        o_row,
        side="buy",
        symbol=sym,
        stake_thb=stake_thb,
        fee_rate=fee_rate,
        leg="open",
        round_trip_id=rt_id,
    )
    open_fill["tape"] = ticker_to_tape_quote(o_row, symbol=sym).to_dict()

    size = open_fill["size"]
    assert size is not None and size > 0

    # Unit tests may pass open_row only — reuse for close. Live network fetches twice.
    if close_row is not None:
        c_row = close_row
    elif open_row is not None:
        c_row = open_row
    else:
        c_row = fetch_public_ticker(sym, timeout=timeout)

    close_fill = paper_fill_from_ticker(
        c_row,
        side="sell",
        symbol=sym,
        size=size,
        fee_rate=fee_rate,
        leg="close",
        round_trip_id=rt_id,
    )
    close_fill["tape"] = ticker_to_tape_quote(c_row, symbol=sym).to_dict()

    open_notional = float(open_fill["notional_thb"] or 0.0)
    close_notional = float(close_fill["notional_thb"] or 0.0)
    open_fee = float(open_fill["fee_estimate"] or 0.0)
    close_fee = float(close_fill["fee_estimate"] or 0.0)
    # Buy pays notional+fee; sell receives notional-fee — paper PnL from fills only.
    realized = round(close_notional - open_notional - open_fee - close_fee, 6)

    state = None
    if record:
        state = record_round_trip_result(rt_dir, realized_pnl_thb=realized, caps=caps)

    return {
        "ok": True,
        "mode": "paper",
        "live": False,
        "venue": "bitkub",
        "symbol": sym,
        "round_trip_id": rt_id,
        "stake_thb": float(stake_thb),
        "open": open_fill,
        "close": close_fill,
        "realized_pnl_thb": realized,
        "pnl_basis": "close_notional - open_notional - open_fee - close_fee (paper fills only)",
        "day_state": state,
        "note": "paper round-trip only — no Bitkub order sent",
    }


def refuse_live(*_args: Any, **_kwargs: Any) -> None:
    """Hard-refuse any live Bitkub order path."""
    raise BitkubPaperError(
        f"Bitkub live orders are not implemented; paper-only. "
        f"Future live path requires {LIVE_GATE_ENV}=1 (not honored here)."
    )


def live_order_stub(*_args: Any, **_kwargs: Any) -> None:
    """
    Live order stub — intentionally unimplemented.

    Future live adapter MUST require env PMM_BITKUB_LIVE_OK=1 plus BITKUB_API_KEY /
    BITKUB_API_SECRET and must never be the default. This function always raises.
    """
    refuse_live()

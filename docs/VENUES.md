# Venues — Patpat-MakeMoney (Phase 1)

Thai-geo desk notes. English docs/code. **Paper-first. No tips. No invented PnL.**

## Geo / regulatory posture (TH)

| Venue | Role (Phase 1) | Notes |
|-------|----------------|-------|
| **Bitkub** | **Primary execution candidate** (later) | SEC-licensed TH exchange. **Paper round-trip** via public ticker + simulated fills. Live orders **not** implemented; future live requires `PMM_BITKUB_LIVE_OK=1` + API creds (hard-refused today). |
| **1inch** | Research / read-only quotes | Spot price HTTP for cross-checks. **No swaps / no execution.** Optional `ONEINCH_API_KEY`; fixture mode without key. |
| **Public BTC tape** | Data layer (primary now) | Binance public `BTCUSDT` last/mark via HTTPS. Used for Ledger tape briefs and paired probes. |
| **Polymarket** | **Optional / non-primary** | Still in-repo for historical BTC 5m skill path. **TH geo: PM often blocked / impractical.** Do not treat as default execution venue. No tip flow. |
| **Kraken / eToro** | Deferred | Out of scope until data-layer paired probes and Bitkub paper mature. |

## Sequence (locked)

1. **Data layer first** — public BTC tape + 1inch read-only quotes (`src/venues/`, `scripts/pmm_tape.py`).
2. **Bitkub paper round-trip** — public ticker → open+close fill JSON + day caps (`src/venues/bitkub/paper.py`, `scripts/pmm_bitkub_paper.py`). Edge log for Thesis falsify (`scripts/pmm_edge_log.py`).
3. Full Bitkub adapter / session runner **after** ≥10 paired data-layer probes.
4. Polymarket remains available but demoted; live PM still gated by existing `PMM_LIVE_OK` / `--live` paths and is not the multi-venue default.

## Modules

```
src/venues/
  __init__.py          # TapeQuote
  public_btc.py        # Binance public BTCUSDT
  oneinch_quotes.py    # read-only spot price (+ fixture)
  bitkub/
    paper.py           # ticker + paper fill + open/close RT; live stub raises
scripts/pmm_tape.py           # multi-venue tape JSON brief (+ --divergence)
scripts/pmm_bitkub_paper.py   # paper RT CLI (--symbol, --stake-thb); refuses --live
scripts/pmm_edge_log.py       # append paper fills -> runtime/edge_log.jsonl
scripts/pmm_edge_scorecard.py # Thesis expectancy / hit-rate from edge_log (no invented PnL)
scripts/pmm_paper_reconcile.py# post-stop reconcile_<ts>.json; gates session_closed
src/venues/divergence.py      # same-currency divergence; cross = unit_mismatch
runtime/bitkub_paper_day_caps.json   # max trades / loss stop (auto-created)
runtime/edge_log.jsonl               # Thesis cage input (paper fills only)
runtime/reconcile_<ts>.json          # post-stop paper checklist artifact
```

## CLIs (paper)

```bash
# Paired tape probe (read-only)
python scripts/pmm_tape.py --all
python scripts/pmm_tape.py --btc --bitkub --bitkub-paper buy

# Bitkub paper open+close (day caps under runtime/)
python scripts/pmm_bitkub_paper.py --symbol BTC_THB --stake-thb 100

# Log paper fills for expectancy falsify (no invented PnL)
python scripts/pmm_bitkub_paper.py --stake-thb 50 --no-record > /tmp/rt.json
python scripts/pmm_edge_log.py --from-json /tmp/rt.json

# Thesis scorecard + triple-tape divergence + post-stop reconcile
python scripts/pmm_edge_scorecard.py
python scripts/pmm_tape.py --all --divergence
python scripts/pmm_paper_reconcile.py
```

Live Bitkub: `PMM_BITKUB_LIVE_OK=1` is documented only; `pmm_bitkub_paper.py --live` and `live_order_stub()` **hard-refuse**.

## Thesis cage (this slice)

1. **Edge scorecard** — `scripts/pmm_edge_scorecard.py` reads `runtime/edge_log.jsonl` only; N fills / round-trips / mean `realized_pnl_thb` from logged fields; fill-rate only if skip data present; day-cap stop flags from `bitkub_paper_day_state.json`. **No invented PnL.**
2. **Triple-tape divergence** — `scripts/pmm_tape.py --divergence` (+ optional `--usdthb`) via `src/venues/divergence.py`. Each mid reported separately; numeric ratio/abs for same-currency pairs only; cross-currency = `unit_mismatch` unless labeled public USDTTHB supplied (never invent FX).
3. **Post-stop paper reconcile** — `scripts/pmm_paper_reconcile.py` writes `runtime/reconcile_<ts>.json` checklist (day_state, edge_log tails, flat open positions, future-live manual steps). **`session_closed:true` blocked unless artifact written.**

## Hard rules

- No `--live` / `--execute` for Polymarket from this venues workstream.
- No Bitkub live orders in Phase 1 (stub only; hard-refuse).
- No tips; no invented prices or PnL (edge_log records paper fills only).
- Secrets only via env (see `.env.example`); never commit real keys.

## Prove

```bash
python scripts/pmm_doctor.py
python -m unittest discover -s tests -v
python scripts/pmm_tape.py --btc
python scripts/pmm_tape.py --all --divergence
python scripts/pmm_bitkub_paper.py --stake-thb 50 --no-record
python scripts/pmm_edge_scorecard.py
python scripts/pmm_paper_reconcile.py --preview
```

# Venues — Patpat-MakeMoney (Phase 1)

Thai-geo desk notes. English docs/code. **Paper-first. No tips. No invented PnL.**

## Geo / regulatory posture (TH)

| Venue | Role (Phase 1) | Notes |
|-------|----------------|-------|
| **Bitkub** | **Primary execution candidate** (later) | SEC-licensed TH exchange. **Paper skeleton only** in this phase — public ticker + simulated fills. Live orders **not** implemented; future live requires `PMM_BITKUB_LIVE_OK=1` + API creds. |
| **1inch** | Research / read-only quotes | Spot price HTTP for cross-checks. **No swaps / no execution.** Optional `ONEINCH_API_KEY`; fixture mode without key. |
| **Public BTC tape** | Data layer (primary now) | Binance public `BTCUSDT` last/mark via HTTPS. Used for Ledger tape briefs and paired probes. |
| **Polymarket** | **Optional / non-primary** | Still in-repo for historical BTC 5m skill path. **TH geo: PM often blocked / impractical.** Do not treat as default execution venue. No tip flow. |
| **Kraken / eToro** | Deferred | Out of scope until data-layer paired probes and Bitkub paper mature. |

## Sequence (locked)

1. **Data layer first** — public BTC tape + 1inch read-only quotes (`src/venues/`, `scripts/pmm_tape.py`).
2. **Bitkub paper skeleton** — public ticker → paper fill JSON (`src/venues/bitkub/paper.py`). No live session runner yet.
3. Full Bitkub adapter / session runner **after** ≥10 paired data-layer probes.
4. Polymarket remains available but demoted; live PM still gated by existing `PMM_LIVE_OK` / `--live` paths and is not the multi-venue default.

## Modules

```
src/venues/
  __init__.py          # TapeQuote
  public_btc.py        # Binance public BTCUSDT
  oneinch_quotes.py    # read-only spot price (+ fixture)
  bitkub/
    paper.py           # public ticker + paper fill JSON; live stub raises
scripts/pmm_tape.py    # CLI JSON brief for Ledger
```

## Hard rules

- No `--live` / `--execute` for Polymarket from this venues workstream.
- No Bitkub live orders in Phase 1 (skeleton/stub only).
- No tips; no invented prices or PnL.
- Secrets only via env (see `.env.example`); never commit real keys.

## Prove

```bash
python scripts/pmm_doctor.py
python -m unittest discover -s tests -v
python scripts/pmm_tape.py --btc
```

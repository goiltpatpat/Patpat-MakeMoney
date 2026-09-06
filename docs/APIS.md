# APIs — Patpat-MakeMoney (Phase 1)

English reference for **public / read-only** market data used by the desk.
**No live trading orders** in this phase. Paper + SCAN only.

## Binance TH (BNTH) — `api.binance.th` ONLY

| Item | Value |
|------|-------|
| Product | Gulf Binance / **binance.th** (Thai-licensed) — **not** Binance.com global |
| Docs | https://www.binance.th/api-docs/en/ |
| REST base | **`https://api.binance.th`** |
| Public tape (we use now) | `GET /api/v1/ticker/price`, `bookTicker`, `24hr` |
| Labeled FX helper | `USDTTHB` via same public ticker → desk `USDTHB` label (`fetch_usdtthb_fx`) |
| Signed trade APIs | Exist in vendor docs; **not wired**. Live orders hard-refused. |
| Hard rule | **Never** call `api.binance.com` and label it Binance TH |

**Public vs signed:** this repo uses **public market data only** today (no API key, no order endpoints).
Signed/trade paths are future-only and must stay behind explicit live gates.

Module: `src/venues/binance_th/tape.py`, thin paper fills in `paper.py`.

## DEX / 1inch — research quotes only

| Item | Value |
|------|-------|
| Role | DEX mid for paper arb SCAN (read-only) |
| API | 1inch Spot Price HTTP (`api.1inch.dev/price/...`) |
| Auth | Optional Bearer `ONEINCH_API_KEY` |
| Swaps | **Never** — no swap / execution paths |
| Fixture | Offline only; money-path **kills** `source=fixture` unless `--allow-fixture` |

Without a key, the money-path arb scanner **does not** silently substitute fixture and claim edge.
Use `--fixture --allow-fixture` for offline unit/dry tests only.

Module: `src/venues/oneinch_quotes.py`.

## Bitkub — public ticker (paper)

| Item | Value |
|------|-------|
| Public | `https://api.bitkub.com/api/v3/market/ticker` |
| Paper | Simulated fills + day caps (`utf-8-sig` JSON loader — PowerShell BOM safe) |
| Live | **Not implemented**; future needs `PMM_BITKUB_LIVE_OK=1` + API creds (hard-refused now) |

## Env vars (relevant)

| Var | Purpose |
|-----|---------|
| `ONEINCH_API_KEY` | Optional 1inch Spot Price Bearer (read-only) |
| `PMM_BINANCE_TH_FIXTURE=1` | BNTH offline fixture ticker |
| `PMM_ARB_ALLOW_FIXTURE=1` | Permit fixture mids in arb opportunity output (tests only; default OFF) |
| `PMM_BITKUB_LIVE_OK` | Documented future Bitkub live gate — **not honored** by paper module |
| `PMM_LIVE_OK` | Polymarket / desk live gate (separate stack) |
| `BITKUB_API_KEY` / `BITKUB_API_SECRET` | Placeholders for future live — unused by paper |

Secrets stay in `.env` / env; never commit real keys.

## Dry-run vs live gates

| Path | Default | Live |
|------|---------|------|
| `pmm_tape.py` | Public read-only | N/A |
| `pmm_bitkub_paper.py` | Paper RT | `--live` hard-refuse |
| `pmm_arb_scan.py` | Paper SCAN | `--live` hard-refuse (exit 2) |
| Fixture money briefs | **Killed** (`money_leg_source_fixture`) | Offline only with `--allow-fixture` |

## Travel Rule note (Feb 2027)

Cross-venue / withdraw-deposit flows face increasing **Travel Rule / KYC friction**.
Arb SCAN includes a non-zero **`travel_rule_buffer_bps`** labeled **ESTIMATE** (not a measured schedule).
Desk posture: falsify paper edge **after** fee + latency + Travel Rule buffers before any future live discussion.
Vendor/regulatory timelines around **Feb 2027** are a planning marker — re-check primary sources; do not treat this note as legal advice.

## Other team-fit methods (paper-only research)

Falsifiable screens — **not tipster**. See also `DESK.md` / `docs/HOLES.md`.

1. **Bitkub ↔ BNTH same-currency basis** — BTC_THB vs BTCTHB mids; report spread in THB only; kill if units mismatch.
2. **Funding / spread screen on TH books** — public bookTicker / depth when available; log basis vs fee floor; no invented prints.
3. **Desk scorecard cadence** — `pmm_edge_scorecard.py` on `edge_log.jsonl` only; N fills, mean realized from logged fields; day-cap stops from state file.

All three stay paper/read-only until Thesis pass criteria are met.

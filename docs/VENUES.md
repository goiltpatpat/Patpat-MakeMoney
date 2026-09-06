# Venues — Patpat-MakeMoney (Phase 1)

Thai-geo desk notes. English docs/code. **Paper-first. No tips. No invented PnL.**

## Geo / regulatory posture (TH)

| Venue | Role (Phase 1) | Notes |
|-------|----------------|-------|
| **Bitkub** | **Primary execution candidate** (later) | SEC-licensed TH exchange. **Paper round-trip** via public ticker + simulated fills. Live orders **not** implemented; future live requires `PMM_BITKUB_LIVE_OK=1` + API creds (hard-refused today). |
| **Binance TH (BNTH)** | **Second TH lane** (does **not** replace Bitkub until Thesis pass) | Thai-licensed **Gulf Binance / binance.th**. Public REST base **`https://api.binance.th`** only (docs: https://www.binance.th/api-docs/en/). **Never** wire `api.binance.com` and label it Binance TH. Paper/read-only ticker + thin paper fills (`binance_th_paper`). Live hard-refused. |
| **1inch** | Research / read-only quotes (DEX mid for arb scan) | Spot price HTTP for cross-checks. **No swaps / no execution.** Optional `ONEINCH_API_KEY`; fixture mode without key. |
| **Public BTC tape** | Data layer (primary now) | Binance **global** public `BTCUSDT` last/mark via HTTPS for tape briefs only — **not** the Binance TH venue. |
| **Polymarket** | **Optional / non-primary** | Still in-repo for historical BTC 5m skill path. **TH geo: PM often blocked / impractical.** Do not treat as default execution venue. No tip flow. |
| **Kraken / eToro** | Deferred | Out of scope until data-layer paired probes and Bitkub paper mature. |

## DEX→CEX arb doctrine (paper / read-only SCAN)

Scanner only — **no live orders, no auto-transfer arb execution.**

1. **Legs:** DEX mid (1inch read-only / fixture) + CEX mid (**Binance TH preferred**, Bitkub secondary).
2. **Gross vs net (required):** Ledger JSON must show:
   - `gross_spread_bps`
   - estimated fee stack (DEX + CEX + withdraw) — configurable
   - `transfer_time_penalty_bps` — **labeled ESTIMATE** (deposit latency buffer; non-zero default; not a measured fact)
   - `travel_rule_buffer_bps` — **labeled ESTIMATE** (Travel Rule / KYC friction; non-zero default)
   - `net_edge_bps` after all costs
3. **Kill rules:** kill if `net_edge_bps <= 0` or `unit_mismatch`.
4. **FX honesty:** refuse inventing USDTHB. Cross-currency (e.g. WBTC-USD vs BTCTHB) = `unit_mismatch` unless a **labeled** public FX quote is supplied (reuse `divergence.py` helpers / `--usdthb`).
5. **Paper stub (optional):** simulate fills on both legs **without** sending orders; edge_log venue tags `dex_paper` / `binance_th_paper`.
6. **Falsify first:** paper scan must survive fee + latency + Travel Rule buffers before any future live discussion.

## Sequence (locked)

1. **Data layer first** — public BTC tape + 1inch read-only quotes (`src/venues/`, `scripts/pmm_tape.py`).
2. **Bitkub paper round-trip** — public ticker → open+close fill JSON + day caps (`src/venues/bitkub/paper.py`, `scripts/pmm_bitkub_paper.py`). Edge log for Thesis falsify (`scripts/pmm_edge_log.py`).
3. **Binance TH lane + DEX→CEX arb SCAN** — `api.binance.th` ticker + `scripts/pmm_arb_scan.py` (paper only; `--live` hard-refuse). BNTH is **second** TH lane — does not replace Bitkub until pass.
4. Full Bitkub adapter / session runner **after** ≥10 paired data-layer probes.
5. Polymarket remains available but demoted; live PM still gated by existing `PMM_LIVE_OK` / `--live` paths and is not the multi-venue default.

## Modules

```
src/venues/
  __init__.py          # TapeQuote
  public_btc.py        # Binance global public BTCUSDT (tape only — NOT Binance TH)
  oneinch_quotes.py    # read-only spot price (+ fixture)
  divergence.py        # same-currency divergence; cross = unit_mismatch
  bitkub/
    paper.py           # ticker + paper fill + open/close RT; live stub raises
  binance_th/
    tape.py            # api.binance.th ticker/price + bookTicker; fixture mode
    paper.py           # thin paper fills (binance_th_paper); live refuse
  arb/
    dex_cex.py         # DEX→CEX opportunity detector (gross vs net + kill rules)
scripts/pmm_tape.py           # multi-venue tape JSON brief (+ --divergence)
scripts/pmm_bitkub_paper.py   # paper RT CLI; refuses --live
scripts/pmm_arb_scan.py       # DEX→CEX arb SCAN CLI (--paper only; --live hard-refuse)
scripts/pmm_edge_log.py       # append paper fills -> runtime/edge_log.jsonl
scripts/pmm_edge_scorecard.py # Thesis expectancy / hit-rate from edge_log
scripts/pmm_paper_reconcile.py# post-stop reconcile_<ts>.json
runtime/bitkub_paper_day_caps.json
runtime/edge_log.jsonl
runtime/reconcile_<ts>.json
```

## Binance TH public API (researched)

| Item | Value |
|------|-------|
| Product | Gulf Binance / **binance.th** (Thai-licensed) — **not** Binance.com global |
| Docs | https://www.binance.th/api-docs/en/ |
| REST base | **`https://api.binance.th`** |
| Price | `GET /api/v1/ticker/price?symbol=BTCTHB` |
| Book | `GET /api/v1/ticker/bookTicker?symbol=BTCTHB` |
| 24hr | `GET /api/v1/ticker/24hr?symbol=BTCTHB` |
| Fixture | `PMM_BINANCE_TH_FIXTURE=1` or `--fixture` on arb scan |

**Hard rule:** never silently call `api.binance.com` and label it Binance TH.

## CLIs (paper)

```bash
# Paired tape probe (read-only)
python scripts/pmm_tape.py --all
python scripts/pmm_tape.py --btc --bitkub --bitkub-paper buy

# Bitkub paper open+close (day caps under runtime/)
python scripts/pmm_bitkub_paper.py --symbol BTC_THB --stake-thb 100

# DEX→CEX arb SCAN (Binance TH CEX leg; labeled FX for USD vs THB)
python scripts/pmm_arb_scan.py --paper --cex binance_th --usdthb 36.0 --usdthb-source desk_labeled
python scripts/pmm_arb_scan.py --paper --fixture --usdthb 36.0 --simulate-paper-fills
# --live is hard-refused (exit 2)

# Log paper fills for expectancy falsify (no invented PnL)
python scripts/pmm_bitkub_paper.py --stake-thb 50 --no-record > /tmp/rt.json
python scripts/pmm_edge_log.py --from-json /tmp/rt.json

# Thesis scorecard + triple-tape divergence + post-stop reconcile
python scripts/pmm_edge_scorecard.py
python scripts/pmm_tape.py --all --divergence
python scripts/pmm_paper_reconcile.py
```

Live Bitkub / BNTH / arb: env gates are documented only; `--live` paths **hard-refuse**.

## Thesis cage (this slice)

1. **Edge scorecard** — `scripts/pmm_edge_scorecard.py` reads `runtime/edge_log.jsonl` only; N fills / round-trips / mean `realized_pnl_thb` from logged fields; fill-rate only if skip data present; day-cap stop flags from `bitkub_paper_day_state.json`. **No invented PnL.**
2. **Triple-tape divergence** — `scripts/pmm_tape.py --divergence` (+ optional `--usdthb`) via `src/venues/divergence.py`. Each mid reported separately; numeric ratio/abs for same-currency pairs only; cross-currency = `unit_mismatch` unless labeled public USDTTHB supplied (never invent FX).
3. **Post-stop paper reconcile** — `scripts/pmm_paper_reconcile.py` writes `runtime/reconcile_<ts>.json` checklist (day_state, edge_log tails, flat open positions, future-live manual steps). **`session_closed:true` blocked unless artifact written.**
4. **DEX→CEX arb SCAN** — gross vs net with fee + non-zero latency + Travel Rule buffers; kill inventing FX; BNTH second TH lane.

## Hard rules

- No `--live` / `--execute` for Polymarket from this venues workstream.
- No Bitkub / Binance TH live orders in Phase 1 (stub only; hard-refuse).
- No auto-transfer arb execution; scan/paper only.
- No tips; no invented prices, PnL, or FX.
- Secrets only via env (see `.env.example`); never commit real keys.
- **Never** label `api.binance.com` as Binance TH.

## Prove

```bash
python scripts/pmm_doctor.py
python -m unittest discover -s tests -v
python scripts/pmm_tape.py --btc
python scripts/pmm_tape.py --all --divergence
python scripts/pmm_bitkub_paper.py --stake-thb 50 --no-record
python scripts/pmm_arb_scan.py --paper --fixture --usdthb 36.0 --usdthb-source prove
python scripts/pmm_edge_scorecard.py
python scripts/pmm_paper_reconcile.py --preview
```

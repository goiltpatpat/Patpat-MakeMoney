# Patpat-MakeMoney Desk Doctrine

## Mission
Turn BTC tape + venue noise into a **falsifiable desk read**, then optionally run skills **paper-first**. Phase 1 sequence: **public data layer → Bitkub paper round-trip**. Polymarket is optional/non-primary (TH geo). Live execution is a gated exception, never the default.

## Roles
- **Ledger (Head):** thinks, assigns, synthesizes, gates live
- **Pulse:** intake — matters vs noise, sources, assets, unverified
- **Grid:** structure — bias, levels, confirm/invalidate, confidence
- **Thesis:** catalysts — agree/conflict with structure, next event

Specialists report to Ledger. This repo is a tool under the Head, not a signal bot.

## Decision flow
1. Pulse / Grid / Thesis briefs (English artifacts)
2. Ledger desk read (bias · levels · matters vs noise · news↔chart · invalidation · confidence)
3. Optional skill **dry-run** (`--profile desk`, no `--execute`)
4. Human go-ahead
5. Live only if still valid: `PMM_LIVE_OK=1` + `--live`/`--execute` + `.env` creds
6. Preflight: `python scripts/pmm_live_preflight.py`
6. Process stop ready: `scripts/btc5m_ctl.sh stop` (does not cancel orders or close positions).

## Ledger session brief (paste template)

```text
### BTC 5m session — Patpat-MakeMoney
Bias + timeframe:
Key levels / impulse / skew:
Catalysts (Thesis) vs noise (Pulse):
Agree / conflict with structure (Grid):
Skill mode: dry-run | live
Profile: desk | conservative | aggressive
Result / fills (fact only):
Invalidation:
Confidence: high | medium | low
Process stop: btc5m_ctl.sh stop (orders and positions require separate handling)
```

## Reality check (runner)
Enforced today: market slot + time floor + CLOB ask threshold + stronger-side + paper-first ctl/hot/watch.
Impulse and skew gates are implemented but default off; enable through direct runner flags (see `docs/RUNTIME.md`). Human sign-off remains an operating procedure, not a persisted approval gate.

## Venues (Phase 1)
- Public BTC tape + optional 1inch research quotes first (scripts/pmm_tape.py)
- Bitkub = SEC-licensed TH **primary execution candidate**; paper open+close RT (scripts/pmm_bitkub_paper.py) + day caps; live hard-refused
- **Binance TH (BNTH)** = **second TH lane** (Gulf / binance.th via api.binance.th only — never api.binance.com); does not replace Bitkub until Thesis pass
- DEX→CEX arb **SCAN** (scripts/pmm_arb_scan.py): gross vs net with fee stack + non-zero transfer latency buffer + Travel Rule buffer; kill inventing FX; --live hard-refuse; paper/read-only first
- Paper fills -> scripts/pmm_edge_log.py -> runtime/edge_log.jsonl (venue tags include dex_paper / binance_th_paper); no invented PnL
- Polymarket stays available but demoted; no tips
- Thesis cage: pmm_edge_scorecard.py + pmm_tape.py --divergence + pmm_paper_reconcile.py + pmm_arb_scan.py (paper-only; session_closed gated)
- See docs/VENUES.md

## Hard rules
- No personalized financial advice
- No promised returns
- No invented prices, prints, or PnL
- No auto-live without explicit human confirmation
- Secrets stay outside the repo (`BTC5M_ENV_FILE` / trading stack `.env`)

## Attribution
Upstream skill: Novals83/5min-btc-polymarket

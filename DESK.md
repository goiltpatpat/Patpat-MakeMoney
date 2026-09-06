# Patpat-MakeMoney Desk Doctrine

## Mission
Turn BTC 5m Polymarket noise into a **falsifiable desk read**, then optionally run this skill **paper-first**. Live execution is a gated exception, never the default.

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
5. Live `--execute` only if still valid
6. Kill switch ready: `scripts/btc5m_ctl.sh stop`

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
Kill switch: btc5m_ctl.sh stop
```

## Reality check (runner)
Enforced today: market slot + time floor + CLOB ask threshold + stronger-side + paper-first ctl/hot/watch.
Not enforced yet: impulse USD move, skew support (see Grid FACT). Treat those as checklist / Thesis inputs until gates land.

## Hard rules
- No personalized financial advice
- No promised returns
- No invented prices, prints, or PnL
- No auto-live without explicit human confirmation
- Secrets stay outside the repo (`BTC5M_ENV_FILE` / trading stack `.env`)

## Attribution
Upstream skill: Novals83/5min-btc-polymarket

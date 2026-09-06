---
name: polymarket-hl-live-trading
description: "Operate a live Polymarket strategy that uses Hyperliquid data for entries and Polymarket CLOB for execution. Includes setup, run/stop, reconcile, and troubleshooting."
---

# Polymarket HL Live Trading Skill

Use this repository when you need a deployable copy of the strategy with **secret-free defaults**.

## Inputs / signal source

- Hyperliquid candles API (`https://api.hyperliquid.xyz/info`, `candleSnapshot`)
- Short horizon momentum + micro-volatility drive side (`UP`/`DOWN`)

## Execution venue

- Polymarket Gamma API for market discovery (`/markets?slug=...`)
- Polymarket CLOB for order posting (`py-clob-client`)

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# fill credentials in .env
```

## Operations

```bash
./scripts/pm_stack.sh up
./scripts/pm_stack.sh status
./scripts/pm_live_stop_graceful.sh
./scripts/pm_stack.sh down
```

## Health / reconcile

```bash
.venv/bin/python scripts/pm_reconcile.py --repo .
cat runtime/pm_reconcile_report.json
```

## Notes

- Do not commit `.env`.
- Use `runtime/` logs for audits and postmortems.
- If close path degrades (orderbook missing/no match), strategy defers close with retry.

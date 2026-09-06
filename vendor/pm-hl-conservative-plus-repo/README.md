# Polymarket HL Strategy (Deploy-Ready Template)

Production-oriented trading bot template:

- **Signal source:** Hyperliquid short-term momentum (`BTC` 1m candles)
- **Execution venue:** Polymarket CLOB (`py-clob-client`)
- **Loop:** market preview → guarded entry → managed exits (SL/TP/trailing/time-exit)
- **Ops:** heartbeat, reconcile snapshot, watchdog, graceful stop, runtime text dashboard

> This repository is intentionally **secret-free**. You only need to copy `.env.example` to `.env` and fill API credentials.

---

## 1) Strategy flow

1. Fetch active Polymarket 15m BTC market from Gamma API (`btc-updown-15m-*`).
2. Fetch Hyperliquid 1m candles and compute short momentum + micro-volatility.
3. Decide direction: `UP` or `DOWN`.
4. Apply entry safety filters:
   - price bounds
   - spread bounds
   - top-of-book liquidity
5. Submit capped BUY order to Polymarket CLOB.
6. Build open-position state and manage exits via:
   - stop-loss
   - take-profit
   - trailing-stop
   - time-exit
   - degraded fallback with deferred retries

---

## 2) Quick start

### Option A: Local Python run

```bash
git clone https://github.com/Novals83/polymarket-hl-strategy.git
cd polymarket-hl-strategy
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### Start stack

```bash
./scripts/pm_stack.sh up
```

### Option B: One-command Docker deployment (with healthcheck)

```bash
cp .env.example .env
# fill secrets in .env

docker compose up -d --build
curl http://localhost:8080/health
```

### Check stack

```bash
./scripts/pm_stack.sh status
tail -n 200 runtime/pm_live_worker.log
```

### Stop stack safely

```bash
./scripts/pm_live_stop_graceful.sh
./scripts/pm_stack.sh down
```

---

## 3) Required credentials (no secrets in repo)

Fill in `.env`:

- `PM_PRIVATE_KEY`
- `PM_FUNDER` (or `PM_ADDRESS`)
- `PM_API_KEY`
- `PM_API_SECRET`
- `PM_API_PASSPHRASE`

Optional:

- `PM_CLOB_BASE` (default `https://clob.polymarket.com`)
- `GAMMA_BASE_URL` (default `https://gamma-api.polymarket.com`)

---

## 4) Runtime files

- `runtime/pm_live_worker.log` — main loop log
- `runtime/trade_journal.jsonl` — high-level entry/exit events
- `runtime/pm_live_exits.log` — close attempts and outcomes
- `runtime/pm_reconcile_report.json` — API snapshot (positions/orders/allowances)
- `runtime/pm_exec_summary_today.json` — daily summary
- `runtime/text_dashboard_pm.txt` — plain-text dashboard

---

## 5) Safety defaults in this template

- Explicit max notional cap
- Entry filter gate (spread/liquidity/price)
- Close path supports deferred mode when orderbook is unavailable
- Manual escalation is debounced
- Graceful stop attempts forced close cycle before worker termination

---

## 6) Skill for OpenClaw

A usage skill is included:

- `skills/polymarket-hl-live-trading/SKILL.md`

It explains setup, operations, and troubleshooting commands.

---

## 7) Disclaimer

This software is for educational and infrastructure purposes. You are solely responsible for trading decisions, key management, and compliance.

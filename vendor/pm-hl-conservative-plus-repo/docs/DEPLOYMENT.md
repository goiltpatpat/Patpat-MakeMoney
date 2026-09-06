# Deployment Guide

## 1) Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill `.env` with your own Polymarket credentials.

## 2) Smoke checks

```bash
./scripts/run_pm_live_trade.sh dry
.venv/bin/python scripts/pm_reconcile.py --repo .
```

## 3) Start services (local)

```bash
./scripts/pm_stack.sh up
```

Starts:
- heartbeat loop
- reconcile loop
- live worker

## 3.1) Start with health API (local)

```bash
./scripts/start_with_health.sh
# health endpoint:
# http://localhost:8080/health
```

## 3.2) Start with Docker Compose

```bash
cp .env.example .env
# fill credentials

docker compose up -d --build
curl http://localhost:8080/health
```

## 4) Monitoring

```bash
tail -f runtime/pm_live_worker.log
tail -f runtime/pm_live_exits.log
cat runtime/pm_reconcile_report.json
```

## 5) Graceful stop

```bash
./scripts/pm_live_stop_graceful.sh
./scripts/pm_stack.sh down
```

## 6) Security

- Never commit `.env`
- Use dedicated wallet + minimal funds
- Rotate API keys on any leakage suspicion
- Restrict host access and logs

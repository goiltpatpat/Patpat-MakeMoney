#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI

app = FastAPI(title="polymarket-hl-strategy-health", version="1.0.0")
RUNTIME = Path(__file__).resolve().parents[1] / "runtime"


def _read_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


@app.get("/health")
def health():
    now = datetime.now(timezone.utc)
    worker_log = RUNTIME / "pm_live_worker.log"
    reconcile = _read_json(RUNTIME / "pm_reconcile_report.json") or {}

    worker_log_age_sec = None
    if worker_log.exists():
        worker_log_age_sec = int(now.timestamp() - worker_log.stat().st_mtime)

    return {
        "ok": True,
        "ts": now.isoformat().replace("+00:00", "Z"),
        "worker_log_exists": worker_log.exists(),
        "worker_log_age_sec": worker_log_age_sec,
        "positions_open": reconcile.get("positions_open"),
        "positions_redeemable": reconcile.get("positions_redeemable"),
        "open_orders_count": reconcile.get("open_orders_count"),
    }


@app.get("/ready")
def ready():
    worker_log = RUNTIME / "pm_live_worker.log"
    healthy_worker = worker_log.exists()
    return {"ready": healthy_worker, "worker_log_exists": healthy_worker}

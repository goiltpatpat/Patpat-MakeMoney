#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path

from py_clob_client.client import ClobClient
from py_clob_client.constants import POLYGON
from py_clob_client.clob_types import ApiCreds

RUN = True


def on_sig(*_):
    global RUN
    RUN = False


def load_env(dotenv: Path) -> None:
    if not dotenv.exists():
        return
    for ln in dotenv.read_text(encoding="utf-8", errors="replace").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        if k and k not in os.environ:
            os.environ[k] = v


def build_client() -> ClobClient:
    c = ClobClient(
        host=os.getenv("PM_CLOB_BASE", "https://clob.polymarket.com"),
        chain_id=POLYGON,
        key=os.getenv("PM_PRIVATE_KEY"),
        signature_type=int(os.getenv("PM_SIGNATURE_TYPE", "2")),
        funder=os.getenv("PM_FUNDER"),
    )
    c.set_api_creds(
        ApiCreds(
            api_key=os.getenv("PM_API_KEY"),
            api_secret=os.getenv("PM_API_SECRET"),
            api_passphrase=os.getenv("PM_API_PASSPHRASE"),
        )
    )
    return c


def main() -> None:
    signal.signal(signal.SIGINT, on_sig)
    signal.signal(signal.SIGTERM, on_sig)

    repo = Path(__file__).resolve().parents[1]
    load_env(repo / ".env")
    runtime = repo / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)

    state_path = runtime / "pm_heartbeat_state.json"
    log_path = runtime / "pm_heartbeat.log"

    interval = float(os.getenv("PM_HEARTBEAT_INTERVAL_SEC", "5"))
    hb_id = ""
    if state_path.exists():
        try:
            hb_id = str(json.loads(state_path.read_text()).get("heartbeat_id") or "")
        except Exception:
            hb_id = ""

    client = build_client()

    while RUN:
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        try:
            resp = client.post_heartbeat(hb_id if hb_id else None)
            # SDK may return dict/string; normalize
            if isinstance(resp, dict):
                hb_id = str(resp.get("heartbeat_id") or resp.get("heartbeatId") or hb_id)
                payload = resp
            else:
                payload = {"raw": str(resp)}
            state_path.write_text(json.dumps({"heartbeat_id": hb_id, "ts": ts}, ensure_ascii=False, indent=2), encoding="utf-8")
            with log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": ts, "ok": True, "heartbeat_id": hb_id, "payload": payload}, ensure_ascii=False) + "\n")
        except Exception as e:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": ts, "ok": False, "heartbeat_id": hb_id, "error": str(e)}, ensure_ascii=False) + "\n")
        time.sleep(max(1.0, interval))


if __name__ == "__main__":
    main()

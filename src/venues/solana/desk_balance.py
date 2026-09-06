"""Read-only Solana desk wallet balance probe (public RPC only — never secrets).

Uses JSON-RPC getBalance (+ optional getTokenAccountsByOwner). Pubkey only.
Never reads seed/private-key files. Never signs or sends.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

DEFAULT_RPC_URL = "https://api.mainnet-beta.solana.com"
DEFAULT_DESK_PUBKEY = "7W3SPbRcGD1GJPpafEYhgduaMxLpmHBG9KGqytqZEhHf"
TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM_ID = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
USER_AGENT = "Patpat-MakeMoney/venues-solana-desk-balance"
DEFAULT_TIMEOUT = 15.0
LAMPORTS_PER_SOL = 1_000_000_000
# Smoke size reminder for docs/ops (not enforced here): 0.001 SOL = 1_000_000 lamports
SMOKE_SOL_LAMPORTS = 1_000_000


class DeskBalanceError(RuntimeError):
    """Raised when a public-RPC balance probe fails."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_desk_pubkey(explicit: Optional[str] = None) -> str:
    """Resolve pubkey from CLI arg or PMM_SOL_DESK_PUBKEY. Never reads secret files."""
    if explicit is not None:
        pk = str(explicit).strip()
        if pk:
            return pk
    env_pk = os.environ.get("PMM_SOL_DESK_PUBKEY", "").strip()
    if env_pk:
        return env_pk
    raise DeskBalanceError(
        "desk pubkey required: pass --balance-pubkey or set PMM_SOL_DESK_PUBKEY "
        "(pubkey only; never a seed/secret path)"
    )


def resolve_rpc_url(explicit: Optional[str] = None) -> str:
    if explicit is not None and str(explicit).strip():
        return str(explicit).strip()
    return os.environ.get("PMM_SOL_RPC_URL", "").strip() or DEFAULT_RPC_URL


def _rpc_call(
    rpc_url: str,
    method: str,
    params: list[Any],
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> Any:
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    ).encode("utf-8")
    req = urllib.request.Request(
        rpc_url,
        data=body,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        raise DeskBalanceError(f"RPC HTTP {e.code} from {rpc_url}: {detail}") from e
    except urllib.error.URLError as e:
        raise DeskBalanceError(f"RPC network error {rpc_url}: {e.reason}") from e
    except TimeoutError as e:
        raise DeskBalanceError(f"RPC timeout {rpc_url}") from e
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        raise DeskBalanceError(f"invalid JSON from RPC {rpc_url}") from e
    if not isinstance(payload, dict):
        raise DeskBalanceError(f"unexpected RPC payload type: {type(payload)}")
    if payload.get("error"):
        raise DeskBalanceError(f"RPC error: {payload['error']!r}")
    return payload.get("result")


@dataclass
class TokenAccountBrief:
    mint: str
    amount_raw: str
    decimals: Optional[int]
    ui_amount: Optional[float]
    program: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DeskBalanceProbe:
    """RO desk wallet balance snapshot (pubkey + public RPC only)."""

    ok: bool
    pubkey: str
    rpc_url: str
    lamports: Optional[int]
    sol: Optional[float]
    token_account_count: Optional[int]
    tokens: list[TokenAccountBrief] = field(default_factory=list)
    ts: str = ""
    source: str = "solana_rpc_getBalance"
    mode: str = "research_dry_run"
    live: bool = False
    signed: bool = False
    execution: str = "balance_readonly"
    note: str = (
        "read-only public RPC; pubkey only; never reads seed/secret files; "
        "smoke size reminder: 0.001 SOL = 1_000_000 lamports"
    )
    errors: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_token_accounts(result: Any, *, program: str) -> list[TokenAccountBrief]:
    out: list[TokenAccountBrief] = []
    if not isinstance(result, dict):
        return out
    value = result.get("value")
    if not isinstance(value, list):
        return out
    for row in value:
        if not isinstance(row, dict):
            continue
        account = row.get("account") if isinstance(row.get("account"), dict) else {}
        data = account.get("data") if isinstance(account, dict) else None
        parsed = data.get("parsed") if isinstance(data, dict) else None
        info = parsed.get("info") if isinstance(parsed, dict) else None
        if not isinstance(info, dict):
            continue
        mint = str(info.get("mint") or "")
        ta = info.get("tokenAmount") if isinstance(info.get("tokenAmount"), dict) else {}
        amount_raw = str(ta.get("amount") or "0")
        decimals: Optional[int] = None
        ui_amount: Optional[float] = None
        if ta.get("decimals") is not None:
            try:
                decimals = int(ta["decimals"])
            except (TypeError, ValueError):
                decimals = None
        if ta.get("uiAmount") is not None:
            try:
                ui_amount = float(ta["uiAmount"])
            except (TypeError, ValueError):
                ui_amount = None
        if mint:
            out.append(
                TokenAccountBrief(
                    mint=mint,
                    amount_raw=amount_raw,
                    decimals=decimals,
                    ui_amount=ui_amount,
                    program=program,
                )
            )
    return out


def fetch_desk_balance(
    pubkey: Optional[str] = None,
    *,
    rpc_url: Optional[str] = None,
    include_token_accounts: bool = True,
    timeout: float = DEFAULT_TIMEOUT,
) -> DeskBalanceProbe:
    """
    Probe SOL lamports (+ optional SPL token accounts) for a desk pubkey via public RPC.

    Never opens seed/secret paths. Fail closed on RPC/parse errors (ok=False + errors).
    """
    pk = resolve_desk_pubkey(pubkey)
    rpc = resolve_rpc_url(rpc_url)
    ts = _utc_now_iso()
    errors: list[dict[str, Any]] = []
    lamports: Optional[int] = None
    tokens: list[TokenAccountBrief] = []

    try:
        bal = _rpc_call(rpc, "getBalance", [pk], timeout=timeout)
        if isinstance(bal, dict) and bal.get("value") is not None:
            lamports = int(bal["value"])
        elif isinstance(bal, int):
            lamports = int(bal)
        else:
            raise DeskBalanceError(f"unexpected getBalance result: {bal!r}")
    except DeskBalanceError as e:
        errors.append({"method": "getBalance", "error": str(e)})
    except Exception as e:
        errors.append({"method": "getBalance", "error": f"{type(e).__name__}: {e}"})

    if include_token_accounts:
        for prog, label in (
            (TOKEN_PROGRAM_ID, "spl-token"),
            (TOKEN_2022_PROGRAM_ID, "spl-token-2022"),
        ):
            try:
                res = _rpc_call(
                    rpc,
                    "getTokenAccountsByOwner",
                    [
                        pk,
                        {"programId": prog},
                        {"encoding": "jsonParsed"},
                    ],
                    timeout=timeout,
                )
                tokens.extend(_parse_token_accounts(res, program=label))
            except DeskBalanceError as e:
                errors.append(
                    {
                        "method": "getTokenAccountsByOwner",
                        "program": label,
                        "error": str(e),
                    }
                )
            except Exception as e:
                errors.append(
                    {
                        "method": "getTokenAccountsByOwner",
                        "program": label,
                        "error": f"{type(e).__name__}: {e}",
                    }
                )

    ok = lamports is not None
    sol = (float(lamports) / LAMPORTS_PER_SOL) if lamports is not None else None
    return DeskBalanceProbe(
        ok=ok,
        pubkey=pk,
        rpc_url=rpc,
        lamports=lamports,
        sol=sol,
        token_account_count=len(tokens) if include_token_accounts else None,
        tokens=tokens,
        ts=ts,
        errors=errors,
    )

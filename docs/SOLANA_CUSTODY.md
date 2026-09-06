# Solana desk custody — Patpat-MakeMoney

English ops SoT for the **team desk wallet**. Not financial advice. Not auto-trade.

## Wallet

| Field | Value |
|-------|--------|
| Role | Patpat-MakeMoney **team** desk wallet (make-money lane) |
| Pubkey | `7W3SPbRcGD1GJPpafEYhgduaMxLpmHBG9KGqytqZEhHf` |
| Network | Solana mainnet-beta |
| Secrets | Outside repo only (`Documents\Patpat-MakeMoney-secrets\`) — **never** in git / chat / agent memory |

## Smoke size

**0.001 SOL = 1_000_000 lamports** is the paper/RO smoke unit. Balance probe and docs use this as a reminder only — it is **not** live spend authorization.

## Thesis phase matrix (brief)

| Phase | Allowed |
|-------|---------|
| **P0 / T1** | RO Jupiter quotes + labeled fee/slip/priority; RO desk pubkey balance (`--balance-pubkey` / `PMM_SOL_DESK_PUBKEY`). `--live` refused. |
| **P1** | Paper logs → `edge_log` |
| **P2** | Optional live via Phantom UI-sign (or later gated local sign) only after P0+P1 + user OK + `PMM_SOL_LIVE_OK` |

## Authority (user grant)

Operator (`PMM_OPERATOR=patzelife`) grants the **Patpat-MakeMoney desk** (Ledger Head + Pulse / Grid / Thesis as assigned) **highest operational care rights** over this wallet for desk make-money work:

**Desk MAY**
- Read balances / token accounts (RPC, explorers) via pubkey only
- Run Jupiter **quote-only** / research tape / paper logs
- Propose levels, invalidation, fund/spend plans
- Maintain env pointers (`PMM_SOL_DESK_PUBKEY`, `PMM_SOL_SECRETS_DIR`, optional `PMM_SOL_RPC_URL`)
- After **explicit** live gates: guide Phantom UI-sign or a future local signer that never pastes seed into chat

**Desk MUST NOT**
- Paste mnemonic / private key into chat, tickets, PRs, or agent memory
- Commit secrets or put them in `.env` values
- Auto-sign / auto-swap / auto-trade without `PMM_SOL_LIVE_OK=1` **and** a fresh explicit user OK for that live step
- Fund or move size that exceeds the stated paper/live checklist
- Read seed/secret files from tooling paths (balance probe is pubkey + public RPC only)

**Human (operator) remains root custody** of the recovery phrase. “Highest team rights” = full desk ops + care mandate, **not** dispersing seed copies to bots.

## Kill switches

- Empty / unset `PMM_SOL_LIVE_OK` → no live spend path
- Any seed leak → rotate wallet, treat old pubkey as burned for desk funds
- Fixture money-path without `--allow-fixture` → kill

See `docs/SOLANA.md`, `docs/ENV.md`, `docs/APIS.md`.

# Solana — research / dry-run tape (Patpat-MakeMoney)

**Paper / read-only only.** No live swaps. No private keys. No tipster. No custody wired.

TH desk primary fiat rails remain **BNTH + Bitkub**. Solana is a **research tape** lane via Jupiter — optional cross-check vs BNTH USDT-ish with **labeled** units only.

## Thesis phase matrix (brief)

| Phase / Thesis | Allowed on Solana lane |
|----------------|------------------------|
| **P0 / T0–T1** | RO Jupiter quotes + labeled fee/slip/priority fields; RO desk **pubkey** balance probe (public RPC). Fixture-kill defaults ON. `--live` hard-refuse. |
| **P1 / T2** | Jupiter quote → **paper fill stub** (`venue=solana_paper`) → `edge_log` + scorecard-readable rows. Net after **API feeBps** only (labeled). No invented PnL. No sign/send. |
| **P2** | Optional live only after P0+P1 + explicit user OK + `PMM_SOL_LIVE_OK` (Phantom UI-sign or gated local signer). **Not wired in this slice.** |

**Smoke size:** **0.001 SOL = 1_000_000 lamports** (paper/RO smoke). Not a live spend authorization.

## API chosen (public docs, verified)

| Role | Endpoint | Notes |
|------|----------|-------|
| **Quote (SoT)** | `GET https://api.jup.ag/swap/v2/order` | **Omit `taker`** → quote only (`transaction=null`). Never call `/execute`. |
| **Price (optional)** | `GET https://api.jup.ag/price/v3?ids={mints}` | USD heuristics price; up to 50 mints. |
| **Balance (RO)** | Solana JSON-RPC `getBalance` (+ optional `getTokenAccountsByOwner`) | Pubkey only via `--balance-pubkey` / `PMM_SOL_DESK_PUBKEY`. Never reads seed files. |
| Docs (order) | https://developers.jup.ag/docs/swap/order-and-execute | Without taker: quote but no transaction |
| Docs (price) | https://developers.jup.ag/docs/price | Price API V3 |
| Portal | https://developers.jup.ag/portal | Optional `x-api-key` (`JUPITER_API_KEY`); **keyless** allowed at low RPS (~0.5) |

**Not used in this slice:** `/execute`, `/build` signing, Raydium compute (optional later), wallet keys, tip flows.

Default pair: **SOL → USDC**

- SOL mint: `So11111111111111111111111111111111111111112` (9 dp)
- USDC mint: `EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v` (6 dp)

## Ledger fields (gross vs net)

CLI / client emit JSON with:

- `mid` — out_ui / in_ui from quote
- `in_amount` / `out_amount` — raw integer amounts from API
- `price_impact_pct` — API field when present
- `route_labels` / `router` — route plan labels
- `slippage_bps` — API (labeled via `gross_vs_net.slippage_bps_label`)
- `fee_bps` — API total fee bps (labeled via `gross_vs_net.fee_bps_label`)
- `prioritization_fee_lamports` — API field when present; else `ESTIMATE_unavailable_*`
- `gross_vs_net` — gross mid vs net after **API** `feeBps` only (no invented fee stack)
- `balance` — optional RO desk probe (`lamports`, `sol`, optional `tokens`)

Fail closed: HTTP/parse errors raise; **no silent fixture**. Fixture requires `--fixture --allow-fixture`.

## Modules

```
src/venues/solana/jupiter_quotes.py   # HTTP quote + price clients
src/venues/solana/desk_balance.py     # RO pubkey balance via public RPC
src/venues/solana/paper.py            # T2 paper fill stub (venue=solana_paper)
scripts/pmm_sol_tape.py               # CLI Ledger JSON; --live refuse (exit 2)
scripts/pmm_sol_paper.py              # T2 paper fill CLI → optional edge_log
src/venues/arb/sol_cex.py             # optional Jupiter vs BNTH stub (unit_mismatch / fixture-kill)
src/venues/basis/sol_thb.py           # SOL–THB same-ccy + Jupiter×FX basis SCAN
scripts/pmm_sol_basis_scan.py         # SOL–THB basis CLI (--live refuse)
docs/SOLANA.md                        # this file
docs/SOLANA_CUSTODY.md                # desk pubkey + authority (secrets outside repo)
```

## T2 paper fill → edge_log

`scripts/pmm_sol_paper.py` turns a Jupiter quote into a **paper fill stub** (`venue=solana_paper`) and can append scorecard-readable rows to `runtime/edge_log.jsonl`.

- Fee / net fields use **API `feeBps` only** when present (labeled `API_feeBps`); otherwise `unavailable` — never invent fee stacks or PnL.
- `realized_pnl_thb` stays null on solana_paper rows (no invented THB PnL).
- `--live` hard-refused (exit 2). Fixture requires `--fixture --allow-fixture`.
- `--batch N` stamps N paper rows from one quote (offline proof path for ≥5 rows).
- BNTH premium labeled row is **out of scope** for this slice (parallel B branch).

## CLI

```bash
# Live network quote-only (keyless or JUPITER_API_KEY)
python scripts/pmm_sol_tape.py
python scripts/pmm_sol_tape.py --price-v3

# RO desk balance (pubkey only; public RPC)
python scripts/pmm_sol_tape.py --balance-only --balance-pubkey 7W3SPbRcGD1GJPpafEYhgduaMxLpmHBG9KGqytqZEhHf
# or: export PMM_SOL_DESK_PUBKEY=... ; python scripts/pmm_sol_tape.py --balance-only --balance-pubkey

# Quote + balance in one JSON
python scripts/pmm_sol_tape.py --balance-pubkey 7W3SPbRcGD1GJPpafEYhgduaMxLpmHBG9KGqytqZEhHf

# Offline fixture (tests only)
python scripts/pmm_sol_tape.py --fixture --allow-fixture

# Hard-refused
python scripts/pmm_sol_tape.py --live   # exit 2

# T2 paper fill (single) + edge_log
python scripts/pmm_sol_paper.py --fixture --allow-fixture --log-edge
python scripts/pmm_sol_paper.py --batch 5 --fixture --allow-fixture --log-edge

# Hard-refused
python scripts/pmm_sol_paper.py --live   # exit 2
```

## Hard rules

- Never sign or send Solana transactions from this repo path.
- Never invent mids / FX / priority fees.
- Never read seed / private-key files for balance or quotes.
- Money-path fixture → kill unless `--allow-fixture`.
- TH fiat rails: Bitkub + BNTH remain primary; Solana is research tape only.
- Solana live / custody: **not wired** (see `docs/HOLES.md`, `docs/SOLANA_CUSTODY.md`).



## SOL–THB basis paper tape (slice B)

Paper / read-only **basis scan** comparing:

1. **Same-ccy THB (preferred):** Bitkub `SOL_THB` vs Binance TH `SOLTHB` (`api.binance.th` only) — extend Bitkub↔BNTH BTC basis patterns; **no FX**.
2. **Jupiter cross-check:** Jupiter SOL/USDC mid × **labeled** `USDTTHB` from BNTH public ticker → THB-equivalent mid vs CEX SOL–THB mid. USDC≈USDT is an **explicit** desk label (never silent invent).

- `net_basis_bps` / fee floors are labeled **ESTIMATE** (paper falsify haircuts).
- Fixture-kill default; `--live` hard-refuse (exit 2).
- Fail closed on HTTP errors — never invent mids/FX.
- No seeds, tips, or Bitkub/BNTH live orders.

```
src/venues/basis/sol_thb.py
scripts/pmm_sol_basis_scan.py
tests/test_sol_thb_basis.py
```

```bash
python scripts/pmm_sol_basis_scan.py --paper
python scripts/pmm_sol_basis_scan.py --paper --prices-only
python scripts/pmm_sol_basis_scan.py --paper --fixture --allow-fixture --prices-only
python scripts/pmm_sol_basis_scan.py --live   # exit 2 REFUSED
```

## Custody / team authority

See [docs/SOLANA_CUSTODY.md](SOLANA_CUSTODY.md) — team desk ops rights; seed stays human-held outside repo.

## Expanded mandate (operator)

Desk may **scout + design** Solana make-money lanes **beyond Jupiter-only** (aggregators, AMMs/DLMM, RFQ, LST/basis screens, CEX↔SOL premium — each with falsify/kill criteria). Paper/read-only first. No tipster. No ungated live. THB rails (Bitkub↔BNTH) remain fiat priority; Solana is a parallel on-chain build lane.


## LST basis paper tape (mSOL / jitoSOL)

Paper / read-only **LST fair-rate vs Jupiter** scan:

1. **Marinade mSOL fair:** `GET https://api.marinade.finance/msol/price_sol` → SOL per 1 mSOL (protocol true price). APY endpoints intentionally unused (no tipster).
2. **jitoSOL fair:** SPL stake-pool ratio `totalLamports / poolTokenSupply` from account `Jito4APyf642JPZPx3hGc6WWJ8zPKtRbRs4P815Awbb` via public RPC `getAccountInfo` (RO decode).
3. **Jupiter leg:** `GET /swap/v2/order` WITHOUT taker for LST→SOL (quote-only). Route labels (Raydium/Orca/Meteora when present) logged as dispersion *hints* only — not independent DEX mids.

- `gross_basis_bps` / `net_basis_bps` labeled; fee floor prefers API `feeBps` else ESTIMATE.
- Fixture-kill default; `--live` hard-refuse (exit 2).
- Fail closed on HTTP/RPC errors — never invent fair rates or mids.
- No seeds, tips, APY marketing, or auto-trade.

`
src/venues/basis/lst.py
scripts/pmm_lst_basis_scan.py
tests/test_lst_basis.py
`

`ash
python scripts/pmm_lst_basis_scan.py --paper
python scripts/pmm_lst_basis_scan.py --paper --lst mSOL --prices-only
python scripts/pmm_lst_basis_scan.py --paper --fixture --allow-fixture --prices-only
python scripts/pmm_lst_basis_scan.py --live   # exit 2 REFUSED
`


## Jupiter quote-dispersion logger (T1-plus)

Paper / read-only **size-ladder dispersion** over Jupiter GET /swap/v2/order (quote-only, no taker):

1. **MVP SoT:** multi-size Jupiter mids (default ladder 0.001 / 0.01 / 0.05 / 0.1 / 0.5 / 1.0 SOL) → dispersion_bps = (max-min)/avg * 1e4 plus adjacent spreads.
2. **Fee+slip stack:** API eeBps / slippageBps / priority fee when present; else labeled **ESTIMATE**.
3. **Optional pool RO mids:** best-effort Raydium / Orca / Meteora public probes. If blocked or unparsed → status deferred (**no invented mids**). Jupiter size-ladder remains SoT.

- Fixture-kill default; --live hard-refuse (exit 2).
- Fail-closed on empty / rate-limit — never invent mids.
- Thesis path: --snaps 20 --fixture --allow-fixture offline; Ledger JSONL via --log.
- No tips, secrets, or auto-trade.

`
src/venues/solana/quote_dispersion.py
scripts/pmm_quote_dispersion.py
tests/test_quote_dispersion.py
`

`ash
python scripts/pmm_quote_dispersion.py --paper --prices-only
python scripts/pmm_quote_dispersion.py --paper --fixture --allow-fixture --no-pools --snaps 20 --log
python scripts/pmm_quote_dispersion.py --live   # exit 2 REFUSED
`

**Deferred:** independent Raydium/Orca/Meteora pool mid extraction may remain deferred when venue APIs block or lack a clear SOL/USDC mid field; documented in Ledger pool_mids_policy.


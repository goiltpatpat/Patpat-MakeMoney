# Solana — research / dry-run tape (Patpat-MakeMoney)

**Paper / read-only only.** No live swaps. No private keys. No tipster. No custody wired.

TH desk primary fiat rails remain **BNTH + Bitkub**. Solana is a **research tape** lane via Jupiter — optional cross-check vs BNTH USDT-ish with **labeled** units only.

## API chosen (public docs, verified)

| Role | Endpoint | Notes |
|------|----------|-------|
| **Quote (SoT)** | `GET https://api.jup.ag/swap/v2/order` | **Omit `taker`** → quote only (`transaction=null`). Never call `/execute`. |
| **Price (optional)** | `GET https://api.jup.ag/price/v3?ids={mints}` | USD heuristics price; up to 50 mints. |
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
- `slippage_bps` — API (labeled)
- `fee_bps` — API total fee bps (labeled)
- `prioritization_fee_lamports` — API field when present; else `ESTIMATE_unavailable_*`
- `gross_vs_net` — gross mid vs net after **API** `feeBps` only (no invented fee stack)

Fail closed: HTTP/parse errors raise; **no silent fixture**. Fixture requires `--fixture --allow-fixture`.

## Modules

```
src/venues/solana/jupiter_quotes.py   # HTTP quote + price clients
scripts/pmm_sol_tape.py               # CLI Ledger JSON; --live refuse (exit 2)
src/venues/arb/sol_cex.py             # optional Jupiter vs BNTH stub (unit_mismatch / fixture-kill)
docs/SOLANA.md                        # this file
```

## CLI

```bash
# Live network quote-only (keyless or JUPITER_API_KEY)
python scripts/pmm_sol_tape.py
python scripts/pmm_sol_tape.py --price-v3

# Offline fixture (tests only)
python scripts/pmm_sol_tape.py --fixture --allow-fixture

# Hard-refused
python scripts/pmm_sol_tape.py --live   # exit 2
```

## Hard rules

- Never sign or send Solana transactions from this repo path.
- Never invent mids / FX / priority fees.
- Money-path fixture → kill unless `--allow-fixture`.
- TH fiat rails: Bitkub + BNTH remain primary; Solana is research tape only.
- Solana live / custody: **not wired** (see `docs/HOLES.md`).

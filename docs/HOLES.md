# Experimental holes log — Patpat-MakeMoney

Tracked defects / hygiene gaps around tip **`26ed49f`** (Binance TH lane + DEX→CEX arb paper scanner) and fixes on `feat/experimental-hygiene`.

## Fixed in this hygiene slice

| ID | Hole @26ed49f | Fix |
|----|---------------|-----|
| H1 | `pmm_arb_scan._load_dex_mid` used `allow_fixture=True if fixture else True` (**always True**) → silent 1inch fixture on money path | Only fixture when `--fixture`; live quote uses `allow_fixture=False`; detector kills fixture legs unless `--allow-fixture` / `PMM_ARB_ALLOW_FIXTURE` |
| H2 | Arb could report `net_edge_bps > 0` from `source=fixture` mids | `detect_dex_cex_opportunity(..., allow_fixture=False)` **KILL** `money_leg_source_fixture` |
| H3 | Bitkub day-caps JSON from PowerShell often has UTF-8 **BOM** → `json.loads` fails on `utf-8` | `load_day_caps` / day state read with **`utf-8-sig`** |
| H4 | BNTH fixture ticker still labeled `binance_th_ticker_price` | Fixture rows set `_fixture`; tape quote `source=fixture` |
| H5 | No first-party labeled USDTHB helper on BNTH | `fetch_usdtthb_fx()` from `api.binance.th` `USDTTHB`; arb prefers it when `--usdthb` omitted |

## Known residual / accepted

| ID | Note |
|----|------|
| R1 | Thesis residual kills (unit_mismatch / fee stack / no 1inch key) survive hygiene — **OK** |
| R2 | Without `ONEINCH_API_KEY`, default arb path errors or kills — does **not** claim edge |
| R3 | Travel Rule / latency buffers remain **estimates** — not measured latency |
| R4 | Bitkub live / BNTH signed trade still unimplemented (hard-refuse) |
| R5 | USDT≈USD for desk FX label is an explicit approximation — documented, not invented FX |

## Fixture-kill rule (money path)

- Any DEX/CEX/FX leg with `source=fixture` → `kill=true`, `kill_reason=money_leg_source_fixture`
- Optional `--allow-fixture` (or `PMM_ARB_ALLOW_FIXTURE=1`) for **offline tests only**
- Default **OFF** for money briefs

## Solana lane residuals

| ID | Note |
|----|------|
| R6 | **Solana live / custody not wired** — research quote tape only (`docs/SOLANA.md`); no sign/send, no `/execute`, no wallet keys |
| R7 | Jupiter keyless low RPS; Portal `JUPITER_API_KEY` optional — rate limits may fail closed (no invented quotes) |
| R8 | Raydium direct compute not wired (optional later) |
| R9 | `sol_cex` BNTH compare requires labeled same-stable (USDC≈USDT) or labeled FX — else `unit_mismatch` |

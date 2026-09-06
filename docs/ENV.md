# Environment — Patpat-MakeMoney

English ops note for local + team env setup.

## Files

| File | Tracked? | Purpose |
|------|----------|---------|
| `.env.example` | yes | Full team template (SoT). Copy → `.env` |
| `.env.local.example` | yes | Thin machine overlay template → `.env.local` |
| `.env` / `.env.local` | **no** | Your real values (gitignored) |
| `Documents\Patpat-MakeMoney-secrets\` | **no** | Wallet phrase / private keys (outside repo) |

## Setup (each teammate)

```powershell
cd Patpat-MakeMoney
copy .env.example .env
# optional: copy .env.local.example .env.local
# edit .env — fill only what you need; leave live gates blank
```

## Rules

1. **Never commit** `.env`, mnemonics, private keys, or API secrets.
2. **Pubkey OK** in `.env` (`PMM_SOL_DESK_PUBKEY`); seed stays in secrets folder only.
3. **Live gates** (`PMM_*_LIVE_OK`) stay empty until explicit desk authorization.
4. **Fixture gates** stay empty outside offline tests.
5. Binance TH base must remain `https://api.binance.th` (not `.com`).
6. Solana lane: Jupiter quote-only until P0+P1 pass; no sign/send from env alone.

See also: `docs/APIS.md`, `docs/SOLANA.md`, `DESK.md`.

## Solana smoke

**0.001 SOL = 1_000_000 lamports** — paper/RO smoke size (see docs/SOLANA.md). Balance probe uses pubkey + public RPC only.


# Vendored execution stack — NOTICE

This directory vendors a Patpat-MakeMoney desk copy of the Polymarket live runner derived from
[Novals83/polymarket-hl-strategy](https://github.com/Novals83/polymarket-hl-strategy).

It is **not** a separate GitHub repository for this team. Source of truth:
[goiltpatpat/Patpat-MakeMoney](https://github.com/goiltpatpat/Patpat-MakeMoney).

Desk delta:
- `--force-side UP|DOWN` — caller owns entry side when set
- HL signal is advisory when force-side is present

Local only (gitignored): `.venv/`, `.env`, `runtime/`.
Paper/dry-run is default. Live requires explicit `--execute` plus credentials.

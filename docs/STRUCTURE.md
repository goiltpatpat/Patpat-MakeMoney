# Patpat-MakeMoney repository structure

```
Patpat-MakeMoney/
  DESK.md                 # desk doctrine + Ledger brief template
  CONTOUR.md              # canonical runners / dependency boundary
  README.md               # team overview
  SKILL.md                # OpenClaw skill definition
  docs/
    STRUCTURE.md          # this file
    RUNTIME.md            # enforced behavior and limitations
  memory-bank/            # local continuity only (gitignored; optional)
  config/
    btc_5m_profiles.yaml  # conservative | aggressive | desk
  src/
    live/pm_live_trade_runner.py  # team execution runner
  src/
    live/pm_live_trade_runner.py
  scripts/
    pmm_ctl.sh            # TEAM entry (wraps btc5m_ctl.sh)
    pmm_doctor.py         # paper-first / profile gates
    btc5m_ctl.sh          # upstream-compatible control (patched paper-first)
    test_btc_5m_session_exit_sl.py
    btc5m_*.py / *.sh     # reports, docker, hot helpers
  tests/
    test_desk_safety.py   # no-credential safety tests
  examples/
    run-example.md
  runtime/                # created at run time (gitignored)
```

Naming:
- **pmm_*** = Patpat-MakeMoney team surface
- **btc5m_*** = upstream-compatible internals (kept for sync)

Default profile: **desk**. Default mode: **dry-run**.

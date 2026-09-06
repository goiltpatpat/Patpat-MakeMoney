# Patpat-MakeMoney — example commands

## Paper / dry-run (default — safe)

```bash
# team entry
scripts/pmm_ctl.sh start --profile desk

# or direct runner (no --execute)
.venv/bin/python scripts/test_btc_5m_session_exit_sl.py --profile desk
```

## Doctor / unit safety checks (no API keys)

```bash
python scripts/pmm_doctor.py
python3 -m unittest discover -s tests -v
```

## Live (opt-in only after Ledger desk gate)

```bash
scripts/pmm_ctl.sh start --profile desk --live
# equivalent:
.venv/bin/python scripts/test_btc_5m_session_exit_sl.py --profile desk --execute
```

## Kill switch

```bash
scripts/pmm_ctl.sh stop
```

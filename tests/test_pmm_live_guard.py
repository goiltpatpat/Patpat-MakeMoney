"""Isolation / live-guard regressions."""
from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

import pmm_live_guard as g


class LiveGuardTests(unittest.TestCase):
    def test_open_exec_env_is_desk_tight(self):
        env = g.open_exec_env({"PM_MAX_SPREAD": "1", "PM_MIN_TOP_ASK_NOTIONAL_USD": "0"})
        self.assertEqual(env["PM_MAX_SPREAD"], "0.03")
        self.assertEqual(env["PM_MIN_TOP_ASK_NOTIONAL_USD"], "30")

    def test_require_live_ok_blocks_execute(self):
        with patch.dict(os.environ, {"PMM_LIVE_OK": ""}, clear=False):
            with self.assertRaises(SystemExit):
                g.require_live_ok(True)
        with patch.dict(os.environ, {"PMM_LIVE_OK": "1"}, clear=False):
            g.require_live_ok(True)
            g.require_live_ok(False)

    def test_day_trade_cap(self):
        repo = Path(__file__).resolve().parents[1]
        g.save_day_state({"day": g.utc_day(), "trades": 8, "realized_pnl_usdc": 0.0}, repo)
        ok, status, _ = g.can_open_live(8, 6.0, root=repo)
        self.assertFalse(ok)
        self.assertEqual(status, "skip_max_trades_per_day")
        g.save_day_state({"day": g.utc_day(), "trades": 0, "realized_pnl_usdc": 0.0}, repo)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Unit checks for Patpat-MakeMoney desk safety (no Polymarket credentials required)."""
from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DeskSafetyTests(unittest.TestCase):
    def test_doctor_passes(self):
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "pmm_doctor.py")],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0, msg=r.stdout + "\n" + r.stderr)

    def test_ctl_start_dry_by_default(self):
        text = (ROOT / "scripts" / "btc5m_ctl.sh").read_text(encoding="utf-8")
        self.assertNotRegex(text, r'runner_cmd=\([^\)]*"--execute"\)')
        self.assertIn("live=0", text)
        self.assertIn("--live|--execute", text)

    def test_desk_profile_tighter_than_aggressive(self):
        text = (ROOT / "config" / "btc_5m_profiles.yaml").read_text(encoding="utf-8")
        self.assertIn("\n  desk:", text)
        # crude extract stake_usd under desk
        m = re.search(r"\n  desk:.*?stake_usd:\s*(\d+)", text, re.S)
        self.assertIsNotNone(m)
        self.assertLessEqual(int(m.group(1)), 5)


if __name__ == "__main__":
    unittest.main()

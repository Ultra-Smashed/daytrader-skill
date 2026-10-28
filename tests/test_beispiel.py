import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from _load import FIX, ROOT, SKILLS

DAX = os.path.join(FIX, "dt-scanner", "dax-v8-5d5m-2026-10-28.json.gz")
PLAN = os.path.join(FIX, "dt-alarm", "plan-sap.json")
CONFIG = os.path.join(SKILLS, "dt-budget", "config.example.json")


def tool(cwd, skill, script, *args):
    p = subprocess.run([sys.executable, os.path.join(SKILLS, skill, script)] + list(args),
                       cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    return p.returncode, p.stdout, p.stderr


class ReadmeBeispielSAP(unittest.TestCase):
    """Die Kette aus dem README: SAP.DE an XETRA, Di 27.10.2026, Beispiel-Config."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(cls.dir, "trader"))
        shutil.copy(PLAN, os.path.join(cls.dir, "trader", "plan.json"))
        shutil.copy(CONFIG, os.path.join(cls.dir, "trader", "config.json"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir)

    def test_1_scanner_um_11_uhr(self):
        code, out, err = tool(self.dir, "dt-scanner", "scan.py", "orb", "--offline", DAX,
                              "--now", "2026-10-27 11:00")
        self.assertEqual(code, 0, err)
        self.assertIn("43 von 43 Charts geladen; 31 nutzbar", out)
        self.assertIn("13 von 31 Charts haben bis 11:00 Uhr über ihrem Opening-Range-Hoch geschlossen", out)
        self.assertIn("10:55 Uhr  SAP.DE      214,90 €  Range 211,70 bis 214,75  +0,07 % drüber", out)

    def test_2_budget_risiko_ticket(self):
        code, out, err = tool(self.dir, "dt-budget", "size.py", "--offline", "--now", "2026-10-27 10:56", "--write")
        self.assertEqual(code, 0, err)
        self.assertIn("= 1,7875 €", out)
        self.assertIn("Größe: 17 Aktien SAP.DE = 3.653,30 € zu 214,90. Max. Verlust am Stop: "
                      "17 × 1,7875 € + 2 € Gebühren = 32,39 €.", out)

        code, out, err = tool(self.dir, "dt-risiko", "check.py", "--now", "2026-10-27 10:56")
        self.assertEqual(code, 0, err)
        self.assertIn("FREIGABE #1 Kauf SAP.DE 17 Aktien", out)
        self.assertIn("max. Verlust 32,39 € (Limit 50 €), Chance/Risiko 1,00", out)
        self.assertIn("0 von 3 Trades, 0 € von 150 € Tagesverlust", out)
        self.assertIn("keine Empfehlung", out)

        code, out, err = tool(self.dir, "dt-broker", "ticket.py", "show", "--now", "2026-10-27 10:56")
        self.assertEqual(code, 0, err)
        self.assertIn("KAUF 17 Stück SAP.DE, Market, gültig heute", out)
        self.assertIn("Stop-Loss 213,22 €", out)
        self.assertIn("Take-Profit 216,58 €", out)
        self.assertNotIn("ACHTUNG LIVE", out)

    def test_3_live_konto_warnt(self):
        live = tempfile.mkdtemp()
        try:
            shutil.copytree(os.path.join(self.dir, "trader"), os.path.join(live, "trader"))
            cfg_path = os.path.join(live, "trader", "config.json")
            with open(cfg_path, encoding="utf-8") as fh:
                cfg = json.load(fh)
            cfg["paper"] = False
            with open(cfg_path, "w", encoding="utf-8") as fh:
                json.dump(cfg, fh)
            tool(live, "dt-budget", "size.py", "--offline", "--now", "2026-10-27 10:56", "--write")
            tool(live, "dt-risiko", "check.py", "--now", "2026-10-27 10:56")
            code, out, _ = tool(live, "dt-broker", "ticket.py", "show", "--now", "2026-10-27 10:56")
            self.assertIn("ACHTUNG LIVE: Diese Order setzt echtes Geld ein.", out)
        finally:
            shutil.rmtree(live)


if __name__ == "__main__":
    unittest.main()

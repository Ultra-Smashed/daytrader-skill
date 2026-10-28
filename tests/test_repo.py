import hashlib
import json
import os
import re
import unittest

from _load import ROOT, SKILLS as SKILLS_DIR

SKILLS = ["dt-scanner", "dt-news", "dt-einstieg", "dt-ausstieg", "dt-zeitmaschine", "dt-risiko",
          "dt-budget", "dt-broker", "dt-alarm", "dt-analyst", "dt-insider"]
ORDER_PATH = ["dt-scanner", "dt-einstieg", "dt-ausstieg", "dt-zeitmaschine", "dt-budget", "dt-insider",
              "dt-risiko", "dt-broker", "dt-alarm"]
OLD_NAMES = ["trader-scanner", "trader-news", "trader-entry", "trader-exit", "trader-timemachine",
             "trader-risk", "trader-budget", "trader-broker", "trader-alerts", "trader-analyst",
             "trader-pelosi", "trader-copycat", "trader-screener", "trader-tax", "trader-rebalance"]


def frontmatter(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    return (m.group(1) if m else ""), text


def every_text_file():
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for f in files:
            if f.endswith((".md", ".py", ".json", ".csv", ".txt", ".xml")) or f == "LICENSE":
                yield os.path.join(base, f)


class Repo(unittest.TestCase):
    def test_eleven_skill_folders(self):
        found = sorted(d for d in os.listdir(SKILLS_DIR)
                       if os.path.isfile(os.path.join(SKILLS_DIR, d, "SKILL.md")))
        self.assertEqual(found, sorted(SKILLS))

    def test_root_layout(self):
        root = sorted(d for d in os.listdir(ROOT) if d not in (".git", ".DS_Store"))
        self.assertEqual(root, sorted([".claude-plugin", ".gitignore", "LICENSE", "README.md", "RISIKOHINWEISE.md", "skills", "tests"]))

    def test_frontmatter_name_and_german_description(self):
        for s in SKILLS:
            fm, text = frontmatter(os.path.join(SKILLS_DIR, s, "SKILL.md"))
            self.assertIn("name: %s\n" % s, fm + "\n", s)
            self.assertRegex(fm, r"description: ", s)
            self.assertGreater(len(fm), 200, "%s: die Beschreibung ist zu dünn" % s)
            self.assertGreater(len(text.splitlines()), 60, s)
            self.assertRegex(text, r"[äöüß]", "%s: SKILL.md sollte deutsch sein" % s)

    def test_order_path_skills_carry_the_safety_rule(self):
        for s in ORDER_PATH:
            _, text = frontmatter(os.path.join(SKILLS_DIR, s, "SKILL.md"))
            low = " ".join(text.lower().split())
            self.assertIn("keine anlageberatung", low, s)
            self.assertIn("ja", low, s)
            self.assertIn("paper", low, s)

    def test_every_skill_carries_the_risk_notes(self):
        for s in SKILLS:
            _, text = frontmatter(os.path.join(SKILLS_DIR, s, "SKILL.md"))
            self.assertIn("\n## Risikohinweise\n", text, s)
            block = text.split("\n## Risikohinweise\n", 1)[1].split("\n## ", 1)[0]
            for word in ("Totalverlust", "Keine Anlageberatung", "0800 1 37 27 00", "RISIKOHINWEISE.md"):
                self.assertIn(word, block, "%s: %s" % (s, word))

    def test_risk_notes_file(self):
        with open(os.path.join(ROOT, "RISIKOHINWEISE.md"), encoding="utf-8") as fh:
            text = " ".join(fh.read().split())
        self.assertTrue(text.startswith("# Risikohinweise"))
        for word in ("Totalverlust", "keine Anlageberatung", "Erlaubnis der BaFin", "15 Minuten verzögert",
                     "Stop ist keine Garantie", "Simulation", "Abgeltungsteuer", "Anlage KAP",
                     "0800 1 37 27 00", "soweit gesetzlich zulässig", "Vorsatz und grobe Fahrlässigkeit"):
            self.assertIn(word, text, word)

    def test_markt_is_the_same_file_in_every_skill(self):
        digests = {}
        for s in SKILLS:
            path = os.path.join(SKILLS_DIR, s, "markt.py")
            self.assertTrue(os.path.isfile(path), "%s/markt.py fehlt" % s)
            with open(path, "rb") as fh:
                digests[s] = hashlib.sha256(fh.read()).hexdigest()
        self.assertEqual(len(set(digests.values())), 1, digests)

    def test_plugin_manifest(self):
        with open(os.path.join(ROOT, ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
            plugin = json.load(fh)
        self.assertEqual(plugin["name"], "daytrader-skill")
        self.assertEqual(plugin["license"], "MIT")
        with open(os.path.join(ROOT, ".claude-plugin", "marketplace.json"), encoding="utf-8") as fh:
            market = json.load(fh)
        self.assertEqual(market["name"], "daytrader-skill")
        self.assertEqual(market["plugins"][0]["name"], "daytrader-skill")

    def test_license_keeps_the_original_copyright(self):
        with open(os.path.join(ROOT, "LICENSE"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("Jake Schincariol", text)
        self.assertIn("MIT License", text)

    def test_readme(self):
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
            readme = " ".join(fh.read().split())
        self.assertTrue(readme.startswith("# Daytrader-Skill"))
        for line in ("Keine Anlageberatung", "Paper", "Abgeltungsteuer", "github.com/Ultra-Smashed/daytrader-skill"):
            self.assertIn(line, readme)
        for s in SKILLS:
            self.assertIn("/" + s, readme, s)
        box = readme.index("Wichtige Risikohinweise")
        self.assertLess(box, readme.index("## Installation"))
        self.assertIn("RISIKOHINWEISE.md", readme[box:readme.index("## Installation")])
        self.assertIn("Totalverlust", readme[box:readme.index("## Installation")])

    def test_no_em_dashes_and_no_personal_email(self):
        for path in every_text_file():
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            rel = os.path.relpath(path, ROOT)
            if not rel.startswith(os.path.join("tests", "fixtures")):
                self.assertNotIn("\u2014", text, rel)
            self.assertNotIn("jakeschincariol" + "@" + "gmail.com", text, rel)

    def test_no_old_skill_names_left(self):
        for path in every_text_file():
            rel = os.path.relpath(path, ROOT)
            if rel.startswith("tests" + os.sep) or rel == "README.md":
                continue
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            for old in OLD_NAMES:
                self.assertNotIn(old, text, rel)

    def test_every_tool_runs_on_python_3_8(self):
        for s in SKILLS:
            folder = os.path.join(SKILLS_DIR, s)
            for f in os.listdir(folder):
                if not f.endswith(".py"):
                    continue
                with open(os.path.join(folder, f), encoding="utf-8") as fh:
                    src = fh.read()
                for bad in ("import zoneinfo", "from zoneinfo", ".removeprefix(", ".removesuffix(",
                            "match ", "list[", "dict[", "tuple["):
                    if bad == "match ":
                        self.assertNotRegex(src, r"(?m)^\s+match \w+.*:$", "%s/%s" % (s, f))
                    elif bad.endswith("["):
                        self.assertNotRegex(src, r"(?<![\w.])%s" % re.escape(bad), "%s/%s" % (s, f))
                    else:
                        self.assertNotIn(bad, src, "%s/%s" % (s, f))

    def test_example_config_is_german_and_safe(self):
        with open(os.path.join(SKILLS_DIR, "dt-budget", "config.example.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
        self.assertEqual(cfg["market"], "xetra")
        self.assertEqual(cfg["account_currency"], "EUR")
        for k in ("max_loss_per_trade", "max_daily_loss", "max_trades_per_day", "min_reward_risk",
                  "require_stop", "fee_per_order", "zeiten"):
            self.assertIn(k, cfg, k)
        self.assertEqual(cfg["zeiten"]["xetra"]["flat_by"], "17:25")
        self.assertIs(cfg["require_stop"], True)
        self.assertIs(cfg["paper"], True)
        for k in ("allow_short", "allow_margin", "allow_options"):
            self.assertIs(cfg.get(k, False), False, k)


if __name__ == "__main__":
    unittest.main()

"""The throwaway repositories the dialogues talk to. Invented projects, names and numbers; each becomes a git repository
under the run's /tmp folder, and a Claude Code session is started in it. NOTES.md holds the facts the status questions
ask about; a typed setup turn, the same in every arm, has the session read it before the call starts."""

SETUP_LINE = "Read NOTES.md now and keep it in mind: you will be asked about it. Reply with the single word: ready."

SLOW_CHECK = """#!/bin/sh
# A slow, harmless check: one line a second into logs/, for the stop dialogues.
mkdir -p logs
i=0
while [ $i -lt ${1:-25} ]; do
  i=$((i+1))
  echo "check step $i" >> logs/check.log
  sleep 1
done
echo "check finished"
"""

FIXTURES = {
    "billing": {
        "NOTES.md": (
            "# billing: status\n\n"
            "- The last test run had 3 failures, all in tests/test_refunds.py. They are about rounding half-cent refunds.\n"
            "- Work branch: fix-refund-rounding.\n"
            "- Next step: switch refund() to Decimal with ROUND_HALF_EVEN.\n"
            "- The staging deploy is blocked until the tests pass.\n"),
        "app/__init__.py": "",
        "app/refunds.py": (
            "from decimal import Decimal\n\n\n"
            "def calc_total(items):\n"
            "    return sum(Decimal(str(i[\"price\"])) * i[\"qty\"] for i in items)\n\n\n"
            "def refund(order_id, amount):\n"
            "    if amount <= 0:\n"
            "        raise ValueError(\"amount must be positive\")\n"
            "    return {\"order\": order_id, \"refunded\": round(float(amount), 2)}\n"),
        "tests/__init__.py": "",
        "tests/test_refunds.py": (
            "import unittest\nfrom decimal import Decimal\n\nfrom app.refunds import calc_total, refund\n\n\n"
            "class Refunds(unittest.TestCase):\n"
            "    def test_total(self):\n"
            "        self.assertEqual(calc_total([{\"price\": 1.5, \"qty\": 2}]), Decimal(\"3.0\"))\n\n"
            "    def test_refund_positive(self):\n"
            "        with self.assertRaises(ValueError):\n"
            "            refund(\"A1\", 0)\n\n\n"
            "if __name__ == \"__main__\":\n    unittest.main()\n"),
        "scripts/slow_check.sh": SLOW_CHECK,
    },
    "quarry": {
        "NOTES.md": (
            "# quarry: status\n\n"
            "- The nightly import loaded 1.2 million rows and took 47 minutes.\n"
            "- The slow step is dedupe_rows: 31 of the 47 minutes.\n"
            "- Plan: add an index on customer_id.\n"
            "- Reviewer for the change: Priya.\n"),
        "pipeline/__init__.py": "",
        "pipeline/load.py": (
            "def load_batches(path, batch_size=500):\n"
            "    with open(path) as f:\n"
            "        batch = []\n"
            "        for line in f:\n"
            "            batch.append(line.rstrip(\"\\n\"))\n"
            "            if len(batch) == batch_size:\n"
            "                yield batch\n"
            "                batch = []\n"
            "        if batch:\n"
            "            yield batch\n\n\n"
            "def dedupe_rows(rows):\n"
            "    seen, out = set(), []\n"
            "    for r in rows:\n"
            "        if r not in seen:\n"
            "            seen.add(r)\n"
            "            out.append(r)\n"
            "    return out\n"),
        "scratch.txt": "scratch\n",  # apr-04 deletes it: at the top level, so no folder name can be taken for /tmp
        "scripts/slow_check.sh": SLOW_CHECK,
    },
    "atlas": {
        "NOTES.md": (
            "# atlas: status\n\n"
            "- The Lighthouse performance score is 71.\n"
            "- The largest asset is hero.png at 2.3 megabytes.\n"
            "- Next: convert hero.png to WebP.\n"),
        "src/hero.js": "export function heroSrc() {\n  return \"/img/hero.png\";\n}\n",
        "README.md": "# atlas\n\nThe marketing site.\n",
    },
    "tariff-api": {
        "NOTES.md": (
            "# tariff-api: status\n\n"
            "- Version 2.4.1.\n"
            "- Open bug: currency rounding for Japanese yen.\n"
            "- Last deploy: Tuesday.\n"),
        "VERSION": "2.4.1\n",
        "api/rates.py": "def convert(amount, rate):\n    return round(amount * rate, 2)\n",
    },
    "tariff-web": {
        "NOTES.md": (
            "# tariff-web: status\n\n"
            "- Version 0.9.0.\n"
            "- The checkout page still shows the old logo.\n"),
        "VERSION": "0.9.0\n",
        "web/checkout.html": "<img src=\"old-logo.svg\" alt=\"logo\">\n",
    },
}

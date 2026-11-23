"""noisy-paths: move a module into a new subpackage and fix every import, the instruction spoken over 6 dB babble."""

from hlk.common import NAMES, Instance, Slot, Turn, confirm_slot, hidden_test, py, readme, rng

GROUP, STRESSOR = "naming", "move a module and fix imports, spoken over 6 dB babble"
MOVES = [("util_dates", "clock", "dates", "iso_day", "def iso_day(y, m, d):\n    return f\"{y:04d}-{m:02d}-{d:02d}\"\n",
          "(2024, 3, 9)", '"2024-03-09"', "util underscore dates", "clock", "dates"),
         ("util_money", "coins", "money", "cents", "def cents(amount):\n    return round(amount * 100)\n",
          "(1.25,)", "125", "util underscore money", "coins", "money"),
         ("util_text", "words", "strings", "shout", "def shout(text):\n    return text.upper() + \"!\"\n",
          "(\"hi\",)", '"HI!"', "util underscore text", "words", "strings")]


def make(seed: int) -> Instance:
    r = rng("noisy-paths", seed)
    old, sub, new, fn, code, call, want, old_said, sub_said, new_said = MOVES[seed % len(MOVES)]
    pkg = r.choice(NAMES)
    files = {f"{pkg}/__init__.py": py(""), f"{pkg}/{old}.py": py(code),
             f"{pkg}/report.py": py(f"from {pkg}.{old} import {fn}\n\n\ndef line(*args):\n    return \"report: \" + str({fn}(*args))\n"),
             f"{pkg}/export.py": py(f"import {pkg}.{old} as helpers\n\n\ndef row(*args):\n    return [helpers.{fn}(*args)]\n"),
             "test_report.py": py(f"import unittest\n\nfrom {pkg}.report import line\n\n\nclass T(unittest.TestCase):\n"
                                  f"    def test_line(self):\n        self.assertTrue(line(*{call}).startswith(\"report: \"))\n"),
             "README.md": readme(pkg, "A small package.")}
    moved = {f"{pkg}/{old}.py": None, f"{pkg}/{sub}/__init__.py": py(""), f"{pkg}/{sub}/{new}.py": py(code),
             f"{pkg}/report.py": py(f"from {pkg}.{sub}.{new} import {fn}\n\n\ndef line(*args):\n    return \"report: \" + str({fn}(*args))\n"),
             f"{pkg}/export.py": py(f"import {pkg}.{sub}.{new} as helpers\n\n\ndef row(*args):\n    return [helpers.{fn}(*args)]\n")}
    hidden = hidden_test(
        f"import pathlib\n\nimport {pkg}.export\nimport {pkg}.report\nfrom {pkg}.{sub}.{new} import {fn}\n\n\n"
        "class Hidden(unittest.TestCase):\n"
        f"    def test_moved(self):\n        self.assertEqual({fn}(*{call}), {want})\n\n"
        f"    def test_old_gone(self):\n        self.assertFalse(pathlib.Path(\"{pkg}/{old}.py\").exists())\n\n"
        f"    def test_callers(self):\n        self.assertEqual({pkg}.report.line(*{call}), \"report: \" + str({want}))\n"
        f"        self.assertEqual({pkg}.export.row(*{call}), [{want}])\n\n"
        f"    def test_no_old_import(self):\n        for p in pathlib.Path(\"{pkg}\").rglob(\"*.py\"):\n"
        f"            self.assertNotIn(\"{old}\", p.read_text(), str(p))\n")
    spoken = (f"Move {pkg} slash {old_said} dot py into a new package, {pkg} slash {sub_said}, and call it {new_said} "
              "dot py. Then fix every import.")
    canonical = f"Move {pkg}/{old}.py to {pkg}/{sub}/{new}.py (a new package) and fix every import."
    return Instance("noisy-paths", seed, GROUP, STRESSOR, {pkg: files}, {pkg: moved},
                    {pkg: {"test_hidden_hlk.py": hidden}}, {pkg: ["test_report.py"]},
                    [Turn("t1", spoken, canonical, "on_start", pkg, noise="babble:6")],
                    [Slot("which_file", [r"\b(which file|which module|where|what name|path|called)\b"],
                          f"From {pkg} slash {old_said} dot py to {pkg} slash {sub_said} slash {new_said} dot py.",
                          f"From {pkg}/{old}.py to {pkg}/{sub}/{new}.py."),
                     confirm_slot()],
                    noise="pink:12")

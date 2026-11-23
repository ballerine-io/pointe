"""long-dictation: a spoken spec of about 45 seconds with six requirements and written disfluencies."""

from hlk.common import NAMES, Instance, Slot, Turn, confirm_slot, hidden_test, py, readme, rng, say_number

GROUP, STRESSOR = "language", "a 45-second spec with six requirements and written disfluencies"
SHAPES = [("shelf", "stack_summary", "stack summary"), ("crate", "bin_report", "bin report"),
          ("rack", "load_overview", "load overview")]
DIGITS = {1: "one decimal place", 2: "two decimal places", 3: "three decimal places"}


def make(seed: int) -> Instance:
    r = rng("long-dictation", seed)
    module, fn, fn_said = SHAPES[seed % len(SHAPES)]
    digits = [2, 1, 3][seed % 3]
    repo = r.choice(NAMES)
    files = {f"{module}.py": py(f'"""Summaries for the {module}."""\n'), "README.md": readme(repo, f"Summaries for the {module}.")}
    solution = (f'"""Summaries for the {module}."""\n\n\ndef {fn}(values):\n    vals = [v for v in values if v is not None]\n'
                '    if not vals:\n        return {"count": 0, "total": 0, "low": None, "high": None, "mean": None}\n'
                '    return {"count": len(vals), "total": sum(vals), "low": min(vals), "high": max(vals),\n'
                f'            "mean": round(sum(vals) / len(vals), {digits})}}\n')
    hidden = hidden_test(
        f"from {module} import {fn}\n\n\nclass Hidden(unittest.TestCase):\n"
        f"    def test_count_total(self):\n        d = {fn}([1, 2, 4])\n        self.assertEqual((d[\"count\"], d[\"total\"]), (3, 7))\n\n"
        f"    def test_low_high(self):\n        d = {fn}([5, -2, 9])\n        self.assertEqual((d[\"low\"], d[\"high\"]), (-2, 9))\n\n"
        f"    def test_mean(self):\n        self.assertEqual({fn}([1, 2, 2])[\"mean\"], round(5 / 3, {digits}))\n\n"
        f"    def test_none_skipped(self):\n        d = {fn}([None, 4, None, 6])\n        self.assertEqual((d[\"count\"], d[\"total\"], d[\"mean\"]), (2, 10, 5))\n\n"
        f"    def test_empty(self):\n        self.assertEqual({fn}([]), {{\"count\": 0, \"total\": 0, \"low\": None, \"high\": None, \"mean\": None}})\n")
    spoken = (f"Okay, so, um, in {module} dot py I need a new function, uh, call it {fn_said}, snake case, that takes a list "
              "of numbers and gives back a dictionary. Um, it should have count, which is how many values there are, "
              "and total, which is the sum. Then, uh, low and high, so the smallest and the largest value. And mean, "
              f"the average, uh, rounded to {DIGITS[digits]}. Oh, and if any of the values are None, just skip them, "
              "like they're not there at all. And, um, for an empty list, count and total are zero and the other three "
              "are None. That's it, I think.")
    canonical = (f"In {module}.py add {fn}(values) returning a dict with keys count, total (sum), low (min), high (max) "
                 f"and mean (average rounded to {digits} decimals). Skip None values. For an empty list return count 0, "
                 "total 0 and low, high, mean as None.")
    return Instance("long-dictation", seed, GROUP, STRESSOR, {repo: files}, {repo: {f"{module}.py": py(solution)}},
                    {repo: {"test_hidden_hlk.py": hidden}}, {repo: ["README.md"]},
                    [Turn("t1", spoken, canonical, "on_start", repo)],
                    [Slot("which_value", [r"\b(round|decimal|empty|none|keys|which|what should)\b"],
                          f"Mean rounded to {DIGITS[digits]}, None values skipped, and an empty list gives zeros for "
                          "count and total and None for the rest.",
                          f"mean rounded to {digits} decimals; skip None; empty list: count 0, total 0, others None."),
                     confirm_slot()])

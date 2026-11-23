"""self-correction: "rename it to X, no wait, to Y, and only in the api package"."""

from hlk.common import NAMES, Instance, Slot, Turn, confirm_slot, hidden_test, py, readme, rng

GROUP, STRESSOR = "language", '"rename it to X, no wait, to Y, and only in the api package"'
RENAMES = [("calc_fee", "compute_levy", "compute_charge", "calc fee", "compute levy", "compute charge"),
           ("get_rate", "fetch_ratio", "fetch_rate", "get rate", "fetch ratio", "fetch rate"),
           ("make_slug", "build_handle", "build_slug", "make slug", "build handle", "build slug")]


def make(seed: int) -> Instance:
    r = rng("self-correction", seed)
    old, wrong, right, old_s, wrong_s, right_s = RENAMES[seed % len(RENAMES)]
    repo = r.choice(NAMES)

    def api(name):
        return {"api/fees.py": py(f"def {name}(amount):\n    return round(amount * 0.03, 2)\n"),
                "api/routes.py": py(f"from api.fees import {name}\n\n\ndef checkout(amount):\n    return amount + {name}(amount)\n")}
    files = {"api/__init__.py": py(""), **api(old), "batch/__init__.py": py(""),
             "batch/jobs.py": py(f"def {old}(rows):\n    \"\"\"A different helper with the same name: per-row handling fee.\"\"\"\n"
                                 "    return len(rows) * 0.5\n"),
             "README.md": readme(repo, "The api package serves checkout; the batch package runs nightly jobs.")}
    hidden = hidden_test(
        f"import pathlib\n\nfrom api.fees import {right}\nfrom api.routes import checkout\nfrom batch.jobs import {old}\n\n\n"
        "class Hidden(unittest.TestCase):\n"
        f"    def test_renamed(self):\n        self.assertEqual({right}(100), 3.0)\n        self.assertEqual(checkout(100), 103.0)\n\n"
        f"    def test_api_clean(self):\n        for p in pathlib.Path(\"api\").rglob(\"*.py\"):\n"
        f"            self.assertNotIn(\"{old}\", p.read_text(), str(p))\n\n"
        f"    def test_no_wrong_name(self):\n        for p in pathlib.Path(\".\").rglob(\"*.py\"):\n"
        f"            if \"hidden_hlk\" not in p.name:\n                self.assertNotIn(\"{wrong}\", p.read_text(), str(p))\n\n"
        f"    def test_batch_kept(self):\n        self.assertEqual({old}([1, 2]), 1.0)\n")
    spoken = f"Rename {old_s} to {wrong_s}, no wait, to {right_s}, and only in the api package."
    canonical = f"Rename {old} to {right}, only in the api package."
    return Instance("self-correction", seed, GROUP, STRESSOR, {repo: files}, {repo: api(right)},
                    {repo: {"test_hidden_hlk.py": hidden}}, {repo: ["batch/jobs.py"]},
                    [Turn("t1", spoken, canonical, "on_start", repo)],
                    [Slot("which_symbol", [r"\b(levy|ratio|handle|which name|which one|new name)\b", wrong, right],
                          f"{right_s.capitalize()}, not {wrong_s}.", f"{right}, not {wrong}."),
                     Slot("confirm_scope", [r"\b(batch|everywhere|all of|both packages|scope|jobs)\b"],
                          "Only the api package. Leave batch alone.", "Only the api package; leave batch alone."),
                     confirm_slot()])

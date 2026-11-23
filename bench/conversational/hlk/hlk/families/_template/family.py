"""<family-name>: one line saying what the stressor is. Copy this folder, rename it, fill in make(), run `run.py verify`.

Rules (hlk/CONTRIBUTING.md): Python standard library and unittest only; invented names from common.NAMES; the hidden
test fails on the untouched repo and passes on `solved`; protected paths are files the task must not change.
"""

from hlk.common import NAMES, Instance, Slot, Turn, confirm_slot, hidden_test, py, readme, rng

GROUP, STRESSOR = "naming", "replace with the stressor, fixed before any run"


def make(seed: int) -> Instance:
    r = rng("template", seed)
    repo = r.choice(NAMES)
    files = {"example.py": py("VALUE = 1\n"), "README.md": readme(repo, "An example.")}
    hidden = hidden_test("import example\n\n\nclass Hidden(unittest.TestCase):\n    def test_value(self):\n"
                         "        self.assertEqual(example.VALUE, 2)\n")
    return Instance("template", seed, GROUP, STRESSOR, {repo: files}, {repo: {"example.py": py("VALUE = 2\n")}},
                    {repo: {"test_hidden_hlk.py": hidden}}, {repo: ["README.md"]},
                    [Turn("t1", "In example dot py, set value to two.", "In example.py set VALUE = 2.", "on_start", repo)],
                    [confirm_slot()])

"""spelled-out: a new name given letter by letter, with "snake case", "all caps" or "dunder"."""

from hlk.common import NAMES, Instance, Slot, Turn, confirm_slot, hidden_test, py, readme, rng, say_number, spell

GROUP, STRESSOR = "naming", 'a new name given letter by letter, with "snake case", "all caps", "dunder"'
WORDS = ["quorum", "brine", "quill", "gimbal", "sorrel", "vellum", "wicket", "zephyr", "tansy", "rivet"]


def make(seed: int) -> Instance:
    r = rng("spelled-out", seed)
    repo = r.choice(NAMES)
    a, b = r.sample(WORDS, 2)
    value = r.choice([3, 4, 7, 9, 11])
    style = seed % 3
    if style == 0:
        name, code = f"{a.upper()}_{b.upper()}", f"{a.upper()}_{b.upper()} = {value}\n"
        spoken = (f"In limits dot py, add a constant, all caps, spelled {spell(a)}, then an underscore, then "
                  f"{spell(b)}, set to {say_number(value)}.")
        canonical = f"In limits.py add a constant {name} = {value}."
        check = f"self.assertEqual(limits.{name}, {value})"
    elif style == 1:
        name, code = f"{a}_{b}", f"def {a}_{b}():\n    return {value}\n"
        spoken = (f"In limits dot py, add a function, snake case, spelled {spell(a)}, underscore, {spell(b)}, "
                  f"that takes nothing and returns {say_number(value)}.")
        canonical = f"In limits.py add a function {name}() that returns {value}."
        check = f"self.assertEqual(limits.{name}(), {value})"
    else:
        name, code = f"__{a}__", f"__{a}__ = {value}\n"
        spoken = (f"In limits dot py, add a module level variable, dunder, spelled {spell(a)}, so double underscore "
                  f"on both sides, set to {say_number(value)}.")
        canonical = f"In limits.py add a module-level variable {name} = {value}."
        check = f"self.assertEqual(getattr(limits, \"{name}\"), {value})"
    base = '"""Limits for the service."""\n\nMAX_USERS = 50\n'
    files = {"limits.py": py(base), "README.md": readme(repo, "Service limits.")}
    hidden = hidden_test(f"import limits\n\n\nclass Hidden(unittest.TestCase):\n    def test_name(self):\n        {check}\n\n"
                         "    def test_kept(self):\n        self.assertEqual(limits.MAX_USERS, 50)\n")
    return Instance("spelled-out", seed, GROUP, STRESSOR, {repo: files}, {repo: {"limits.py": py(base + "\n" + code)}},
                    {repo: {"test_hidden_hlk.py": hidden}}, {repo: ["README.md"]},
                    [Turn("t1", spoken, canonical, "on_start", repo)],
                    [Slot("which_symbol", [r"\b(spell|spelling|which name|what name|called|exact name|how do you)\b"],
                          f"It is spelled {spell(a)}" + (f", underscore, {spell(b)}." if style < 2 else ", with double underscores."),
                          f"The name is {name}."),
                     confirm_slot()])

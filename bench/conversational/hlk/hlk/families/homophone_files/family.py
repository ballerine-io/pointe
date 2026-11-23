"""homophone-files: two files whose names sound the same (cash.py and cache.py); the description tells them apart."""

from hlk.common import NAMES, Instance, Slot, Turn, confirm_slot, hidden_test, py, readme, rng, say_number

GROUP, STRESSOR = "naming", "cache.py against cash.py, auth against oath"
PAIRS = [("cash", "cache", "money: limits for cash payments", "caching: entry limits for the in-memory cache",
          "the one about money", "the caching one"),
         ("oath", "auth", "pledges: how many signatures an oath needs", "login: how many attempts before a lockout",
          "the one about pledges", "the login one"),
         ("sail", "sale", "boats: how many sails a boat may carry", "discounts: how many items a sale may cover",
          "the one about boats", "the discount one")]


def make(seed: int) -> Instance:
    r = rng("homophone-files", seed)
    target, twin, about, twin_about, says, twin_says = PAIRS[seed % len(PAIRS)]
    repo = r.choice(NAMES)
    old, new = 10, r.choice([25, 40, 64, 75])
    files = {f"{target}.py": py(f'"""Helpers for {about}."""\n\nLIMIT = {old}\n'),
             f"{twin}.py": py(f'"""Helpers for {twin_about}."""\n\nLIMIT = {old}\n'),
             "README.md": readme(repo, f"`{target}.py` is about {about.split(':')[0]}; `{twin}.py` is about "
                                       f"{twin_about.split(':')[0]}.")}
    hidden = hidden_test(f"import {target}\nimport {twin}\n\n\nclass Hidden(unittest.TestCase):\n"
                         f"    def test_target(self):\n        self.assertEqual({target}.LIMIT, {new})\n\n"
                         f"    def test_twin(self):\n        self.assertEqual({twin}.LIMIT, {old})\n")
    spoken = (f"In {target} dot py, {says}, not {twin_says}, change the limit from ten to {say_number(new)}.")
    canonical = f"In {target}.py ({about.split(':')[0]}, not {twin}.py), change LIMIT from {old} to {new}."
    return Instance("homophone-files", seed, GROUP, STRESSOR, {repo: files},
                    {repo: {f"{target}.py": py(f'"""Helpers for {about}."""\n\nLIMIT = {new}\n')}},
                    {repo: {"test_hidden_hlk.py": hidden}}, {repo: [f"{twin}.py"]},
                    [Turn("t1", spoken, canonical, "on_start", repo)],
                    [Slot("which_file", [r"\b(which|both|did you mean)\b", twin, target],
                          f"{says.capitalize()}: {target}, spelled {', '.join(target.upper())}.",
                          f"{target}.py, {about.split(':')[0]}."),
                     confirm_slot()])

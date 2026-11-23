"""dictated-literals: three spoken values: a number with a unit, a version string and a hex colour."""

from hlk.common import NAMES, Instance, Slot, Turn, confirm_slot, hidden_test, py, readme, rng, say_number

GROUP, STRESSOR = "naming", "three spoken values: a number with a unit, a version string, a hex colour"
TIMEOUTS = [(2500, "two and a half seconds"), (1500, "one and a half seconds"), (4000, "four seconds"),
            (750, "three quarters of a second")]
VERSIONS = [("3.12.0", "three point twelve point zero"), ("2.7.4", "two point seven point four"),
            ("5.0.11", "five point zero point eleven")]
COLOURS = [("#ff8800", "f f eight eight zero zero"), ("#1e90ff", "one e nine zero f f"),
           ("#c0ffee", "c zero f f e e")]


def make(seed: int) -> Instance:
    r = rng("dictated-literals", seed)
    repo = r.choice(NAMES)
    ms, ms_said = TIMEOUTS[(seed + r.randrange(4)) % 4]
    ver, ver_said = VERSIONS[seed % 3]
    col, col_said = COLOURS[(seed + 1) % 3]
    base = 'TIMEOUT_MS = 1000\nVERSION = "1.0.0"\nACCENT = "#000000"\n'
    files = {"config.py": py('"""Settings for the service."""\n\n' + base), "README.md": readme(repo, "Service settings.")}
    hidden = hidden_test("import config\n\n\nclass Hidden(unittest.TestCase):\n"
                         f"    def test_timeout(self):\n        self.assertEqual(config.TIMEOUT_MS, {ms})\n\n"
                         f"    def test_version(self):\n        self.assertEqual(config.VERSION, \"{ver}\")\n\n"
                         f"    def test_accent(self):\n        self.assertEqual(config.ACCENT.lower(), \"{col}\")\n")
    spoken = (f"In config dot py, set the timeout to {ms_said}, it is stored in milliseconds, set the version to "
              f"{ver_said}, and set the accent colour to hex {col_said}.")
    canonical = f'In config.py set TIMEOUT_MS = {ms}, VERSION = "{ver}" and ACCENT = "{col}".'
    solved = py('"""Settings for the service."""\n\n' + f'TIMEOUT_MS = {ms}\nVERSION = "{ver}"\nACCENT = "{col}"\n')
    return Instance("dictated-literals", seed, GROUP, STRESSOR, {repo: files}, {repo: {"config.py": solved}},
                    {repo: {"test_hidden_hlk.py": hidden}}, {repo: ["README.md"]},
                    [Turn("t1", spoken, canonical, "on_start", repo)],
                    [Slot("which_value", [r"\b(millisecond|format|hex|which value|exact|string|confirm the)\b"],
                          f"The timeout is {say_number(ms)} milliseconds, the version is {ver_said}, and the colour "
                          f"is hash {col_said}.", f'TIMEOUT_MS = {ms}, VERSION = "{ver}", ACCENT = "{col}".'),
                     confirm_slot()])

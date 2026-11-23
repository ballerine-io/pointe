"""twin-symbols: fix the snake_case function while its camelCase twin sits in a sibling file and must not change."""

from hlk.common import NAMES, Instance, Slot, Turn, confirm_slot, hidden_test, py, readme, rng, say_number

GROUP, STRESSOR = "naming", "fix parse_retry_after while parseRetryAfter exists in a sibling file"
PAIRS = [("parse_retry_after", "parseRetryAfter", "retry", "parse retry after", "a Retry-After value"),
         ("read_cache_ttl", "readCacheTtl", "ttl", "read cache t t l", "a cache lifetime"),
         ("load_page_size", "loadPageSize", "paging", "load page size", "a page size setting")]


def make(seed: int) -> Instance:
    r = rng("twin-symbols", seed)
    snake, camel, module, spoken_name, what = PAIRS[seed % len(PAIRS)]
    repo = r.choice(NAMES)
    n = r.choice([45, 90, 120, 300, 600])
    m = r.choice([7, 12, 30])
    body = (f'def {snake}(value):\n    """Seconds, from {what} such as "{m}"."""\n    return int(value)\n')
    twin = (f'def {camel}(value):\n    """The legacy camelCase twin, kept for old callers. It must not change."""\n'
            f'    return int(value)\n')
    fixed = (f'def {snake}(value):\n    """Seconds, from {what} such as "{m}" or "{n}s"."""\n'
             f'    return int(str(value).strip().removesuffix("s"))\n')
    files = {f"{module}.py": py(body), "compat.py": py(twin),
             f"test_{module}.py": py(f"import unittest\n\nfrom {module} import {snake}\n\n\nclass T(unittest.TestCase):\n"
                                     f"    def test_plain(self):\n        self.assertEqual({snake}(\"{m}\"), {m})\n"),
             "README.md": readme(repo, f"Small helpers for {what}s.")}
    hidden = hidden_test(f"from {module} import {snake}\n\n\nclass Hidden(unittest.TestCase):\n"
                         f"    def test_suffix(self):\n        self.assertEqual({snake}(\"{n}s\"), {n})\n\n"
                         f"    def test_plain(self):\n        self.assertEqual({snake}(\"{m}\"), {m})\n")
    spoken = (f"In {module} dot py, fix {spoken_name}, the snake case one, so it also accepts a value that ends in s, "
              f"like {say_number(n)} s, which should give {say_number(n)}. Don't touch the camel case version in compat dot py.")
    canonical = (f'In {module}.py, fix {snake} so it also accepts a value with a trailing s, like "{n}s" (returns {n}). '
                 f"Do not change {camel} in compat.py.")
    return Instance("twin-symbols", seed, GROUP, STRESSOR, {repo: files}, {repo: {f"{module}.py": py(fixed)}},
                    {repo: {"test_hidden_hlk.py": hidden}}, {repo: ["compat.py", f"test_{module}.py"]},
                    [Turn("t1", spoken, canonical, "on_start", repo)],
                    [Slot("which_symbol", [r"\b(which|camel|both|compat)\b", camel.lower()],
                          f"Only the snake case one, {spoken_name}, in {module} dot py.", f"Only {snake} in {module}.py."),
                     confirm_slot()])

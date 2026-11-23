"""two-repo-handoff: a field renamed in one repo and its consumer in another, two sessions addressed by name."""

from hlk.common import NAMES, Instance, Slot, Turn, confirm_slot, hidden_test, py, readme, rng

GROUP, STRESSOR = "control", "a field renamed in one repo and its consumer in another, two sessions by name"
FIELDS = [("cust_id", "customer_id", "cust id", "customer underscore id"),
          ("qty", "quantity", "q t y", "quantity"),
          ("ts", "timestamp", "t s", "timestamp")]


def make(seed: int) -> Instance:
    r = rng("two-repo-handoff", seed)
    old, new, old_s, new_s = FIELDS[seed % 3]
    a, b = r.sample(NAMES, 2)
    src = lambda f: py(f"def make_record(key, amount):\n    return {{\"{f}\": key, \"amount\": amount}}\n")
    dst = lambda f: py(f"def owner_of(record):\n    return record[\"{f}\"]\n")
    repos = {a: {"records.py": src(old), "README.md": readme(a, f"Produces records that {b} reads.")},
             b: {"reader.py": dst(old), "README.md": readme(b, f"Reads the records {a} produces.")}}
    hid_a = hidden_test(f"from records import make_record\n\n\nclass Hidden(unittest.TestCase):\n"
                        f"    def test_field(self):\n        rec = make_record(7, 1.5)\n        self.assertEqual(rec[\"{new}\"], 7)\n"
                        f"        self.assertNotIn(\"{old}\", rec)\n")
    hid_b = hidden_test(f"from reader import owner_of\n\n\nclass Hidden(unittest.TestCase):\n"
                        f"    def test_reads_new(self):\n        self.assertEqual(owner_of({{\"{new}\": 5, \"amount\": 1}}), 5)\n\n"
                        f"    def test_end_to_end(self):\n        from records import make_record\n"
                        f"        self.assertEqual(owner_of(make_record(9, 2.0)), 9)\n")
    t1s = f"Tell {a} to rename the record field {old_s} to {new_s} in make record."
    t1c = f"In records.py, rename the record field {old} to {new} in make_record."
    t2s = f"Now tell {b} to read {new_s} instead of {old_s} in reader dot py."
    t2c = f"In reader.py, read {new} instead of {old}."
    return Instance("two-repo-handoff", seed, GROUP, STRESSOR, repos,
                    {a: {"records.py": src(new)}, b: {"reader.py": dst(new)}},
                    {a: {"test_hidden_hlk.py": hid_a}, b: {"test_hidden_hlk.py": hid_b}},
                    {a: ["README.md"], b: ["README.md"]},
                    [Turn("t1", t1s, t1c, "on_start", a), Turn("t2", t2s, t2c, "on_idle", b)],
                    [Slot("which_session", [r"\b(which session|which one|which repo|which project|where)\b", f"{a}.*{b}|{b}.*{a}"],
                          f"{a.capitalize()} makes the records, {b} reads them.", f"{a}: records.py; {b}: reader.py."),
                     confirm_slot()],
                    needs=("text_in", "sessions"))

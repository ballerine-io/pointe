import os
import unittest

import marlstone


def setUpModule():
    # The benchmark's marker: the file exists once these tests have run.
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".tests_ran"), "w") as f:
        f.write("ran\n")


class TotalTest(unittest.TestCase):
    def test_total(self):
        self.assertEqual(marlstone.total([("bolt", 3), ("nut", 4)]), 7)

    def test_low_stock(self):
        self.assertEqual(marlstone.low_stock([("bolt", 3), ("nut", 9)]), ["bolt"])


if __name__ == "__main__":
    unittest.main()

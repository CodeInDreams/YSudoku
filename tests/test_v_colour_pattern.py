import unittest

from ysudoku.v_colour_pattern import target_exclusions


class VPatternTest(unittest.TestCase):
    def test_r2c3_pattern(self):
        # R1C4/R1C5 and R3C2/R3C3, all knight peers of R2C3.
        pair_a = [3, 4]
        pair_b = [19, 20]
        peers = {3, 4, 19, 20}
        self.assertEqual(target_exclusions(11, pair_a, pair_b, peers), {1, 2, 3, 4})

    def test_missing_peer_is_not_excluded(self):
        self.assertEqual(target_exclusions(11, [3, 4], [19, 20], {3, 4, 19}), set())

    def test_shared_colour_is_not_two_classes(self):
        self.assertEqual(target_exclusions(11, [3, 4], [3, 20], {3, 4, 20}), set())


if __name__ == "__main__":
    unittest.main()

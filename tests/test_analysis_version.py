import unittest

from ysudoku.pipeline import ANALYSIS_VERSION


class AnalysisVersionTest(unittest.TestCase):
    def test_version_is_positive(self):
        self.assertGreaterEqual(ANALYSIS_VERSION, 1)


if __name__ == "__main__":
    unittest.main()

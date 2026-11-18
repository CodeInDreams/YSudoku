import unittest

from ysudoku.state import Contradiction, Reason, State, Unit


class StateEventTest(unittest.TestCase):
    def test_last_elimination_is_recorded(self):
        st = State(9, [Unit("row", 0, list(range(9)))], record=True)
        st.dom[0] = 0b10
        st.begin()
        with self.assertRaises(Contradiction):
            st.elim(0, 2, Reason("test"))
        self.assertEqual([(e.kind, e.cell, e.value) for e in st.events],
                         [("elim", 0, 2)])


if __name__ == "__main__":
    unittest.main()

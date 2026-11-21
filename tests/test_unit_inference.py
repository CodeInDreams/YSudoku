import unittest

from ysudoku.constraints_ir import AllDifferent
from ysudoku.constraints import IRSupport
from ysudoku.model import parse_puzzle
from ysudoku.rules import build_inventory, compile_spec
from ysudoku.solve import Solver
from ysudoku.state import bits
from ysudoku.techniques import hidden_subset4, locked_candidates


def _custom(cells, op="all_different"):
    return {
        "kind": "custom",
        "cells": cells,
        "predicate": {"op": op, "args": [{"op": "var", "index": i} for i in range(len(cells))]},
    }


class UnitInferenceTest(unittest.TestCase):
    def test_split_line_can_lock_a_digit_and_form_hidden_triple(self):
        puzzle = parse_puzzle({
            "cells": [[{} for _ in range(9)] for _ in range(9)],
            "lines": [{"wayPoints": [[3.5, 4.5], [2.5, 5.5], [1.5, 5.5],
                                     [1.5, 7.5], [2.5, 8.5], [5.5, 8.5]]}],
        })
        line = ["R4C5", "R3C6", "R2C6", "R2C7", "R2C8", "R3C9",
                "R4C9", "R5C9", "R6C9"]
        rules = compile_spec(puzzle, build_inventory(puzzle), {"rules": [
            _custom(line[:6]), _custom(line[3:]), _custom(line[:3] + line[6:]),
        ]})
        solver = Solver(puzzle, rules)
        state = solver.state
        self.assertEqual(solver.units[-1].kind, "line")
        r4c5, r3c6, r2c6 = 31, 23, 14
        for cell in puzzle.box_regions()[1]:
            if cell not in (r3c6, r2c6):
                state.elim(cell, 2)
        for cell in puzzle.lines[0].cells:
            if cell not in (r4c5, r3c6):
                state.elim(cell, 4)
            if cell not in (r4c5, r3c6, r2c6):
                state.elim(cell, 8)

        events = locked_candidates(state)
        self.assertTrue(any(e.cell == r4c5 and e.value == 2 for e in events))
        self.assertTrue(any(e.reason.data["target_unit"] == "第1条线" for e in events))
        hidden_subset4(state)
        self.assertEqual([list(bits(state.dom[c])) for c in (r2c6, r3c6, r4c5)],
                         [[2, 8], [2, 4, 8], [4, 8]])

    def test_only_proven_pairs_complete_a_unit(self):
        puzzle = parse_puzzle({"cells": [[{} for _ in range(4)] for _ in range(4)]})
        conditional = _custom(["R3C3", "R4C4"])
        conditional["predicate"] = {
            "op": "or", "args": [conditional["predicate"], {"op": "const", "value": 1}],
        }
        rules = compile_spec(puzzle, [], {"rules": [
            _custom(["R1C1", "R2C2", "R3C3"]), _custom(["R1C1", "R2C2", "R4C4"]),
            conditional,
        ]})
        self.assertFalse(any(unit.kind == "distinct" for unit in Solver(puzzle, rules).units))
        rules.constraints.append(IRSupport([AllDifferent((10, 15))]))
        self.assertEqual(Solver(puzzle, rules).units[-1].cells, [0, 5, 10, 15])

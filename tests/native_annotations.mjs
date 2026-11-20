import assert from "node:assert/strict";
import { annotationChanges, nativeAnnotations } from "../web/src/lib/nativeAnnotations.js";

const undecided = nativeAnnotations({
  colours: [{ region: true, cells: [8], colour: 3 }],
  region_options: [{ cells: [8], colours: [4, 5] }],
  region_edges: [
    { cells: [8, 7], fixed: false },
    { cells: [8, 17], fixed: false },
    { cells: [8, 9], fixed: true }, // End of one row and start of the next.
  ],
}, 9);
assert.deepEqual([...undecided.values()].filter(a => a.op === "colour").map(a => a.index), [4, 5]);
assert.equal(undecided.size, 4);

const resolved = nativeAnnotations({
  colours: [{ region: true, cells: [8], colour: 4 }],
  region_edges: [{ cells: [7, 8], fixed: true }],
}, 9);
assert.deepEqual(annotationChanges(undecided, resolved), [
  { op: "colour", cell: 8, index: 5, enabled: false },
  { op: "pen", cells: [8, 17], index: 6, enabled: false },
  { op: "pen", cells: [7, 8], index: 4, enabled: true },
]);

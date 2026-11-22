import { annotationChanges, nativeAnnotations } from "./nativeAnnotations.js";

function digitsOf(mask, n) {
  const out = [];
  for (let v = 1; v <= n; v++) if (mask & (1 << (v - 1))) out.push(v);
  return out;
}

export function buildStepActions(analysis) {
  const n = analysis.puzzle.size;
  const steps = [];
  let state = new Map();
  const marked = new Set();
  const values = new Map();
  let annotations = new Map();
  (analysis.puzzle?.givens || []).forEach((value, cell) => { if (value) values.set(cell, value); });
  let inBranch = false;
  let branchBase = null;
  let branchCell = null;
  const MAX_POSITIVE = 5;
  const digits = (mask) => digitsOf(mask || 0, n);
  const same = (a, b) => a.size === b.size && [...a].every((d) => b.has(d));

  for (let stepIndex = 0; stepIndex < analysis.steps.length; stepIndex++) {
    const step = analysis.steps[stepIndex];
    const actions = [];
    if (step.branch && !step.revert && !inBranch) {
      inBranch = true;
      branchCell = (step.events || []).find((ev) => ev.kind === "place")?.cell ?? null;
      branchBase = { state: new Map(state), marked: new Set(marked), values: new Map(values) };
      actions.push({ op: "snapshot_start", cell: branchCell });
    }
    if (step.revert) {
      actions.push({ op: "undo_to_snapshot", cell: branchCell });
      if (branchBase) {
        state = new Map(branchBase.state);
        marked.clear();
        branchBase.marked.forEach((cell) => marked.add(cell));
        values.clear();
        branchBase.values.forEach((value, cell) => values.set(cell, value));
      }
      inBranch = false;
      branchBase = null;
      branchCell = null;
      // Previously saved rollback steps may have no conclusion events.
      if (!step.events?.length) {
        steps.push(actions);
        continue;
      }
    }
    const pre = step.pre_dom || [];
    const elimsByCell = new Map();
    const placeByCell = new Map();
    for (const ev of step.events || []) {
      if (ev.kind === "elim") {
        if (!elimsByCell.has(ev.cell)) elimsByCell.set(ev.cell, new Set());
        elimsByCell.get(ev.cell).add(ev.value);
      } else if (ev.kind === "place") {
        placeByCell.set(ev.cell, ev.value);
      }
    }
    const affected = new Set([...elimsByCell.keys(), ...placeByCell.keys()]);
    const nextState = new Map();

    const update = (cell, desired, place) => {
      const current = state.get(cell);
      const isMarked = marked.has(cell);
      if (place !== undefined) {
        if (isMarked || current?.size) actions.push({ op: "candidates", cell, digits: [] });
        actions.push({ op: "place", cell, value: place });
        values.set(cell, place);
        marked.delete(cell);
        return;
      }
      if (desired.size === 1) {
        if (!current || !isMarked || !same(current, desired)) {
          actions.push({ op: "candidates", cell, digits: [...desired] });
          marked.add(cell);
        }
        nextState.set(cell, desired);
        return;
      }
      if (desired.size === 0) {
        if (isMarked || current?.size) actions.push({ op: "candidates", cell, digits: [] });
        marked.delete(cell);
        return;
      }
      if (desired.size > MAX_POSITIVE) {
        if (isMarked) actions.push({ op: "candidates", cell, digits: [] });
        marked.delete(cell);
        nextState.set(cell, desired);
        return;
      }
      if (!current || !isMarked || !same(current, desired)) {
        actions.push({ op: "candidates", cell, digits: [...desired] });
        marked.add(cell);
      }
      nextState.set(cell, desired);
    };

    const refreshCells = step.technique === "candidate_map"
      ? Array.from({ length: n * n }, (_, i) => i)
      : [...state.keys()];
    for (const cell of refreshCells) {
      if (!affected.has(cell)) update(cell, new Set(digits(pre[cell])));
    }
    for (const cell of affected) {
      const desired = new Set(digits(pre[cell]));
      for (const value of elimsByCell.get(cell) || []) desired.delete(value);
      update(cell, desired, placeByCell.get(cell));
    }
    state = nextState;
    if (!inBranch) {
      const next = nativeAnnotations(step.visual || {}, n);
      actions.push(...annotationChanges(annotations, next));
      annotations = next;
    }
    steps.push(actions);
  }
  return steps;
}


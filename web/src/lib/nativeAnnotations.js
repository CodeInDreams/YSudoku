const PEN_COLOURS = { confirmed: 1, candidate: 5, excluded: 4 };

// Each visual describes the annotations for one frame. Send only changes
// from the previous frame so obsolete colours and edges can be removed.
export function nativeAnnotations(visual, n) {
  const annotations = new Map();
  const choices = new Map();
  for (const option of visual.region_options || []) {
    for (const cell of option.cells) choices.set(cell, option.colours);
  }

  const colours = new Map();
  function addColour(cell, index) {
    if (!colours.has(cell)) colours.set(cell, new Set());
    const set = colours.get(cell);
    if (set.size < 4) set.add(index);
  }
  for (const [cell, options] of choices) {
    for (const index of options) addColour(cell, index);
  }
  for (const group of visual.colours || []) {
    for (const cell of group.cells) {
      if (!group.region || !choices.has(cell)) addColour(cell, group.colour);
    }
  }
  for (const [cell, indices] of colours) {
    for (const index of indices) {
      annotations.set(`colour:${cell}:${index}`, { op: "colour", cell, index });
    }
  }

  for (const edge of visual.region_edges || []) {
    const [a, b] = [...edge.cells].sort((x, y) => x - y);
    if (!(b - a === n || (b - a === 1 && a % n !== n - 1))) continue;
    const status = edge.status ?? (edge.fixed ? "confirmed" : "candidate");
    annotations.set(`edge:${a}:${b}`, { op: "pen", cells: [a, b], index: PEN_COLOURS[status] });
  }
  return annotations;
}

export function annotationChanges(previous, next) {
  const actions = [];
  for (const [key, action] of previous) {
    if (!next.has(key)) actions.push({ ...action, enabled: false });
  }
  for (const [key, action] of next) {
    if (previous.get(key)?.index !== action.index) actions.push({ ...action, enabled: true });
  }
  return actions;
}

#!/usr/bin/env node
/**
 * Read-only SudokuPad mirror for the web UI.
 *
 * A long-lived Chromium opens the puzzle.  The UI receives a cropped PNG of the
 * board only, so SudokuPad's own chrome is never shown.  Commands are plain
 * HTTP; the page itself is never exposed to the browser client.
 */
import http from "http";
import fs from "fs";
import path from "path";
import { chromium } from "playwright";

const PORT = Number(process.env.YSUDOKU_LIVE_PORT || 8791);
const IDLE_MS = Math.max(0, Number(process.env.YSUDOKU_LIVE_IDLE_SECONDS || 600)) * 1000;
const MIN_IDLE = Math.max(0, Number(process.env.YSUDOKU_LIVE_MIN_IDLE || 0));
const executablePath = process.env.YSUDOKU_CHROME || undefined;

let browser = null;
let context = null;
let page = null;
let puzzleUrl = "";
let board = null;
let lastRect = null;

let latest = null;
let work = Promise.resolve();
let ledger = new Map();  // cell -> { digit: number, corners: Set<number> }
let valueState = new Map();  // cell -> placed digit
let markState = new Map();   // cell -> Set of Centre candidates
let branchSnapshot = null;
let lastUsed = Date.now();

function touch() { lastUsed = Date.now(); }

async function closeBrowser() {
  await context?.close().catch(() => {});
  context = null;
  page = null;
  await browser?.close().catch(() => {});
  browser = null;
  board = null;
  latest = null;
  console.log(JSON.stringify({ ok: true, event: "browser-recycled" }));
}

const CHECK_MS = Math.max(1000, Math.min(30000, IDLE_MS / 4 || 30000));
setInterval(async () => {
  if (!browser || MIN_IDLE > 0 || IDLE_MS === 0) return;
  if (Date.now() - lastUsed > IDLE_MS) await closeBrowser();
}, CHECK_MS).unref();

async function ensurePage() {
  if (!browser) {
    browser = await chromium.launch({
      headless: true,
      executablePath,
      args: ["--no-sandbox", "--disable-dev-shm-usage"],
    });
  }
  if (!context || !page || page.isClosed()) {
    context = await browser.newContext({
      viewport: { width: 1200, height: 1000 },
      colorScheme: "light",
    });
    await context.addInitScript(() => {
      const settings = {
        hidesvenpeek: true, hidesupportlinks: true, showplayinsudokupad: false,
        largedigits: false, toolpen: true, toolletter: true, flipkeypad: false,
        hidetimer: true, dashedgrid: false, hidecolours: false, showseen: false,
        checkonfinish: false, pauseonstart: false, selection: "default",
        multicolour: true, outlinesondigits: false, outlinesonlines: false,
        hidesolved: true, autocheck: true, conflictchecker: "on",
        checkpencilmarks: false, repeatundodelay: 700, repeatundointerval: 100,
        toolletter_mode: "altletter", marksolveddigits: "off", uitheme: "monolight",
        cellpaste: false, puzzleevents: "off",
      };
      try {
        const current = JSON.parse(localStorage.getItem("svencodes_settings") || "{}");
        localStorage.setItem("svencodes_settings", JSON.stringify({ ...current, ...settings }));
      } catch {
        localStorage.setItem("svencodes_settings", JSON.stringify(settings));
      }
    });
    page = await context.newPage();
    await page.emulateMedia({ colorScheme: "light" });
  }
  touch();
  return page;
}

async function open(url, logicalN = 0, crop = false) {
  await ensurePage();
  ledger = new Map();
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForSelector("svg.boardsvg", { timeout: 15000 }).catch(() => {});
  // The start overlay darkens the board; click it as soon as it appears,
  // otherwise a cropped screenshot captures the dimmed start screen.
  let started = false;
  try {
    const start = page.getByRole("button", { name: /Start Puzzle|Resume Puzzle|Continue/i });
    await start.first().waitFor({ state: "visible", timeout: 10000 });
    await start.first().click();
    started = true;
    await page.waitForTimeout(300);
    if (await start.first().isVisible().catch(() => false)) {
      await start.first().click().catch(() => {});
      await page.waitForTimeout(300);
    }
  } catch { /* puzzle already started or a resume overlay */ }
  await page.waitForSelector("svg.boardsvg", { timeout: 30000 });
  let lastView = "";
  for (let i = 0; i < 40; i++) {
    const current = await page.locator("svg.boardsvg").getAttribute("viewBox");
    if (current && current === lastView) break;
    lastView = current;
    await page.waitForTimeout(50);
  }
  if (!started) {
    // Some reopen paths show a play/resume overlay instead of "Start Puzzle";
    // clicking the board centre dismisses it (or merely selects a cell).
    const b = await page.locator("svg.boardsvg").boundingBox();
    if (b) {
      await page.mouse.click(b.x + b.width / 2, b.y + b.height / 2);
      await page.waitForTimeout(300);
    }
  }
  const box = await page.locator("svg.boardsvg").boundingBox();
  if (!box) throw new Error("board not visible");
  const { units, x, y, scaleX, scaleY } = await page.locator("svg.boardsvg").evaluate(svg => {
    const transform = svg.getScreenCTM();
    return {
      units: svg.viewBox.baseVal.width,
      x: transform.e,
      y: transform.f,
      scaleX: transform.a,
      scaleY: transform.d,
    };
  });
  const n = logicalN || Math.max(1, Math.round((units - 32) / 64));
  const grid = { x, y, width: n * 64 * scaleX, height: n * 64 * scaleY };
  // The outer strokes straddle the grid edge. Keep room on all four sides and
  // use the same integer pixel bounds for the PNG and its overlay coordinates.
  const padX = Math.max(2, 6 * scaleX);
  const padY = Math.max(2, 6 * scaleY);
  const left = Math.floor(crop ? Math.max(box.x, grid.x - padX) : box.x);
  const top = Math.floor(crop ? Math.max(box.y, grid.y - padY) : box.y);
  const right = Math.ceil(crop ? Math.min(box.x + box.width, grid.x + grid.width + padX) : box.x + box.width);
  const bottom = Math.ceil(crop ? Math.min(box.y + box.height, grid.y + grid.height + padY) : box.y + box.height);
  const capture = { x: left, y: top, width: right - left, height: bottom - top };
  const rect = { x: grid.x - left, y: grid.y - top, width: grid.width, height: grid.height,
                 imageWidth: capture.width, imageHeight: capture.height };
  board = { box, grid, capture, rect, n };
  lastRect = rect;

  const initial = await readBoard();
  valueState = new Map();
  markState = new Map();
  initial.values.forEach((value, cell) => { if (value) valueState.set(cell, value); });
  initial.corners.forEach((digits, cell) => markState.set(cell, new Set(digits)));
  puzzleUrl = url;
}

async function shot() {
  latest = await page.screenshot({
    clip: board.capture,
    type: "png",
  });
  return latest;
}

function center(r, c) {
  const { grid, n } = board;
  return [grid.x + (c + 0.5) * grid.width / n, grid.y + (r + 0.5) * grid.height / n];
}

async function cellPoint(r, c) {
  return center(r, c);
}

async function readBoard() {
  return await page.evaluate((n) => {
    const values = new Array(n * n).fill(0);
    const centre = Array.from({ length: n * n }, () => []);
    const corners = Array.from({ length: n * n }, () => []);
    const colors = Array.from({ length: n * n }, () => []);
    const pen = Array.from({ length: n * n }, () => []);
    const errors = Array.from({ length: n * n }, () => []);
    const cellAt = (x, y) => {
      if (!Number.isFinite(x) || !Number.isFinite(y)) return -1;
      let r, c;
      if (Math.abs(x % 64) < 1 && Math.abs(y % 64) < 1) {
        c = Math.round(x / 64); r = Math.round(y / 64);
      } else {
        c = Math.floor((x - 32) / 64); r = Math.floor((y - 32) / 64);
      }
      if (r < 0 || r >= n || c < 0 || c >= n) return -1;
      return r * n + c;
    };
    for (const t of document.querySelectorAll("#cell-values text")) {
      const cell = cellAt(parseFloat(t.getAttribute("x")), parseFloat(t.getAttribute("y")));
      if (cell >= 0) values[cell] = Number(t.textContent);
    }
    for (const t of document.querySelectorAll("#cell-candidates text")) {
      const cell = cellAt(parseFloat(t.getAttribute("x")), parseFloat(t.getAttribute("y")));
      if (cell < 0) continue;
      for (const span of t.querySelectorAll("tspan[data-val]")) {
        const v = Number(span.getAttribute("data-val"));
        if (v) centre[cell].push(v);
      }
    }
    for (const t of document.querySelectorAll("#cell-pencilmarks text[data-val]")) {
      const cell = cellAt(parseFloat(t.getAttribute("x")), parseFloat(t.getAttribute("y")));
      const v = Number(t.getAttribute("data-val"));
      if (cell >= 0 && v) corners[cell].push(v);
    }
    const colorNode = document.getElementById("cell-colors");
    if (colorNode) {
      for (const el of colorNode.querySelectorAll("rect, path, polygon, circle")) {
        let x = parseFloat(el.getAttribute("x"));
        let y = parseFloat(el.getAttribute("y"));
        if (!Number.isFinite(x) || !Number.isFinite(y)) {
          const box = el.getBBox?.();
          if (box) { x = box.x; y = box.y; }
        }
        const cell = cellAt(x, y);
        if (cell < 0) continue;
        colors[cell].push({
          fill: el.getAttribute("fill") || getComputedStyle(el).fill,
          stroke: el.getAttribute("stroke") || null,
        });
      }
    }
    const penNode = document.getElementById("cell-pen");
    if (penNode) {
      for (const el of penNode.querySelectorAll("path, line, polyline, circle, rect")) {
        const box = el.getBBox?.();
        if (!box) continue;
        const cell = cellAt(box.x + box.width / 2, box.y + box.height / 2);
        if (cell < 0) continue;
        pen[cell].push({ tag: el.tagName, d: el.getAttribute("d") || "", fill: el.getAttribute("fill") || null });
      }
    }
    const errorNode = document.getElementById("cell-errors");
    if (errorNode) {
      for (const el of errorNode.querySelectorAll("*")) {
        let x = parseFloat(el.getAttribute("x"));
        let y = parseFloat(el.getAttribute("y"));
        if (!Number.isFinite(x) || !Number.isFinite(y)) {
          const box = el.getBBox?.();
          if (box) { x = box.x; y = box.y; }
        }
        const cell = cellAt(x, y);
        if (cell >= 0) errors[cell].push(el.tagName);
      }
    }
    const state = Array.from({ length: n * n }, (_, cell) => ({
      value: values[cell] || 0,
      centre: [...new Set(centre[cell])].sort((a, b) => a - b),
      corners: [...new Set(corners[cell])].sort((a, b) => a - b),
      colors: colors[cell],
      pen: pen[cell],
      errors: errors[cell],
    }));
    return {
      values,
      corners: centre,
      centre,
      pencilmarks: corners,
      colors,
      pen,
      errors,
      state,
    };
  }, board.n);
}

async function selectTool(id) {
  await page.click(`#${id}`, { force: true }).catch(() => {});
}

async function apply(digits, corners, reset, pen) {
  if (!page || !puzzleUrl) throw new Error("no puzzle");
  const digitList = digits || [];
  const cornerList = corners || [];
  const hasWork = digitList.length || cornerList.length;
  if (!reset && !hasWork && latest) return latest;
  if (reset) {
    await open(puzzleUrl);
    ledger = new Map();
  }

  const state = await readBoard();
  const clickCell = async (cell) => {
    const r = Math.floor(cell / board.n);
    const c = cell % board.n;
    const [x, y] = await cellPoint(r, c);
    await page.mouse.click(x, y);
  };

  // always type digits with the Digit tool, never whatever dial was left over
  await page.click("#control-normal").catch(() => {});
  for (const [cell, value] of digitList) {
    if (state.values[cell] === Number(value)) continue;
    await clickCell(cell);
    await page.keyboard.type(String(value));
    state.values[cell] = Number(value);
    state.corners[cell] = [];
    await page.waitForTimeout(35);
  }

  const target = new Map();
  for (const [cell, list] of cornerList) {
    const set = new Set((list || []).map(Number));
    if (set.size) target.set(cell, set);
  }
  await page.click("#control-centre").catch(() => {});
  for (const [cell, wanted] of target) {
    if (state.values[cell]) continue;  // solved cells keep their digit
    const current = new Set(state.corners[cell] || []);
    if (current.size === wanted.size && [...wanted].every((d) => current.has(d))) continue;
    await clickCell(cell);
    // Toggle old centre marks off instead of Delete: Delete would clear the
    // whole cell when the dial has no marks.
    for (const digit of current) {
      await page.keyboard.type(String(digit));
      await page.waitForTimeout(12);
    }
    for (const digit of wanted) {
      await page.keyboard.type(String(digit));
      await page.waitForTimeout(18);
    }
    state.corners[cell] = [...wanted];
  }
  for (let cell = 0; cell < board.n * board.n; cell++) {
    if (target.has(cell) || state.values[cell]) continue;
    if (!(state.corners[cell] || []).length) continue;
    await clickCell(cell);
    for (const digit of state.corners[cell] || []) {
      await page.keyboard.type(String(digit));
      await page.waitForTimeout(12);
    }
    state.corners[cell] = [];
  }
  await page.click("#control-normal").catch(() => {});
  if (pen && pen.length) {
    // Native pen layer for this step only: clear it, then draw with the pen
    // tool (circle on a centre, drag between two centres for a line).
    await page.evaluate(() => {
      const layer = document.querySelector("#cell-pen");
      if (layer) layer.innerHTML = "";
    });
    await page.click("#control-pen").catch(() => {});
    for (const action of pen) {
      const cells = action.cells || [];
      if (action.op === "circle" && cells.length) {
        const r = Math.floor(cells[0] / board.n);
        const c = cells[0] % board.n;
        const [x, y] = await cellPoint(r, c);
        await page.mouse.click(x, y);
      } else if (action.op === "connect" && cells.length >= 2) {
        const [r1, c1] = [Math.floor(cells[0] / board.n), cells[0] % board.n];
        const [r2, c2] = [Math.floor(cells[1] / board.n), cells[1] % board.n];
        const [x1, y1] = center(r1, c1);
        const [x2, y2] = center(r2, c2);
        await page.mouse.move(x1, y1);
        await page.mouse.down();
        await page.mouse.move(x2, y2, { steps: 6 });
        await page.mouse.up();
      }
      await page.waitForTimeout(30);
    }
    await page.click("#control-normal").catch(() => {});
  }
  await page.waitForTimeout(120);
  return shot();
}

async function useTool(id) {
  for (let attempt = 0; attempt < 4; attempt++) {
    const ok = await page.evaluate((toolId) =>
      Boolean(document.getElementById(toolId)?.classList.contains("selected")), id).catch(() => false);
    if (ok) return true;
    const locator = page.locator(`#${id}`);
    const box = await locator.boundingBox().catch(() => null);
    if (box) {
      await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2).catch(() => {});
    } else {
      await page.click(`#${id}`, { force: true }).catch(() => {});
    }
    await page.waitForTimeout(90);
  }
  return false;
}

async function clearSelection() {
  await page.keyboard.press("Escape").catch(() => {});
  await page.evaluate(() => {
    const select = document.getElementById("control-select");
    if (select && /selected/.test(select.className)) select.click();
  }).catch(() => {});
  if (board) {
    const viewport = page.viewportSize() || { width: 1200, height: 900 };
    const x = board.grid.x + board.grid.width / 2;
    const y = Math.min(viewport.height - 4, board.box.y + board.box.height + 24);
    await page.mouse.click(x, y).catch(() => {});
  }
  await page.waitForTimeout(15);
}

function cellEqual(a, b) {
  if (!a || !b) return false;
  return JSON.stringify(a) === JSON.stringify(b);
}

function boardEqual(a, b) {
  if (!a || !b) return false;
  if (a.state && b.state) return JSON.stringify(a.state) === JSON.stringify(b.state);
  return false;
}

// Colour keys from SudokuPad's first and second native palette pages.
// The solver's first six colour IDs are ordered blue, green, yellow,
// orange, red and purple. The transparent swatches are unused.
const colourKeys = ["9", "4", "8", "6", "7", "5", ..."bcdefghij"];

async function applyAnnotation(action) {
  const n = board.n;
  await page.evaluate(({ action, n, colourKeys }) => {
    const app = Framework.app;
    const getCell = index => app.grid.getCell(Math.floor(index / n), index % n);
    const enabled = action.enabled !== false;
    if (action.op === "colour") {
      const key = colourKeys[Number(action.index) - 3];
      const cell = getCell(action.cell);
      if (!key || !cell || cell.colours.includes(key) === enabled) return;
      app.act({ type: "groupstart" });
      app.act({ type: "deselect" });
      app.act({ type: "select", arg: [cell] });
      app.act({ type: "colour", arg: key });
    } else {
      const [a, b] = [...action.cells].sort((x, y) => x - y);
      const side = b - a === n ? "8" : b - a === 1 && a % n !== n - 1 ? "7" : null;
      const cell = getCell(a);
      if (!side || !cell) return;
      const previous = cell.pen.find(value => value[0] === side);
      const color = String(action.index);
      if (enabled && !["1", "4", "5"].includes(color)) return;
      if (enabled ? previous === side + color : !previous) return;
      app.act({ type: "groupstart" });
      app.act({ type: "deselect" });
      app.act({ type: "select", arg: [cell] });
      if (previous) app.act({ type: "pen", arg: side });
      if (enabled) {
        app.act({ type: "pencolor", arg: color });
        app.act({ type: "pen", arg: side });
      }
    }
    app.act({ type: "deselect" });
    app.act({ type: "groupend" });
  }, { action, n, colourKeys });
}

async function act(action) {
  if (action.op === "snapshot_start") {
    branchSnapshot = await readBoard();
    return;
  }
  if (action.op === "undo_to_snapshot") {
    let matched = false;
    for (let i = 0; i < 1000; i++) {
      const now = await readBoard();
      if (boardEqual(branchSnapshot, now)) { matched = true; break; }
      await page.click("#control-undo", { force: true }).catch(() => {});
      await page.waitForTimeout(120);
    }
    if (!matched) throw new Error("global snapshot not reached by undo");
    const now = await readBoard();
    valueState = new Map();
    markState = new Map();
    now.values.forEach((value, cell) => { if (value) valueState.set(cell, value); });
    now.corners.forEach((digits, cell) => markState.set(cell, new Set(digits)));
    return;
  }
  if (action.op === "reload_base") {
    await open(action.url);
    for (const item of action.actions || []) await act(item);
    await page.waitForTimeout(200);
    const now = await readBoard();
    valueState = new Map(); markState = new Map();
    now.values.forEach((v,c)=>{if(v)valueState.set(c,v)});
    now.corners.forEach((d,c)=>markState.set(c,new Set(d)));
    return;
  }
  if (action.op === "batch") {
    await page.click("#control-select").catch(() => {});
    for (const cell of action.cells || []) {
      const r = Math.floor(cell / board.n);
      const c = cell % board.n;
      const [x, y] = await cellPoint(r, c);
      await page.mouse.click(x, y);
      await page.waitForTimeout(20);
    }
    await page.click("#control-select").catch(() => {});
    if (action.tool === "centre" && !(await useTool("control-centre"))) {
      throw new Error("centre tool unavailable");
    }
    if (action.tool !== "centre" && !(await useTool("control-normal"))) {
      throw new Error("digit tool unavailable");
    }
    for (const digit of action.digits || []) {
      await page.keyboard.type(String(digit));
      await page.waitForTimeout(20);
    }
  } else if (action.op === "pen" || action.op === "colour") {
    await applyAnnotation(action);
  } else if (action.op === "place") {
    await clearSelection();
    const r = Math.floor(action.cell / board.n);
    const c = action.cell % board.n;
    const [x, y] = await cellPoint(r, c);
    await page.mouse.click(x, y);
    if (!(await useTool("control-normal"))) throw new Error("digit tool unavailable");
    await page.keyboard.type(String(action.value));
    valueState.set(action.cell, Number(action.value));
    markState.delete(action.cell);
    await page.waitForTimeout(20);
  } else if (action.op === "candidates") {
    await clearSelection();
    const r = Math.floor(action.cell / board.n);
    const c = action.cell % board.n;
    const [x, y] = await cellPoint(r, c);
    await page.mouse.click(x, y);
    if (!(await useTool("control-centre"))) throw new Error("centre tool unavailable");
    if (valueState.get(action.cell)) {
      console.error(JSON.stringify({ event: "candidate-skip-solved", cell: action.cell }));
      return;
    }
    const before = new Set(markState.get(action.cell) || []);
    const wanted = new Set((action.digits || []).map(Number));
    for (const digit of before) if (!wanted.has(digit)) await page.keyboard.type(String(digit));
    for (const digit of wanted) if (!before.has(digit)) await page.keyboard.type(String(digit));
    const check = await readBoard();
    if (check.values[action.cell]) {
      // A failed tool switch turned a candidate into a digit.
      await clearCellValue(action.cell);
      await page.waitForTimeout(30);
      await page.mouse.click(...(await cellPoint(r, c)));
      await useTool("control-centre");
      for (const digit of wanted) await page.keyboard.type(String(digit));
      await page.waitForTimeout(30);
    }
    markState.set(action.cell, wanted);
    await page.waitForTimeout(12);
  } else if (action.op === "mark" || action.op === "elim" || action.op === "clear") {
    if (!(await useTool("control-centre"))) throw new Error("centre tool unavailable");
    const r = Math.floor(action.cell / board.n);
    const c = action.cell % board.n;
    const [x, y] = await cellPoint(r, c);
    await page.mouse.click(x, y);
    for (const digit of action.digits || [action.value]) {
      if (digit == null) continue;
      await page.keyboard.type(String(digit));
      await page.waitForTimeout(12);
    }
  }
}

async function clearCellValue(cell) {
  await clearSelection();
  const r = Math.floor(cell / board.n);
  const c = cell % board.n;
  const [x, y] = await cellPoint(r, c);
  await page.mouse.click(x, y);
  if (!(await useTool("control-normal"))) throw new Error("digit tool unavailable");
  await page.keyboard.press("Backspace");
  valueState.delete(cell);
  markState.delete(cell);
  await page.waitForTimeout(15);
}

async function setCellValue(cell, value) {
  await clearSelection();
  const r = Math.floor(cell / board.n);
  const c = cell % board.n;
  const [x, y] = await cellPoint(r, c);
  await page.mouse.click(x, y);
  if (!(await useTool("control-normal"))) throw new Error("digit tool unavailable");
  await page.keyboard.type(String(value));
  valueState.set(cell, Number(value));
  markState.delete(cell);
  await page.waitForTimeout(15);
}

async function ensureCellValue(cell, value, known = null) {
  if (known && known.values[cell] === Number(value)) return true;
  for (let attempt = 0; attempt < 4; attempt++) {
    const now = attempt === 0 && known ? known : await readBoard();
    if (now.values[cell] === Number(value)) return true;
    try { await clearCellValue(cell); } catch { /* ignore */ }
    try { await setCellValue(cell, value); } catch { /* retry */ }
  }
  const final = await readBoard();
  return final.values[cell] === Number(value);
}

async function buildSession(url, steps, session, targetDir, size = 0, crop = false) {
  await open(url, size, crop);
  const dir = targetDir || path.join(process.cwd(), ".cache", "frames", session);
  fs.mkdirSync(dir, { recursive: true });
  const initial = await shot();
  const rect = { ...board.rect, imageWidth: initial.readUInt32BE(16), imageHeight: initial.readUInt32BE(20) };
  fs.writeFileSync(path.join(dir, "grid.json"), JSON.stringify(rect));
  fs.writeFileSync(path.join(dir, "-1.png"), initial);
  try {
  const initialBoard = await readBoard();
  let expected = new Map();
  initialBoard.values.forEach((value, cell) => { if (value) expected.set(cell, value); });
  for (let i = 0; i < steps.length; i++) {
    let valueTouched = false;
    for (const action of steps[i] || []) {
      if (["place", "clear", "undo", "redo", "undo_to_snapshot", "reload_base"].includes(action.op)) {
        valueTouched = true;
      }
      await act(action);
      if (["undo", "redo", "undo_to_snapshot", "reload_base"].includes(action.op)) {
        const base = await readBoard();
        expected = new Map();
        base.values.forEach((value, cell) => { if (value) expected.set(cell, value); });
      }
      if (action.op === "place") expected.set(action.cell, Number(action.value));
    }
    if (valueTouched) {
      // One reconciliation pass per step: missing, wrong, then stray values.
      let actual = await readBoard();
      for (const [cell, value] of expected.entries()) {
        if (actual.values[cell] !== value) {
          const ok = await ensureCellValue(cell, value, actual);
          if (!ok) console.error(JSON.stringify({event:"restore-warning", cell, value}));
        }
      }
      const wrong = actual.values
        .map((value, cell) => (value && expected.has(cell) && value !== expected.get(cell) ? cell : -1))
        .filter((cell) => cell >= 0);
      for (const cell of wrong) await setCellValue(cell, expected.get(cell));
      const stray = actual.values
        .map((value, cell) => (value && !expected.has(cell) ? cell : -1))
        .filter((cell) => cell >= 0);
      for (const cell of stray) await clearCellValue(cell);
      if (wrong.length || stray.length) {
        actual = await readBoard();
        const left = actual.values
          .map((value, cell) => (value && !expected.has(cell) ? cell : -1))
          .filter((cell) => cell >= 0);
        if (left.length) throw new Error(`stray values remain: ${left.join(",")}`);
      }
      for (const [cell, value] of expected.entries()) {
        if (actual.values[cell] !== value) {
          const ok = await ensureCellValue(cell, value, actual);
          if (!ok) console.error(JSON.stringify({event:"final-restore-warning", cell, value}));
        }
      }
    }
    await clearSelection();
    fs.writeFileSync(path.join(dir, `${i}.png`), await shot());
  }
  } catch (err) {
    fs.writeFileSync(path.join(dir, "error.json"), JSON.stringify({
      message: String(err?.message || err), stack: String(err?.stack || ""),
    }));
    throw err;
  }
  await page.click("#control-normal").catch(() => {});
}

function json(res, code, obj) {
  const body = Buffer.from(JSON.stringify(obj));
  res.writeHead(code, { "Content-Type": "application/json", "Content-Length": body.length });
  res.end(body);
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, "http://127.0.0.1");
  if (req.method === "GET" && url.pathname === "/health") {
    return json(res, 200, { ok: true, ready: Boolean(page), browser: Boolean(browser),
                            n: board?.n || 0, idle_for: Math.round((Date.now() - lastUsed) / 1000) });
  }
  if (req.method === "GET" && url.pathname === "/grid") {
    return json(res, 200, board?.rect || lastRect || null);
  }
  if (req.method === "GET" && url.pathname === "/state") {
    return readBoard().then((state) => json(res, 200, state)).catch((err) => json(res, 500, { error: String(err?.message || err) }));
  }
  if (req.method === "GET" && url.pathname === "/frame" && url.searchParams.get("session")) {
    const session = path.basename(url.searchParams.get("session") || "");
    const step = path.basename(url.searchParams.get("step") || "0");
    const file = path.join(process.cwd(), ".cache", "frames", session, `${step}.png`);
    if (fs.existsSync(file)) {
      const data = fs.readFileSync(file);
      res.writeHead(200, { "Content-Type": "image/png", "Content-Length": data.length,
                           "Cache-Control": "no-store" });
      return res.end(data);
    }
    return json(res, 404, { error: "no such frame" });
  }
  if (req.method === "GET" && url.pathname === "/frame") {
    if (!latest) return json(res, 404, { error: "no frame" });
    res.writeHead(200, { "Content-Type": "image/png", "Content-Length": latest.length,
                         "Cache-Control": "no-store" });
    return res.end(latest);
  }
  let raw = "";
  req.on("data", (chunk) => { raw += chunk; });
  req.on("end", async () => {
    let body = {};
    try { body = raw ? JSON.parse(raw) : {}; } catch { return json(res, 400, { error: "bad json" }); }
    try {
      if (url.pathname === "/initial-frame") {
        const capture = async () => {
          await open(body.url, Number(body.size) || 0, Boolean(body.crop));
          return shot();
        };
        touch();
        const png = await (work = work.then(capture, capture));
        res.writeHead(200, { "Content-Type": "image/png", "Cache-Control": "no-store" });
        return res.end(png);
      }
      if (url.pathname === "/build") {
        if (!body.url) return json(res, 400, { error: "url required" });
        touch();
        const session = String(body.session || Date.now().toString(36));
        const steps = body.steps || [];
        const targetDir = body.dir || null;
        work = work.then(
          () => buildSession(body.url, steps, session, targetDir, Number(body.size) || 0, Boolean(body.crop)),
          () => buildSession(body.url, steps, session, targetDir, Number(body.size) || 0, Boolean(body.crop)),
        ).catch(() => {});
        return json(res, 200, { ok: true, session, count: steps.length });
      }
      if (url.pathname === "/start") {
        if (!body.url) return json(res, 400, { error: "url required" });
        touch();
        await (work = work.then(async () => { await open(body.url); await shot(); }, async () => { await open(body.url); await shot(); }));
        return json(res, 200, { ok: true, n: board.n });
      }
      if (url.pathname === "/place") {
        if (!page) return json(res, 410, { error: "browser recycled", restart: true });
        touch();
        await (work = work.then(
          () => apply(body.digits || body.places || [], body.corners || [], Boolean(body.reset)),
          () => apply(body.digits || body.places || [], body.corners || [], Boolean(body.reset)),
        ));
        return json(res, 200, { ok: true, bytes: latest.length });
      }
      return json(res, 404, { error: "not found" });
    } catch (err) {
      return json(res, 500, { error: err?.message || String(err) });
    }
  });
});

ensurePage().then(() => {
  console.log(JSON.stringify({ event: "pool-warm", pages: 1 }));
}).catch((err) => {
  console.error(JSON.stringify({ event: "pool-warm-failed", error: String(err?.message || err) }));
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(JSON.stringify({ ok: true, port: PORT }));
});

process.on("SIGTERM", async () => {
  await browser?.close().catch(() => {});
  process.exit(0);
});

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
let latest = null;
let work = Promise.resolve();
let ledger = new Map();  // cell -> { digit: number, corners: Set<number> }
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

async function open(url) {
  if (!browser) {
    browser = await chromium.launch({
      headless: true,
      executablePath,
      args: ["--no-sandbox", "--disable-dev-shm-usage"],
    });
  }
  if (context) {
    await context.close().catch(() => {});
  }
  context = await browser.newContext({
    viewport: { width: 1200, height: 1000 },
    colorScheme: "light",
  });
  page = await context.newPage();
  await page.emulateMedia({ colorScheme: "light" });
  ledger = new Map();
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(1200);
  // The start overlay darkens the board; click it as soon as it appears,
  // otherwise a cropped screenshot captures the dimmed start screen.
  let started = false;
  try {
    const start = page.getByText("Start Puzzle");
    await start.first().waitFor({ state: "visible", timeout: 4000 });
    await start.first().click();
    started = true;
    await page.waitForTimeout(900);
  } catch { /* puzzle already started or a resume overlay */ }
  await page.waitForSelector("svg.boardsvg", { timeout: 30000 });
  await page.waitForTimeout(300);
  if (!started) {
    // Some reopen paths show a play/resume overlay instead of "Start Puzzle";
    // clicking the board centre dismisses it (or merely selects a cell).
    const b = await page.locator("svg.boardsvg").boundingBox();
    if (b) {
      await page.mouse.click(b.x + b.width / 2, b.y + b.height / 2);
      await page.waitForTimeout(600);
    }
  }
  const box = await page.locator("svg.boardsvg").boundingBox();
  if (!box) throw new Error("board not visible");
  const viewBox = await page.locator("svg.boardsvg").getAttribute("viewBox");
  const parts = (viewBox || "-16 -16 608 608").trim().split(/\s+/).map(Number);
  const units = parts[2] || 608;
  const n = Math.max(1, Math.round((units - 32) / 64));
  const pad = 16 / units;
  const grid = {
    x: box.x + box.width * pad,
    y: box.y + box.height * pad,
    width: box.width * (1 - 2 * pad),
    height: box.height * (1 - 2 * pad),
  };
  board = { box, grid, n };
  puzzleUrl = url;
}

async function shot() {
  const { grid } = board;
  latest = await page.screenshot({
    clip: { x: grid.x, y: grid.y, width: grid.width, height: grid.height },
    type: "png",
  });
  return latest;
}

function center(r, c) {
  const { grid, n } = board;
  const unit = grid.width / n;
  return [grid.x + (c + 0.5) * unit, grid.y + (r + 0.5) * unit];
}

async function cellPoint(r, c) {
  const box = await page.locator("svg.boardsvg").boundingBox();
  const viewBox = await page.locator("svg.boardsvg").getAttribute("viewBox");
  const parts = (viewBox || "-16 -16 608 608").trim().split(/\s+/).map(Number);
  const units = parts[2] || 608;
  const pad = 16 / units;
  const unit = (box.width * (1 - 2 * pad)) / board.n;
  return [box.x + box.width * pad + (c + 0.5) * unit,
          box.y + box.height * pad + (r + 0.5) * unit];
}

async function readBoard() {
  return await page.evaluate((n) => {
    const values = new Array(n * n).fill(0);
    const corners = Array.from({ length: n * n }, () => []);
    const toCell = (x, y) => {
      const c = Math.floor((x - 32) / 64);
      const r = Math.floor((y - 32) / 64);
      if (r < 0 || r >= n || c < 0 || c >= n) return -1;
      return r * n + c;
    };
    for (const t of document.querySelectorAll("#cell-values text")) {
      const x = parseFloat(t.getAttribute("x"));
      const y = parseFloat(t.getAttribute("y"));
      const cell = toCell(x, y - 3.8);
      if (cell >= 0) values[cell] = Number(t.textContent);
    }
    for (const t of document.querySelectorAll("#cell-candidates text")) {
      const x = parseFloat(t.getAttribute("x"));
      const y = parseFloat(t.getAttribute("y"));
      const cell = toCell(x, y);
      if (cell < 0) continue;
      for (const span of t.querySelectorAll("tspan[data-val]")) {
        const v = Number(span.getAttribute("data-val"));
        if (v) corners[cell].push(v);
      }
    }
    return { values, corners };
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
  const box = await page.locator("svg.boardsvg").boundingBox().catch(() => null);
  if (box) {
    const viewport = page.viewportSize() || { width: 1200, height: 900 };
    const x = box.x + box.width / 2;
    const y = Math.min(viewport.height - 4, box.y + box.height + 24);
    await page.mouse.click(x, y).catch(() => {});
  }
  await page.waitForTimeout(15);
}

async function act(action) {
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
  } else if (action.op === "place") {
    await clearSelection();
    const r = Math.floor(action.cell / board.n);
    const c = action.cell % board.n;
    const [x, y] = await cellPoint(r, c);
    await page.mouse.click(x, y);
    if (!(await useTool("control-normal"))) throw new Error("digit tool unavailable");
    await page.keyboard.type(String(action.value));
    await page.waitForTimeout(30);
    const placed = await readBoard();
    if (placed.values[action.cell] !== Number(action.value)) {
      console.error(JSON.stringify({
        event: "place-warning", cell: action.cell, wanted: action.value,
        actual: placed.values[action.cell] || 0,
      }));
    }
  } else if (action.op === "candidates") {
    await clearSelection();
    const r = Math.floor(action.cell / board.n);
    const c = action.cell % board.n;
    const [x, y] = await cellPoint(r, c);
    await page.mouse.click(x, y);
    if (!(await useTool("control-centre"))) throw new Error("centre tool unavailable");
    const current = await readBoard();
    if (current.values[action.cell]) {
      console.error(JSON.stringify({ event: "candidate-skip-solved", cell: action.cell }));
      return;
    }
    const before = new Set(current.corners[action.cell] || []);
    const wanted = new Set((action.digits || []).map(Number));
    for (const digit of before) if (!wanted.has(digit)) await page.keyboard.type(String(digit));
    for (const digit of wanted) if (!before.has(digit)) await page.keyboard.type(String(digit));
    await page.waitForTimeout(20);
    const after = await readBoard();
    const got = new Set(after.corners[action.cell] || []);
    if (after.values[action.cell] || got.size !== wanted.size || [...wanted].some((d) => !got.has(d))) {
      throw new Error(`candidate mismatch at cell ${action.cell}`);
    }
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
  await page.waitForTimeout(25);
  const after = await readBoard();
  if (after.values[cell]) throw new Error(`could not clear stray value at cell ${cell}`);
}

async function setCellValue(cell, value) {
  await clearSelection();
  const r = Math.floor(cell / board.n);
  const c = cell % board.n;
  const [x, y] = await cellPoint(r, c);
  await page.mouse.click(x, y);
  if (!(await useTool("control-normal"))) throw new Error("digit tool unavailable");
  await page.keyboard.type(String(value));
  await page.waitForTimeout(25);
  const after = await readBoard();
  if (after.values[cell] !== Number(value)) throw new Error(`could not restore value at cell ${cell}`);
}

async function ensureCellValue(cell, value) {
  for (let attempt = 0; attempt < 4; attempt++) {
    const now = await readBoard();
    if (now.values[cell] === Number(value)) return true;
    try { await clearCellValue(cell); } catch { /* ignore */ }
    try { await setCellValue(cell, value); } catch { /* retry */ }
  }
  const final = await readBoard();
  return final.values[cell] === Number(value);
}

async function buildSession(url, steps, session, targetDir) {
  await open(url);
  const dir = targetDir || path.join(process.cwd(), ".cache", "frames", session);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, "-1.png"), await shot());
  try {
  const expected = new Map();
  for (let i = 0; i < steps.length; i++) {
    for (const action of steps[i] || []) {
      if (action.op === "place") expected.set(action.cell, Number(action.value));
      await act(action);
    }
    // Safety net: make every scheduled value present, then restore wrong values.
    let actual = await readBoard();
    for (const [cell, value] of expected.entries()) {
      if (actual.values[cell] !== value) {
        const ok = await ensureCellValue(cell, value);
        if (!ok) console.error(JSON.stringify({event:"restore-warning", cell, value}));
      }
    }
    actual = await readBoard();
    const wrong = actual.values
      .map((value, cell) => (value && expected.has(cell) && value !== expected.get(cell) ? cell : -1))
      .filter((cell) => cell >= 0);
    for (const cell of wrong) await setCellValue(cell, expected.get(cell));
    actual = await readBoard();
    const stray = actual.values
      .map((value, cell) => (value && !expected.has(cell) ? cell : -1))
      .filter((cell) => cell >= 0);
    for (const cell of stray) await clearCellValue(cell);
    if (stray.length) {
      actual = await readBoard();
      const left = actual.values
        .map((value, cell) => (value && !expected.has(cell) ? cell : -1))
        .filter((cell) => cell >= 0);
      if (left.length) throw new Error(`stray values remain: ${left.join(",")}`);
    }
    const beforeShot = await readBoard();
    for (const [cell, value] of expected.entries()) {
      if (beforeShot.values[cell] !== value) {
        const ok = await ensureCellValue(cell, value);
        if (!ok) console.error(JSON.stringify({event:"final-restore-warning", cell, value}));
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
      if (url.pathname === "/build") {
        if (!body.url) return json(res, 400, { error: "url required" });
        touch();
        const session = String(body.session || Date.now().toString(36));
        const steps = body.steps || [];
        const targetDir = body.dir || null;
        work = work.then(
          () => buildSession(body.url, steps, session, targetDir),
          () => buildSession(body.url, steps, session, targetDir),
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

server.listen(PORT, "127.0.0.1", () => {
  console.log(JSON.stringify({ ok: true, port: PORT }));
});

process.on("SIGTERM", async () => {
  await browser?.close().catch(() => {});
  process.exit(0);
});

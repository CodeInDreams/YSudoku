#!/usr/bin/env node
/**
 * Read-only SudokuPad mirror for the web UI.
 *
 * A long-lived Chromium opens the puzzle.  The UI receives a cropped PNG of the
 * board only, so SudokuPad's own chrome is never shown.  Commands are plain
 * HTTP; the page itself is never exposed to the browser client.
 */
import http from "http";
import { chromium } from "playwright";

const PORT = Number(process.env.YSUDOKU_LIVE_PORT || 8791);
const IDLE_MS = Math.max(0, Number(process.env.YSUDOKU_LIVE_IDLE_SECONDS || 600)) * 1000;
const MIN_IDLE = Math.max(0, Number(process.env.YSUDOKU_LIVE_MIN_IDLE || 0));
const executablePath = process.env.YSUDOKU_CHROME || undefined;

let browser = null;
let page = null;
let puzzleUrl = "";
let board = null;
let latest = null;
let work = Promise.resolve();
let ledger = new Map();  // cell -> { digit: number, corners: Set<number> }
let lastUsed = Date.now();

function touch() { lastUsed = Date.now(); }

async function closeBrowser() {
  await page?.close().catch(() => {});
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
  if (page) {
    await page.close().catch(() => {});
  }
  page = await browser.newPage({ viewport: { width: 1200, height: 1000 }, colorScheme: "light" });
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
    for (const t of document.querySelectorAll("#cell-pencilmarks text")) {
      const x = parseFloat(t.getAttribute("x"));
      const y = parseFloat(t.getAttribute("y"));
      const cell = toCell(x, y);
      const v = Number(t.getAttribute("data-val") || t.textContent);
      if (cell >= 0 && v) corners[cell].push(v);
    }
    return { values, corners };
  }, board.n);
}

async function apply(digits, corners, reset) {
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
    const [x, y] = center(r, c);
    await page.mouse.click(x, y);
  };

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
  await page.click("#control-corner").catch(() => {});
  for (const [cell, wanted] of target) {
    if (state.values[cell]) continue;  // solved cells keep their digit
    const current = new Set(state.corners[cell] || []);
    if (current.size === wanted.size && [...wanted].every((d) => current.has(d))) continue;
    await clickCell(cell);
    // Delete only if this cell really has pencil marks; otherwise SudokuPad
    // falls back to clearing the cell (including its value).
    if (current.size) await page.keyboard.press("Delete").catch(() => {});
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
    await page.keyboard.press("Delete").catch(() => {});
    state.corners[cell] = [];
  }
  await page.click("#control-normal").catch(() => {});
  await page.waitForTimeout(120);
  return shot();
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

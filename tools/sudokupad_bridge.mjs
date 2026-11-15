#!/usr/bin/env node
/**
 * Drive a real SudokuPad page with Playwright: open the puzzle, press
 * "Start Puzzle" and fill the given 81-digit solution by clicking each cell
 * and typing the digit.
 *
 * Usage:
 *   node tools/sudokupad_bridge.mjs --url <sudokupad-url> --solution <81 digits> [--headed] [--screenshot out.png]
 *
 * Needs: npm i playwright && npx playwright install chromium
 * Optional env: YSUDOKU_CHROME=/path/to/chrome
 */
import { chromium } from "playwright";

const args = {};
for (let i = 2; i < process.argv.length; i += 2) {
  const key = process.argv[i].replace(/^--/, "");
  args[key] = process.argv[i + 1];
}

const url = args.url;
const solution = String(args.solution || "").replace(/[^0-9]/g, "");
if (!url || solution.length !== 81) {
  console.error("usage: --url <url> --solution <81 digits> [--headed] [--screenshot file]");
  process.exit(2);
}

const headed = Boolean(args.headed);
const delay = Number(args.delay || 35);
const executablePath = process.env.YSUDOKU_CHROME || undefined;

const browser = await chromium.launch({
  headless: !headed,
  executablePath,
  args: ["--no-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage({ viewport: { width: 1100, height: 1000 } });
try {
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(2200);

  const start = page.getByText("Start Puzzle");
  if (await start.count()) {
    await start.first().click();
    await page.waitForTimeout(500);
  }

  await page.waitForSelector("svg.boardsvg", { timeout: 30000 });
  const box = await page.locator("svg.boardsvg").boundingBox();
  if (!box) throw new Error("board not visible");

  // viewBox is "-16 -16 608 608": 64 units per cell, 16 units of padding.
  const center = (r, c) => [
    box.x + (32 + c * 64) * box.width / 608,
    box.y + (32 + r * 64) * box.height / 608,
  ];

  let filled = 0;
  for (let r = 0; r < 9; r++) {
    for (let c = 0; c < 9; c++) {
      const digit = solution[r * 9 + c];
      if (digit === "0") continue;
      const [x, y] = center(r, c);
      await page.mouse.click(x, y);
      await page.keyboard.type(digit);
      filled += 1;
      if (delay) await page.waitForTimeout(delay);
    }
  }
  await page.waitForTimeout(700);
  const ok = page.getByRole("button", { name: "OK" });
  if (await ok.count()) {
    await ok.first().click();
    await page.waitForTimeout(400);
  }
  if (args.screenshot) await page.screenshot({ path: args.screenshot });
  console.log(JSON.stringify({ ok: true, filled, url }));
} catch (err) {
  console.error(err?.stack || String(err));
  process.exitCode = 1;
} finally {
  await browser.close();
}

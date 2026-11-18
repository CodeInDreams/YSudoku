// Pixel-level check: detect the 9x9 grid border in the frame and compare it
// with the grid_rect returned by the renderer.
import { chromium } from '/tmp/pw/node_modules/playwright/index.mjs';

const BASE = process.env.YS_BASE || 'http://127.0.0.1:8765';
const key = `pixel-${Date.now().toString(36)}`;

async function main() {
  const build = await fetch(`${BASE}/api/live/build`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url: 'https://sudokupad.app/ad4xg01xip', steps: [], key, size: 9 }),
  });
  if (!build.ok) throw new Error(`build ${build.status}`);
  let rect = null;
  for (let i = 0; i < 80 && !rect; i++) {
    await new Promise((r) => setTimeout(r, 500));
    const r = await fetch(`${BASE}/api/live/grid?session=${key}`);
    if (r.ok) rect = await r.json();
  }
  if (!rect) throw new Error('no rect');
  let frame;
  for (let i = 0; i < 80; i++) {
    const r = await fetch(`${BASE}/api/live/frame?session=${key}&step=-1`);
    if (r.ok) { frame = Buffer.from(await r.arrayBuffer()); break; }
    await new Promise((r) => setTimeout(r, 500));
  }
  if (!frame) throw new Error('no frame');

  const browser = await chromium.launch({ headless: true,
    executablePath: process.env.PLAYWRIGHT_CHROMIUM || undefined,
    args: ['--no-sandbox'] });
  const page = await browser.newPage();
  const data = 'data:image/png;base64,' + frame.toString('base64');
  const detected = await page.evaluate(async (src) => {
    const img = new Image();
    await new Promise((ok, bad) => { img.onload = ok; img.onerror = bad; img.src = src; });
    const c = document.createElement('canvas');
    c.width = img.width; c.height = img.height;
    const g = c.getContext('2d'); g.drawImage(img, 0, 0);
    const px = (x, y) => { const d = g.getImageData(x, y, 1, 1).data; return d[0] + d[1] + d[2] < 240; };
    const cols = [], rows = [];
    for (let x = 0; x < img.width; x++) {
      let n = 0; for (let y = 0; y < img.height; y++) if (px(x, y)) n++;
      if (n > img.height * 0.5) cols.push(x);
    }
    for (let y = 0; y < img.height; y++) {
      let n = 0; for (let x = 0; x < img.width; x++) if (px(x, y)) n++;
      if (n > img.width * 0.5) rows.push(y);
    }
    return { width: img.width, height: img.height,
             x0: Math.min(...cols), x1: Math.max(...cols),
             y0: Math.min(...rows), y1: Math.max(...rows) };
  }, data);
  await browser.close();

  const dx = Math.abs(detected.x0 - rect.x);
  const dy = Math.abs(detected.y0 - rect.y);
  const dw = Math.abs((detected.x1 - detected.x0) - rect.width);
  const dh = Math.abs((detected.y1 - detected.y0) - rect.height);
  console.log(JSON.stringify({ rect, detected, deltas: { dx, dy, dw, dh } }, null, 2));
  if (Math.max(dx, dy, dw, dh) > 4) throw new Error('grid_rect does not match the detected grid');
  console.log('grid pixels ok');
}

main().catch((e) => { console.error(e.message); process.exit(1); });

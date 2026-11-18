import http from "http";
import { chromium } from "playwright";

const PORT = 8792;
const PUZZLE_URL = "https://sudokupad.app/pyivck2m15";
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM || undefined, args: ["--no-sandbox"] });
const context = await browser.newContext({ viewport: { width: 1000, height: 900 } });
await context.addInitScript(() => {
  localStorage.setItem("svencodes_settings", JSON.stringify({
    selection: "default", toolpen: true, toolletter: true, largedigits: false,
    checkpencilmarks: false, marksolveddigits: "off", puzzleevents: "off", uitheme: "monolight",
  }));
});
const page = await context.newPage();
await page.goto(PUZZLE_URL, { waitUntil: "domcontentloaded", timeout: 60000 });
await page.waitForTimeout(2000);
const start = page.getByText("Start Puzzle");
if (await start.count()) await start.first().click();
await page.waitForSelector("svg.boardsvg", { timeout: 30000 });
await page.waitForTimeout(500);
const box = await page.locator("svg.boardsvg").boundingBox();
const unit = box.width / 9;

let latestShot = null;
async function shot() {
  try { latestShot = await page.screenshot({ type: "png" }); } catch { /* navigation */ }
  return latestShot;
}
async function cell(r, c) {
  const b = await page.locator("svg.boardsvg").boundingBox();
  const u = b.width / 9;
  await page.mouse.click(b.x + (c + 0.5) * u, b.y + (r + 0.5) * u);
  await page.waitForTimeout(80);
}
let lastState = { cells: Array.from({ length: 81 }, () => ({ value: 0, centre: [], corners: [], colors: [] })) };
async function state() {
  try {
    const value = await page.evaluate(() => {
    const cells = Array.from({ length: 81 }, () => ({ value: 0, centre: [], corners: [], colors: [] }));
    const at = (x, y) => {
      const c = Math.floor((x - 32) / 64), r = Math.floor((y - 32) / 64);
      return r >= 0 && r < 9 && c >= 0 && c < 9 ? r * 9 + c : -1;
    };
    for (const t of document.querySelectorAll("#cell-values text")) {
      const i = at(parseFloat(t.getAttribute("x")), parseFloat(t.getAttribute("y")));
      if (i >= 0) cells[i].value = Number(t.textContent);
    }
    for (const t of document.querySelectorAll("#cell-candidates text")) {
      const i = at(parseFloat(t.getAttribute("x")), parseFloat(t.getAttribute("y")));
      if (i < 0) continue;
      cells[i].centre = [...t.querySelectorAll("tspan[data-val]")].map((e) => +e.getAttribute("data-val"));
    }
    for (const t of document.querySelectorAll("#cell-pencilmarks text[data-val]")) {
      const i = at(parseFloat(t.getAttribute("x")), parseFloat(t.getAttribute("y")));
      if (i >= 0) cells[i].corners.push(+t.getAttribute("data-val"));
    }
    return { cells, undoDisabled: document.querySelector("#control-undo")?.disabled ?? null };
    });
    lastState = value;
    return value;
  } catch {
    return lastState;
  }
}
async function place() {
  await page.click("#control-normal");
  await cell(0, 3);
  await page.keyboard.type("1");
  await page.waitForTimeout(250);
}
async function undo() { await page.click("#control-undo"); await page.waitForTimeout(250); }
async function redo() { await page.click("#control-redo"); await page.waitForTimeout(250); }

const ops = [
  { label: "初始盘面", run: async () => {}, back: async () => {} },
  { label: "假设 R1C4 = 1", run: place, back: undo },
  { label: "Undo 一次", run: undo, back: redo },
  { label: "Redo 一次", run: redo, back: undo },
  { label: "Undo 回到假设前", run: undo, back: redo },
];
let cursor = 0;
async function resetTo(index) {
  // Reload from scratch to make Prev deterministic.
  await page.goto(PUZZLE_URL, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2500);
  const s = page.getByText("Start Puzzle");
  if (await s.count()) { await s.first().click().catch(() => {}); await page.waitForTimeout(800); }
  await page.waitForSelector("svg.boardsvg", { timeout: 30000 });
  await page.waitForTimeout(800);
  for (let i = 1; i <= index; i++) { await ops[i].run(); await page.waitForTimeout(500); }
  await page.waitForTimeout(500);
}

const html = `<!doctype html><meta charset="utf-8"><title>Rollback Demo</title>
<style>body{font:14px system-ui;margin:0;background:#111;color:#eee}header{padding:12px;display:flex;gap:8px;align-items:center}button{padding:6px 12px}main{display:grid;grid-template-columns:1fr 320px;gap:12px;padding:12px}img{width:100%;background:#fff;border-radius:6px}pre{white-space:pre-wrap;font-size:11px;background:#1b1b1b;padding:8px;border-radius:6px;max-height:75vh;overflow:auto}#board{display:grid;grid-template-columns:repeat(9,1fr);width:min(420px,100%);aspect-ratio:1;margin-top:10px;border:2px solid #222}.cell{border:1px solid #888;position:relative;display:flex;align-items:center;justify-content:center;background:#fff;color:#111;font-size:20px}.centre{position:absolute;inset:0;display:grid;grid-template-columns:repeat(3,1fr);font-size:9px;color:#2563eb}.corners{position:absolute;inset:2px;display:grid;grid-template-columns:repeat(3,1fr);font-size:7px;color:#777}</style>
<header><b>Rollback Demo</b><button id="prev">上一步</button><button id="next">下一步</button><span id="label"></span></header>
<main><div><img id="shot"><div id="board"></div></div><pre id="state"></pre></main>
<script>
let busy=false;
async function refresh(){const r=await fetch('/state');const d=await r.json();document.getElementById('label').textContent=d.label;document.getElementById('state').textContent=JSON.stringify(d.state,null,2);document.getElementById('shot').src='/shot?t='+Date.now();const b=document.getElementById('board');b.innerHTML='';d.state.cells.forEach((c,i)=>{const e=document.createElement('div');e.className='cell';if(c.colors.length)e.style.background='#f3c7c7';if(c.value)e.innerHTML='<b>'+c.value+'</b>';else{e.innerHTML='<div class=centre>'+(c.centre||[]).join(' ')+'</div><div class=corners>'+(c.corners||[]).join(' ')+'</div>';}b.appendChild(e);});}
document.getElementById('next').onclick=async()=>{if(busy)return;busy=true;await fetch('/next',{method:'POST'});await refresh();busy=false;};
document.getElementById('prev').onclick=async()=>{if(busy)return;busy=true;await fetch('/prev',{method:'POST'});await refresh();busy=false;};
refresh();
</script>`;

const server = http.createServer(async (req, res) => {
  const u = new URL(req.url, "http://127.0.0.1");
  if (u.pathname === "/") { res.writeHead(200, {"Content-Type":"text/html"}); return res.end(html); }
  if (u.pathname === "/shot") {
    const png = await shot(); res.writeHead(200, {"Content-Type":"image/png","Cache-Control":"no-store"}); return res.end(png);
  }
  if (u.pathname === "/state") {
    const st = await state(); res.writeHead(200, {"Content-Type":"application/json"}); return res.end(JSON.stringify({label:ops[cursor].label,state:st}));
  }
  if (u.pathname === "/next" && req.method === "POST") {
    try { if (cursor < ops.length - 1) { await ops[cursor + 1].run(); cursor += 1; } } catch (e) { console.error(e); }
    res.writeHead(200, {"Content-Type":"application/json"}); return res.end(JSON.stringify({cursor}));
  }
  if (u.pathname === "/prev" && req.method === "POST") {
    try { if (cursor > 0) { await ops[cursor].back(); cursor -= 1; } await page.waitForTimeout(250); } catch (e) { console.error(e); }
    res.writeHead(200, {"Content-Type":"application/json"}); return res.end(JSON.stringify({cursor}));
  }
  res.writeHead(404); res.end("not found");
});
server.listen(PORT, "0.0.0.0", () => console.log(`rollback demo http://127.0.0.1:${PORT}/`));

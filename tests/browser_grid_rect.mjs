// Visual regression: the grid rect must describe the inner 9x9 area of the
// full screenshot. Run with the web server on :8765.
const BASE = process.env.YS_BASE || "http://127.0.0.1:8765";
const URL = "https://sudokupad.app/ad4xg01xip";
const key = `test-${Date.now().toString(36)}`;

async function post(path, body) {
  const r = await fetch(BASE + path, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${path} ${r.status}`);
  return r.json();
}

async function main() {
  await post("/api/live/build", { url: URL, steps: [], key, size: 9 });
  let rect = null;
  for (let i = 0; i < 60 && !rect; i++) {
    await new Promise((r) => setTimeout(r, 500));
    const r = await fetch(`${BASE}/api/live/grid?session=${key}`);
    if (r.ok) rect = await r.json();
  }
  if (!rect) throw new Error("grid rect never appeared");
  if (rect.width >= rect.imageWidth * 0.99) throw new Error("rect covers the whole image");
  if (rect.x <= 0 || rect.y <= 0) throw new Error("rect has no outside-clue margin");
  if (rect.x + rect.width > rect.imageWidth + 2) throw new Error("rect overflows right");
  if (rect.y + rect.height > rect.imageHeight + 2) throw new Error("rect overflows bottom");
  const ratio = rect.width / rect.imageWidth;
  if (ratio < 0.7 || ratio > 0.9) throw new Error(`unexpected grid ratio ${ratio}`);

  const img = await fetch(`${BASE}/api/live/frame?session=${key}&step=-1`);
  if (!img.ok) throw new Error(`frame ${img.status}`);
  const png = Buffer.from(await img.arrayBuffer());
  const width = png.readUInt32BE(16);
  const height = png.readUInt32BE(20);
  if (Math.abs(width - rect.imageWidth) > 2) throw new Error(`frame width ${width} != rect ${rect.imageWidth}`);
  if (Math.abs(height - rect.imageHeight) > 2) throw new Error(`frame height ${height} != rect ${rect.imageHeight}`);
  console.log("grid rect ok", JSON.stringify({ ...rect, frame: [width, height] }));
}

main().catch((err) => { console.error(err.message); process.exit(1); });

// Grid geometry and screenshot margins, with and without outside clues.
// Run with the web server on :8765.
const BASE = process.env.YS_BASE || "http://127.0.0.1:8765";

async function post(path, body) {
  const r = await fetch(BASE + path, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${path} ${r.status}`);
  return r.json();
}

async function check(puzzleId, crop) {
  const url = `https://sudokupad.app/${puzzleId}`;
  const { frames } = await post("/api/solve", { url, llm: false });
  const key = frames.session;
  let rect = null;
  for (let i = 0; i < 180 && !rect; i++) {
    await new Promise((r) => setTimeout(r, 500));
    const r = await fetch(`${BASE}/api/live/grid?session=${key}`);
    if (r.ok) rect = await r.json();
  }
  if (!rect) throw new Error("grid rect never appeared");
  const right = rect.imageWidth - rect.x - rect.width;
  const bottom = rect.imageHeight - rect.y - rect.height;
  if (Math.min(rect.x, rect.y, right, bottom) <= 0) throw new Error("grid touches or crosses the capture edge");
  if (crop) {
    if (Math.abs(rect.x - right) > 1.01 || Math.abs(rect.y - bottom) > 1.01) {
      throw new Error("cropped margins are asymmetric");
    }
    if (Math.max(rect.x, right, rect.y, bottom) > 1 + rect.width / 96) {
      throw new Error("too much blank margin around the cropped grid");
    }
  } else {
    const ratio = rect.width / rect.imageWidth;
    if (ratio < 0.7 || ratio > 0.9) throw new Error(`unexpected full-board grid ratio ${ratio}`);
  }

  for (const step of [-1, 0]) {
    let img;
    for (let i = 0; i < 180; i++) {
      img = await fetch(`${BASE}/api/live/frame?session=${key}&step=${step}`);
      if (img.ok) break;
      await new Promise((r) => setTimeout(r, 500));
    }
    if (!img?.ok) throw new Error(`frame ${step} never appeared`);
    const png = Buffer.from(await img.arrayBuffer());
    if (png.readUInt32BE(16) !== rect.imageWidth || png.readUInt32BE(20) !== rect.imageHeight) {
      throw new Error(`PNG dimensions disagree with grid metadata for frame ${step}`);
    }
  }
  console.log("grid rect ok", JSON.stringify({ puzzleId, crop, ...rect }));
}

try {
  await check("ps23dp93mp", true);
  await check("ad4xg01xip", false);
} catch (err) {
  console.error(err.message);
  process.exit(1);
}

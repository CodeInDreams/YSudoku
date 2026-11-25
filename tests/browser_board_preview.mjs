// Compare the streamed preview with the rendered opening and first solve frames.
// Use a server with an empty store so the preview is captured on this request.
import assert from "node:assert/strict";

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || "../tools/node_modules/playwright/index.mjs");
const base = process.env.YS_BASE || "http://127.0.0.1:8765";
const browser = await chromium.launch({
  executablePath: process.env.PLAYWRIGHT_CHROMIUM || undefined,
  args: ["--no-sandbox"],
});

async function geometry(image) {
  await image.waitFor({ timeout: 120_000 });
  await image.evaluate(img => img.decode());
  return image.evaluate(img => {
    const { width, height } = img.getBoundingClientRect();
    return { width, height, pixels: [img.naturalWidth, img.naturalHeight],
      filter: getComputedStyle(img).filter };
  });
}

try {
  const page = await browser.newPage({ locale: "en-US", viewport: { width: 1280, height: 900 } });
  await page.addInitScript(() => localStorage.setItem("ysudoku.theme", "dark"));
  await page.goto(base);

  for (const id of ["0ctlhhx84e", "ad4xg01xip"]) {
    const form = page.locator("header form");
    await form.locator("input").fill(`https://sudokupad.app/${id}`);
    await form.locator("button[type=submit]").click();
    const preview = await geometry(page.locator('img[src^="/api/rulesheet/"]').first());
    const opening = await geometry(page.locator('img[src^="/api/live/frame"][src*="step=-1&"]'));
    const slider = page.getByRole("slider").last();
    await slider.press("ArrowRight");
    const first = await geometry(page.locator('img[src^="/api/live/frame"][src*="step=0&"]'));

    assert.equal(preview.filter, "brightness(0.8) contrast(1.04)");
    for (const frame of [opening, first]) {
      assert.deepEqual(frame.pixels, preview.pixels);
      assert.equal(frame.filter, preview.filter);
      assert(Math.abs(frame.width - preview.width) < 1);
      assert(Math.abs(frame.height - preview.height) < 1);
    }

    await slider.press("Home");
    await page.locator('img[src^="/api/live/frame"][src*="step=-1&"]').waitFor();
    await page.waitForFunction(() => !document.querySelector("header form button[type=submit]")?.disabled,
      null, { timeout: 120_000 });
    console.log(id, preview.pixels.join("×"), "preview, opening, and first step match");
  }
} finally {
  await browser.close();
}

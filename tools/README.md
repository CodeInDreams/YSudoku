# SudokuPad bridge (optional)

Drives a real SudokuPad page with Playwright: opens the puzzle, presses
"Start Puzzle" and fills a solution by clicking cells and typing digits.

```bash
cd tools
npm install
npx playwright install chromium

node sudokupad_bridge.mjs --url https://sudokupad.app/6uhr6irwvd \
  --solution 348672951... --headed --screenshot out.png
```

`--headed` shows the browser so you can watch it. Without it the run is
headless. `YSUDOKU_CHROME` can point at a specific Chromium binary.

This is a local convenience/automation tool; it is not used by the web UI
and it does not read SudokuPad's internal state.

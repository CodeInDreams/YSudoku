# YSudoku

English | [中文](README.zh-CN.md)

**See why every digit is right.**

[![CI](https://github.com/CodeInDreams/ysudoku/actions/workflows/ci.yml/badge.svg)](https://github.com/CodeInDreams/ysudoku/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

> Pronounced **WHY-soo-doh-koo** (/ˌwaɪ suːˈdoʊkuː/), i.e. "why sudoku".

YSudoku turns a [SudokuPad](https://sudokupad.app) link into a **step-by-step, playable,
interactive explanation** — not a black-box answer.

- **Not brute force.** Every step says which rule was used, what was eliminated, and why.
- **Machine-checkable.** An optional refutation audit verifies each conclusion independently.
- **Playable.** Highlights, constraint outlines, candidate strikes and digit pops are animated.

## Quick start

The core has no third-party dependencies; Python 3.10+.

```bash
git clone git@github.com:CodeInDreams/ysudoku.git
cd ysudoku
python3 -m ysudoku --web
# open http://127.0.0.1:8765/
```

The **Example** button loads a real puzzle — *Globosite* by lgastako (229 steps, ~2 s) — with a
link to the original SudokuPad page. You can paste a SudokuPad link, a **Logic Masters puzzle page**
(the SudokuPad link is extracted automatically), a bare puzzle id, or a local JSON file.

Text-only reasoning from the CLI:

```bash
python3 -m ysudoku 7v57yvn5vf
python3 -m ysudoku --no-chains 7v57yvn5vf          # disable refutation (T4); it is on by default
python3 -m ysudoku --audit --json https://sudokupad.app/eynwusqy5l > out.json
```

Optional install as a command:

```bash
pip install -e .
ysudoku --web
```

### Autofill the real SudokuPad page (optional)

Playwright can drive the actual SudokuPad page — click cells, type digits, press buttons:

```bash
cd tools
npm install
npx playwright install chromium
cd ..
python3 -m ysudoku --browser https://sudokupad.app/6uhr6irwvd
```

It opens a real browser, presses **Start Puzzle**, then types the solution cell by cell:

![Autofill in the real SudokuPad](docs/sudokupad-autofill.png)

This is a local automation helper. It is not used by the web UI, and it only *writes* to the page;
it does not read SudokuPad's internal state.

## How it works

```
link → api/puzzle → scl payload → custom LZW + zipper decode
     → grid / cages / lines / circles / dots / arrows
     → element inventory + official rules text
     → LLM compiles the text into JSON constraints (validated against the built-in solution)
     → constraint propagation + human techniques
     → each step: explanation + animation script
```

SudokuPad's JSON only stores **what is drawn**, not what it means: a Kropki dot is just a black
circle, a "trisection circle" is just a thick grey circle. YSudoku adds a *graphics → semantics*
compiler, uses the puzzle's own solution as a closed-loop check, and falls back to colour/keyword
heuristics when no LLM is configured.

### LLM configuration (optional)

The default is DeepSeek `deepseek-flash`, but any OpenAI-compatible endpoint works
(OpenAI / Ollama / vLLM / OneAPI):

```bash
export SUDOKU_LLM_API_KEY=sk-...
export SUDOKU_LLM_BASE_URL=https://api.deepseek.com   # or https://api.openai.com/v1
export SUDOKU_LLM_MODEL=deepseek-flash
```

Local Ollama (no paid key):

```bash
ollama run qwen2.5:7b
export SUDOKU_LLM_BASE_URL=http://localhost:11434/v1
export SUDOKU_LLM_API_KEY=local
export SUDOKU_LLM_MODEL=qwen2.5:7b
```

Without a key the web UI greys out **LLM rules** and shows "no key · local heuristics".

### Live SudokuPad view (read-only)

The main board is now a **read-only mirror of SudokuPad**, not a separate SVG board: a local
Playwright Chromium opens the puzzle, crops the screenshot to the puzzle area (any grid size) and
streams it to the page. Step playback clicks and types the placements in SudokuPad itself, so
digits, cage outlines and SudokuPad's own rendering are what you see; the web page only displays an
image and cannot be clicked.

Requirements: Node.js + Playwright/Chromium (`npm i playwright` in `tools/`, or the paths already
used by `tools/sudokupad_bridge.mjs`). Without them the badge reports that the mirror failed.

The browser is pooled as a single session and recycled after 10 minutes idle:

```bash
YSUDOKU_LIVE_IDLE_SECONDS=600   # default; 0 disables recycling
YSUDOKU_LIVE_MIN_IDLE=0         # default; keep 0 to release the browser completely
```

A recycled session returns 410 and the UI restarts it automatically.

Frames are cached per step and the next two steps are prefetched in the background, so pressing
"next" reuses an existing screenshot instead of waiting for SudokuPad again.

The explanation layer (P2/P3/P4) is drawn as a transparent SVG overlay on top of the screenshot:
focus cells, unit/group boxes, candidate digits after an elimination, link lines, chips and
coloured groups. This keeps the mirror read-only and works for any grid size; SudokuPad's native
colour/line palette is not scripted.

### Rule sheet for vision models

The rule compiler sends the model a **rendered rule sheet**: grid coordinates, a number on every
drawn element, outside clues and a text legend mapping each number to its element id, cells and
attributes.  `deepseek-flash` accepts it as a PNG data URI; this resolves spatial rules (arrow
direction, which side a clue is on, which circle surrounds which cells) that text alone loses.
If the model rejects images, the compiler falls back to the text worksheet.  The sheet is also
shown in the web UI under **规则图（视觉）**.

### Global outside clues (optional)

Some puzzles put *global* clues outside the grid: Full Rank (the rank of a line among all 36
directional numbers), X-Sums, or even "every clue value appears twice, once as each type".
Cell-by-cell propagation cannot handle those. Install the optional CP-SAT solver:

```bash
pip install "ysudoku[global-clues]"     # or simply: pip install ortools
```

YSudoku encodes the grid, all 36 directional line numbers, the rank comparisons, the prefix sums
and the unknown type pairing into CP-SAT. *Double Take* by Flinty & palpot (`439w9opvs4`) solves in
about 5 seconds and recovers the 12-clue type assignment; the result is checked against the
official solution. Without OR-Tools such puzzles are reported as unsupported (with a hint), never
silently stalled.

### Rule cache

Compiled specs are cached by a fingerprint of *puzzle id + rules text + element inventory*:

- `.cache/rules/<id>.json` — written automatically after a successful LLM compile (gitignored)
- `rules/<id>.json` — shared cache, written by `--save-rules`, safe to commit and reuse

```bash
python3 -m ysudoku --save-rules <sudokupad-url>   # write to the shared cache
python3 -m ysudoku --no-cache <sudokupad-url>     # bypass the cache
```

Health check: `GET /api/health` reports LLM availability, model name and cache counts.

### Repair after getting stuck

If the spec compiles but the solver stalls, YSudoku sends **diagnostics** (techniques tried, unused
elements, warnings) back to the LLM and asks for a corrected full spec. The new spec must still pass
validation against the official solution. This only re-interprets the rules; the answer is never
sent to the model.

The **Allow refutation** checkbox lets the solver try assumption/contradiction as a last resort.
Those steps are labelled **T4** and explicitly marked as refutation, not direct deduction.

For the boundaries of LLM-authored rules, the typed DSL and its trust guardrails, see
[docs/rule-dsl.md](docs/rule-dsl.md) (Chinese).

## Supported constraints

| Category | Constraints |
|---|---|
| Sums | Killer cages (combinations + per-cell matching), Little Killer, 45 rule (innies/outies) |
| Lines | Thermo, arrow (experimental), palindrome, Renban, German/Dutch Whisper, between, consecutive |
| Dots / clues | Kropki (consecutive / 1:2), XV, quadruple circles (`?` supported) |
| Global | Diagonal, anti-knight, anti-king, jigsaw regions, 6×6, modular 2×2, entropy 2×2 |
| Chaos | Cages, quadruples, **region-count rules** (trisection / unbalanced circles) with exact count GAC + connectivity reachability |
| Other | Odd/even, clone, sandwich, skyscraper, region-sum line |
| Outside clues | Sandwich / skyscraper / X-Sums; Full Rank + unknown type pairing via optional CP-SAT |
| L2 custom | Typed predicates (`sum` / `count` / `ordered` / `all_different` / …), composed by the LLM, marked as *hypothesis* |

Technique tiers: T1 constraint-local → T2 naked/hidden singles, locked candidates, subsets, 45 rule →
T3 X-Wing, XY-Wing, W-Wing, **colouring** (single-digit strong links, A/B colours, colour wrap/trap),
**3D Medusa** (cell+digit candidates, strong/weak links), **X-Chain**, **ALS-XZ** →
T4 refutation (always on in the UI; `--no-chains` disables it in the CLI).
Every step carries a structured reason and an animation script; T4 steps are always marked.

## Animation and UI

- Left: candidates, region borders, constraint outlines (cages, arrows, fish links)
- Right: conclusion, premises, effects; expandable rule interpretation and step list
- Light theme by default (SudokuPad is light), dark toggle available and remembered
- **Local history**: every analysis is recorded in `.cache/history.json` (title, time, status,
  steps); the History panel reopens a puzzle or clears the list. Nothing leaves the machine.
- Responsive phone layout: stacked header, full-width board, touch-sized controls
- Controls: previous / next / play-pause / speed / scrubber / arrow keys
- **SudokuPad original + annotations**: embeds the official page and projects highlights/links on
  top. Use **Calibrate** (three sliders) to align; the overlay is click-through, so the original
  stays fully playable. Cross-origin limits apply: it does not read SudokuPad's state or sync moves.
- Each step's `visual` field is a small script — `focus`, `groups`, `links`, `chips` — that the
  front-end replays as highlights, strokes, candidate strikes and pops.

## Layout

```
ysudoku/
  decode.py      SudokuPad LZW + zipper decoder (field-by-field verified against the app)
  model.py       grid / regions / cages / lines / circles / dots / arrows
  sudokupad.py   link parsing, API fetch, local cache
  rules.py       element inventory, LLM/heuristic specs, constraint compilation
  rulecache.py   rule cache (local + shared)
  llm.py         OpenAI-compatible client + rule-compilation prompts
  predicate.py   typed predicate AST for L2 custom rules
  state.py       candidate domains, event log, units
  constraints.py propagation + checking for every constraint
  techniques.py  human techniques (45 rule, wings, colouring, Medusa, chains, ALS)
  chaos.py       chaos-construction search (region + digit)
  solve.py       scheduler, audit, answer checks
  search.py      referee only: uniqueness, refutation, hints
  narrate.py     explanations + animation scripts
  server.py      stdlib HTTP server
  static/        single-page front-end (vanilla JS/CSS/SVG)
tests/           decoder, engine, plain sudoku, LLM mock/repair, techniques
fixtures/        demo puzzles and raw payloads
rules/           shared rule specs (committable)
docs/            rule DSL and trust design
```

## Known limitations

- **Chaos construction** is a search solver, not step-by-step human reasoning. Region-count rules
  now use exact GAC and connectivity reachability, but *Tringle and Cross* still times out at ~0.9M nodes.
  Vision/region-border rules are not supported.
- **Full Rank / mixed outside-clue types** require the optional OR-Tools dependency; without it
  they are reported as unsupported (Double Take is the regression case).
- **Fog puzzles / puzzles with a scratch table** are unsupported (the grid payload itself is incomplete).
- Author-specific drawing conventions depend on LLM compilation; without a key, heuristics may misread them.
- Hard puzzles can still stall. The solver reports *stuck* instead of silently brute-forcing.
- Arrow semantics are still being verified and marked experimental.
- Rule repair needs an LLM; without one you get heuristics plus local solving.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

CI runs the same suite on every push.

## Roadmap

- **P2 (mostly done)**: XY-Wing / W-Wing / refutation, sandwich, skyscraper, region-sum line,
  clone, odd/even, 6×6; remaining: f-puzzles import
- **P2.5 (first version)**: typed rule DSL — the LLM composes new constraints from a fixed predicate
  vocabulary (no generated code); every authored rule carries a source and a *hypothesis* badge and
  can be falsified by the official solution. See [docs/rule-dsl.md](docs/rule-dsl.md).
- **P3 (partial)**: chaos search and region-count propagation are in; next is explainable
  region-by-region reasoning and stronger region GAC.

## Contributing

PRs are welcome. When adding a constraint or technique, include a publicly accessible SudokuPad
link as a regression case and make sure `python3 -m unittest discover -s tests` passes. Shared rule
specs live in `rules/`; the format is documented in [rules/README.md](rules/README.md).

## License

MIT — see [LICENSE](LICENSE).

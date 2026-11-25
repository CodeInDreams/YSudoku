# Changelog

User-facing features and fixes are recorded here. See [CONTRIBUTING.md](CONTRIBUTING.md) for version and release rules.

## Unreleased

Target version: 1.2.1-beta

### Added

- Consume required digits through generic constraint protocols (`digit_demands`, `sum_terms`, `region_counts`, `choice_premise`) instead of rule-name branches.
- Apply a circle's required digit to a partial Chaos Construction region. Tringle and Cross now derives `R3C2 != 9` and places `R3C3 = 9`.

### Fixed

- Do not auto-regenerate missing frames after a solve failure; wait for an explicit retry.
- Keep region digit explanation notes out of `Step.events`, fixing `'str' object has no attribute 'to_dict'`.
- Match the board preview's aspect ratio, crop, and dark-mode dimming to the playback frames. Use the rendered opening frame once it is available.
- Keep the full outer border when cropping the playable grid.

## [1.2.0] - 2026-11-24

### Added

- Solve **The Smiler** by combining shaded inversion clues with 2×2, perimeter, and connectivity constraints. The walkthrough displays the two colour regions and explains how digit and colour deductions inform each other.
- Solve **Fidget** by combining Between Line endpoint choices with all-different house matching. Between lines now propagate back to their endpoints, and Renban deductions account for equal cells on palindrome and clone clues. Walkthroughs include the supporting cases.
- Solve **Renban Lies** with separate deductions for written digits and effective values. This supports liar-cell puzzles that combine the same model with Renban, Kropki, and XV clues.

### Fixed

- Distinguish Between, pink Renban, and grey palindrome lines in local rule detection. A consecutive Renban set no longer becomes a separate consecutive-line constraint.
- Count the starting cell of a looped Renban once when the line returns to it.
- Recover supplied answers when a SudokuPad canvas pads the playable grid with blank note cells.

## [1.1.0-beta] - 2026-11-24

### Added

- Import supported f-puzzles (`fpuz`) layouts served by SudokuPad, including puzzles opened through a Logic Masters link. Imported clues include killer cages, standard Kropki dots, and Dutch Whisper lines.
- Extend Chaos Construction deductions to uncoloured frontier cells and compare viable region shapes across fragments. The walkthrough explains new same-region and different-region relationships. Full Chaos Construction solving remains in development.

### Changed

- Shorten candidate and region-count refutation paths by replaying deductions and retaining shorter paths that reach the same result. Candidate summaries appear only when the solver ultimately stalls.

### Fixed

- Avoid interpreting the ordinary word “between” in dot rules as a Between Line clue.
- Report liar-cell puzzles that use separate written digits and effective values as unsupported. This prevents false rule conflicts caused by applying value-based constraints to written digits.

## [1.0.0] - 2026-11-23

- First stable release. Open SudokuPad puzzles or compatible Logic Masters links and replay bilingual, step-by-step Sudoku explanations.
- Reuse shared puzzle history and cached walkthroughs, with a choice to regenerate after solver or language changes.
- Self-host with local or optional LLM rule parsing, concurrency and usage limits, and configurable storage.

[1.2.0]: https://github.com/CodeInDreams/YSudoku/releases/tag/v1.2.0
[1.1.0-beta]: https://github.com/CodeInDreams/YSudoku/releases/tag/v1.1.0-beta
[1.0.0]: https://github.com/CodeInDreams/YSudoku/releases/tag/v1.0.0

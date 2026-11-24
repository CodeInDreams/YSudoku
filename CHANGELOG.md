# Changelog

User-facing features and fixes are recorded here. See [CONTRIBUTING.md](CONTRIBUTING.md) for version and release rules.

## Unreleased

Target version: 1.2.0-beta

### Added

- Add separate written-digit and effective-value deductions for liar-cell puzzles with Renban, Kropki and XV clues. The walkthrough shows both domains and explains how the liar-cell rules link them.

### Fixed

- Treat the closing point of a looped Renban as part of the same cell. Recover supplied answers when a SudokuPad canvas pads the playable grid with blank note cells.

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

[1.1.0-beta]: https://github.com/CodeInDreams/YSudoku/releases/tag/v1.1.0-beta
[1.0.0]: https://github.com/CodeInDreams/YSudoku/releases/tag/v1.0.0

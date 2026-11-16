"""Render a labelled rule sheet as a PNG, using only the standard library.

The image is intentionally schematic: grid, coordinates, element numbers and
outside clues.  The text legend in the prompt maps each number to its element
id and exact cells, so the model gets both spatial layout and precise data.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

CELL = 64
MARGIN = 58
GRID = CELL * 9

_DIGITS = {
    "0": ["###", "#.#", "#.#", "#.#", "###"],
    "1": [".#.", "##.", ".#.", ".#.", "###"],
    "2": ["###", "..#", "###", "#..", "###"],
    "3": ["###", "..#", "###", "..#", "###"],
    "4": ["#.#", "#.#", "###", "..#", "..#"],
    "5": ["###", "#..", "###", "..#", "###"],
    "6": ["###", "#..", "###", "#.#", "###"],
    "7": ["###", "..#", "..#", "..#", "..#"],
    "8": ["###", "#.#", "###", "#.#", "###"],
    "9": ["###", "#.#", "###", "..#", "###"],
    "?": ["###", "..#", ".##", "...", ".#."],
}

_COLORS = {
    "arrow": (200, 40, 40),
    "thermo": (210, 90, 30),
    "line": (40, 120, 80),
    "cage": (170, 120, 20),
    "circle": (120, 60, 180),
    "quadruple": (120, 60, 180),
    "dot": (40, 80, 180),
    "marker": (120, 60, 180),
    "clue": (20, 20, 20),
}


class Canvas:
    def __init__(self, width: int, height: int):
        self.w, self.h = width, height
        self.px = bytearray(b"\xff" * (width * height * 3))

    def _set(self, x: int, y: int, color) -> None:
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            self.px[i:i + 3] = bytes(color)

    def rect(self, x0: int, y0: int, x1: int, y1: int, color) -> None:
        for y in range(max(0, y0), min(self.h, y1)):
            for x in range(max(0, x0), min(self.w, x1)):
                self._set(x, y, color)

    def line(self, x0: int, y0: int, x1: int, y1: int, color, width: int = 1) -> None:
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            for ox in range(-width // 2, width // 2 + 1):
                for oy in range(-width // 2, width // 2 + 1):
                    self._set(x0 + ox, y0 + oy, color)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def disk(self, cx: int, cy: int, r: int, color) -> None:
        for y in range(cy - r, cy + r + 1):
            for x in range(cx - r, cx + r + 1):
                if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                    self._set(x, y, color)

    def text(self, x: int, y: int, text: str, scale: int, color) -> None:
        """Draw digits only; unknown characters are skipped."""
        cursor = x
        for ch in str(text):
            glyph = _DIGITS.get(ch)
            if glyph:
                for gy, row in enumerate(glyph):
                    for gx, bit in enumerate(row):
                        if bit == "#":
                            self.rect(cursor + gx * scale, y + gy * scale,
                                      cursor + (gx + 1) * scale, y + (gy + 1) * scale, color)
            cursor += 4 * scale


def _png(path: Path, canvas: Canvas) -> None:
    raw = bytearray()
    for y in range(canvas.h):
        raw.append(0)
        raw.extend(canvas.px[y * canvas.w * 3:(y + 1) * canvas.w * 3])

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)

    header = struct.pack(">IIBBBBB", canvas.w, canvas.h, 8, 2, 0, 0, 0)
    payload = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def render(puzzle, elements, path) -> dict[int, str]:
    """Render a rule sheet; return {number: element_id} for the legend."""
    path = Path(path)
    width = GRID + 2 * MARGIN
    height = GRID + 2 * MARGIN
    canvas = Canvas(width, height)

    def cell_xy(cell: int) -> tuple[int, int]:
        r, c = divmod(cell, puzzle.size)
        return MARGIN + c * CELL, MARGIN + r * CELL

    # grid
    for i in range(10):
        color = (40, 40, 40) if i % 3 == 0 else (175, 175, 175)
        width_line = 2 if i % 3 == 0 else 1
        x = MARGIN + i * CELL
        y = MARGIN + i * CELL
        canvas.line(x, MARGIN, x, MARGIN + GRID, color, width_line)
        canvas.line(MARGIN, y, MARGIN + GRID, y, color, width_line)

    # coordinates
    for i in range(puzzle.size):
        canvas.text(MARGIN + i * CELL + CELL // 2 - 6, MARGIN - 26, str(i + 1), 3, (60, 60, 60))
        canvas.text(MARGIN - 30, MARGIN + i * CELL + CELL // 2 - 8, str(i + 1), 3, (60, 60, 60))

    # givens
    for cell, value in puzzle.givens.items():
        x, y = cell_xy(cell)
        canvas.text(x + CELL // 2 - 14, y + CELL // 2 - 15, str(value), 6, (20, 20, 20))

    legend: dict[int, str] = {}
    for number, element in enumerate(elements, 1):
        legend[number] = element.id
        color = _COLORS.get(element.kind, (80, 80, 80))
        cells = element.cells
        if element.kind in ("arrow", "thermo", "line", "between", "renban", "palindrome", "region_sum") and len(cells) > 1:
            points = [cell_xy(c) for c in cells]
            for (x0, y0), (x1, y1) in zip(points, points[1:]):
                canvas.line(x0 + CELL // 2, y0 + CELL // 2, x1 + CELL // 2, y1 + CELL // 2, color, 3)
        if not cells:
            continue
        texts = (element.attrs or {}).get("texts") or []
        if element.kind in ("circle", "quadruple", "marker") and texts:
            xs = [cell_xy(c)[0] for c in cells]
            ys = [cell_xy(c)[1] for c in cells]
            cx = (min(xs) + max(xs)) // 2 + CELL // 2
            cy = (min(ys) + max(ys)) // 2 + CELL // 2
            radius = max(18, (max(xs) - min(xs)) // 2)
            for deg in range(0, 360, 6):
                import math
                a = math.radians(deg)
                canvas.disk(int(cx + radius * math.cos(a)), int(cy + radius * math.sin(a)), 1, color)
            for cell, text in zip(cells, texts):
                if text and text != "?":
                    tx, ty = cell_xy(cell)
                    canvas.text(tx + CELL // 2 - 8, ty + CELL // 2 - 8, str(text), 3, color)
            legend[number] = element.id
            x, y = cell_xy(cells[0])
        canvas.disk(x + 14, y + 14, 11, color)
        canvas.text(x + 9, y + 9, str(number), 2, (255, 255, 255))

    # outside clues
    for clue in puzzle.clues:
        if clue.side in ("top", "bottom"):
            x = MARGIN + clue.index * CELL + CELL // 2 - 8
            y = 14 if clue.side == "top" else MARGIN + GRID + 16
        else:
            x = 12 if clue.side == "left" else MARGIN + GRID + 16
            y = MARGIN + clue.index * CELL + CELL // 2 - 8
        canvas.text(x, y, str(clue.value), 3, (20, 20, 20))

    _png(path, canvas)
    return legend


def legend_text(puzzle, elements, legend: dict[int, str]) -> str:
    lines = ["Numbers on the image identify elements (legend):"]
    by_id = {element.id: element for element in elements}
    for number, element_id in legend.items():
        element = by_id[element_id]
        cells = " ".join(f"R{c // puzzle.size + 1}C{c % puzzle.size + 1}" for c in element.cells)
        attrs = ", ".join(f"{k}={v}" for k, v in (element.attrs or {}).items())
        lines.append(f"#{number} = {element_id} ({element.kind}): {cells}" + (f" [{attrs}]" if attrs else ""))
    if puzzle.clues:
        lines.append("Outside clues (side, index, value): " + "; ".join(
            f"{c.side} {c.index + 1}={c.value}" for c in puzzle.clues
        ))
    return "\n".join(lines)

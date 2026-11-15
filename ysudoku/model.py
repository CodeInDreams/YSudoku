"""Normalised puzzle model for SudokuPad payloads."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import dist


@dataclass
class Cage:
    id: int
    cells: list[int]
    total: int | None
    unique: bool = True


@dataclass
class Line:
    id: int
    cells: list[int]
    color: str
    thickness: float
    closed: bool = False
    raw_points: list[list[float]] = field(default_factory=list)


@dataclass
class Circle:
    id: int
    center: tuple[float, float]
    cells: list[int]
    fill: str
    border: str
    thickness: float
    texts: list[str] = field(default_factory=list)


@dataclass
class Arrow:
    id: int
    circle: int
    arm: list[int]
    color: str = "#000000"
    points: list[list[float]] = field(default_factory=list)


@dataclass
class Dot:
    id: int
    center: tuple[float, float]
    cells: list[int]
    fill: str


@dataclass
class TextMark:
    id: int
    pos: tuple[float, float]
    text: str


@dataclass
class Puzzle:
    puzzle_id: str
    size: int
    title: str
    author: str
    rules_text: str
    givens: dict[int, int]
    regions: list[list[int]]
    cages: list[Cage]
    lines: list[Line]
    circles: list[Circle]
    dots: list[Dot]
    markers: list[Circle]
    arrows: list[Arrow]
    texts: list[TextMark]
    solution: list[int] | None
    raw: dict = field(repr=False, default_factory=dict)

    # ---------------------------------------------------------------- geometry
    def cell(self, r: int, c: int) -> int:
        return r * self.size + c

    def rc(self, cell: int) -> tuple[int, int]:
        return divmod(cell, self.size)

    @property
    def cells(self) -> range:
        return range(self.size * self.size)

    def box_regions(self) -> list[list[int]]:
        """Return the standard box regions for this size."""
        n = self.size
        if n == 9:
            h, w = 3, 3
        elif n == 6:
            h, w = 2, 3
        elif n == 4:
            h, w = 2, 2
        else:
            h = w = int(n ** 0.5)
        out = []
        for br in range(0, n, h):
            for bc in range(0, n, w):
                out.append([self.cell(r, c) for r in range(br, br + h)
                            for c in range(bc, bc + w)])
        return out

    def is_standard_boxes(self) -> bool:
        boxes = {frozenset(b) for b in self.box_regions()}
        return len(self.regions) == len(boxes) and all(
            frozenset(r) in boxes for r in self.regions
        )

    def summary(self) -> dict:
        return {
            "id": self.puzzle_id,
            "size": self.size,
            "title": self.title,
            "author": self.author,
            "givens": len(self.givens),
            "regions": "standard" if self.is_standard_boxes() else f"jigsaw({len(self.regions)})",
            "cages": len(self.cages),
            "lines": len(self.lines),
            "circles": len(self.circles),
            "dots": len(self.dots),
        }


# ------------------------------------------------------------------ utilities


def _cell_from_xy(x: float, y: float, n: int) -> int | None:
    """Snap an (x=col, y=row) point to a cell id if it sits on a cell centre."""
    c = int(x)
    r = int(y)
    if abs(x - (c + 0.5)) <= 0.35 and abs(y - (r + 0.5)) <= 0.35:
        if 0 <= r < n and 0 <= c < n:
            return r * n + c
    return None


def _path_cells(points: list[list[float]], n: int) -> list[int]:
    """Map a polyline to the ordered cells it passes through.

    Points are (x=col, y=row).  Interior samples must sit near a cell centre;
    the two endpoints are snapped with floor() so slightly offset arrow tips
    still register.
    """
    if not points:
        return []
    pts = [(float(x), float(y)) for x, y in points]
    cells: list[int] = []

    def push(cell: int) -> None:
        if not cells or cells[-1] != cell:
            cells.append(cell)

    x, y = pts[0]
    c, r = int(x), int(y)
    if 0 <= r < n and 0 <= c < n:
        push(r * n + c)

    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        steps = max(1, int(dist((x0, y0), (x1, y1)) * 8))
        for k in range(steps + 1):
            x = x0 + (x1 - x0) * k / steps
            y = y0 + (y1 - y0) * k / steps
            c, r = int(x), int(y)
            if not (0 <= r < n and 0 <= c < n):
                continue
            if abs(x - (c + 0.5)) > 0.3 or abs(y - (r + 0.5)) > 0.3:
                continue
            push(r * n + c)

    x, y = pts[-1]
    c, r = int(x), int(y)
    if 0 <= r < n and 0 <= c < n:
        push(r * n + c)
    return cells


def _line_cells(points: list[list[float]], n: int) -> list[int]:
    cells: list[int] = []
    for x, y in points:
        cell = _cell_from_xy(float(x), float(y), n)
        if cell is None:
            return []  # decorative line (border, arrow head, ...)
        if not cells or cells[-1] != cell:
            cells.append(cell)
    return cells


def _norm_color(value: str | None, default: str = "#000000") -> str:
    if not value:
        return default
    value = str(value).strip()
    if not value.startswith("#"):
        value = "#" + value
    if len(value) == 5:  # #dddf -> #ddddddff shorthand from the zipper
        value = "#" + "".join(ch * 2 for ch in value[1:])
    return value.lower()


def _dot_cells(x: float, y: float, n: int) -> list[int]:
    """Return the two cells touching a dot drawn on a cell edge."""
    fx, fy = x - int(x), y - int(y)
    if abs(fx - 0.5) < 0.02 and abs(fy) < 0.02:
        c = int(x)
        r = int(y)
        return [cell for cell in ((r - 1) * n + c, r * n + c) if 0 <= cell < n * n]
    if abs(fy - 0.5) < 0.02 and abs(fx) < 0.02:
        r = int(y)
        c = int(x)
        return [cell for cell in (r * n + c - 1, r * n + c) if 0 <= cell < n * n]
    return []


def _cell_from_coords(item, n: int) -> int | None:
    if isinstance(item, dict):
        r, c = item.get("r"), item.get("c")
    elif isinstance(item, (list, tuple)) and len(item) == 2:
        r, c = item
    else:
        return None
    if r is None or c is None:
        return None
    return int(r) * n + int(c)


def parse_puzzle(data: dict, puzzle_id: str = "") -> Puzzle:
    cells = data.get("cells") or []
    regions_raw = data.get("regions") or []
    total_region_cells = sum(len(r) for r in regions_raw)
    if total_region_cells:
        n = int(round(total_region_cells ** 0.5))
    else:
        n = len(cells) or 9
    if len(cells) > n or any(len(row) > n for row in cells):
        raise ValueError(
            f"网格数据异常（期望 {n}x{n}，实际 {len(cells)} 行）；"
            "雾战/带草稿表的题目暂不支持"
        )
    meta = data.get("metadata") or {}

    givens: dict[int, int] = {}
    for r, row in enumerate(cells):
        for c, cell in enumerate(row):
            value = cell.get("value") if isinstance(cell, dict) else None
            if value is None or value == "":
                continue
            try:
                givens[r * n + c] = int(value)
            except (TypeError, ValueError):
                continue

    regions: list[list[int]] = []
    for region in data.get("regions") or []:
        parsed = [p for p in (_cell_from_coords(item, n) for item in region) if p is not None]
        if parsed:
            regions.append(parsed)
    if not regions:
        regions = []

    cages: list[Cage] = []
    for i, cage in enumerate(data.get("cages") or []):
        cells_in = [p for p in (_cell_from_coords(item, n) for item in cage.get("cells") or []) if p is not None]
        if not cells_in:
            continue
        total = cage.get("value")
        if isinstance(total, str):
            total = int(total) if total.strip().lstrip("-").isdigit() else None
        cages.append(Cage(i, cells_in, total, bool(cage.get("unique", True))))

    lines: list[Line] = []
    for i, line in enumerate(data.get("lines") or []):
        points = line.get("wayPoints") or []
        if not points:
            continue
        cells_in = _path_cells(points, n)
        lines.append(
            Line(
                i,
                cells_in,
                _norm_color(line.get("color") or line.get("c")),
                float(line.get("thickness") or 0),
                closed=bool(points and points[0] == points[-1]),
                raw_points=[[float(p[0]), float(p[1])] for p in points],
            )
        )

    circles: list[Circle] = []
    markers: list[Circle] = []
    dots: list[Dot] = []
    for i, over in enumerate(data.get("overlays") or []):
        center = over.get("center") or [0, 0]
        x, y = float(center[0]), float(center[1])
        w = float(over.get("width") or 0)
        h = float(over.get("height") or 0)
        if w < 0.2 or h < 0.2:
            continue  # plain text mark, collected separately
        fill = _norm_color(over.get("backgroundColor"), "#ffffff")
        border = _norm_color(over.get("borderColor") or over.get("color"), "#000000")
        thick = float(over.get("thickness") or 0)
        if w < 0.6 and h < 0.6:
            pair = _dot_cells(x, y, n)
            if pair:
                dots.append(Dot(i, (x, y), pair, fill))
            continue
        if float(x).is_integer() and float(y).is_integer():
            cx, cy = int(x), int(y)
            around = [
                (cy - 1) * n + (cx - 1), (cy - 1) * n + cx,
                cy * n + (cx - 1), cy * n + cx,
            ]
            circles.append(
                Circle(i, (x, y), [c for c in around if 0 <= c < n * n], fill, border, thick)
            )
        elif abs(x - int(x) - 0.5) < 0.01 and abs(y - int(y) - 0.5) < 0.01:
            cell = int(y) * n + int(x)
            markers.append(Circle(i, (x, y), [cell], fill, border, thick))

    texts: list[TextMark] = []
    for i, over in enumerate(data.get("overlays") or []):
        text = over.get("text")
        if not text:
            continue
        center = over.get("center") or [0, 0]
        texts.append(TextMark(i, (float(center[0]), float(center[1])), str(text)))

    # Attach the text marks that sit inside a circle (quadruple digits).
    for circle in circles:
        near = [
            t for t in texts
            if dist(t.pos, circle.center) <= 0.45 and (t.text.isdigit() or t.text == "?")
        ]
        near.sort(key=lambda t: (t.pos[1], t.pos[0]))
        circle.texts = [t.text for t in near]

    arrows: list[Arrow] = []
    for i, arrow in enumerate(data.get("arrows") or []):
        points = arrow.get("wayPoints") or []
        cells_in = _path_cells(points, n)
        if len(cells_in) < 2:
            continue
        # SudokuPad's arrow tool starts at the circle and draws towards the head.
        head = cells_in[0]
        arm = cells_in[1:]
        arrows.append(Arrow(i, head, arm, _norm_color(arrow.get("color")),
                           [[float(p[0]), float(p[1])] for p in points]))

    solution = None
    raw_solution = meta.get("solution")
    if isinstance(raw_solution, str) and len(raw_solution) == n * n:
        solution = [int(ch) if ch.isdigit() else 0 for ch in raw_solution]

    return Puzzle(
        puzzle_id=puzzle_id or data.get("id", ""),
        size=n,
        title=meta.get("title", "Untitled"),
        author=meta.get("author", ""),
        rules_text=(meta.get("rules") or "").strip(),
        givens=givens,
        regions=regions,
        cages=cages,
        lines=lines,
        circles=circles,
        dots=dots,
        markers=markers,
        arrows=arrows,
        texts=texts,
        solution=solution,
        raw=data,
    )

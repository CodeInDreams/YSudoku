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
class XVClue:
    id: int
    center: tuple[float, float]
    cells: list[int]
    mark: str


@dataclass
class Clue:
    id: int
    pos: tuple[float, float]
    side: str  # top | bottom | left | right
    index: int  # 0-based row for left/right, column for top/bottom
    value: int


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
    xv_clues: list[XVClue]
    markers: list[Circle]
    arrows: list[Arrow]
    clues: list[Clue]
    texts: list[TextMark]
    solution: list[int] | None
    rule_sheet: str = ""
    source_url: str = ""
    raw: dict = field(repr=False, default_factory=dict)

    # ---------------------------------------------------------------- geometry
    def cell(self, r: int, c: int) -> int:
        return r * self.size + c

    def rc(self, cell: int) -> tuple[int, int]:
        return divmod(cell, self.size)

    @property
    def cells(self) -> range:
        return range(self.size * self.size)

    @property
    def has_outside_clues(self) -> bool:
        return bool(self.clues) or any(
            not (0 <= r < self.size and 0 <= c < self.size)
            for arrow in self.arrows for r, c in (arrow.points or [])
        )

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

    @property
    def is_chaos(self) -> bool:
        text = (self.rules_text or "").lower()
        return any(key in text for key in (
            "chaos construction", "chaos sudoku", "regions are hidden",
            "hidden regions", "regions must be determined",
        )) or (not self.regions and "chaos" in text)

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
            "clues": len(self.clues),
        }


# ------------------------------------------------------------------ utilities


def _cell_from_xy(x: float, y: float, n: int) -> int | None:
    """Snap a (row, col) point to a cell id if it sits on a cell centre."""
    r = int(x)
    c = int(y)
    if abs(x - (r + 0.5)) <= 0.35 and abs(y - (c + 0.5)) <= 0.35:
        if 0 <= r < n and 0 <= c < n:
            return r * n + c
    return None


def _svg_points(duration: str, n: int, cell_size: float = 64.0) -> list[list[float]]:
    """Convert a simple SVG path (M/L/Q/C/H/V) to cell-centre coordinates."""
    import re
    tokens = re.findall(r"[MLQCHVmlqchv]|-?\d+(?:\.\d+)?", str(duration or ""))
    if not tokens:
        return []
    points: list[list[float]] = []
    x = y = 0.0
    cmd = "M"
    i = 0
    while i < len(tokens):
        if tokens[i].isalpha():
            cmd = tokens[i]
            i += 1
            continue
        try:
            if cmd in "ML":
                x, y = float(tokens[i]), float(tokens[i + 1]); i += 2
                points.append([y / cell_size, x / cell_size])
            elif cmd in "HV":
                if cmd == "H":
                    x = float(tokens[i]); i += 1
                else:
                    y = float(tokens[i]); i += 1
                points.append([y / cell_size, x / cell_size])
            elif cmd in "QC":
                nums = [float(tokens[i + k]) for k in range(4)]
                i += 4
                points.append([nums[1] / cell_size, nums[0] / cell_size])
                points.append([nums[3] / cell_size, nums[2] / cell_size])
                x, y = nums[2], nums[3]
            else:
                i += 1
        except (IndexError, ValueError):
            break
    return points


def _path_cells(points: list[list[float]], n: int) -> list[int]:
    """Map a polyline to the ordered cells it passes through.

    Points are (row, col).  Interior samples must sit near a cell centre;
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
    r, c = int(x), int(y)
    if 0 <= r < n and 0 <= c < n:
        push(r * n + c)

    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        steps = max(1, int(dist((x0, y0), (x1, y1)) * 8))
        for k in range(steps + 1):
            x = x0 + (x1 - x0) * k / steps
            y = y0 + (y1 - y0) * k / steps
            r, c = int(x), int(y)
            if not (0 <= r < n and 0 <= c < n):
                continue
            if abs(x - (r + 0.5)) > 0.3 or abs(y - (c + 0.5)) > 0.3:
                continue
            push(r * n + c)

    x, y = pts[-1]
    r, c = int(x), int(y)
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
    """Return the two cells touching a dot drawn on a cell edge (x=row, y=col)."""
    fx, fy = x - int(x), y - int(y)
    if abs(fx - 0.5) < 0.02 and abs(fy) < 0.02:
        r = int(x)
        c = int(y)
        return [cell for cell in (r * n + c - 1, r * n + c) if 0 <= cell < n * n]
    if abs(fy - 0.5) < 0.02 and abs(fx) < 0.02:
        r = int(x)
        c = int(y)
        return [cell for cell in ((r - 1) * n + c, r * n + c) if 0 <= cell < n * n]
    return []


def _cell_from_coords(item, n: int, one_based: bool = False) -> int | None:
    if isinstance(item, dict):
        r, c = item.get("r"), item.get("c")
    elif isinstance(item, (list, tuple)) and len(item) == 2:
        r, c = item
    else:
        return None
    if r is None or c is None:
        return None
    r, c = int(r), int(c)
    if one_based:
        r, c = r - 1, c - 1
    if r < 0 or c < 0 or r >= n or c >= n:
        return None
    return r * n + c


def parse_puzzle(data: dict, puzzle_id: str = "") -> Puzzle:
    cells = data.get("cells") or []
    regions_raw = data.get("regions") or []
    total_region_cells = sum(len(r) for r in regions_raw)
    if total_region_cells:
        n = int(round(total_region_cells ** 0.5))
    else:
        n = len(cells) or 9
    if len(cells) > n or any(len(row) > n for row in cells):
        # SudokuPad/LMD often pads the playable n x n grid with an outer ring
        # of rank/outside clues.  Keep only the playable top-left n x n area.
        if len(cells) >= n and all(len(row) >= n for row in cells[:n]):
            cells = [row[:n] for row in cells[:n]]
        else:
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
    one_based = any(
        (isinstance(item, (list, tuple)) and len(item) == 2
         and (int(item[0]) == n or int(item[1]) == n))
        for region in (data.get("regions") or []) for item in region
    )
    for region in data.get("regions") or []:
        parsed = [p for p in (_cell_from_coords(item, n, one_based) for item in region)
                  if p is not None]
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
        points = line.get("wayPoints") or _svg_points(line.get("duration"), n)
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
    xv_clues: list[XVClue] = []
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
            mark = str(over.get("text") or "").strip().upper()
            if pair and mark in ("X", "V"):
                xv_clues.append(XVClue(i, (x, y), pair, mark))
            elif pair:
                dots.append(Dot(i, (x, y), pair, fill))
            continue
        if float(x).is_integer() and float(y).is_integer():
            cr, cc = int(x), int(y)
            around = [
                (cr - 1) * n + (cc - 1), (cr - 1) * n + cc,
                cr * n + (cc - 1), cr * n + cc,
            ]
            circles.append(
                Circle(i, (x, y), [c for c in around if 0 <= c < n * n], fill, border, thick)
            )
        elif abs(x - int(x) - 0.5) < 0.01 and abs(y - int(y) - 0.5) < 0.01:
            cell = int(x) * n + int(y)
            markers.append(Circle(i, (x, y), [cell], fill, border, thick))

    # Some editors store X/V as underlays rather than overlays.
    for i, over in enumerate(data.get("underlays") or []):
        mark = str(over.get("text") or "").strip().upper()
        if mark not in ("X", "V"):
            continue
        center = over.get("center") or [0, 0]
        pair = _dot_cells(float(center[0]), float(center[1]), n)
        if pair:
            xv_clues.append(XVClue(1000 + i, (float(center[0]), float(center[1])), pair, mark))

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

    clues: list[Clue] = []
    for source in (data.get("underlays") or []) + (data.get("overlays") or []):
        raw_text = source.get("text")
        if raw_text is None:
            continue
        text = str(raw_text).strip()
        if not text.isdigit():
            continue
        center = source.get("center") or [0, 0]
        x, y = float(center[0]), float(center[1])  # x=row, y=col
        side = index = None
        if x < 0:
            side, index = "top", int(y)
        elif x >= n:
            side, index = "bottom", int(y)
        elif y < 0:
            side, index = "left", int(x)
        elif y >= n:
            side, index = "right", int(x)
        if side is None or not (0 <= index < n):
            continue
        clues.append(Clue(len(clues), (x, y), side, index, int(text)))

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
        xv_clues=xv_clues,
        markers=markers,
        arrows=arrows,
        clues=clues,
        texts=texts,
        solution=solution,
        source_url=str(meta.get("source_url") or ""),
        raw=data,
    )

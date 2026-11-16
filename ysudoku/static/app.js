/* YSudoku front-end: animated, step-through explanations. */
(() => {
  const $ = (id) => document.getElementById(id);
  const SVG_NS = "http://www.w3.org/2000/svg";

  const S = {
    data: null, n: 9, dom: [], vals: [], regions: [], idx: -1,
    playing: false, timer: null, showCands: true, animating: false,
    live: { ready: false, step: -1, applied: 0, busy: false, pending: null, timer: null, url: "" },
  };

  const TIER_LABEL = { 1: "T1 直接推理", 2: "T2 基础技巧", 3: "T3 进阶技巧" };
  const THEME_KEY = "ysudoku.theme";
  const CAL_KEY = "ysudoku.overlay.cal";
  let cal = { x: 0.07, y: 0.07, size: 0.86 };
  try {
    const saved = JSON.parse(localStorage.getItem(CAL_KEY) || "{}");
    if (typeof saved.x === "number" && typeof saved.y === "number" && typeof saved.size === "number") {
      cal = saved;
    }
  } catch (err) { /* ignore */ }

  const el = (name, attrs = {}, parent = null) => {
    const node = document.createElementNS(SVG_NS, name);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    if (parent) parent.appendChild(node);
    return node;
  };

  const candPos = (n, v) => {
    const col = (v - 1) % 3, row = Math.floor((v - 1) / 3);
    const rows = Math.ceil(n / 3);
    return { x: 0.2 + col * 0.3, y: 0.22 + row * (0.56 / Math.max(rows, 1)) };
  };

  function cellOf(r, c) { return r * S.n + c; }
  function rc(cell) { return [Math.floor(cell / S.n), cell % S.n]; }

  async function checkHealth() {
    try {
      const res = await fetch("/api/health");
      const h = await res.json();
      const box = $("use-llm");
      const note = $("llm-note");
      if (!h.llm_available) {
        box.checked = false;
        box.disabled = true;
        note.textContent = "未配置 key · 本地启发式";
        note.title = "设置 SUDOKU_LLM_API_KEY 后重启即可启用 LLM 规则编译";
      } else {
        note.textContent = h.llm_model || "LLM 就绪";
        note.classList.add("ok");
        note.title = "规则由 LLM 编译；题面若带官方答案，只用于自检，不参与求解";
      }
    } catch (err) { /* health is best-effort */ }
  }

  // ------------------------------------------------------------------ load
  async function loadPuzzle(url, endpoint = "/api/solve") {
    if (!url && endpoint === "/api/solve") return;
    setLoading(true);
    try {
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url,
          llm: $("use-llm").checked,
          audit: $("audit").checked,
          chains: true,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "解析失败");
      init(data);
    } catch (err) {
      setLoading(false);
      showStatus("bad", "出错了：" + err.message);
    }
  }

  function setLoading(on) {
    $("loading").classList.toggle("hidden", !on);
    $("go").disabled = on;
  }

  function placementsUpTo(idx) {
    const out = [];
    if (!S.data || idx < 0) return out;
    for (let i = 0; i <= idx && i < S.data.steps.length; i++) {
      for (const ev of S.data.steps[i].events || []) {
        if (ev.kind === "place") out.push([ev.cell, ev.value]);
      }
    }
    return out;
  }

  async function refreshFrame() {
    try {
      const res = await fetch(`/api/live/frame?t=${Date.now()}`, { cache: "no-store" });
      if (!res.ok) return;
      const blob = await res.blob();
      const img = $("live-frame");
      if (img.dataset.url) URL.revokeObjectURL(img.dataset.url);
      const url = URL.createObjectURL(blob);
      img.dataset.url = url;
      img.src = url;
    } catch (err) { /* keep the last frame */ }
  }

  async function startLive(url) {
    const loading = $("live-loading");
    $("live-view").classList.remove("hidden");
    loading.classList.remove("hidden");
    S.live = { ready: false, step: -1, applied: 0, busy: false, pending: null, timer: null, url };
    if (!url) {
      loading.classList.add("hidden");
      $("live-badge").textContent = "没有 SudokuPad 链接";
      return;
    }
    try {
      const res = await fetch("/api/live/start", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.error || "启动失败");
      S.live.ready = true;
      await refreshFrame();
      loading.classList.add("hidden");
      seekLive(S.idx);
    } catch (err) {
      loading.classList.add("hidden");
      $("live-badge").textContent = `SudokuPad 镜像启动失败：${err.message || err}`;
    }
  }

  function scheduleLive(idx) {
    if (!S.live || !S.live.ready) return;
    S.live.pending = idx;
    clearTimeout(S.live.timer);
    S.live.timer = setTimeout(() => {
      const target = S.live.pending;
      S.live.pending = null;
      seekLive(target);
    }, 110);
  }

  async function seekLive(idx, forceReset = false) {
    if (!S.live || !S.live.ready || S.live.busy) {
      if (S.live) S.live.pending = idx;
      return;
    }
    const places = placementsUpTo(idx);
    const reset = forceReset || idx < S.live.step || places.length < S.live.applied;
    const send = reset ? places : places.slice(S.live.applied);
    if (!reset && !send.length && idx === S.live.step) return;
    S.live.busy = true;
    $("live-loading").classList.remove("hidden");
    try {
      const res = await fetch("/api/live/place", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ places: send, reset }),
      });
      const body = await res.json().catch(() => ({}));
      if (res.status === 410) {
        await startLive(S.live.url);
        return;
      }
      if (!res.ok) throw new Error(body.error || "操作失败");
      S.live.step = idx;
      S.live.applied = places.length;
      await refreshFrame();
    } catch (err) {
      $("live-badge").textContent = `SudokuPad 操作失败：${err.message || err}`;
    } finally {
      S.live.busy = false;
      $("live-loading").classList.add("hidden");
      if (S.live.pending !== null) {
        const next = S.live.pending;
        S.live.pending = null;
        scheduleLive(next);
      }
    }
  }

  function init(data) {
    S.data = data;
    S.n = data.puzzle.size;
    S.regions = (data.chaos_regions && data.chaos_regions.length)
      ? data.chaos_regions
      : (data.puzzle.regions || []);
    S.clues = data.puzzle.clues || [];
    const sheetPanel = $("rulesheet-panel");
    if (data.rule_sheet) {
      $("rulesheet").src = data.rule_sheet;
      sheetPanel.classList.remove("hidden");
    } else {
      sheetPanel.classList.add("hidden");
    }
    S.dom = data.initial.slice();
    S.vals = data.puzzle.givens.slice();
    S.idx = -1;
    S.playing = false;
    clearTimeout(S.timer);

    $("puzzle-title").textContent = data.puzzle.title || "未命名";
    $("puzzle-meta").textContent = [data.puzzle.author, `${S.n}×${S.n}`, `${countGiven()} 个提示数`]
      .filter(Boolean).join(" · ");
    const prov = $("provenance");
    prov.textContent = "";
    if (data.demo) {
      prov.textContent = data.source_url
        ? `${data.provenance || "真实题示例"}`
        : "内置生成示例 · 程序生成，非已发表题目";
      prov.classList.toggle("demo", !data.source_url);
    } else {
      prov.classList.remove("demo");
      if (data.provenance) prov.textContent = `来源：${data.provenance}`;
    }
    if (data.source_url && data.source_url.startsWith("http")) {
      const link = document.createElement("a");
      link.href = data.source_url;
      link.target = "_blank";
      link.rel = "noopener";
      link.className = "src-link";
      link.textContent = " · 在 SudokuPad 打开原题";
      prov.appendChild(link);
    }

    buildBoard();
    drawStatic();
    renderRules();
    renderStatus();
    buildStepList();
    resetView();
    resetBoard();
    if ((data.status === "solved-search" || data.status === "solved-global") && data.final) {
      S.vals = data.final.slice();
      S.dom = S.vals.map((v, i) => (v ? 1 << (v - 1) : S.data.initial[i]));
      render();
    }

    $("scrub").max = Math.max(0, data.steps.length - 1);
    $("scrub").value = 0;
    updateControls();
    showStep(-1, false);
    setLoading(false);
    startLive(data.source_url || "");
    refreshHistory();
    if (data.steps.length) {
      setTimeout(() => showStep(0, true), 350);
    }
  }

  function resetView() {
    $("sp-frame").src = "about:blank";
    $("tab-embed").disabled = !(S.data && S.data.source_url);
    $("embed-open").href = (S.data && S.data.source_url) || "#";
    setView("board");
  }

  function setView(view) {
    const embed = view === "embed" && S.data && S.data.source_url;
    $("board-view").classList.toggle("hidden", embed);
    $("embed-view").classList.toggle("hidden", !embed);
    $("embed-hint").classList.toggle("hidden", !embed);
    $("tab-board").classList.toggle("active", !embed);
    $("tab-embed").classList.toggle("active", embed);
    if (embed && $("sp-frame").src !== S.data.source_url) {
      $("sp-frame").src = S.data.source_url;
    }
    requestAnimationFrame(renderOverlay);
  }

  function renderOverlay() {
    const svg = $("sp-overlay");
    const stage = $("embed-view");
    if (!svg || !stage) return;
    const w = stage.clientWidth || 0;
    const h = stage.clientHeight || 0;
    svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    svg.innerHTML = "";
    if (stage.classList.contains("hidden") || !w || !h) return;

    const side = Math.min(w, h) * cal.size;
    const left = cal.x * w;
    const top = cal.y * h;

    if (!$("calib-panel").classList.contains("hidden") || S.idx < 0) {
      const frame = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      frame.setAttribute("x", left);
      frame.setAttribute("y", top);
      frame.setAttribute("width", side);
      frame.setAttribute("height", side);
      frame.setAttribute("fill", "none");
      frame.setAttribute("stroke", "rgba(255,210,138,.35)");
      frame.setAttribute("stroke-dasharray", "6 6");
      svg.appendChild(frame);
    }

    if (!S.data || S.idx < 0) return;
    const step = S.data.steps[S.idx];
    const cellRect = (cell) => {
      const r = Math.floor(cell / S.n), c = cell % S.n;
      return {
        x: left + c * side / S.n,
        y: top + r * side / S.n,
        w: side / S.n,
        h: side / S.n,
      };
    };
    const rect = (cell, fill, stroke) => {
      const g = cellRect(cell);
      const node = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      node.setAttribute("x", g.x); node.setAttribute("y", g.y);
      node.setAttribute("width", g.w); node.setAttribute("height", g.h);
      node.setAttribute("fill", fill);
      node.setAttribute("stroke", stroke);
      node.setAttribute("stroke-width", "2");
      svg.appendChild(node);
    };
    for (const cell of step.visual.focus || []) rect(cell, "rgba(255,210,138,.22)", "rgba(255,210,138,.85)");
    for (const cell of step.visual.premise || []) rect(cell, "rgba(88,166,255,.10)", "rgba(88,166,255,.45)");

    for (const link of step.visual.links || []) {
      const node = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
      node.setAttribute("points", link.points.map(([y, x]) =>
        `${left + x * side / S.n},${top + y * side / S.n}`).join(" "));
      node.setAttribute("fill", "none");
      node.setAttribute("stroke", link.color || "#58a6ff");
      node.setAttribute("stroke-width", "3");
      node.setAttribute("stroke-dasharray", link.dashed ? "8 6" : "");
      node.setAttribute("opacity", "0.9");
      svg.appendChild(node);
    }
    for (const chip of step.visual.chips || []) {
      const g = cellRect(chip.cell);
      const node = document.createElementNS("http://www.w3.org/2000/svg", "text");
      node.setAttribute("x", g.x + g.w / 2);
      node.setAttribute("y", g.y + g.h / 2);
      node.setAttribute("text-anchor", "middle");
      node.setAttribute("dominant-baseline", "central");
      node.setAttribute("font-size", Math.max(10, g.h * 0.3));
      node.setAttribute("fill", chip.color || "#ffd28a");
      node.textContent = chip.text;
      svg.appendChild(node);
    }
  }

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    const button = $("theme-toggle");
    if (button) button.textContent = theme === "light" ? "🌙" : "☀️";
  }

  const STATUS_LABEL = {
    solved: "已解出", "solved-global": "全局求解", "solved-search": "搜索求解",
    stuck: "卡住", unsupported: "不支持", invalid: "规则冲突",
  };

  async function refreshHistory() {
    try {
      const res = await fetch("/api/history");
      if (!res.ok) return;
      renderHistory(await res.json());
    } catch (err) { /* history is best-effort */ }
  }

  function renderHistory(entries) {
    const box = $("history");
    if (!box) return;
    box.innerHTML = "";
    if (!entries || !entries.length) {
      const empty = document.createElement("div");
      empty.className = "muted";
      empty.textContent = "还没有记录。";
      box.appendChild(empty);
      return;
    }
    for (const entry of entries.slice(0, 40)) {
      const row = document.createElement("div");
      row.className = "history-row";
      const title = document.createElement("div");
      title.className = "history-title";
      title.textContent = entry.title || entry.id || entry.target || "未命名";
      const meta = document.createElement("div");
      meta.className = "history-meta";
      const at = (entry.at || "").replace("T", " ").slice(0, 16);
      const status = STATUS_LABEL[entry.status] || entry.status;
      meta.textContent = `${at} · ${status} · ${entry.steps || 0} 步`;
      row.appendChild(title);
      row.appendChild(meta);
      row.addEventListener("click", () => {
        stopPlay();
        loadPuzzle(entry.demo ? "" : entry.target, entry.demo ? "/api/demo" : "/api/solve");
      });
      box.appendChild(row);
    }
  }

  function countGiven() {
    return S.data.puzzle.givens.filter((v) => v > 0).length;
  }

  // ------------------------------------------------------------------ board
  function buildBoard() {
    const svg = $("board");
    svg.innerHTML = "";
    const pad = S.clues && S.clues.length ? 1 : 0;
    svg.setAttribute("viewBox", `${-pad} ${-pad} ${S.n + 2 * pad} ${S.n + 2 * pad}`);
    el("g", { id: "layer-groups" }, svg);
    el("g", { id: "layer-cells" }, svg);
    el("g", { id: "layer-regions" }, svg);
    el("g", { id: "layer-static" }, svg);
    el("g", { id: "layer-links" }, svg);
    el("g", { id: "layer-vals" }, svg);
    el("g", { id: "layer-cands" }, svg);
    el("g", { id: "layer-chips" }, svg);
    el("g", { id: "layer-ghosts" }, svg);

    const cells = $("layer-cells");
    for (let r = 0; r < S.n; r++) {
      for (let c = 0; c < S.n; c++) {
        const rect = el("rect", {
          x: c + 0.004, y: r + 0.004, width: 0.992, height: 0.992,
          rx: 0.03, class: "cell", id: `cell-${r}-${c}`,
        }, cells);
        rect.dataset.cell = cellOf(r, c);
      }
    }

    const grid = $("layer-regions");
    for (let i = 1; i < S.n; i++) {
      el("line", { x1: 0, y1: i, x2: S.n, y2: i, class: "gridline" }, grid);
      el("line", { x1: i, y1: 0, x2: i, y2: S.n, class: "gridline" }, grid);
    }
    drawRegionBorders(grid);

    const vals = $("layer-vals");
    for (let cell = 0; cell < S.n * S.n; cell++) {
      el("text", { id: `val-${cell}`, class: "val", x: 0, y: 0 }, vals);
    }
    const cands = $("layer-cands");
    for (let cell = 0; cell < S.n * S.n; cell++) {
      for (let v = 1; v <= S.n; v++) {
        el("text", { id: `can-${cell}-${v}`, class: "can", x: 0, y: 0 }, cands);
      }
    }
  }

  function regionOf(cell) {
    if (!S.regions.length) return -1;
    for (let i = 0; i < S.regions.length; i++) {
      if (S.regions[i].includes(cell)) return i;
    }
    return -1;
  }

  function drawRegionBorders(layer) {
    const n = S.n;
    const reg = [];
    for (let cell = 0; cell < n * n; cell++) reg.push(regionOf(cell));
    const box = (r, c) => {
      const bh = n === 6 ? 2 : 3, bw = n === 6 ? 3 : 3;
      return Math.floor(r / bh) * 100 + Math.floor(c / bw);
    };
    for (let r = 0; r < n; r++) {
      for (let c = 0; c < n; c++) {
        const here = reg[cellOf(r, c)] >= 0 ? reg[cellOf(r, c)] : box(r, c);
        if (c + 1 < n) {
          const right = reg[cellOf(r, c + 1)] >= 0 ? reg[cellOf(r, c + 1)] : box(r, c + 1);
          if (here !== right) el("line", { x1: c + 1, y1: r, x2: c + 1, y2: r + 1, class: "regionline" }, layer);
        }
        if (r + 1 < n) {
          const down = reg[cellOf(r + 1, c)] >= 0 ? reg[cellOf(r + 1, c)] : box(r + 1, c);
          if (here !== down) el("line", { x1: c, y1: r + 1, x2: c + 1, y2: r + 1, class: "regionline" }, layer);
        }
        if (r === 0) el("line", { x1: c, y1: 0, x2: c + 1, y2: 0, class: "regionline" }, layer);
        if (c === 0) el("line", { x1: 0, y1: r, x2: 0, y2: r + 1, class: "regionline" }, layer);
        if (r === n - 1) el("line", { x1: c, y1: n, x2: c + 1, y2: n, class: "regionline" }, layer);
        if (c === n - 1) el("line", { x1: n, y1: r, x2: n, y2: r + 1, class: "regionline" }, layer);
      }
    }
  }

  function resetBoard() {
    S.dom = S.data.initial.slice();
    S.vals = S.data.puzzle.givens.slice();
    render();
  }

  function render() {
    const n = S.n;
    for (let cell = 0; cell < n * n; cell++) {
      const [r, c] = rc(cell);
      const rect = document.getElementById(`cell-${r}-${c}`);
      const value = S.vals[cell];
      rect.classList.toggle("given", S.data.puzzle.givens[cell] > 0);
      rect.classList.toggle("solved", value > 0);
      const val = document.getElementById(`val-${cell}`);
      val.textContent = value || "";
      val.setAttribute("x", c + 0.5);
      val.setAttribute("y", r + 0.53);
      val.setAttribute("font-size", "0.5");
      val.classList.toggle("given", S.data.puzzle.givens[cell] > 0);
      val.classList.toggle("placed", S.data.puzzle.givens[cell] === 0 && value > 0);
      for (let v = 1; v <= n; v++) {
        const node = document.getElementById(`can-${cell}-${v}`);
        const bit = 1 << (v - 1);
        const show = !value && (S.dom[cell] & bit);
        node.textContent = show && S.showCands ? v : "";
        const p = candPos(n, v);
        node.setAttribute("x", c + p.x);
        node.setAttribute("y", r + p.y);
      }
    }
  }


  // ------------------------------------------------------- static constraints
  const STATIC_COLOR = {
    thermo: "#f97316", renban: "#c084fc", palindrome: "#94a3b8",
    between: "#a3a3a3", german_whisper: "#22c55e", dutch_whisper: "#4ade80",
    consecutive: "#fb923c", region_sum: "#38bdf8", little_killer: "#eab308",
    sandwich: "#f472b6", skyscraper: "#f59e0b",
  };

  function centerOf(cell) {
    return [cell % S.n + 0.5, Math.floor(cell / S.n) + 0.5];
  }

  function staticPolyline(layer, cells, color, dashed = false, width = 0.055) {
    if (!cells || cells.length < 2) return;
    const pts = cells.map((cell) => {
      const [x, y] = centerOf(cell);
      return `${x},${y}`;
    }).join(" ");
    el("polyline", {
      points: pts, class: "static-line", stroke: color,
      "stroke-width": width, "stroke-dasharray": dashed ? "0.12 0.08" : "",
    }, layer);
  }

  function staticLabel(layer, cell, text, cls = "static-label") {
    const [x, y] = centerOf(cell);
    el("text", { x: x - 0.32, y: y - 0.22, class: cls }, layer).textContent = text;
  }

  function drawCage(layer, cells, sum, hot = false) {
    if (!cells || !cells.length) return;
    const set = new Set(cells);
    const n = S.n;
    for (const cell of cells) {
      const r = Math.floor(cell / n), c = cell % n;
      el("rect", {
        x: c + 0.005, y: r + 0.005, width: 0.99, height: 0.99,
        class: hot ? "cage-fill hot" : "cage-fill",
      }, layer);
      const edge = (x1, y1, x2, y2) =>
        el("line", { x1, y1, x2, y2, class: hot ? "cage-edge hot" : "cage-edge" }, layer);
      if (!set.has(cell - n)) edge(c, r, c + 1, r);
      if (!set.has(cell + n)) edge(c, r + 1, c + 1, r + 1);
      if (c === 0 || !set.has(cell - 1)) edge(c, r, c, r + 1);
      if (c === n - 1 || !set.has(cell + 1)) edge(c + 1, r, c + 1, r + 1);
    }
    if (sum !== null && sum !== undefined && !hot) {
      const first = cells.reduce((a, b) => {
        const ra = Math.floor(a / n), rb = Math.floor(b / n);
        if (ra !== rb) return ra < rb ? a : b;
        return (a % n) <= (b % n) ? a : b;
      });
      const r = Math.floor(first / n), c = first % n;
      el("text", { x: c + 0.2, y: r + 0.3, class: "static-label" }, layer).textContent = String(sum);
    }
  }

  function drawStatic() {
    const layer = $("layer-static");
    if (!layer) return;
    layer.innerHTML = "";
    for (const clue of (S.data.puzzle.clues || [])) {
      let x = clue.index + 0.5, y = clue.index + 0.5;
      if (clue.side === "top") { x = clue.index + 0.5; y = -0.45; }
      if (clue.side === "bottom") { x = clue.index + 0.5; y = S.n + 0.45; }
      if (clue.side === "left") { x = -0.45; y = clue.index + 0.5; }
      if (clue.side === "right") { x = S.n + 0.45; y = clue.index + 0.5; }
      el("text", {
        x, y, "text-anchor": "middle", "dominant-baseline": "central",
        class: "static-label", "font-size": "0.42",
      }, layer).textContent = String(clue.value);
    }
    const cons = (S.data && S.data.constraints) || [];
    for (const con of cons) {
      const cells = con.cells || [];
      switch (con.kind) {
        case "cage":
          drawCage(layer, con.cells, con.sum);
          break;
        case "thermo":
        case "renban":
        case "palindrome":
        case "between":
        case "region_sum":
        case "little_killer":
          staticPolyline(layer, cells, STATIC_COLOR[con.kind] || "#94a3b8");
          if (con.sum !== undefined && con.sum !== null) staticLabel(layer, cells[0], String(con.sum));
          break;
        case "sandwich":
          staticPolyline(layer, cells, STATIC_COLOR.sandwich);
          if (con.sum !== undefined) staticLabel(layer, cells[0], String(con.sum));
          break;
        case "skyscraper":
          staticPolyline(layer, cells, STATIC_COLOR.skyscraper);
          if (con.clue !== undefined) staticLabel(layer, cells[0], `见${con.clue}`);
          break;
        case "arrow": {
          const arm = con.arm || [];
          staticPolyline(layer, [con.circle, ...arm], "#eab308");
          const [cx, cy] = centerOf(con.circle);
          el("circle", { cx, cy, r: 0.16, fill: "none", stroke: "#eab308", "stroke-width": 0.04 }, layer);
          break;
        }
        case "kropki": {
          const [ax, ay] = centerOf(con.a);
          const [bx, by] = centerOf(con.b);
          el("circle", {
            cx: (ax + bx) / 2, cy: (ay + by) / 2, r: 0.1,
            fill: con.variant === "black" ? "#0b1020" : "#ffffff",
            stroke: "#94a3b8", "stroke-width": 0.02, class: "static-dot",
          }, layer);
          break;
        }
        case "xv": {
          const [ax, ay] = centerOf(con.a);
          const [bx, by] = centerOf(con.b);
          el("text", {
            x: (ax + bx) / 2, y: (ay + by) / 2 + 0.05, class: "static-label",
            "text-anchor": "middle", "font-size": "0.16",
          }, layer).textContent = con.sum === 5 ? "V" : "X";
          break;
        }
        case "quadruple": {
          const xs = cells.map((c) => c % S.n + 0.5);
          const ys = cells.map((c) => Math.floor(c / S.n) + 0.5);
          const cx = xs.reduce((a, b) => a + b, 0) / xs.length;
          const cy = ys.reduce((a, b) => a + b, 0) / ys.length;
          el("circle", { cx, cy, r: 0.3, fill: "none", stroke: "#38d39f", "stroke-width": 0.04, opacity: 0.7 }, layer);
          el("text", {
            x: cx, y: cy, "text-anchor": "middle", "dominant-baseline": "central",
            class: "static-label", "font-size": "0.13",
          }, layer).textContent = (con.digits || []).join("");
          break;
        }
        case "odd":
        case "even":
          for (const cell of cells) staticLabel(layer, cell, con.kind === "odd" ? "奇" : "偶", "static-label dim");
          break;
        case "clone":
          staticPolyline(layer, cells, "#f472b6", true);
          break;
        case "german_whisper":
        case "dutch_whisper":
        case "consecutive":
          staticPolyline(layer, [con.a, con.b], STATIC_COLOR[con.kind] || "#22c55e");
          break;
        case "custom":
          staticPolyline(layer, cells, "#f472b6", true);
          if (cells.length) staticLabel(layer, cells[0], "L2");
          break;
        default:
          break;
      }
    }
  }

  // ------------------------------------------------------------------ steps
  function applyEvents(step) {
    for (const ev of step.events) {
      if (ev.kind === "place") {
        S.vals[ev.cell] = ev.value;
        S.dom[ev.cell] = 1 << (ev.value - 1);
      } else {
        S.dom[ev.cell] &= ~(1 << (ev.value - 1));
      }
    }
  }

  function clearOverlay() {
    for (const id of ["layer-groups", "layer-links", "layer-chips", "layer-ghosts"]) {
      $(id).innerHTML = "";
    }
    document.querySelectorAll(".cell.focus, .cell.place, .cell.premise").forEach((n) => {
      n.classList.remove("focus", "place", "premise");
    });
  }

  function drawGroups(visual) {
    const layer = $("layer-groups");
    for (const g of visual.groups || []) {
      if (!g.cells || !g.cells.length) continue;
      if (g.kind === "cage") {
        drawCage(layer, g.cells, null, true);
        continue;
      }
      const pts = g.cells.map(rc);
      const minR = Math.min(...pts.map((p) => p[0])) - 0.03;
      const maxR = Math.max(...pts.map((p) => p[0])) + 1.03;
      const minC = Math.min(...pts.map((p) => p[1])) - 0.03;
      const maxC = Math.max(...pts.map((p) => p[1])) + 1.03;
      el("rect", {
        x: minC, y: minR, width: maxC - minC, height: maxR - minR, rx: 0.1,
        class: `overlay-group ${g.kind || ""}`,
      }, layer);
    }
  }

  function drawLinks(visual) {
    const layer = $("layer-links");
    for (const link of visual.links || []) {
      const pts = link.points.map(([y, x]) => `${x},${y}`).join(" ");
      const node = el("polyline", {
        points: pts, class: "overlay-link",
        stroke: link.color || "#58a6ff", "stroke-width": link.kind === "dot" ? 0.06 : 0.09,
        "stroke-dasharray": link.dashed ? "0.16 0.12" : "",
      }, layer);
      if (!link.dashed) {
        const len = node.getTotalLength ? node.getTotalLength() : 3;
        node.style.strokeDasharray = `${len}`;
        node.style.strokeDashoffset = `${len}`;
        node.style.transition = "stroke-dashoffset .55s ease-out";
        requestAnimationFrame(() => { node.style.strokeDashoffset = "0"; });
      }
    }
    for (const chip of visual.chips || []) {
      const [r, c] = rc(chip.cell);
      el("text", {
        x: c + 0.5, y: r + 0.5, class: "chip-text",
        fill: chip.color || "",
      }, $("layer-chips")).textContent = chip.text;
    }
  }

  function ghostElims(step) {
    const layer = $("layer-ghosts");
    let delay = 0;
    for (const ev of step.events) {
      if (ev.kind !== "elim" || ev.reason.kind === "unit_peer") continue;
      const [r, c] = rc(ev.cell);
      const p = candPos(S.n, ev.value);
      // the eliminated candidate disappears with a red flash at its old spot
      const g = el("text", {
        x: c + p.x, y: r + p.y, class: "ghost elim",
        "font-size": "0.16", style: `animation-delay:${delay}ms`,
      }, layer);
      g.textContent = ev.value;
      g.addEventListener("animationend", () => g.remove());
      delay += 26;
    }
    for (const ev of step.events) {
      if (ev.kind !== "place") continue;
      const [r, c] = rc(ev.cell);
      const g = el("text", {
        x: c + 0.5, y: r + 0.55, class: "ghost place",
        "font-size": "0.55", style: `animation-delay:${delay}ms`,
      }, layer);
      g.textContent = ev.value;
      g.addEventListener("animationend", () => g.remove());
      delay += 40;
    }
    return delay;
  }

  function markCells(step) {
    const focus = new Set(step.visual.focus || []);
    const premise = new Set(step.visual.premise || []);
    for (const cell of focus) {
      const [r, c] = rc(cell);
      const node = document.getElementById(`cell-${r}-${c}`);
      if (node) node.classList.add(step.events.some((e) => e.kind === "place" && e.cell === cell) ? "place" : "focus");
    }
    for (const cell of premise) {
      if (focus.has(cell)) continue;
      const [r, c] = rc(cell);
      const node = document.getElementById(`cell-${r}-${c}`);
      if (node) node.classList.add("premise");
    }
  }

  function showStep(i, animate) {
    if (!S.data) return;
    const steps = S.data.steps;
    i = Math.max(-1, Math.min(i, steps.length - 1));
    clearOverlay();
    if (i < S.idx) {
      resetBoard();
      S.idx = -1;
    }
    if (i === S.idx) {
      if (i >= 0) renderPanel(steps[i]);
      updateControls();
      renderOverlay();
      scheduleLive(S.idx);
      return;
    }
    if (!animate) {
      while (S.idx < i) { S.idx += 1; applyEvents(steps[S.idx]); }
      render();
      if (i >= 0) renderPanel(steps[i]);
      updateControls();
      renderOverlay();
      scheduleLive(S.idx);
      return;
    }
    const step = steps[i];
    S.idx = i;
    applyEvents(step);
    render();
    clearOverlay();
    drawGroups(step.visual);
    drawLinks(step.visual);
    markCells(step);
    ghostElims(step);
    updateControls();
    renderPanel(step);
    renderOverlay();
    scheduleLive(S.idx);
  }

  function renderPanel(step) {
    $("step-index").textContent = `第 ${step.index + 1} 步`;
    $("step-title").textContent = step.title;
    $("step-tier").textContent = TIER_LABEL[step.tier] || `T${step.tier}`;
    $("step-detail").textContent = step.detail;
    const audit = $("step-audit");
    audit.className = "audit";
    if (step.audit === "ok") { audit.textContent = "✓ 已用穷举反证校验：结论唯一必然"; audit.classList.remove("hidden"); }
    else if (step.audit === "bad") { audit.textContent = "✗ 反证失败：这一步可能不成立"; audit.classList.add("bad"); audit.classList.remove("hidden"); }
    else if (step.audit === "unknown") { audit.textContent = "… 审计超出预算，未判定"; audit.classList.add("unknown"); audit.classList.remove("hidden"); }
    else if (step.audit === "skipped") { audit.textContent = "审计额度已用完"; audit.classList.add("unknown"); audit.classList.remove("hidden"); }
    else { audit.classList.add("hidden"); }

    document.querySelectorAll("#step-list li").forEach((li, idx) => {
      li.classList.toggle("active", idx === step.index);
    });
    const active = document.querySelector("#step-list li.active");
    // On phones this used to scroll the whole page to the step list, hiding the
    // board and the pause button.  Only auto-scroll the list on wider screens.
    if (active && window.innerWidth > 720) active.scrollIntoView({ block: "nearest" });
    $("scrub").value = step.index;
    $("progress-label").textContent = `${step.index + 1} / ${S.data.steps.length}`;
  }

  function updateControls() {
    const total = S.data ? S.data.steps.length : 0;
    $("prev").disabled = S.idx <= 0;
    $("next").disabled = !S.data || S.idx >= total - 1;
    $("play").textContent = S.playing ? "⏸ 暂停" : "▶ 播放";
    $("play").disabled = !total;
    if (total) $("progress-label").textContent = `${S.idx + 1} / ${total}`;
  }

  function buildStepList() {
    const list = $("step-list");
    list.innerHTML = "";
    S.data.steps.forEach((step, i) => {
      const li = document.createElement("li");
      li.innerHTML = `<span class="n">${i + 1}</span><span>${step.title}</span>`;
      li.addEventListener("click", () => { stopPlay(); showStep(i, true); });
      list.appendChild(li);
    });
  }

  function playLoop() {
    if (!S.playing) return;
    if (S.idx >= S.data.steps.length - 1) { stopPlay(); return; }
    showStep(S.idx + 1, true);
    const wait = Math.max(Number($("speed").value), 620);
    S.timer = setTimeout(playLoop, wait);
  }

  function startPlay() {
    if (!S.data || !S.data.steps.length) return;
    if (S.idx >= S.data.steps.length - 1) { resetBoard(); S.idx = -1; }
    S.playing = true;
    updateControls();
    playLoop();
  }

  function stopPlay() {
    S.playing = false;
    clearTimeout(S.timer);
    updateControls();
  }

  // ------------------------------------------------------------------ panels
  function renderRules() {
    const box = $("rules");
    box.innerHTML = "";
    const rules = S.data.rules;
    const grouped = new Map();
    for (const r of rules.resolved || []) {
      if (r.kind === "_ignored") continue;
      const key = r.kind;
      if (!grouped.has(key)) grouped.set(key, { label: r.label || key, count: 0, hypothesis: false });
      grouped.get(key).count += r.count || 1;
      if (r.hypothesis) grouped.get(key).hypothesis = true;
    }
    for (const [, info] of grouped) {
      const row = document.createElement("div");
      row.className = "rule-row";
      const tag = info.hypothesis ? '<span class="hypo">推测</span>' : "";
      row.innerHTML = `<span class="rule-kind">${info.label}</span>${tag}<span class="rule-count">× ${info.count}</span>`;
      box.appendChild(row);
    }
    const source = document.createElement("div");
    source.className = "muted";
    const sourceLabel = {
      llm: "LLM 编译（已用官方答案校验）",
      cache: "LLM 编译（本地缓存）",
      "llm-repair": "LLM 卡住后二次修复",
      manual: "手动规则",
      heuristic: "本地启发式",
    }[rules.source] || rules.source;
    source.textContent = `来源：${sourceLabel}`;
    box.appendChild(source);
    if (rules.warnings && rules.warnings.length) {
      const ul = document.createElement("ul");
      ul.className = "warn-list";
      for (const w of rules.warnings.slice(0, 8)) {
        const li = document.createElement("li");
        li.textContent = w;
        ul.appendChild(li);
      }
      box.appendChild(ul);
    }
  }

  function renderStatus() {
    const node = $("status");
    const d = S.data;
    node.className = "status";
    if (d.status === "solved-search") {
      node.classList.add("ok");
      node.textContent = `混沌构造：搜索求解完成` + (d.message ? ` · ${d.message}` : "");
    } else if (d.status === "solved-global") {
      node.classList.add("ok");
      node.textContent = `全局线索：CP-SAT 求解完成` + (d.message ? ` · ${d.message}` : "");
    } else if (d.status === "solved") {
      node.classList.add("ok");
      node.textContent = `已解出 · ${d.steps.length} 步` + (d.solution_check ? ` · ${d.solution_check}` : "");
    } else if (d.status === "unsupported") {
      node.classList.add("warn");
      node.textContent = `暂不支持 · ${d.message || ""}`;
    } else if (d.status === "stuck") {
      node.classList.add("warn");
      node.textContent = `推理卡住 · 已完成 ${d.steps.length} 步` + (d.message ? ` · ${d.message}` : "");
    } else {
      node.classList.add("bad");
      node.textContent = `无法完成 · ${d.message || d.status}`;
    }
    if (d.audit && d.audit.checks) {
      node.textContent += ` · 审计 ${d.audit.ok}/${d.audit.checks}` + (d.audit.bad ? `，${d.audit.bad} 处异常` : "");
    }
    node.classList.remove("hidden");
  }

  function showStatus(kind, text) {
    const node = $("status");
    node.className = `status ${kind}`;
    node.textContent = text;
    node.classList.remove("hidden");
  }

  // ------------------------------------------------------------------ events
  $("load-form").addEventListener("submit", (e) => {
    e.preventDefault();
    stopPlay();
    loadPuzzle($("url").value.trim());
  });
  $("history-clear").addEventListener("click", async (event) => {
    event.preventDefault();
    try { await fetch("/api/history/clear", { method: "POST" }); } catch (err) { /* ignore */ }
    refreshHistory();
  });
  $("calib-toggle").addEventListener("click", () => {
    $("calib-panel").classList.toggle("hidden");
    $("cal-x").value = cal.x;
    $("cal-y").value = cal.y;
    $("cal-size").value = cal.size;
    renderOverlay();
  });
  for (const [id, key] of [["cal-x", "x"], ["cal-y", "y"], ["cal-size", "size"]]) {
    $(id).addEventListener("input", (e) => {
      cal[key] = Number(e.target.value);
      try { localStorage.setItem(CAL_KEY, JSON.stringify(cal)); } catch (err) { /* ignore */ }
      renderOverlay();
    });
  }
  $("cal-reset").addEventListener("click", () => {
    cal = { x: 0.07, y: 0.07, size: 0.86 };
    $("cal-x").value = cal.x; $("cal-y").value = cal.y; $("cal-size").value = cal.size;
    try { localStorage.setItem(CAL_KEY, JSON.stringify(cal)); } catch (err) { /* ignore */ }
    renderOverlay();
  });
  window.addEventListener("resize", () => renderOverlay());
  $("tab-board").addEventListener("click", () => setView("board"));
  $("tab-embed").addEventListener("click", () => setView("embed"));
  $("demo").addEventListener("click", () => {
    stopPlay();
    $("url").value = "";
    loadPuzzle("", "/api/demo");
  });
  $("prev").addEventListener("click", () => { stopPlay(); showStep(S.idx - 1, true); });
  $("next").addEventListener("click", () => { stopPlay(); showStep(S.idx + 1, true); });
  $("play").addEventListener("click", () => { S.playing ? stopPlay() : startPlay(); });
  $("show-cands").addEventListener("change", (e) => { S.showCands = e.target.checked; render(); });
  $("show-constraints").addEventListener("change", (e) => {
    $("layer-static").style.display = e.target.checked ? "" : "none";
  });
  $("scrub").addEventListener("input", (e) => {
    stopPlay();
    const target = Number(e.target.value);
    if (target === S.idx) return;
    showStep(target, false);
  });
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT") return;
    if (e.key === "ArrowRight") { stopPlay(); showStep(S.idx + 1, true); }
    if (e.key === "ArrowLeft") { stopPlay(); showStep(S.idx - 1, true); }
    if (e.key === " ") { e.preventDefault(); S.playing ? stopPlay() : startPlay(); }
  });
  $("speed").addEventListener("input", () => {
    if (S.playing) { clearTimeout(S.timer); playLoop(); }
  });

  let theme = null;
  try { theme = localStorage.getItem(THEME_KEY); } catch (err) { /* ignore */ }
  applyTheme(theme || "light");
  $("theme-toggle").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
    try { localStorage.setItem(THEME_KEY, next); } catch (err) { /* ignore */ }
    applyTheme(next);
  });

  checkHealth();
  $("url").focus();
})();

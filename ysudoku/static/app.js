/* YSudoku front-end: animated, step-through explanations. */
(() => {
  const $ = (id) => document.getElementById(id);
  const SVG_NS = "http://www.w3.org/2000/svg";

  const S = {
    data: null, n: 9, dom: [], vals: [], regions: [], idx: -1,
    playing: false, timer: null, showCands: true, animating: false,
  };

  const TIER_LABEL = { 1: "T1 直接推理", 2: "T2 基础技巧", 3: "T3 进阶技巧" };

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
        note.title = "规则由 LLM 编译，并用题面答案自动校验";
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
          chains: $("chains").checked,
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

  function init(data) {
    S.data = data;
    S.n = data.puzzle.size;
    S.regions = data.puzzle.regions || [];
    S.dom = data.initial.slice();
    S.vals = data.puzzle.givens.slice();
    S.idx = -1;
    S.playing = false;
    clearTimeout(S.timer);

    $("puzzle-title").textContent = data.puzzle.title || "未命名";
    $("puzzle-meta").textContent = [data.puzzle.author, `${S.n}×${S.n}`, `${countGiven()} 个提示数`]
      .filter(Boolean).join(" · ");

    buildBoard();
    renderRules();
    renderStatus();
    buildStepList();
    resetBoard();

    $("scrub").max = Math.max(0, data.steps.length - 1);
    $("scrub").value = 0;
    updateControls();
    showStep(-1, false);
    setLoading(false);
    if (data.steps.length) {
      setTimeout(() => showStep(0, true), 350);
    }
  }

  function countGiven() {
    return S.data.puzzle.givens.filter((v) => v > 0).length;
  }

  // ------------------------------------------------------------------ board
  function buildBoard() {
    const svg = $("board");
    svg.innerHTML = "";
    svg.setAttribute("viewBox", `0 0 ${S.n} ${S.n}`);
    el("g", { id: "layer-groups" }, svg);
    el("g", { id: "layer-cells" }, svg);
    el("g", { id: "layer-regions" }, svg);
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
      return;
    }
    if (!animate) {
      while (S.idx < i) { S.idx += 1; applyEvents(steps[S.idx]); }
      render();
      if (i >= 0) renderPanel(steps[i]);
      updateControls();
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
    if (active) active.scrollIntoView({ block: "nearest" });
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
      if (!grouped.has(key)) grouped.set(key, { label: r.label || key, count: 0 });
      grouped.get(key).count += r.count || 1;
    }
    for (const [, info] of grouped) {
      const row = document.createElement("div");
      row.className = "rule-row";
      row.innerHTML = `<span class="rule-kind">${info.label}</span><span class="rule-count">× ${info.count}</span>`;
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
    if (d.status === "solved") {
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
  $("demo").addEventListener("click", () => {
    stopPlay();
    $("url").value = "";
    loadPuzzle("", "/api/demo");
  });
  $("prev").addEventListener("click", () => { stopPlay(); showStep(S.idx - 1, true); });
  $("next").addEventListener("click", () => { stopPlay(); showStep(S.idx + 1, true); });
  $("play").addEventListener("click", () => { S.playing ? stopPlay() : startPlay(); });
  $("show-cands").addEventListener("change", (e) => { S.showCands = e.target.checked; render(); });
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

  checkHealth();
  $("url").focus();
})();

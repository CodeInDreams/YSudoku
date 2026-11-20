import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle, ArrowUpDown, Check, ChevronDown, ChevronLeft, ChevronRight,
  Database, FilePenLine, FolderOpen, Languages, Loader2, Moon, Pause, Play,
  Save, Search, Settings, ShieldCheck, Sparkles, Star, Sun, Trash2, X,
} from "lucide-react";
import { Button } from "./components/ui/button";
import { Input } from "./components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "./components/ui/card";
import { Badge } from "./components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./components/ui/tabs";
import { Textarea } from "./components/ui/textarea";
import { Switch } from "./components/ui/switch";
import { Popover, PopoverContent, PopoverTrigger } from "./components/ui/popover";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Slider } from "./components/ui/slider";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from "./components/ui/dropdown-menu";
import { detectLang, translate } from "./i18n";
import logoLight from "./assets/logo-light.svg";
import logoDark from "./assets/logo-dark.svg";

const TECH_EN = {
  cage: "Killer cage", hidden_single: "Hidden single", naked_single: "Naked single",
  class_cover: "2×2 class cover", whisper: "Whisper", renban: "Renban", arrow: "Arrow",
  thermo: "Thermometer", sandwich: "Sandwich", xsum: "X-Sums", skyscraper: "Skyscraper",
  consecutive: "Consecutive", parity: "Parity", region: "Region",
};
const RULE_EN = {
  killer: "Killer cages", cage: "Killer cages", whisper: "Whispers", renban: "Renbans",
  arrow: "Arrows", thermo: "Thermometers", sandwich: "Sandwiches", xsum: "X-Sums",
  region: "Regions", skyscraper: "Skyscrapers", consecutive: "Consecutive",
  modular: "Global modularity (2×2: 1/4/7, 2/5/8, 3/6/9)",
  entropy: "Global entropy (2×2: low/mid/high)",
};

function digitsOf(mask, n) {
  const out = [];
  for (let v = 1; v <= n; v++) if (mask & (1 << (v - 1))) out.push(v);
  return out;
}

const PERSIST_KEY = "ysudoku.ui.v1";
const DEFAULT_SETTINGS = { max_rules: 100, max_steps: 100, max_frames: 10, max_mb: 500 };

function readPersisted() {
  try {
    return JSON.parse(localStorage.getItem(PERSIST_KEY) || "{}") || {};
  } catch {
    return {};
  }
}

function detectGridRect(img, size) {
  try {
    const canvas = document.createElement("canvas");
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(img, 0, 0);
    const { width, height } = canvas;
    const pixels = ctx.getImageData(0, 0, width, height).data;
    const dark = (x, y) => {
      const i = (y * width + x) * 4;
      return pixels[i] + pixels[i + 1] + pixels[i + 2] < 240;
    };
    const cols = [];
    const rows = [];
    for (let x = 0; x < width; x++) {
      let n = 0;
      for (let y = 0; y < height; y++) if (dark(x, y)) n++;
      if (n > height * 0.5) cols.push(x);
    }
    for (let y = 0; y < height; y++) {
      let n = 0;
      for (let x = 0; x < width; x++) if (dark(x, y)) n++;
      if (n > width * 0.5) rows.push(y);
    }
    function axis(lines) {
      const centers = [];
      for (let i = 0; i < lines.length; i++) {
        const first = lines[i];
        while (lines[i+1] === lines[i]+1) i++;
        // Canvas coordinates denote pixel edges. Sampled pixels are centered
        // half a pixel inside those edges.
        centers.push((first + lines[i] + 1) / 2);
      }
      let best = null;
      for (const start of centers) {
        for (const end of centers) {
          const spacing = (end - start) / size;
          if (spacing < 8) continue;
          const matched = [start];
          let error = 0;
          for (let i = 1; i < size; i++) {
            const expected = start + i * spacing;
            const nearest = centers.reduce((a, b) => Math.abs(a - expected) <= Math.abs(b - expected) ? a : b);
            error += Math.abs(nearest - expected);
            matched.push(nearest);
          }
          if (error <= size - 1 && (!best || error < best.error)) {
            matched.push(end);
            // Fit all grid lines so that rounding or unequal stroke widths
            // at the outside border cannot shift the whole overlay.
            const middle = size / 2;
            const average = matched.reduce((sum, line) => sum + line, 0) / matched.length;
            const slope = matched.reduce((sum, line, index) => sum + (index - middle) * (line - average), 0)
              / matched.reduce((sum, _, index) => sum + (index - middle) ** 2, 0);
            best = { start: average - middle * slope, span: size * slope, error };
          }
        }
      }
      return best;
    }
    const x = axis(cols);
    const y = axis(rows);
    if (!x || !y || Math.abs(x.span - y.span) > 3) return null;
    return {
      x: x.start, y: y.start,
      width: x.span, height: y.span,
      imageWidth: width, imageHeight: height,
    };
  } catch {
    return null;
  }
}

function candidateStateUpTo(analysis, idx) {
  const state = new Map();
  if (!analysis) return state;
  const n = analysis.puzzle.size;
  for (let i = 0; i <= idx && i < analysis.steps.length; i++) {
    const step = analysis.steps[i];
    const pre = step.pre_dom || [];
    for (const cell of state.keys()) state.set(cell, new Set(digitsOf(pre[cell] || 0, n)));
    for (const ev of step.events || []) {
      if (ev.kind === "place") state.delete(ev.cell);
      else if (ev.kind === "elim") {
        if (!state.has(ev.cell)) state.set(ev.cell, new Set(digitsOf(pre[ev.cell] || 0, n)));
        state.get(ev.cell).delete(ev.value);
      }
    }
  }
  return state;
}

function CellColours({ visual, n }) {
  const cells = new Map();
  const hex = new Map();
  const choices = new Map();
  for (const option of visual.region_options || []) {
    for (const cell of option.cells) choices.set(cell, option.colours);
  }
  function add(cell, colour) {
    if (!cells.has(cell)) cells.set(cell, new Set());
    cells.get(cell).add(colour);
  }
  for (const group of visual.colours || []) {
    hex.set(group.colour, group.hex);
    for (const cell of group.cells) {
      if (!(group.region && choices.has(cell))) add(cell, group.colour);
    }
  }
  for (const [cell, colours] of choices) {
    for (const colour of colours) add(cell, colour);
  }
  return [...cells].map(([cell, colours]) => [...colours].map((colour, i) => (
    <rect key={cell + "/" + colour} x={cell % n + i / colours.size} y={Math.floor(cell / n)}
      width={1 / colours.size} height="1" fill={hex.get(colour) || "#8ab4e8"} opacity="0.45" />
  )));
}

function buildStepActions(analysis) {
  const n = analysis.puzzle.size;
  const steps = [];
  let state = new Map();
  const marked = new Set();
  const values = new Map();
  const colourState = new Map();
  const penState = new Set();
  (analysis.puzzle?.givens || []).forEach((value, cell) => { if (value) values.set(cell, value); });
  let inBranch = false;
  let branchBase = null;
  let branchCell = null;
  const baseActions = [];
  const MAX_POSITIVE = 5;
  const digits = (mask) => digitsOf(mask || 0, n);
  const same = (a, b) => a.size === b.size && [...a].every((d) => b.has(d));

  for (let stepIndex = 0; stepIndex < analysis.steps.length; stepIndex++) {
    const step = analysis.steps[stepIndex];
    const actions = [];
    if (step.branch && !inBranch) {
      inBranch = true;
      branchCell = (step.events || []).find((ev) => ev.kind === "place")?.cell ?? null;
      branchBase = { state: new Map(state), marked: new Set(marked), values: new Map(values) };
    }
    if (step.revert) {
      actions.push({ op: "undo_to_snapshot", cell: branchCell });
      if (branchBase) {
        state = new Map(branchBase.state);
        marked.clear();
        branchBase.marked.forEach((cell) => marked.add(cell));
        values.clear();
        branchBase.values.forEach((value, cell) => values.set(cell, value));
      }
      inBranch = false;
      steps.push(actions);
      continue;
    }
    const pre = step.pre_dom || [];
    const elimsByCell = new Map();
    const placeByCell = new Map();
    for (const ev of step.events || []) {
      if (ev.kind === "elim") {
        if (!elimsByCell.has(ev.cell)) elimsByCell.set(ev.cell, new Set());
        elimsByCell.get(ev.cell).add(ev.value);
      } else if (ev.kind === "place") {
        placeByCell.set(ev.cell, ev.value);
      }
    }
    const affected = new Set([...elimsByCell.keys(), ...placeByCell.keys()]);
    const nextState = new Map();

    const update = (cell, desired, place) => {
      const current = state.get(cell);
      const isMarked = marked.has(cell);
      if (place !== undefined) {
        if (isMarked || current?.size) actions.push({ op: "candidates", cell, digits: [] });
        actions.push({ op: "place", cell, value: place });
        values.set(cell, place);
        marked.delete(cell);
        return;
      }
      if (desired.size === 1) {
        if (!current || !isMarked || !same(current, desired)) {
          actions.push({ op: "candidates", cell, digits: [...desired] });
          marked.add(cell);
        }
        nextState.set(cell, desired);
        return;
      }
      if (desired.size === 0) {
        if (isMarked || current?.size) actions.push({ op: "candidates", cell, digits: [] });
        marked.delete(cell);
        return;
      }
      if (desired.size > MAX_POSITIVE) {
        if (isMarked) actions.push({ op: "candidates", cell, digits: [] });
        marked.delete(cell);
        nextState.set(cell, desired);
        return;
      }
      if (!current || !isMarked || !same(current, desired)) {
        actions.push({ op: "candidates", cell, digits: [...desired] });
        marked.add(cell);
      }
      nextState.set(cell, desired);
    };

    const refreshCells = step.technique === "candidate_map"
      ? Array.from({ length: n * n }, (_, i) => i)
      : [...state.keys()];
    for (const cell of refreshCells) {
      if (!affected.has(cell)) update(cell, new Set(digits(pre[cell])));
    }
    for (const cell of affected) {
      const desired = new Set(digits(pre[cell]));
      for (const value of elimsByCell.get(cell) || []) desired.delete(value);
      update(cell, desired, placeByCell.get(cell));
    }
    state = nextState;
    for (const edge of step.visual?.region_edges || []) {
      const cells = edge.cells || [];
      if (cells.length !== 2) continue;
      const key = `${cells[0]}-${cells[1]}`;
      if (penState.has(key)) continue;
      penState.add(key);
      actions.push({ op: "pen", cells, index: edge.fixed ? 4 : 6 });
    }
    for (const item of step.visual?.colours || []) {
      for (const cell of item.cells || []) {
        const applied = colourState.get(cell) || new Set();
        if (applied.has(item.colour)) continue;
        applied.add(item.colour);
        colourState.set(cell, applied);
        actions.push({ op: "colour", cell, index: item.colour });
      }
    }
    const nextStep = analysis.steps[stepIndex + 1];
    if (!inBranch && nextStep?.branch && !nextStep.revert) {
      const nextCell = (nextStep.events || []).find((ev) => ev.kind === "place")?.cell ?? null;
      actions.push({ op: "snapshot_start", cell: nextCell });
    }
    if (!step.branch) baseActions.push(...actions);
    steps.push(actions);
  }
  return steps;
}

async function postJson(url, body) {
  const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function fmtBytes(n) {
  if (!n) return "0 B";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}

function SectionLabel({ children, extra, tone = "neutral" }) {
  const color = tone === "danger" ? "text-rose-700 dark:text-rose-200"
    : tone === "success" ? "text-emerald-700 dark:text-emerald-200"
      : "text-muted-foreground";
  return (
    <div className="flex items-center gap-2">
      <span className={`text-[10px] font-medium uppercase tracking-[0.12em] ${color}`}>{children}</span>
      {extra}
    </div>
  );
}

function Digits({ digits, tone = "neutral" }) {
  const styles = {
    neutral: "border bg-background text-foreground",
    danger: "border-rose-300 bg-rose-100 font-medium text-rose-700 dark:border-rose-600 dark:bg-rose-500/20 dark:text-rose-100",
    success: "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300",
  };
  return (
    <div className="flex flex-wrap gap-1">
      {digits.map((digit, index) => (
        <span key={`${digit}-${index}`} className={`grid h-5 min-w-5 place-items-center rounded px-1 font-mono text-[11px] ${styles[tone]}`}>{digit}</span>
      ))}
    </div>
  );
}

function StepNarrative({ step, lang, n, t }) {
  const lines = String(step.detail || "").split("\n");
  const lead = [];
  const combos = [];
  let comboCount = null;
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) continue;
    const countMatch = line.match(/共\s*(\d+)\s*组/);
    if (countMatch) { comboCount = Number(countMatch[1]); continue; }
    if (/^\{.*\}$/.test(line)) {
      const digits = line.replace(/[{}]/g, "").split(/[、,，\s]+/).filter(Boolean);
      if (digits.length) combos.push(digits);
      continue;
    }
    if (/^R\d+C\d+\s*[≠=]/.test(line)) continue;
    if (line.includes("按这些组合") || line.includes("当前可行的数字组合")) continue;
    lead.push(line);
  }
  const places = [];
  const elims = new Map();
  for (const ev of step.events || []) {
    if (ev.kind === "place") places.push(ev);
    else if (ev.kind === "elim") {
      if (!elims.has(ev.cell)) elims.set(ev.cell, []);
      const list = elims.get(ev.cell);
      if (!list.includes(ev.value)) list.push(ev.value);
    }
  }
  const cellName = (cell) => `R${Math.floor(cell / n) + 1}C${(cell % n) + 1}`;
  const reason = step.events?.[0]?.reason?.data || {};
  let classLead = "";
  if (lang === "en" && step.technique === "class_cover" && reason.forced_cell != null && reason.forced_class) {
    const others = (reason.cells || []).filter((cell) => cell !== reason.forced_cell);
    classLead = `Every 2×2 region must contain one digit from each of ${(reason.classes || []).map((c) => `{${c.join(",")}}`).join(", ")}. The other cells (${others.map(cellName).join(", ")}) cannot be ${reason.forced_class.join(",")}, so ${cellName(reason.forced_cell)} must be ${reason.forced_class.join(",")}; the other digits are eliminated.`;
  }
  const candidates = step.candidates || [];
  return (
    <div className="space-y-3">
      {lang === "zh" && lead.length > 0 && <p className="whitespace-pre-wrap text-[13px] leading-7 text-foreground/90">{lead.join("\n")}</p>}
      {classLead && <p className="text-[13px] leading-7 text-foreground/90">{classLead}</p>}
      {combos.length > 0 && (
        <div className="rounded-lg border bg-muted/30 p-3">
          <SectionLabel extra={<Badge variant="outline">{comboCount === 1 || combos.length === 1 ? t("step.combinationOne") : t("step.combinationCount", { n: comboCount || combos.length })}</Badge>}>{t("step.combinations")}</SectionLabel>
          <div className="mt-2 grid grid-cols-2 gap-1.5 sm:grid-cols-3">
            {combos.map((digits, index) => (
              <div key={index} className="flex items-center justify-center gap-1 rounded-md border bg-background px-2 py-1.5 shadow-sm">
                {digits.map((digit, i) => <span key={i} className="grid h-5 w-5 place-items-center rounded bg-muted font-mono text-[11px]">{digit}</span>)}
              </div>
            ))}
          </div>
        </div>
      )}
      {places.length > 0 && (
        <div className="rounded-lg border border-emerald-200/70 bg-emerald-50/40 p-3 dark:border-emerald-800/80 dark:bg-emerald-950/30">
          <SectionLabel tone="success">{t("step.placed")}</SectionLabel>
          <div className="mt-2 space-y-1.5">
            {places.map((ev, index) => (
              <div key={index} className="flex items-center gap-2 text-xs"><span className="font-mono text-muted-foreground">{cellName(ev.cell)}</span><span className="text-muted-foreground">=</span><Digits digits={[ev.value]} tone="success" /></div>
            ))}
          </div>
        </div>
      )}
      {elims.size > 0 && (
        <div className="rounded-lg border border-rose-200/70 bg-rose-50/50 p-3 dark:border-rose-700/70 dark:bg-rose-950/40">
          <SectionLabel tone="danger">{t("step.eliminated")}</SectionLabel>
          <div className="mt-2 space-y-1.5">
            {[...elims.entries()].map(([cell, digits]) => (
              <div key={cell} className="flex items-center gap-2 text-xs"><span className="font-mono text-muted-foreground">{cellName(cell)}</span><span className="text-rose-500 dark:text-rose-300">≠</span><Digits digits={digits} tone="danger" /></div>
            ))}
          </div>
        </div>
      )}
      {candidates.length > 0 && (
        <div className="rounded-lg border bg-muted/30 p-3">
          <SectionLabel>{t("step.candidates")}</SectionLabel>
          <div className="mt-2 grid gap-1.5">
            {candidates.map((candidate) => (
              <div key={candidate.cell} className="flex items-center justify-between gap-2 rounded-md border bg-background px-2 py-1.5">
                <span className="font-mono text-[11px] text-muted-foreground">{cellName(candidate.cell)}</span>
                <Digits digits={candidate.digits} />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function GithubMark({ className = "h-4 w-4" }) {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true" className={className} fill="currentColor">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.012 8.012 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
    </svg>
  );
}

function looksLikePuzzle(value) {
  const text = String(value || "").trim();
  return /^https?:\/\//i.test(text) || /sudokupad\.app/i.test(text) || (/^[a-z0-9_-]{6,}$/i.test(text) && /\d/.test(text));
}

function PageHead({ title, description, badges, actions }) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2"><h1 className="text-2xl font-semibold tracking-tight">{title}</h1>{badges}</div>
        {description && <p className="mt-1.5 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

function EmptyState({ title, hint, action }) {
  return (
    <Card className="border-dashed">
      <CardContent className="flex min-h-[300px] flex-col items-center justify-center gap-3 text-center">
        <div className="grid h-11 w-11 place-items-center rounded-full bg-muted"><FolderOpen className="h-5 w-5 text-muted-foreground" /></div>
        <div><div className="font-medium">{title}</div><p className="mt-1 max-w-md text-sm text-muted-foreground">{hint}</p></div>
        {action}
      </CardContent>
    </Card>
  );
}

export default function App() {
  const [analysis, setAnalysis] = useState(null);
  const [busy, setBusy] = useState(false);
  const [url, setUrl] = useState("");
  const [target, setTarget] = useState("");
  const [llm, setLlm] = useState(true);
  const [audit, setAudit] = useState(false);
  const [idx, setIdx] = useState(-1);
  const [playing, setPlaying] = useState(false);
  const persisted = readPersisted();
  const [speed, setSpeed] = useState(() => Number(persisted.speed) || 1100);
  const [session, setSession] = useState(null);

  const [previewSrc, setPreviewSrc] = useState("");
  const [openingTitle, setOpeningTitle] = useState("");
  const [previewJob, setPreviewJob] = useState("");
  const [frameSrc, setFrameSrc] = useState("");
  const [frameStep, setFrameStep] = useState(-2);
  const [ready, setReady] = useState(false);
  const [retry, setRetry] = useState(0);
  const [frameVersion, setFrameVersion] = useState(0);
  const [view, setView] = useState(() => persisted.view || "solve");
  const [inspectorTab, setInspectorTab] = useState(() => persisted.inspectorTab || "explain");
  const [store, setStore] = useState(null);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("recent");
  const [favOnly, setFavOnly] = useState(false);
  const [error, setError] = useState("");
  const [notes, setNotes] = useState("");
  const [deleted, setDeleted] = useState(false);
  const [frameErrors, setFrameErrors] = useState(0);
  const [sessionGrid, setSessionGrid] = useState(null);
  const [frameGeometry, setFrameGeometry] = useState(null);
  const [lang, setLang] = useState(detectLang);
  const [dark, setDark] = useState(() => {
    try { return localStorage.getItem("ysudoku.theme") === "dark"; } catch { return false; }
  });
  const [rulePrompt, setRulePrompt] = useState(() => readPersisted().rulePrompt || "");
  const [conflictChoice, setConflictChoice] = useState(() => readPersisted().conflictChoice || "");
  const [settings, setSettings] = useState(() => ({
    ...DEFAULT_SETTINGS,
    ...(persisted.settings || {}),
  }));

  useEffect(() => {
    if (!analysis || (analysis.lang || "zh") === lang) return undefined;
    let cancelled = false;
    let timer = null;
    (async () => {
      try {
        const data = await postJson("/api/solve", {
          url: analysis.source_url || target,
          demo: !!analysis.demo,
          llm, audit, chains: true, lang,
        });
        if (cancelled) return;
        const next = data.steps || [];
        let count = Math.min(5, next.length);
        const apply = () => {
          if (cancelled) return;
          setAnalysis((prev) => prev ? {
            ...prev, steps: next.slice(0, count), rules: data.rules || prev.rules,
            status: data.status || prev.status, message: data.message || "",
            conflicts: data.conflicts || [], lang,
          } : prev);
          count = Math.min(next.length, count + 5);
          if (count >= next.length && timer) { clearInterval(timer); timer = null; }
        };
        apply();
        if (next.length > 5) timer = setInterval(apply, 40);
      } catch { /* keep current text */ }
    })();
    return () => { cancelled = true; if (timer) clearInterval(timer); };
  }, [lang, analysis?.storage?.key]);

  useEffect(() => {
    try {
      localStorage.setItem(PERSIST_KEY, JSON.stringify({
        speed, settings, view, inspectorTab, rulePrompt, conflictChoice,
      }));
    } catch {
      /* storage unavailable */
    }
  }, [speed, settings, view, inspectorTab, rulePrompt, conflictChoice]);
  const [stars, setStars] = useState(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [headerHidden, setHeaderHidden] = useState(false);
  const stepListRef = useRef(null);
  const stepScrollRef = useRef(0);
  const [phase, setPhase] = useState("idle");
  const [streamRules, setStreamRules] = useState([]);
  const [streamSteps, setStreamSteps] = useState([]);
  const [streamTarget, setStreamTarget] = useState([]);
  const finalPayload = useRef(null);
  const [frameProgress, setFrameProgress] = useState({ frames: 0, total: 0, complete: false });

  useEffect(() => {
    if (!session) return;
    let cancelled = false;
    let timer = null;
    const load = async (attempt = 0) => {
      if (cancelled) return;
      try {
        const r = await fetch(`/api/live/grid?session=${encodeURIComponent(session)}`);
        if (r.ok) {
          const data = await r.json();
          if (data && !cancelled) { setSessionGrid({ session, rect: data }); return; }
        }
      } catch { /* retry */ }
      if (attempt < 120 && !cancelled) timer = setTimeout(() => load(attempt + 1), 500);
    };
    load();
    return () => { cancelled = true; if (timer) clearTimeout(timer); };
  }, [session, frameVersion, frameProgress.complete]);
  const frameTimer = useRef(null);
  const streamToken = useRef(0);

  const t = (key, vars) => translate(lang, key, vars);
  const puzzleUnit = (count) => (lang === "zh" ? "个谜题" : count === 1 ? "puzzle" : "puzzles");
  const steps = analysis?.steps || [];
  const n = analysis?.puzzle?.size || 9;
  const current = idx >= 0 ? steps[idx] : null;
  const statusLabel = (status) => t(`status.${status || "none"}`) || status;
  const stepTitle = (step) => (lang === "en" ? TECH_EN[step.technique] || step.title : step.title);
  const ruleLabel = (rule) => (lang === "en" ? RULE_EN[rule.kind] || rule.label || rule.kind : rule.label || rule.kind);
  const cellName = (cell) => `R${Math.floor(cell / n) + 1}C${(cell % n) + 1}`;
  const englishSummary = (step) => {
    const places = [];
    const elims = new Map();
    for (const ev of step.events || []) {
      if (ev.kind === "place") places.push(`${ev.value} in ${cellName(ev.cell)}`);
      else if (ev.kind === "elim") {
        if (!elims.has(ev.cell)) elims.set(ev.cell, []);
        elims.get(ev.cell).push(ev.value);
      }
    }
    const parts = [];
    if (places.length) parts.push(`Place ${places.join(", ")}.`);
    for (const [cell, values] of elims) parts.push(`Eliminate ${values.join(", ")} from ${cellName(cell)}.`);
    return parts.length ? parts.join(" ") : step.detail;
  };

  useEffect(() => {
    document.documentElement.removeAttribute("data-accent");
  }, []);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    try { localStorage.setItem("ysudoku.theme", dark ? "dark" : "light"); } catch { /* ignore */ }
  }, [dark]);

  useEffect(() => {
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
    try { localStorage.setItem("ysudoku.lang", lang); } catch { /* ignore */ }
  }, [lang]);

  useEffect(() => {
    if (streamSteps.length >= streamTarget.length) {
      if (finalPayload.current !== null) {
        const payload = finalPayload.current;
        finalPayload.current = null;
        applyAnalysis(payload);
      }
      return;
    }
    const timer = setTimeout(() => {
      setStreamSteps(streamTarget.slice(0, streamSteps.length + 1));
    }, 20);
    return () => clearTimeout(timer);
  }, [streamSteps, streamTarget]);

  useEffect(() => {
    const el = stepListRef.current;
    if (!el) return;
    el.scrollTop = stepScrollRef.current;
  }, [streamSteps.length, phase]);

  useEffect(() => {
    let lastY = window.scrollY;
    const onScroll = () => {
      const y = window.scrollY;
      if (window.innerWidth >= 1024) {
        setHeaderHidden(false);
        lastY = y;
        return;
      }
      if (y > lastY + 8 && y > 70) setHeaderHidden(true);
      else if (y < lastY - 8) setHeaderHidden(false);
      lastY = y;
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    if (!playing || deleted || (frameStep !== idx && !(idx === -1 && previewSrc))) return;
    if (idx >= steps.length - 1) { setPlaying(false); return; }
    const timer = setTimeout(() => setIdx((value) => Math.min(value + 1, steps.length - 1)), speed);
    return () => clearTimeout(timer);
  }, [playing, idx, steps.length, speed, deleted, frameStep, previewSrc]);

  useEffect(() => {
    const onKey = (event) => {
      if (view !== "solve" || !steps.length || event.target.closest?.("input, select, textarea, button, [role=slider]")) return;
      if (event.key === "ArrowRight") { setPlaying(false); setIdx((v) => Math.min(v + 1, steps.length - 1)); }
      if (event.key === "ArrowLeft") { setPlaying(false); setIdx((v) => Math.max(v - 1, -1)); }
      if (event.key === " ") { event.preventDefault(); togglePlayback(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [steps.length, view, idx, playing, deleted]);

  async function refreshStore() {
    try {
      const res = await fetch("/api/store");
      if (res.ok) {
        const data = await res.json();
        setStore(data);
        if (data.info?.settings) setSettings(data.info.settings);
      }
    } catch { /* ignore */ }
  }

  useEffect(() => { refreshStore(); }, []);

  useEffect(() => {
    fetch("https://api.github.com/repos/CodeInDreams/ysudoku")
      .then((res) => res.ok ? res.json() : null)
      .then((data) => { if (data && typeof data.stargazers_count === "number") setStars(data.stargazers_count); })
      .catch(() => {});
  }, []);

  async function verifyCurrentCache(key) {
    if (!key) return;
    if (phase === "rendering") return;
    try {
      const res = await fetch("/api/store");
      if (!res.ok) return;
      const data = await res.json();
      const entry = (data.entries || []).find((item) => item.key === key);
      if (!entry || !entry.layers?.rules || !entry.layers?.steps) {
        setDeleted(true);
        setPlaying(false);
        setReady(false);
        return;
      }
      if (!entry.layers?.frames) {
        setPhase("rendering");
        setReady(false);
        if (analysis) startLive(analysis);
      }
    } catch { /* ignore */ }
  }

  useEffect(() => {
    if (!session || deleted) return undefined;
    let cancelled = false;
    const src = `/api/live/frame?session=${session}&step=${idx}&t=${frameVersion}-${retry}`;
    const probe = new Image();
    probe.onload = () => {
      if (cancelled) return;
      const width = probe.naturalWidth;
      const height = probe.naturalHeight;
      const rect = detectGridRect(probe, analysis?.puzzle?.size || 9);
      setFrameGeometry({ src, width, height, rect });
      setFrameSrc(src);
      setFrameStep(idx);
      setReady(true);
      setFrameErrors(0);
    };
    probe.onerror = () => {
      if (cancelled) return;
      const next = frameErrors + 1;
      setFrameErrors(next);
      if (next >= 24 && phase !== "rendering") verifyCurrentCache(analysis?.storage?.key);
      setTimeout(() => setRetry((value) => value + 1), 450);
    };
    probe.src = src;
    return () => { cancelled = true; };
  }, [session, idx, retry, deleted, phase, analysis]);

  function applyAnalysis(data, keepView = false) {
    setAnalysis(data);
    if (!keepView) setView("solve");
    setIdx(-1);
    setPlaying(false);
    setDeleted(false);
    setFrameErrors(0);
    setError("");
    setNotes(data.notes || data.rules?.notes || "");
    setPhase(data.cached ? "opening" : "rendering");
    startLive(data);
    refreshStore();
  }

  async function startLive(nextAnalysis) {
    const token = streamToken.current;
    setReady(false);
    setSession(null);
    setSessionGrid(null);
    setFrameSrc("");
    setFrameStep(-2);
    setDeleted(false);
    setFrameErrors(0);
    setFrameVersion(Date.now());
    try {
      const actions = buildStepActions(nextAnalysis);
      let hash = 2166136261;
      const text = "frame-v28:" + JSON.stringify(actions);
      for (let i = 0; i < text.length; i++) { hash ^= text.charCodeAt(i); hash = Math.imul(hash, 16777619); }
      const data = await postJson("/api/live/build", {
        url: nextAnalysis.source_url || "",
        size: nextAnalysis.puzzle?.size || 0,
        steps: actions,
        key: nextAnalysis.storage?.key || "",
        steps_hash: (hash >>> 0).toString(16),
      });
      if (token !== streamToken.current) return;
      setSession(data.session);
      if (data.cached && data.complete) {
        setPhase("done");
      } else {
        setPhase("rendering");
        startFrameProgress(data.session, actions.length);
      }
      setRetry((v) => v + 1);
    } catch (err) {
      if (token === streamToken.current) {
        setPhase("failed");
        setError(`${t("error.build")}: ${err.message}`);
      }
    }
  }

  function startFrameProgress(key, total) {
    if (frameTimer.current) clearInterval(frameTimer.current);
    setFrameProgress({ frames: 0, total, complete: false });
    if (!key || !total) { setPhase("done"); return; }
    const token = streamToken.current;
    const tick = async () => {
      try {
        const res = await fetch(`/api/live/progress?session=${encodeURIComponent(key)}&total=${total}`);
        if (res.ok) {
          const data = await res.json();
          if (token !== streamToken.current) return;
          setFrameProgress({ frames: data.frames || 0, total: data.total || total, complete: !!data.complete });
          if (data.error) {
            setError(`${t("error.build")}: ${data.error.message || "render failed"}`);
            setPhase("failed");
            if (frameTimer.current) clearInterval(frameTimer.current);
            frameTimer.current = null;
            return;
          }
          if (data.complete) {
            setPhase("done");
            if (frameTimer.current) clearInterval(frameTimer.current);
            frameTimer.current = null;
          }
        }
      } catch { /* keep polling */ }
    };
    tick();
    frameTimer.current = setInterval(tick, 500);
  }

  async function streamSolve(body, targetUrl, title = "") {
    const token = ++streamToken.current;
    setOpeningTitle(title);
    setPreviewSrc("");
    setPreviewJob("");
    setView("solve");
    setSession(null);
    setSessionGrid(null);
    setFrameSrc("");
    setFrameStep(-2);
    setReady(false);
    setIdx(-1);
    if (frameTimer.current) clearInterval(frameTimer.current);
    setBusy(true); setError(""); setPlaying(false);
    setAnalysis(null); setStreamRules([]); setStreamSteps([]); setStreamTarget([]); finalPayload.current = null;
    setPhase("opening");
    try {
      const { id } = await postJson("/api/solve/start", { ...body, wait_for_preview: true });
      while (token === streamToken.current) {
        await new Promise((resolve) => setTimeout(resolve, 300));
        const res = await fetch(`/api/job?id=${encodeURIComponent(id)}`);
        const job = await res.json().catch(() => ({}));
        if (token !== streamToken.current) return;
        if (!res.ok) throw new Error(job.error || "job failed");
        if (job.title) setOpeningTitle(job.title);
        if (job.preview) { setPreviewJob(id); setPreviewSrc(job.preview); }
        if (job.phase === "preview" || job.phase === "rules") setPhase(job.phase);
        setStreamRules(job.rules || []);
        setStreamTarget(job.steps || []);
        if (job.phase === "solving") setPhase("solving");
        if (job.status === "done") {
          setTarget(targetUrl);
          setUrl(targetUrl);
          if (job.payload?.cached) {
            applyAnalysis(job.payload);
          } else {
            finalPayload.current = job.payload;
            setPhase("solving");
          }
          break;
        }
        if (job.status === "failed") throw new Error(job.error || "solve failed");
      }
    } catch (err) {
      if (token === streamToken.current) {
        setPhase("failed");
        setError(`${t("error.solve")}: ${err.message}`);
      }
    } finally {
      if (token === streamToken.current) setBusy(false);
    }
  }

  async function submit(payload) {
    await streamSolve({ url: payload.url, llm, audit, chains: true, demo: false, rule_prompt: rulePrompt, lang }, payload.url);
  }

  async function demo() {
    await streamSolve({ demo: true, llm, audit, chains: true, rule_prompt: rulePrompt, lang }, "");
  }

  async function refreshRules() {
    if (!analysis) return;
    setBusy(true); setPlaying(false);
    try {
      const data = await postJson("/api/store/refresh_rules", { target: target || "", demo: !!analysis.demo, notes });
      applyAnalysis(data, true);
      setInspectorTab("explain");
    } catch (err) { setError(`${t("error.refresh")}: ${err.message}`); }
    finally { setBusy(false); }
  }

  async function toggleFavorite(entry) {
    await postJson("/api/store/favorite", { key: entry.key, favorite: !entry.favorite });
    refreshStore();
  }

  function exitPuzzle() {
    ++streamToken.current;
    setOpeningTitle("");
    if (frameTimer.current) clearInterval(frameTimer.current);
    setBusy(false);
    setPreviewJob("");
    setPlaying(false);
    setAnalysis(null);
    setSession(null);
    setSessionGrid(null);
    setFrameSrc("");
    setFrameStep(-2);
    setIdx(-1);
    setDeleted(false);
    setReady(false);
    setPreviewSrc("");
    setPhase("idle");
    setView("solve");
  }

  async function rebuildEntry(entry) {
    if (entry.demo) await demo();
    else await loadEntry(entry);
  }

  async function removeLayer(entry, layer) {
    const isCurrent = entry.key === analysis?.storage?.key;
    const label = t(`layers.${layer}`);
    const cascade = layer === "rules" ? t("history.cascadeRules") : layer === "steps" ? t("history.cascadeSteps") : "";
    const message = isCurrent
      ? t("history.confirmDeleteCurrentLayer", { title: entry.title, layer: label })
      : t("history.confirmDelete", { title: entry.title, layer: label });
    if (!window.confirm(`${message}\n\n${cascade}`.trim())) return;
    await postJson("/api/store/delete", { key: entry.key, layer });
    if (isCurrent) await rebuildEntry(entry);
    refreshStore();
  }

  async function removeEntry(entry) {
    const isCurrent = entry.key === analysis?.storage?.key;
    if (isCurrent) {
      if (!window.confirm(t("history.deleteCurrentConfirm", { title: entry.title }))) return;
      await postJson("/api/store/delete", { key: entry.key, layer: "all" });
      exitPuzzle();
    } else {
      if (!window.confirm(t("history.deletePuzzleConfirm", { title: entry.title }))) return;
      await postJson("/api/store/delete", { key: entry.key, layer: "all" });
    }
    refreshStore();
  }

  async function saveSettings() {
    await postJson("/api/store/settings", settings);
    refreshStore();
  }

  async function loadEntry(entry) {
    setView("solve");
    setError("");
    setPlaying(false);
    setAnalysis(null);
    setStreamRules([]);
    setStreamSteps([]);
    setStreamTarget([]);
    const targetUrl = entry.demo ? "" : entry.target;
    setTarget(targetUrl);
    setUrl(targetUrl);
    await streamSolve(
      entry.demo
        ? { demo: true, llm, audit, chains: true }
        : { url: entry.target, llm, audit, chains: true, demo: false, lang },
      targetUrl, entry.title,
    );
  }

  async function cacheAlive() {
    if (!analysis?.storage?.key || !ready) return true;
    if (phase === "rendering") return true;
    try {
      const res = await fetch("/api/store");
      const data = await res.json().catch(() => ({}));
      const entry = (data.entries || []).find((item) => item.key === analysis.storage.key);
      if (!entry || !entry.layers?.steps) {
        setDeleted(true);
        setPlaying(false);
        setReady(false);
        setError(t("step.deleted"));
        return false;
      }
      if (!entry.layers?.frames) {
        setPhase("rendering");
        setReady(false);
        startLive(analysis);
        return true;
      }
    } catch { /* network errors should not block playback */ }
    return true;
  }

  async function nextStep() {
    if (deleted) { setError(t("step.deleted")); setPlaying(false); return; }
    setPlaying(false);
    if (!(await cacheAlive())) return;
    setIdx((v) => Math.min(steps.length - 1, v + 1));
  }

  function togglePlayback() {
    if (!steps.length || deleted) return;
    if (!playing && idx === steps.length - 1) setIdx(-1);
    setPlaying(!playing);
  }

  function goToStart() {
    setPlaying(false);
    setIdx(-1);
  }

  function prevStep() {
    if (deleted) { setError(t("step.deleted")); setPlaying(false); return; }
    setPlaying(false);
    setIdx((v) => Math.max(-1, v - 1));
  }

  const filteredEntries = useMemo(() => {
    const list = (store?.entries || []).filter((entry) => {
      if (favOnly && !entry.favorite) return false;
      if (!query) return true;
      return `${entry.title} ${entry.author}`.toLowerCase().includes(query.toLowerCase());
    });
    return list.sort((a, b) => sort === "title" ? String(a.title).localeCompare(String(b.title)) : (b.at || 0) - (a.at || 0));
  }, [store, query, sort, favOnly]);

  const searchResults = useMemo(() => {
    const text = url.trim().toLowerCase();
    if (!text) return [];
    return (store?.entries || []).filter((entry) =>
      `${entry.title} ${entry.author} ${entry.target}`.toLowerCase().includes(text)
    ).slice(0, 6);
  }, [store, url]);

  const overlay = useMemo(() => {
    if (!analysis || frameStep < 0 || deleted) return null;
    const state = candidateStateUpTo(analysis, frameStep);
    const negatives = [];
    for (const [cell, set] of state) {
      if (set.size <= 5) continue;
      const excluded = [];
      for (let v = 1; v <= n; v++) if (!set.has(v)) excluded.push(v);
      if (excluded.length && excluded.length <= 3) negatives.push({ cell, digits: excluded });
    }
    return { visual: steps[frameStep]?.visual || {}, negatives };
  }, [analysis, frameStep, n, steps, deleted]);

  const resolvedRules = useMemo(() => {
    const merged = new Map();
    for (const rule of analysis?.rules?.resolved || streamRules || []) {
      if (rule.kind === "_ignored") continue;
      const label = ruleLabel(rule);
      merged.set(label, (merged.get(label) || 0) + Number(rule.count || 1));
    }
    return [...merged.entries()].map(([label, count]) => ({ label, count }));
  }, [analysis, lang, streamRules]);

  const displaySteps = analysis ? steps : streamSteps;
  const phasePct = phase === "rules" ? 8
    : phase === "solving" ? Math.min(85, 15 + streamSteps.length * 2)
      : phase === "rendering" ? (frameProgress.total ? Math.round((frameProgress.frames / frameProgress.total) * 100) : 12)
        : phase === "done" ? 100 : 0;
  const phaseLabel = ["opening", "preview"].includes(phase) ? t("board.loading") : phase === "rules" ? t("phase.rules")
    : phase === "solving" ? `${t("phase.solving")} · ${t("phase.steps", { n: streamSteps.length })}`
      : phase === "rendering" ? `${t("phase.rendering")} · ${t("phase.frames", { done: frameProgress.frames, total: frameProgress.total })}`
        : phase === "done" ? t("phase.done") : phase === "failed" ? t("phase.failed") : "";
  const phaseHint = phase === "rules" ? t("phase.rulesHint")
    : phase === "solving" ? t("phase.solvingHint")
      : phase === "rendering" ? t("phase.renderingHint") : "";

  const currentEntry = (store?.entries || []).find((entry) => entry.key === analysis?.storage?.key);
  const candidateCount = current?.candidates?.length || 0;
  const isSolved = ["solved", "solved-global", "solved-search"].includes(analysis?.status);

  const navItems = [["solve", "nav.solve"], ["rules", "nav.rules"], ["history", "nav.history"]];

  const emptySolve = (
    <EmptyState title={t("empty.solveTitle")} hint={t("empty.solveHint")}
      action={<Button onClick={demo} disabled={busy}>{t("header.demo")}</Button>} />
  );

  const showingPreview = previewSrc && (!frameSrc || idx < 0);
  const geometry = frameGeometry?.src === frameSrc ? frameGeometry : null;
  const metadata = sessionGrid?.session === session ? sessionGrid.rect : null;
  const savedRect = geometry && metadata?.imageWidth === geometry.width && metadata?.imageHeight === geometry.height
    ? metadata : null;
  const measuredRect = geometry?.rect;
  const gridRect = measuredRect && (!savedRect || ["x", "y", "width", "height"].every(
    key => Math.abs(measuredRect[key] - savedRect[key]) <= 3
  )) ? measuredRect : savedRect;
  const boardCard = (analysis || previewSrc) && (
    <Card className="overflow-hidden">
      <CardHeader className="flex-row items-center gap-3 space-y-0 border-b py-3.5">
        <div><CardTitle className="text-sm">{t("board.title")}</CardTitle><p className="mt-0.5 text-xs text-muted-foreground">{idx < 0 ? t("board.initial") : t(candidateCount === 1 ? "board.descCandidate" : "board.descCandidates", { i: idx + 1, c: candidateCount })}</p></div>
        <div className="ml-auto flex items-center gap-1.5"><Badge variant="outline">{t("board.readonly")}</Badge><Badge variant="outline">{t("board.readonly.badge")}</Badge></div>
      </CardHeader>
      <CardContent className="p-5">
        <div className="relative mx-auto flex w-full max-w-[540px] items-center justify-center overflow-hidden rounded-[2px] border bg-white dark:border-border dark:bg-neutral-800"
          style={{ aspectRatio: geometry && !showingPreview ? `${geometry.width} / ${geometry.height}` : "1 / 1" }}>
          {!ready && !previewSrc && !deleted && <div className="absolute inset-0 z-10 grid place-items-center gap-2 bg-white/80 text-xs text-slate-500 dark:bg-neutral-800/90 dark:text-neutral-300"><Loader2 className="h-5 w-5 animate-spin text-primary" />{t("board.loading")}</div>}
          {deleted && (
            <div className="absolute inset-0 z-20 grid place-items-center bg-background/90 p-6 text-center">
              <div className="max-w-xs space-y-2">
                <AlertTriangle className="mx-auto h-6 w-6 text-amber-500" />
                <div className="text-sm font-medium">{t("step.deletedShort")}</div>
                <p className="text-xs text-muted-foreground">{t("step.deleted")}</p>
              </div>
            </div>
          )}
          {showingPreview && !deleted && (
            <img src={previewSrc} alt={t("board.initial")} className="h-full w-full object-contain"
              onLoad={() => {
                if (previewJob) requestAnimationFrame(() => requestAnimationFrame(() => {
                  fetch(`/api/job/preview-ready?id=${encodeURIComponent(previewJob)}`, { method: "POST" }).catch(() => {});
                }));
              }} />
          )}
          {frameSrc && !showingPreview && !deleted && (
            <img src={frameSrc} alt="SudokuPad"
              className={`h-full w-full object-fill transition-opacity ${ready ? "opacity-100" : "opacity-0"}`}
              style={{ filter: dark ? "brightness(0.8) contrast(1.04)" : undefined }}
              onLoad={() => setReady(true)} />
          )}
          {overlay && gridRect && idx >= 0 && !showingPreview && ready && !deleted && (
            <svg className="pointer-events-none absolute" viewBox={`0 0 ${n} ${n}`} preserveAspectRatio="none"
              style={{
                left: `${(gridRect.x / gridRect.imageWidth) * 100}%`,
                top: `${(gridRect.y / gridRect.imageHeight) * 100}%`,
                width: `${(gridRect.width / gridRect.imageWidth) * 100}%`,
                height: `${(gridRect.height / gridRect.imageHeight) * 100}%`,
              }}>
              <CellColours visual={overlay.visual} n={n} />
              {(overlay.visual.region_edges || []).map(({ cells: [a, b], fixed }) => {
                const vertical = Math.abs(a - b) === 1;
                const cell = Math.max(a, b);
                const x = cell % n, y = Math.floor(cell / n);
                return <line key={a + "/" + b} x1={x} y1={y} x2={x + (vertical ? 0 : 1)}
                  y2={y + (vertical ? 1 : 0)} stroke="#155e75" strokeWidth="0.065"
                  strokeDasharray={fixed ? undefined : "0.12 0.10"} />;
              })}
              {overlay.visual.assumption && (() => {
                const a = overlay.visual.assumption;
                const cells = a.cells || [];
                if (!cells.length) return null;
                const rows = cells.map((c) => Math.floor(c / n));
                const cols = cells.map((c) => c % n);
                const minR = Math.min(...rows), maxR = Math.max(...rows);
                const minC = Math.min(...cols), maxC = Math.max(...cols);
                const label = a.label || "假设";
                const width = Math.min(n - 0.1, Math.max(1.1, label.length * 0.098 + 0.3));
                const x = Math.min(n - width - 0.05, Math.max(0.05, (minC + maxC + 1) / 2 - width / 2));
                const above = minR > 0.7;
                const y = above ? Math.max(0.03, minR - 0.26) : Math.min(n - 0.28, maxR + 1.03);
                return (
                  <g>
                    <rect x={minC + 0.02} y={minR + 0.02} width={maxC - minC + 0.96} height={maxR - minR + 0.96} rx="0.07" fill="#dc2626" fillOpacity="0.10" stroke="#dc2626" strokeWidth="0.055" strokeDasharray="0.12 0.07" />
                    <rect x={x} y={y} width={width} height="0.24" rx="0.06" fill="#dc2626" fillOpacity="0.92" />
                    <text x={x + width / 2} y={y + 0.17} textAnchor="middle" fontSize="0.135" fontWeight="600" fill="#fff" style={{ fontFamily: "ui-sans-serif, system-ui" }}>{label}</text>
                  </g>
                );
              })()}
              {(overlay.visual.focus || []).map((cell) => {
                const r = Math.floor(cell / n), c = cell % n;
                return <rect key={`f${cell}`} x={c + 0.03} y={r + 0.03} width="0.94" height="0.94" rx="0.06" fill="rgba(217,119,6,.12)" stroke="#d97706" strokeWidth="0.045" />;
              })}
              {overlay.negatives.map(({ cell, digits }) => {
                const r = Math.floor(cell / n), c = cell % n;
                const stepX = 0.17;
                const startX = c + 0.5 - (digits.length * stepX) / 2;
                return digits.map((v, i) => (
                  <text key={`n${cell}-${v}`} x={startX + i * stepX + stepX / 2} y={r + 0.88} textAnchor="middle" fontSize="0.26" fontWeight="600" fill="#b91c1c" textDecoration="line-through" style={{ fontFamily: "ui-sans-serif, system-ui" }}>{v}</text>
                ));
              })}
            </svg>
          )}
          <span className="pointer-events-none absolute right-0.5 top-0.5 rounded-sm bg-white/35 px-1 py-px text-[8px] font-normal text-slate-400/75 dark:bg-black/20 dark:text-neutral-600">{t("board.liveFrame", { i: idx + 1, n: steps.length })}</span>
        </div>
      </CardContent>
      <div className="flex items-center gap-2 border-t px-4 py-3">
        <Button variant="outline" size="icon" className="h-8 w-8" onClick={prevStep} disabled={idx <= -1 || deleted}><ChevronLeft className="h-4 w-4" /></Button>
        <Button size="sm" onClick={togglePlayback} disabled={!steps.length || deleted}>
          {playing ? <Pause className="mr-1 h-3.5 w-3.5" /> : <Play className="mr-1 h-3.5 w-3.5" />}
          {playing ? t("player.pause") : t("player.play")}
        </Button>
        <Button variant="outline" size="icon" className="h-8 w-8" onClick={nextStep} disabled={idx >= steps.length - 1 || deleted}><ChevronRight className="h-4 w-4" /></Button>
        <span className="ml-2 hidden text-xs text-muted-foreground sm:inline">{t("player.speed")}</span>
        <Slider value={[2600 - speed]} min={200} max={2400} step={100} onValueChange={([value]) => setSpeed(2600 - value)} className="w-28" />
        <span className="ml-auto font-mono text-[11px] text-muted-foreground">{t("player.step", { i: idx + 1, n: steps.length })}</span>
      </div>
      <div className="border-t px-4 py-3">
        <Slider
          value={[idx + 1]}
          min={0}
          max={steps.length}
          step={1}
          onValueChange={([value]) => { setPlaying(false); setIdx(value - 1); }}
          disabled={!steps.length || deleted}
        />
      </div>
    </Card>
  );

  const inspector = analysis && (
    <Card>
      <Tabs value={inspectorTab} onValueChange={setInspectorTab}>
        <div className="border-b px-4">
          <TabsList className="h-auto w-full justify-start gap-5 rounded-none bg-transparent p-0">
            <TabsTrigger value="explain" className="rounded-none border-b-2 border-transparent px-0 pb-2.5 pt-3 text-[13px] text-muted-foreground shadow-none data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:font-semibold data-[state=active]:text-foreground data-[state=active]:shadow-none">{t("inspector.explain")}</TabsTrigger>
            <TabsTrigger value="candidates" className="rounded-none border-b-2 border-transparent px-0 pb-2.5 pt-3 text-[13px] text-muted-foreground shadow-none data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:font-semibold data-[state=active]:text-foreground data-[state=active]:shadow-none">{t("inspector.candidates")}</TabsTrigger>
            <TabsTrigger value="rules" className="rounded-none border-b-2 border-transparent px-0 pb-2.5 pt-3 text-[13px] text-muted-foreground shadow-none data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:font-semibold data-[state=active]:text-foreground data-[state=active]:shadow-none">{t("inspector.rules")}</TabsTrigger>
          </TabsList>
        </div>
        <CardContent className="p-4">
          {deleted && <div className="mb-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">{t("step.deleted")}</div>}
          <TabsContent value="explain" className="mt-0">
            {current ? (
              <div className="space-y-3">
                <div className="flex items-center gap-2"><h2 className="text-sm font-semibold">{stepTitle(current)}</h2><Badge variant="outline">{t("step.tier", { tier: current.tier })}</Badge></div>
                <p className="text-[11px] text-muted-foreground">{t("step.of", { i: idx + 1, n: steps.length })}</p>
                <StepNarrative step={current} lang={lang} n={n} t={t} />
                {current.visual?.region_progress && (
                  <p className="text-xs text-muted-foreground">
                    {lang === "zh"
                      ? `区域完成 ${current.visual.region_progress.complete}/${current.visual.region_progress.total} · 单色格 ${current.visual.region_progress.coloured}/${n * n}`
                      : `${current.visual.region_progress.complete}/${current.visual.region_progress.total} regions complete · ${current.visual.region_progress.coloured}/${n * n} single-colour cells`}
                  </p>
                )}
                {current.visual?.region_pairs?.length > 0 && (
                  <details className="text-xs">
                    <summary className="cursor-pointer">{lang === "zh" ? "区域颜色关系" : "Region colour relationships"}</summary>
                    <table className="mt-2 w-full"><tbody>
                      {current.visual.colours.filter(group => group.region).map(group => {
                        const related = current.visual.region_pairs.filter(p => p.a === group.colour || p.b === group.colour);
                        const list = possible => related.filter(p => p.possible === possible).map(p => p.a === group.colour ? p.b : p.a).join(", ") || "—";
                        return <tr key={group.colour} className="border-b">
                          <th className="p-1 text-left"><span style={{ backgroundColor: group.hex }} className="mr-1 inline-block h-3 w-3 rounded-sm" />
                            {cellName(group.cells[0])} (#{group.colour})</th>
                          <td>{lang === "zh" ? "可能同区" : "May match"} {list(true)}</td>
                          <td>{lang === "zh" ? "确定异区" : "Distinct"} {list(false)}</td>
                        </tr>;
                      })}
                    </tbody></table>
                  </details>
                )}
                {current.audit === "ok" && <div className="rounded-md bg-emerald-50 px-2 py-1 text-[11px] text-emerald-700 dark:bg-emerald-950 dark:text-emerald-200">✓ {t("step.audited")}</div>}
                {current.audit === "bad" && <div className="rounded-md bg-rose-50 px-2 py-1 text-[11px] text-rose-700 dark:bg-rose-950 dark:text-rose-200">✗ {t("step.auditBad")}</div>}
                <div className="flex gap-2 pt-1">
                  <Button variant="outline" size="sm" className="flex-1" onClick={prevStep} disabled={idx <= -1 || deleted}>{t("step.prev")}</Button>
                  <Button size="sm" className="flex-1" onClick={nextStep} disabled={idx >= steps.length - 1 || deleted}>{t("step.next")}</Button>
                </div>
              </div>
            ) : phase !== "idle" && !analysis ? (
              <div className="space-y-3 py-3">
                <div className="flex items-center gap-2 text-sm font-medium"><Loader2 className="h-4 w-4 animate-spin text-primary" />{phaseLabel}</div>
                <div className="space-y-2">
                  {Array.from({ length: 3 }).map((_, i) => <div key={i} className="h-3 animate-pulse rounded bg-muted" style={{ width: `${92 - i * 16}%` }} />)}
                </div>
              </div>
            ) : (
              <div className="py-6 text-center"><div className="text-sm font-medium">{t("step.none")}</div><p className="mt-1 text-xs text-muted-foreground">{t("step.noneHint")}</p></div>
            )}
          </TabsContent>
          <TabsContent value="candidates" className="mt-0">
            {idx >= 0 ? (
              <div className="space-y-1">
                {[...candidateStateUpTo(analysis, idx)].slice(0, 40).map(([cell, set]) => (
                  <div key={cell} className="flex items-center justify-between border-b py-1.5 text-xs last:border-0">
                    <span className="font-mono text-muted-foreground">R{Math.floor(cell / n) + 1}C{(cell % n) + 1}</span>
                    <span className="font-mono">{set.size > 6 ? t("candidates.count", { n: set.size }) : [...set].join(" ") || "—"}</span>
                  </div>
                ))}
              </div>
            ) : <p className="py-6 text-center text-xs text-muted-foreground">{t("step.noneHint")}</p>}
          </TabsContent>
          <TabsContent value="rules" className="mt-0 space-y-1">
            {resolvedRules.map((rule, i) => (
              <div key={i} className="flex items-center justify-between border-b py-1.5 text-xs last:border-0"><span>{rule.label}</span><span className="text-muted-foreground">× {rule.count}</span></div>
            ))}
            {analysis?.conflicts?.length > 0 && (
              <Button variant="outline" size="sm" className="mt-3 w-full"
                onClick={() => setConflictChoice("")}>
                重新选择规则识别
              </Button>
            )}
            <Button variant="link" size="sm" className="mt-2 px-0" onClick={() => setView("rules")}>{t("nav.rules")} →</Button>
          </TabsContent>
        </CardContent>
      </Tabs>
    </Card>
  );

  const stepsCard = (analysis || ["rules", "solving", "rendering"].includes(phase)) && (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 py-3.5">
        <CardTitle className="text-sm">{t("tabs.steps")}</CardTitle>
        <div className="flex items-center gap-2">
          {["rules", "solving", "rendering"].includes(phase) && <Badge variant="outline">{phaseLabel}</Badge>}
          <span className="text-[11px] text-muted-foreground">{displaySteps.length}{phase === "solving" ? "…" : ""}</span>
        </div>
      </CardHeader>
      <CardContent className="p-2 pt-0">
        <div
          ref={stepListRef}
          className="max-h-[260px] overflow-y-auto"
          style={{ overflowAnchor: "none" }}
          onScroll={(e) => { stepScrollRef.current = e.currentTarget.scrollTop; }}
        >
          {(analysis || previewSrc) && (
            <button onClick={goToStart} disabled={deleted} aria-current={idx < 0 ? "step" : undefined}
              className={`flex w-full items-center gap-3 rounded-md px-2.5 py-1.5 text-left text-xs ${idx < 0 ? "bg-muted font-medium" : "text-muted-foreground hover:bg-muted/60"}`}>
              <span className="w-6 text-right font-mono text-[10.5px]">0</span>{t("board.initial")}
            </button>
          )}
          {displaySteps.map((step, i) => (
            <button key={i} disabled={!analysis || deleted} onClick={() => { setPlaying(false); setIdx(i); }} className={`flex w-full items-center gap-3 rounded-md px-2.5 py-1.5 text-left text-xs ${i === idx ? "bg-muted font-medium text-foreground" : "text-muted-foreground hover:bg-muted/60"}`}>
              <span className="w-6 text-right font-mono text-[10.5px]">{i + 1}</span><span className="truncate">{stepTitle(step)}</span>
              <Badge variant="outline" className="ml-auto">{t("step.tier", { tier: step.tier })}</Badge>
            </button>
          ))}
          {phase === "rendering" && (
            <div className="flex animate-pulse items-center gap-3 rounded-md px-2.5 py-2 text-[11px] text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" />{phaseLabel}
            </div>
          )}
          {["rules", "solving"].includes(phase) && !analysis && Array.from({ length: 3 }).map((_, i) => (
            <div key={`sk-${i}`} className="flex animate-pulse items-center gap-3 rounded-md px-2.5 py-2">
              <span className="h-2.5 w-5 rounded bg-muted" />
              <span className="h-2.5 flex-1 rounded bg-muted" />
              <span className="h-2.5 w-8 rounded bg-muted" />
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );

  const entryTable = (entries, byOpened = false) => (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-xs">
        <thead><tr className="text-left text-muted-foreground">
          <th className="border-b px-3 py-2 font-medium">{t("table.puzzle")}</th>
          <th className="border-b px-3 py-2 font-medium">{t("table.status")}</th>
          <th className="border-b px-3 py-2 font-medium">{t("table.steps")}</th>
          <th className="border-b px-3 py-2 font-medium">{t("history.layers")}</th>
          <th className="border-b px-3 py-2 font-medium">{t(byOpened ? "table.opened" : "table.saved")}</th>
        </tr></thead>
        <tbody>
          {entries.map((entry) => {
            const isCurrent = entry.key === analysis?.storage?.key;
            const timestamp = byOpened ? entry.opened_at : entry.at;
            return (
              <tr key={entry.key} className={`cursor-pointer border-b last:border-0 hover:bg-muted/40 ${isCurrent ? "bg-muted/30" : ""}`} onClick={() => loadEntry(entry)}>
                <td className="px-3 py-2.5">
                  <div className="flex items-center gap-2">
                    <div className="min-w-0"><div className="truncate font-medium">{entry.title}</div><div className="text-[10.5px] text-muted-foreground">{entry.author || entry.key}{isCurrent ? ` · ${t("history.current")}` : ""}</div></div>
                    <div className="ml-auto flex items-center gap-1.5">
                      <button className={`${entry.favorite ? "text-amber-500" : "text-muted-foreground"}`} title={t("history.favorite")} onClick={(e) => { e.stopPropagation(); toggleFavorite(entry); }}><Star className="h-3.5 w-3.5" fill={entry.favorite ? "currentColor" : "none"} /></button>
                      <button className="text-rose-500 hover:text-rose-600" title={isCurrent ? t("history.deleteCurrentConfirm", { title: entry.title }) : t("history.deletePuzzle")} onClick={(e) => { e.stopPropagation(); removeEntry(entry); }}><Trash2 className="h-3.5 w-3.5" /></button>
                    </div>
                  </div>
                </td>
                <td className="px-3 py-2.5"><Badge variant={["solved", "solved-global", "solved-search"].includes(entry.status) ? "success" : "outline"}>{statusLabel(entry.status)}</Badge></td>
                <td className="px-3 py-2.5 font-mono text-[11px] text-muted-foreground">{entry.steps_count || 0}</td>
                <td className="px-3 py-2.5">
                  <div className="flex flex-wrap gap-1">
                    {["rules", "steps", "frames"].map((layer) => entry.layers?.[layer] && (
                      <span key={layer} className="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] text-muted-foreground">
                        {t(`layers.${layer}`)} {fmtBytes(entry.sizes?.[layer])}
                        <button className="text-rose-500 hover:text-rose-600" title={isCurrent ? t("history.confirmDeleteCurrentLayer", { title: entry.title, layer: t(`layers.${layer}`) }) : t("history.delete", { layer: t(`layers.${layer}`) })} onClick={(e) => { e.stopPropagation(); removeLayer(entry, layer); }}><X className="h-3 w-3" /></button>
                      </span>
                    ))}
                  </div>
                </td>
                <td className="px-3 py-2.5 text-[10.5px] text-muted-foreground">{timestamp ? new Date(timestamp * 1000).toLocaleDateString(lang === "zh" ? "zh-CN" : "en-US") : ""}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {!entries.length && <div className="px-3 py-8 text-center text-xs text-muted-foreground">{t("history.empty")}</div>}
    </div>
  );

  return (
    <div className="min-h-screen bg-background">
      <header className={`sticky top-0 z-30 border-b bg-background/95 backdrop-blur transition-transform duration-200 lg:translate-y-0 ${headerHidden ? "-translate-y-full" : "translate-y-0"}`}>
        <div className="mx-auto flex min-h-14 max-w-[1440px] flex-wrap items-center gap-2 px-4 py-2 lg:flex-nowrap lg:gap-3 lg:px-6 lg:py-0">
          <div className="flex items-center gap-2.5">
            <img src={dark ? logoDark : logoLight} alt="YSudoku" className="h-8 w-8 rounded-lg" />
            <div><div className="text-sm font-semibold leading-tight tracking-tight">YSudoku</div><div className="hidden text-[10.5px] text-muted-foreground sm:block">{t("brand.sub")}</div></div>
          </div>
          <nav className="flex h-14 items-stretch gap-3 sm:gap-4">
            {navItems.map(([value, key]) => (
              <button key={value} onClick={() => { setView(value); setPlaying(false); }}
                className={`whitespace-nowrap border-b-2 px-0.5 text-[13px] transition-colors sm:text-sm ${view === value ? "border-primary font-semibold text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"}`}>
                {t(key)}
              </button>
            ))}
          </nav>
          <form className="order-last flex w-full min-w-0 items-center gap-1.5 lg:order-none lg:w-auto lg:flex-1" onSubmit={(e) => {
            e.preventDefault();
            if (looksLikePuzzle(url)) { setSearchOpen(false); submit({ url }); }
            else { setQuery(url); setView("history"); setSearchOpen(false); }
          }}>
            <div className="relative min-w-0 flex-1">
              <Search className="absolute left-2.5 top-2 h-3.5 w-3.5 text-muted-foreground" />
              <Input value={url} onChange={(e) => { setUrl(e.target.value); setSearchOpen(true); }}
                onFocus={() => setSearchOpen(true)} onBlur={() => setTimeout(() => setSearchOpen(false), 140)}
                placeholder={t("header.url")} className="h-8 pl-8 text-xs" />
              {searchOpen && url.trim() && !looksLikePuzzle(url) && (
                <div className="absolute left-0 top-full z-50 mt-1 w-full overflow-hidden rounded-lg border bg-background shadow-md" onMouseDown={(e) => e.preventDefault()}>
                  {searchResults.length ? searchResults.map((entry) => (
                    <button key={entry.key} type="button" onClick={() => { setSearchOpen(false); loadEntry(entry); }}
                      className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-xs hover:bg-accent">
                      <span className="min-w-0"><span className="block truncate font-medium">{entry.title}</span><span className="text-[10.5px] text-muted-foreground">{entry.author || entry.key}</span></span>
                      <Badge variant={["solved", "solved-global", "solved-search"].includes(entry.status) ? "success" : "outline"}>{statusLabel(entry.status)}</Badge>
                    </button>
                  )) : <div className="px-3 py-3 text-xs text-muted-foreground">{t("search.noResults")}</div>}
                </div>
              )}
            </div>
            <Button type="submit" size="sm" className="whitespace-nowrap" disabled={busy}>{busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : t("header.solve")}</Button>
            <Button type="button" size="sm" variant="outline" className="whitespace-nowrap" onClick={demo} disabled={busy}>{t("header.demo")}</Button>
          </form>
          <div className="ml-auto flex items-center gap-1">
            <Button variant="ghost" size="sm" asChild className="gap-1.5 whitespace-nowrap text-xs text-muted-foreground">
              <a href="https://github.com/CodeInDreams/ysudoku" target="_blank" rel="noreferrer" title="GitHub"><GithubMark className="h-4 w-4 text-foreground" /><span className="hidden sm:inline">{stars ? stars : "Star"}</span></a>
            </Button>
            <Button variant="ghost" size="icon" onClick={() => setDark((value) => !value)} title={dark ? t("header.light") : t("header.dark")}>
              {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </Button>
            <Popover>
              <PopoverTrigger asChild><Button variant="ghost" size="icon" title={t("settings.title")}><Settings className="h-4 w-4" /></Button></PopoverTrigger>
              <PopoverContent align="end" className="w-[min(360px,calc(100vw-24px))] p-0">
                <div className="border-b px-4 py-3">
                  <div className="text-sm font-semibold">{t("settings.title")}</div>
                </div>
                <div className="divide-y">
                  <div className="flex items-center gap-3 px-4 py-3">
                    <Languages className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-medium">{t("settings.language")}</div>
                      <div className="text-xs text-muted-foreground">{t("settings.languageDesc")}</div>
                    </div>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="outline" size="sm" className="h-8 gap-1.5 text-xs">{lang === "zh" ? "中文" : "English"}<ChevronDown className="h-3 w-3 opacity-60" /></Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" className="w-32">
                        <DropdownMenuItem onClick={() => setLang("zh")} className={lang === "zh" ? "bg-accent font-medium" : ""}><span className="flex-1">中文</span>{lang === "zh" && <Check className="h-4 w-4" />}</DropdownMenuItem>
                        <DropdownMenuItem onClick={() => setLang("en")} className={lang === "en" ? "bg-accent font-medium" : ""}><span className="flex-1">English</span>{lang === "en" && <Check className="h-4 w-4" />}</DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                  <div className="flex items-center gap-3 px-4 py-3">
                    <Sparkles className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-medium">{t("header.llm")}</div>
                      <div className="text-xs text-muted-foreground">{t("settings.llmDesc")}</div>
                    </div>
                    <Switch checked={llm} onCheckedChange={setLlm} title={t("help.llm")} />
                  </div>
                  <div className="flex items-center gap-3 px-4 py-3">
                    <ShieldCheck className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-medium">{t("header.audit")}</div>
                      <div className="text-xs text-muted-foreground">{t("settings.auditDesc")}</div>
                    </div>
                    <Switch checked={audit} onCheckedChange={setAudit} title={t("help.audit")} />
                  </div>
                </div>
              </PopoverContent>
            </Popover>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1280px] px-4 py-6 lg:px-6 lg:py-8">
        {view === "solve" && (
          <>
            <PageHead
              title={analysis?.puzzle?.title || openingTitle || t(phase === "idle" ? "page.waiting" : "table.puzzle")}
              description={analysis ? (
                <span>
                  {analysis.puzzle.author || ""} · {t("page.givens", { n: analysis.puzzle.givens.filter(Boolean).length })}
                  {(analysis.source_url || target) && (
                    <> · <a
                      href={analysis.source_url || target}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="underline-offset-4 hover:text-foreground hover:underline"
                    >{t("page.original")} ↗</a></>
                  )}
                  {isSolved ? ` · ${statusLabel(analysis.status)}` : ""}
                </span>
              ) : (phase === "idle" ? t("empty.solve") : null)}
              badges={analysis ? <><Badge variant="outline">{n}×{n}</Badge><Badge variant={isSolved ? "success" : "outline"}>{statusLabel(analysis.status)}</Badge></> : null}
            />
            {analysis?.conflicts?.length > 0 && !conflictChoice && (
              <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
                <div className="w-full max-w-lg rounded-xl border bg-card p-5 shadow-xl">
                  <h2 className="text-base font-semibold">规则识别冲突</h2>
                  <p className="mt-1.5 text-sm text-muted-foreground">
                    {analysis.conflicts[0].question}
                  </p>
                  <div className="mt-4 grid gap-2">
                    {analysis.conflicts[0].options.map((option, index) => (
                      <button key={option.id} type="button"
                        onClick={() => {
                          setConflictChoice(option.id);
                          streamSolve({ url: target, llm: option.id === "llm", audit, chains: true, demo: false, rule_prompt: rulePrompt, rule_mode: option.id, lang }, target);
                        }}
                        className={`rounded-lg border px-3 py-2.5 text-left text-sm transition-colors hover:border-primary ${index === 0 ? "border-primary bg-primary/5" : "bg-background"}`}>
                        <span className="font-medium">{option.label}</span>
                        {index === 0 && <span className="ml-2 text-xs text-muted-foreground">推荐</span>}
                      </button>
                    ))}
                  </div>
                  <textarea value={rulePrompt} onChange={(e) => setRulePrompt(e.target.value)}
                    placeholder="补充规则说明（可选）"
                    className="mt-3 w-full resize-y rounded-lg border bg-background px-3 py-2 text-sm outline-none focus:border-primary" rows={3} />
                  <div className="mt-4 flex justify-end">
                    <button type="button" onClick={() => setConflictChoice("dismiss")}
                      className="rounded-lg border px-3 py-2 text-sm text-muted-foreground hover:text-foreground">
                      暂不选择
                    </button>
                  </div>
                </div>
              </div>
            )}
            {["rules", "solving", "rendering"].includes(phase) && (
              <div className="mb-5 rounded-lg border bg-card px-3 py-2.5">
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                  <span className="font-medium">{phaseLabel}</span>
                  <span className="text-muted-foreground">{phasePct}%</span>
                </div>
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
                  <div className={`h-full rounded-full bg-primary transition-all ${phase === "rules" || phase === "solving" ? "animate-pulse" : ""}`} style={{ width: `${Math.max(4, phasePct)}%` }} />
                </div>
                {phaseHint && <div className="mt-1 text-[11px] text-muted-foreground">{phaseHint}</div>}
              </div>
            )}
            {!analysis && !previewSrc ? (phase === "idle" ? emptySolve : (
              <Card>
                <CardContent className="flex min-h-[320px] items-center justify-center text-sm text-muted-foreground">
                  <div role="status">{phase === "failed" ? t("phase.failed") : t("board.loading")}</div>
                </CardContent>
              </Card>
            )) : (
              <>
                <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1.55fr)_minmax(320px,.85fr)]">
                  <div className="min-w-0 space-y-6">{boardCard}</div>
                  <div className="min-w-0 space-y-6">{inspector}{stepsCard}</div>
                </div>

              </>
            )}
            {!!store?.entries?.length && (
                <div className="mt-6">
                  <Card>
                    <CardHeader className="flex-row items-center justify-between space-y-0 py-3.5"><div><CardTitle className="text-sm">{t("history.recentOpens")}</CardTitle><p className="mt-0.5 text-xs text-muted-foreground">{t("history.recentDesc")}</p></div><Button variant="outline" size="sm" onClick={() => setView("history")}>{t("history.openAll")}</Button></CardHeader>
                    <CardContent className="p-0">{entryTable([...(store?.entries || [])].sort((a, b) => b.opened_at - a.opened_at).slice(0, 4), true)}</CardContent>
                  </Card>
                </div>
            )}
          </>
        )}

        {view === "rules" && (
          <>
            <PageHead title={t("rules.title")} description={analysis ? t("rules.desc", { model: "deepseek-flash" }) : (phaseHint || t("empty.solve"))}
              badges={phase !== "idle" && phase !== "done" ? <Badge variant="outline">{phaseLabel}</Badge> : null} />
            {!analysis ? (phase === "idle" ? emptySolve : (
              <Card>
                <CardHeader className="flex-row items-center justify-between space-y-0 py-3.5">
                  <div><CardTitle className="text-sm">{t("rules.title")}</CardTitle><p className="mt-0.5 text-xs text-muted-foreground">{phaseHint}</p></div>
                  <Loader2 className="h-4 w-4 animate-spin text-primary" />
                </CardHeader>
                <CardContent className="space-y-2 pt-0">
                  {resolvedRules.map((rule, i) => (
                    <div key={i} className="flex items-center justify-between border-b py-2 text-sm last:border-0"><span>{rule.label}</span><span className="text-xs text-muted-foreground">× {rule.count}</span></div>
                  ))}
                  {!resolvedRules.length && Array.from({ length: 4 }).map((_, i) => (
                    <div key={i} className="flex animate-pulse items-center justify-between border-b py-2"><span className="h-3 w-1/3 rounded bg-muted" /><span className="h-3 w-8 rounded bg-muted" /></div>
                  ))}
                </CardContent>
              </Card>
            )) : (
              <div className="space-y-6">
                <Card className="overflow-hidden">
                  <CardHeader className="flex-row items-start gap-3 space-y-0 border-b py-3.5">
                    <div className="grid h-8 w-8 shrink-0 place-items-center rounded-md bg-muted"><FilePenLine className="h-4 w-4 text-muted-foreground" /></div>
                    <div className="min-w-0">
                      <CardTitle className="text-sm">{t("rules.notes")}</CardTitle>
                      <p className="mt-0.5 text-xs text-muted-foreground">{t("rules.notesHint")}</p>
                    </div>
                  </CardHeader>
                  <CardContent className="pt-4">
                    <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={4} placeholder={t("rules.notesPlaceholder")} className="min-h-[104px] resize-y bg-muted/30 text-sm leading-6" />
                    <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                      <span className="text-[11px] text-muted-foreground">{t("rules.saveHint")}</span>
                      <Button size="sm" onClick={refreshRules} disabled={busy}><Save className="mr-1 h-3.5 w-3.5" />{t("rules.save")}</Button>
                    </div>
                  </CardContent>
                </Card>
                <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1.3fr)_minmax(300px,.7fr)]">
                  <Card>
                    <CardHeader><CardTitle className="text-sm">{t("rules.title")}</CardTitle><p className="text-xs text-muted-foreground">{t("rules.forced")}</p></CardHeader>
                    <CardContent className="space-y-1 pt-0">
                      {resolvedRules.map((rule, i) => (
                        <div key={i} className="flex items-center justify-between border-b py-2 text-sm last:border-0"><span>{rule.label}</span><span className="text-xs text-muted-foreground">× {rule.count}</span></div>
                      ))}
                      {analysis.rules?.warnings?.length ? <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200"><AlertTriangle className="mr-1 inline h-3.5 w-3.5" />{analysis.rules.warnings[0]}</div> : null}
                    </CardContent>
                  </Card>
                  <Card>
                    <CardHeader><CardTitle className="text-sm">{t("rules.sheet")}</CardTitle><p className="text-xs text-muted-foreground">{t("rules.source")}: {analysis.spec_source || analysis.provenance || "—"}</p></CardHeader>
                    <CardContent>{analysis.rule_sheet ? <img src={analysis.rule_sheet} alt="rule sheet" className="w-full rounded-md border bg-white" /> : <p className="text-xs text-muted-foreground">—</p>}</CardContent>
                  </Card>
                </div>
                <Card>
                  <CardHeader className="py-3.5"><CardTitle className="text-sm">{t("rules.original")}</CardTitle><p className="text-xs text-muted-foreground">{t("rules.originalHint")}</p></CardHeader>
                  <CardContent className="pt-0"><div className="rules-markdown rounded-lg bg-muted/40 px-4 py-3"><ReactMarkdown remarkPlugins={[remarkGfm]}>{analysis.puzzle.rules || "—"}</ReactMarkdown></div></CardContent>
                </Card>
              </div>
            )}
          </>
        )}

        {view === "history" && (
          <>
            <PageHead title={t("history.title")} description={t("history.desc")} />
            <div className="grid gap-4 sm:grid-cols-3">
              {[["rules", "layers.rules"], ["steps", "layers.steps"], ["frames", "layers.frames"]].map(([layer, key]) => (
                <Card key={layer}><CardContent className="p-4"><div className="text-xs text-muted-foreground">{t(key)}</div><div className="mt-1 text-lg font-semibold">{store?.info?.counts?.[layer] || 0} <span className="text-xs font-normal text-muted-foreground">{puzzleUnit(store?.info?.counts?.[layer] || 0)}</span></div><div className="text-xs text-muted-foreground">{fmtBytes(store?.info?.sizes?.[layer])}</div></CardContent></Card>
              ))}
            </div>
            <Card className="mt-4">
              <CardContent className="flex flex-wrap items-center gap-2 p-3">
                <Database className="h-4 w-4 text-muted-foreground" />
                <span className="text-xs text-muted-foreground">{t("history.location")}:</span>
                <code className="break-all text-[11px]">{store?.info?.location || "—"}</code>
                <span className="ml-auto text-xs text-muted-foreground">{fmtBytes(store?.info?.total)}</span>
              </CardContent>
            </Card>
            <Card className="mt-4">
              <CardHeader className="py-3.5"><div className="flex flex-wrap items-center gap-2">
                <div className="relative min-w-[180px] flex-1"><Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" /><Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("history.search")} className="h-8 pl-8 text-xs" /></div>
                <DropdownMenu><DropdownMenuTrigger asChild><Button variant="outline" size="sm" className="h-8 gap-1.5 text-xs"><ArrowUpDown className="h-3.5 w-3.5" />{sort === "recent" ? t("history.recent") : t("history.byTitle")}<ChevronDown className="h-3 w-3 opacity-60" /></Button></DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="w-36">
                    <DropdownMenuItem onClick={() => setSort("recent")} className={sort === "recent" ? "bg-accent font-medium" : ""}><span className="flex-1">{t("history.recent")}</span>{sort === "recent" && <Check className="h-4 w-4" />}</DropdownMenuItem>
                    <DropdownMenuItem onClick={() => setSort("title")} className={sort === "title" ? "bg-accent font-medium" : ""}><span className="flex-1">{t("history.byTitle")}</span>{sort === "title" && <Check className="h-4 w-4" />}</DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
                <label className="flex items-center gap-1.5 text-xs text-muted-foreground"><input type="checkbox" checked={favOnly} onChange={(e) => setFavOnly(e.target.checked)} />{t("history.favOnly")}</label>
              </div></CardHeader>
              <CardContent className="p-0">{entryTable(filteredEntries)}</CardContent>
            </Card>
            <Card className="mt-4">
              <CardHeader className="py-3.5"><CardTitle className="text-sm">{t("history.settings")}</CardTitle><p className="text-xs text-muted-foreground">{t("history.settingsDesc")}</p></CardHeader>
              <CardContent className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
                {[["max_rules", "history.maxRules"], ["max_steps", "history.maxSteps"], ["max_frames", "history.maxFrames"], ["max_mb", "history.maxMb"]].map(([key, label]) => (
                  <label key={key} className="flex items-center justify-between gap-2 rounded-md border px-2.5 py-2"><span className="text-muted-foreground">{t(label)}</span><input type="number" min="0" value={settings[key] ?? ""} onChange={(e) => setSettings((s) => ({ ...s, [key]: Number(e.target.value) }))} className="w-14 bg-transparent text-right outline-none" /></label>
                ))}
                <Button size="sm" className="col-span-2 sm:col-span-4" onClick={saveSettings}>{t("history.save")}</Button>
              </CardContent>
            </Card>
          </>
        )}

        {error && <div className="mt-4 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-200">{error}</div>}
        <p className="mt-8 text-center text-[11px] text-muted-foreground">{t("footer.local")}</p>
        {currentEntry && deleted && <div className="sr-only">{t("step.deleted")}</div>}
      </main>
    </div>
  );
}

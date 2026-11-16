import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle, ArrowUpDown, Check, ChevronDown, ChevronLeft, ChevronRight,
  Database, FolderOpen, HelpCircle, Languages, Loader2, Moon, Play, RotateCw,
  Search, Star, Sun, X,
} from "lucide-react";
import { Button } from "./components/ui/button";
import { Input } from "./components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "./components/ui/card";
import { Badge } from "./components/ui/badge";
import { Switch } from "./components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./components/ui/tabs";
import { Popover, PopoverContent, PopoverTrigger } from "./components/ui/popover";
import {
  DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent,
  DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from "./components/ui/dropdown-menu";
import { detectLang, translate } from "./i18n";

const TECH_EN = {
  cage: "Killer cage", hidden_single: "Hidden single", naked_single: "Naked single",
  class_cover: "Class cover", whisper: "Whisper", renban: "Renban", arrow: "Arrow",
  thermo: "Thermometer", sandwich: "Sandwich", xsum: "X-Sums", skyscraper: "Skyscraper",
  consecutive: "Consecutive", parity: "Parity", region: "Region",
};
const RULE_EN = {
  killer: "Killer cages", cage: "Killer cages", whisper: "Whispers", renban: "Renbans",
  arrow: "Arrows", thermo: "Thermometers", sandwich: "Sandwiches", xsum: "X-Sums",
  region: "Regions", skyscraper: "Skyscrapers", consecutive: "Consecutive",
};

function digitsOf(mask, n) {
  const out = [];
  for (let v = 1; v <= n; v++) if (mask & (1 << (v - 1))) out.push(v);
  return out;
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

function buildStepActions(analysis) {
  const n = analysis.puzzle.size;
  const steps = [];
  const state = new Map();
  const marked = new Set();
  const MAX_POSITIVE = 6;
  for (const step of analysis.steps) {
    const actions = [];
    const pre = step.pre_dom || [];
    for (const [cell, set] of Array.from(state.entries())) {
      const desired = new Set(digitsOf(pre[cell] || 0, n));
      const removed = [...set].filter((d) => !desired.has(d));
      const added = [...desired].filter((d) => !set.has(d));
      if (marked.has(cell)) {
        for (const d of removed) actions.push({ op: "elim", cell, value: d });
        if (added.length) actions.push({ op: "mark", cell, digits: added });
      }
      state.set(cell, desired);
    }
    for (const ev of step.events || []) {
      if (ev.kind === "place") {
        if (state.has(ev.cell)) {
          const set = state.get(ev.cell);
          if (!set.has(ev.value)) throw new Error(`candidate invariant broken at step ${step.index + 1}`);
          if (marked.has(ev.cell)) actions.push({ op: "clear", cell: ev.cell, digits: [...set] });
          state.delete(ev.cell);
          marked.delete(ev.cell);
        }
        actions.push({ op: "place", cell: ev.cell, value: ev.value });
      } else if (ev.kind === "elim") {
        if (!state.has(ev.cell)) {
          const digits = digitsOf(step.pre_dom?.[ev.cell] || 0, n).filter((d) => d !== ev.value);
          state.set(ev.cell, new Set(digits));
          if (digits.length === 1) {
            actions.push({ op: "place", cell: ev.cell, value: digits[0] });
            state.delete(ev.cell);
          } else if (digits.length <= MAX_POSITIVE) {
            actions.push({ op: "mark", cell: ev.cell, digits });
            marked.add(ev.cell);
          }
        } else {
          const set = state.get(ev.cell);
          set.delete(ev.value);
          if (set.size === 1) {
            const [value] = set;
            if (marked.has(ev.cell)) actions.push({ op: "clear", cell: ev.cell, digits: [...set] });
            actions.push({ op: "place", cell: ev.cell, value });
            state.delete(ev.cell);
            marked.delete(ev.cell);
          } else if (marked.has(ev.cell)) actions.push({ op: "elim", cell: ev.cell, value: ev.value });
          else if (set.size <= MAX_POSITIVE) {
            actions.push({ op: "mark", cell: ev.cell, digits: [...set] });
            marked.add(ev.cell);
          }
        }
      }
    }
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
  const [speed, setSpeed] = useState(1100);
  const [session, setSession] = useState(null);
  const [ready, setReady] = useState(false);
  const [retry, setRetry] = useState(0);
  const [view, setView] = useState("solve");
  const [inspectorTab, setInspectorTab] = useState("explain");
  const [store, setStore] = useState(null);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("recent");
  const [favOnly, setFavOnly] = useState(false);
  const [error, setError] = useState("");
  const [deleted, setDeleted] = useState(false);
  const [frameErrors, setFrameErrors] = useState(0);
  const [lang, setLang] = useState(detectLang);
  const [dark, setDark] = useState(() => {
    try { return localStorage.getItem("ysudoku.theme") === "dark"; } catch { return false; }
  });
  const [settings, setSettings] = useState({ max_rules: 100, max_steps: 100, max_frames: 10, max_mb: 500 });

  const t = (key, vars) => translate(lang, key, vars);
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
    if (!playing || deleted) return;
    if (idx >= steps.length - 1) { setPlaying(false); return; }
    const timer = setTimeout(() => setIdx((value) => Math.min(value + 1, steps.length - 1)), speed);
    return () => clearTimeout(timer);
  }, [playing, idx, steps.length, speed, deleted]);

  useEffect(() => {
    const onKey = (event) => {
      if (view !== "solve" || event.target.tagName === "INPUT" || event.target.tagName === "SELECT") return;
      if (event.key === "ArrowRight") { setPlaying(false); setIdx((v) => Math.min(v + 1, steps.length - 1)); }
      if (event.key === "ArrowLeft") { setPlaying(false); setIdx((v) => Math.max(v - 1, -1)); }
      if (event.key === " ") { event.preventDefault(); setPlaying((v) => !v); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [steps.length, view]);

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

  async function verifyCurrentCache(key) {
    if (!key) return;
    try {
      const res = await fetch("/api/store");
      if (!res.ok) return;
      const data = await res.json();
      const entry = (data.entries || []).find((item) => item.key === key);
      if (!entry || !entry.layers?.frames) {
        setDeleted(true);
        setPlaying(false);
        setReady(false);
      }
    } catch { /* ignore */ }
  }

  function applyAnalysis(data) {
    setAnalysis(data);
    setIdx(-1);
    setPlaying(false);
    setDeleted(false);
    setFrameErrors(0);
    setError("");
    setView("solve");
    startLive(data);
    refreshStore();
  }

  async function startLive(nextAnalysis) {
    setReady(false);
    setSession(null);
    setDeleted(false);
    setFrameErrors(0);
    try {
      const actions = buildStepActions(nextAnalysis);
      let hash = 2166136261;
      const text = "frame-v6:" + JSON.stringify(actions);
      for (let i = 0; i < text.length; i++) { hash ^= text.charCodeAt(i); hash = Math.imul(hash, 16777619); }
      const data = await postJson("/api/live/build", {
        url: nextAnalysis.source_url || "",
        steps: actions,
        key: nextAnalysis.storage?.key || "",
        steps_hash: (hash >>> 0).toString(16),
      });
      setSession(data.session);
      setRetry((v) => v + 1);
    } catch (err) {
      setError(`${t("error.build")}: ${err.message}`);
    }
  }

  async function submit(payload) {
    setBusy(true); setError(""); setPlaying(false);
    try {
      const data = await postJson("/api/solve", { url: payload.url, llm, audit, chains: true });
      setTarget(payload.url); setUrl(payload.url); applyAnalysis(data);
    } catch (err) { setError(`${t("error.solve")}: ${err.message}`); }
    finally { setBusy(false); }
  }

  async function demo() {
    setBusy(true); setError(""); setPlaying(false);
    try {
      const data = await postJson("/api/demo", {});
      setTarget(""); setUrl(""); applyAnalysis(data);
    } catch (err) { setError(`${t("error.solve")}: ${err.message}`); }
    finally { setBusy(false); }
  }

  async function refreshRules() {
    if (!analysis) return;
    setBusy(true); setPlaying(false);
    try {
      const data = await postJson("/api/store/refresh_rules", { target: target || "", demo: !!analysis.demo });
      applyAnalysis(data);
      setInspectorTab("explain");
    } catch (err) { setError(`${t("error.refresh")}: ${err.message}`); }
    finally { setBusy(false); }
  }

  async function toggleFavorite(entry) {
    await postJson("/api/store/favorite", { key: entry.key, favorite: !entry.favorite });
    refreshStore();
  }

  async function removeLayer(entry, layer) {
    if (entry.key === analysis?.storage?.key) return;
    const label = t(`layers.${layer}`);
    if (!window.confirm(t("history.confirmDelete", { title: entry.title, layer: label }))) return;
    await postJson("/api/store/delete", { key: entry.key, layer });
    refreshStore();
  }

  async function saveSettings() {
    await postJson("/api/store/settings", settings);
    refreshStore();
  }

  async function loadEntry(entry) {
    setBusy(true); setError(""); setPlaying(false);
    try {
      const data = entry.demo ? await postJson("/api/demo", {}) : await postJson("/api/solve", { url: entry.target, llm, audit, chains: true });
      setTarget(entry.demo ? "" : entry.target);
      setUrl(entry.demo ? "" : entry.target);
      applyAnalysis(data);
    } catch (err) { setError(`${t("error.solve")}: ${err.message}`); }
    finally { setBusy(false); }
  }

  async function cacheAlive() {
    if (!analysis?.storage?.key || !ready) return true;
    try {
      const res = await fetch("/api/store");
      const data = await res.json().catch(() => ({}));
      const entry = (data.entries || []).find((item) => item.key === analysis.storage.key);
      if (!entry || !entry.layers?.steps || !entry.layers?.frames) {
        setDeleted(true);
        setPlaying(false);
        setReady(false);
        setError(t("step.deleted"));
        return false;
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

  function prevStep() {
    if (deleted) { setError(t("step.deleted")); setPlaying(false); return; }
    setPlaying(false);
    setIdx((v) => Math.max(-1, v - 1));
  }

  function onFrameError() {
    if (deleted) return;
    setReady(false);
    const next = frameErrors + 1;
    setFrameErrors(next);
    if (next >= 24) verifyCurrentCache(analysis?.storage?.key);
    setTimeout(() => setRetry((v) => v + 1), 450);
  }

  const filteredEntries = useMemo(() => {
    const list = (store?.entries || []).filter((entry) => {
      if (favOnly && !entry.favorite) return false;
      if (!query) return true;
      return `${entry.title} ${entry.author}`.toLowerCase().includes(query.toLowerCase());
    });
    return list.sort((a, b) => sort === "title" ? String(a.title).localeCompare(String(b.title)) : (b.at || 0) - (a.at || 0));
  }, [store, query, sort, favOnly]);

  const overlay = useMemo(() => {
    if (!analysis || idx < 0 || deleted) return null;
    const state = candidateStateUpTo(analysis, idx);
    const negatives = [];
    for (const [cell, set] of state) {
      if (set.size <= 6) continue;
      const excluded = [];
      for (let v = 1; v <= n; v++) if (!set.has(v)) excluded.push(v);
      if (excluded.length && excluded.length <= 3) negatives.push({ cell, digits: excluded });
    }
    return { visual: steps[idx]?.visual || {}, negatives };
  }, [analysis, idx, n, steps, deleted]);

  const currentEntry = (store?.entries || []).find((entry) => entry.key === analysis?.storage?.key);
  const isSolved = ["solved", "solved-global", "solved-search"].includes(analysis?.status);

  const navItems = [["solve", "nav.solve"], ["rules", "nav.rules"], ["history", "nav.history"]];

  const emptySolve = (
    <EmptyState title={t("empty.solveTitle")} hint={t("empty.solveHint")}
      action={<Button onClick={demo} disabled={busy}>{t("header.demo")}</Button>} />
  );

  const boardCard = analysis && (
    <Card className="overflow-hidden">
      <CardHeader className="flex-row items-center gap-3 space-y-0 border-b py-3.5">
        <div><CardTitle className="text-sm">{t("board.title")}</CardTitle><p className="mt-0.5 text-xs text-muted-foreground">{t("board.desc", { i: idx + 1, n: steps.length })}</p></div>
        <div className="ml-auto flex items-center gap-1.5"><Badge variant="outline">{t("board.readonly")}</Badge><Badge variant="outline">{t("board.readonly.badge")}</Badge></div>
      </CardHeader>
      <CardContent className="p-4">
        <div className="relative mx-auto flex aspect-square w-full max-w-[540px] items-center justify-center overflow-hidden rounded-md border bg-white">
          {!ready && !deleted && <div className="absolute inset-0 z-10 grid place-items-center gap-2 bg-white/80 text-xs text-slate-500"><Loader2 className="h-5 w-5 animate-spin text-primary" />{t("board.loading")}</div>}
          {deleted && (
            <div className="absolute inset-0 z-20 grid place-items-center bg-background/90 p-6 text-center">
              <div className="max-w-xs space-y-2">
                <AlertTriangle className="mx-auto h-6 w-6 text-amber-500" />
                <div className="text-sm font-medium">{t("step.deletedShort")}</div>
                <p className="text-xs text-muted-foreground">{t("step.deleted")}</p>
              </div>
            </div>
          )}
          {session && !deleted && (
            <img key={`${session}-${idx}-${retry}`} src={`/api/live/frame?session=${session}&step=${idx}&t=${retry}`}
              alt="SudokuPad" className={`h-full w-full object-contain transition-opacity ${ready ? "opacity-100" : "opacity-0"}`}
              onLoad={() => { setReady(true); setFrameErrors(0); }} onError={onFrameError} />
          )}
          {overlay && ready && !deleted && (
            <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox={`0 0 ${n} ${n}`} preserveAspectRatio="none">
              {(overlay.visual.groups || []).map((group, i) => {
                if (!group.cells?.length) return null;
                const rows = group.cells.map((c) => Math.floor(c / n));
                const cols = group.cells.map((c) => c % n);
                const color = ["#2563eb", "#d97706", "#059669", "#dc2626", "#7c3aed", "#0d9488"][i % 6];
                return <rect key={i} x={Math.min(...cols) + 0.03} y={Math.min(...rows) + 0.03} width={Math.max(...cols) - Math.min(...cols) + 0.94} height={Math.max(...rows) - Math.min(...rows) + 0.94} rx="0.08" fill={color} fillOpacity="0.10" stroke={color} strokeOpacity="0.55" strokeWidth="0.045" />;
              })}
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
          <span className="pointer-events-none absolute right-1.5 top-1.5 rounded bg-white/70 px-1.5 py-0.5 text-[10px] text-slate-500">SudokuPad · {t("board.readonly.badge")}</span>
        </div>
      </CardContent>
      <div className="flex items-center gap-2 border-t px-4 py-3">
        <Button variant="outline" size="icon" className="h-8 w-8" onClick={prevStep} disabled={idx <= -1 || deleted}><ChevronLeft className="h-4 w-4" /></Button>
        <Button size="sm" onClick={() => setPlaying((v) => !v)} disabled={!steps.length || deleted}><Play className="mr-1 h-3.5 w-3.5" />{playing ? t("player.pause") : t("player.play")}</Button>
        <Button variant="outline" size="icon" className="h-8 w-8" onClick={nextStep} disabled={idx >= steps.length - 1 || deleted}><ChevronRight className="h-4 w-4" /></Button>
        <span className="ml-2 hidden text-xs text-muted-foreground sm:inline">{t("player.speed")}</span>
        <input type="range" min="200" max="2400" step="100" value={speed} onChange={(e) => setSpeed(Number(e.target.value))} className="w-28 accent-primary" />
        <span className="ml-auto font-mono text-[11px] text-muted-foreground">{t("player.step", { i: idx + 1, n: steps.length })}</span>
      </div>
      <div className="border-t px-4 py-2">
        <input type="range" min="-1" max={Math.max(0, steps.length - 1)} value={idx} onChange={(e) => { setPlaying(false); setIdx(Number(e.target.value)); }} className="w-full accent-primary" disabled={!steps.length || deleted} />
      </div>
    </Card>
  );

  const inspector = analysis && (
    <Card>
      <Tabs value={inspectorTab} onValueChange={setInspectorTab}>
        <div className="border-b px-4">
          <TabsList className="h-auto w-full justify-start gap-5 rounded-none bg-transparent p-0">
            <TabsTrigger value="explain" className="rounded-none border-b-2 border-transparent px-0 pb-2.5 pt-3 text-xs text-muted-foreground shadow-none data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:font-semibold data-[state=active]:text-foreground data-[state=active]:shadow-none">{t("inspector.explain")}</TabsTrigger>
            <TabsTrigger value="candidates" className="rounded-none border-b-2 border-transparent px-0 pb-2.5 pt-3 text-xs text-muted-foreground shadow-none data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:font-semibold data-[state=active]:text-foreground data-[state=active]:shadow-none">{t("inspector.candidates")}</TabsTrigger>
            <TabsTrigger value="rules" className="rounded-none border-b-2 border-transparent px-0 pb-2.5 pt-3 text-xs text-muted-foreground shadow-none data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:font-semibold data-[state=active]:text-foreground data-[state=active]:shadow-none">{t("inspector.rules")}</TabsTrigger>
          </TabsList>
        </div>
        <CardContent className="p-4">
          {deleted && <div className="mb-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">{t("step.deleted")}</div>}
          <TabsContent value="explain" className="mt-0">
            {current ? (
              <div className="space-y-3">
                <div className="flex items-center gap-2"><h2 className="text-sm font-semibold">{stepTitle(current)}</h2><Badge variant="outline">{t("step.tier", { tier: current.tier })}</Badge><span className="ml-auto text-[11px] text-muted-foreground">{t("step.label", { i: idx + 1 })}</span></div>
                <p className="whitespace-pre-wrap text-[13px] leading-7 text-foreground/90">{lang === "en" ? englishSummary(current) : current.detail}</p>
                {current.candidates?.length ? (
                  <div className="rounded-md bg-muted px-3 py-2 font-mono text-[11px] leading-6">
                    {current.candidates.map((c) => `R${Math.floor(c.cell / n) + 1}C${(c.cell % n) + 1} {${c.digits.join(",")}}`).join("  ")}
                  </div>
                ) : null}
                {current.audit === "ok" && <div className="rounded-md bg-emerald-50 px-2 py-1 text-[11px] text-emerald-700 dark:bg-emerald-950 dark:text-emerald-200">✓ {t("step.audited")}</div>}
                {current.audit === "bad" && <div className="rounded-md bg-rose-50 px-2 py-1 text-[11px] text-rose-700 dark:bg-rose-950 dark:text-rose-200">✗ {t("step.auditBad")}</div>}
                <div className="flex gap-2 pt-1">
                  <Button variant="outline" size="sm" className="flex-1" onClick={prevStep} disabled={idx <= -1 || deleted}>{t("step.prev")}</Button>
                  <Button size="sm" className="flex-1" onClick={nextStep} disabled={idx >= steps.length - 1 || deleted}>{t("step.next")}</Button>
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
            {(analysis.rules?.resolved || []).filter((r) => r.kind !== "_ignored").map((rule, i) => (
              <div key={i} className="flex items-center justify-between border-b py-1.5 text-xs last:border-0"><span>{ruleLabel(rule)}</span><span className="text-muted-foreground">× {rule.count || 1}</span></div>
            ))}
            <Button variant="link" size="sm" className="mt-2 px-0" onClick={() => setView("rules")}>{t("nav.rules")} →</Button>
          </TabsContent>
        </CardContent>
      </Tabs>
    </Card>
  );

  const stepsCard = analysis && (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 py-3.5"><CardTitle className="text-sm">{t("tabs.steps")}</CardTitle><span className="text-[11px] text-muted-foreground">{steps.length}</span></CardHeader>
      <CardContent className="p-2 pt-0">
        <div className="max-h-[260px] overflow-y-auto">
          {steps.map((step, i) => (
            <button key={i} onClick={() => { setPlaying(false); setIdx(i); }} className={`flex w-full items-center gap-3 rounded-md px-2.5 py-1.5 text-left text-xs ${i === idx ? "bg-muted font-medium text-foreground" : "text-muted-foreground hover:bg-muted/60"}`}>
              <span className="w-6 text-right font-mono text-[10.5px]">{i + 1}</span><span className="truncate">{stepTitle(step)}</span>
              <Badge variant="outline" className="ml-auto">{t("step.tier", { tier: step.tier })}</Badge>
            </button>
          ))}
        </div>
      </CardContent>
    </Card>
  );

  const entryTable = (entries, compact = false) => (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-xs">
        <thead><tr className="text-left text-muted-foreground">
          <th className="border-b px-3 py-2 font-medium">{t("table.puzzle")}</th>
          <th className="border-b px-3 py-2 font-medium">{t("table.status")}</th>
          <th className="border-b px-3 py-2 font-medium">{t("table.steps")}</th>
          <th className="border-b px-3 py-2 font-medium">{t("history.layers")}</th>
          <th className="border-b px-3 py-2 font-medium">{t("table.saved")}</th>
        </tr></thead>
        <tbody>
          {entries.map((entry) => {
            const isCurrent = entry.key === analysis?.storage?.key;
            return (
              <tr key={entry.key} className={`cursor-pointer border-b last:border-0 hover:bg-muted/40 ${isCurrent ? "bg-muted/30" : ""}`} onClick={() => loadEntry(entry)}>
                <td className="px-3 py-2.5">
                  <div className="flex items-center gap-2">
                    <div className="min-w-0"><div className="truncate font-medium">{entry.title}</div><div className="text-[10.5px] text-muted-foreground">{entry.author || entry.key}{isCurrent ? ` · ${t("history.current")}` : ""}</div></div>
                    <button className={`ml-auto ${entry.favorite ? "text-amber-500" : "text-muted-foreground"}`} onClick={(e) => { e.stopPropagation(); toggleFavorite(entry); }}><Star className="h-3.5 w-3.5" fill={entry.favorite ? "currentColor" : "none"} /></button>
                  </div>
                </td>
                <td className="px-3 py-2.5"><Badge variant={["solved", "solved-global", "solved-search"].includes(entry.status) ? "success" : "outline"}>{statusLabel(entry.status)}</Badge></td>
                <td className="px-3 py-2.5 font-mono text-[11px] text-muted-foreground">{entry.steps_count || 0}</td>
                <td className="px-3 py-2.5">
                  <div className="flex flex-wrap gap-1">
                    {["rules", "steps", "frames"].map((layer) => entry.layers?.[layer] && (
                      <span key={layer} className="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] text-muted-foreground">
                        {t(`layers.${layer}`)} {fmtBytes(entry.sizes?.[layer])}
                        <button className={`${isCurrent ? "cursor-not-allowed opacity-30" : "text-rose-500 hover:text-rose-600"}`} disabled={isCurrent} title={isCurrent ? t("history.currentProtected") : t("history.delete", { layer: t(`layers.${layer}`) })} onClick={(e) => { e.stopPropagation(); removeLayer(entry, layer); }}><X className="h-3 w-3" /></button>
                      </span>
                    ))}
                  </div>
                </td>
                <td className="px-3 py-2.5 text-[10.5px] text-muted-foreground">{entry.at ? new Date(entry.at * 1000).toLocaleDateString(lang === "zh" ? "zh-CN" : "en-US") : ""}</td>
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
      <header className="sticky top-0 z-30 border-b bg-background/95 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-[1280px] items-center gap-3 px-4 sm:gap-5 lg:gap-6 lg:px-6">
          <div className="flex items-center gap-2.5">
            <div className="grid h-8 w-8 place-items-center rounded-lg bg-primary text-sm text-primary-foreground">◈</div>
            <div><div className="text-sm font-semibold leading-tight tracking-tight">YSudoku</div><div className="hidden text-[10.5px] text-muted-foreground sm:block">{t("brand.sub")}</div></div>
          </div>
          <nav className="flex h-14 items-stretch gap-3 sm:gap-5">
            {navItems.map(([value, key]) => (
              <button key={value} onClick={() => { setView(value); setPlaying(false); }}
                className={`whitespace-nowrap border-b-2 px-0.5 text-[13px] transition-colors sm:text-sm ${view === value ? "border-primary font-semibold text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"}`}>
                {t(key)}
              </button>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-1.5">
            <DropdownMenu>
              <DropdownMenuTrigger asChild><Button variant="ghost" size="sm" className="gap-1.5 whitespace-nowrap text-xs text-muted-foreground"><Languages className="h-4 w-4" /><span className="hidden sm:inline">{lang === "zh" ? "中文" : "EN"}</span></Button></DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-36">
                <DropdownMenuLabel>{t("header.language")}</DropdownMenuLabel>
                <DropdownMenuItem onClick={() => setLang("zh")}><span className="flex-1">中文</span>{lang === "zh" && <Check className="h-4 w-4" />}</DropdownMenuItem>
                <DropdownMenuItem onClick={() => setLang("en")}><span className="flex-1">English</span>{lang === "en" && <Check className="h-4 w-4" />}</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <DropdownMenu>
              <DropdownMenuTrigger asChild><Button variant="ghost" size="icon" title={t("header.theme")}>{dark ? <Moon className="h-4 w-4" /> : <Sun className="h-4 w-4" />}</Button></DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-36">
                <DropdownMenuLabel>{t("header.theme")}</DropdownMenuLabel>
                <DropdownMenuItem onClick={() => setDark(false)}><Sun className="h-4 w-4" /><span className="flex-1">{t("header.light")}</span>{!dark && <Check className="h-4 w-4" />}</DropdownMenuItem>
                <DropdownMenuItem onClick={() => setDark(true)}><Moon className="h-4 w-4" /><span className="flex-1">{t("header.dark")}</span>{dark && <Check className="h-4 w-4" />}</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <div className="hidden h-7 w-7 place-items-center rounded-full bg-muted text-[10px] font-semibold sm:grid">YS</div>
          </div>
        </div>
      </header>

      <div className="border-b bg-card">
        <div className="mx-auto flex max-w-[1280px] flex-wrap items-center gap-2 px-4 py-2.5 lg:px-6">
          <form className="flex min-w-[260px] flex-1 items-center gap-2" onSubmit={(e) => { e.preventDefault(); submit({ url }); }}>
            <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder={t("header.url")} className="h-8 text-xs" />
            <Button type="submit" size="sm" className="whitespace-nowrap" disabled={busy}>{busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : t("header.solve")}</Button>
            <Button type="button" size="sm" variant="outline" className="whitespace-nowrap" onClick={demo} disabled={busy}>{t("header.demo")}</Button>
          </form>
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground"><Switch checked={llm} onCheckedChange={setLlm} className="scale-90" />{t("header.llm")}</label>
            <Popover><PopoverTrigger asChild><Button variant="ghost" size="icon" className="h-6 w-6"><HelpCircle className="h-3.5 w-3.5" /></Button></PopoverTrigger><PopoverContent className="text-xs leading-relaxed">{t("help.llm")}</PopoverContent></Popover>
            <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground"><Switch checked={audit} onCheckedChange={setAudit} className="scale-90" />{t("header.audit")}</label>
            <Popover><PopoverTrigger asChild><Button variant="ghost" size="icon" className="h-6 w-6"><HelpCircle className="h-3.5 w-3.5" /></Button></PopoverTrigger><PopoverContent className="text-xs leading-relaxed">{t("help.audit")}</PopoverContent></Popover>
          </div>
        </div>
      </div>

      <main className="mx-auto max-w-[1280px] px-4 py-6 lg:px-6 lg:py-8">
        {view === "solve" && (
          <>
            <PageHead
              title={analysis?.puzzle?.title || t("page.waiting")}
              description={analysis ? `${analysis.puzzle.author || ""} · ${t("page.givens", { n: analysis.puzzle.givens.filter(Boolean).length })}${isSolved ? ` · ${statusLabel(analysis.status)}` : ""}` : t("empty.solve")}
              badges={analysis ? <><Badge variant="outline">{n}×{n}</Badge><Badge variant={isSolved ? "success" : "outline"}>{statusLabel(analysis.status)}</Badge></> : null}
              actions={analysis ? <><Button variant="outline" size="sm" onClick={refreshRules} disabled={busy}><RotateCw className="mr-1 h-3.5 w-3.5" />{t("rules.refresh")}</Button><Button size="sm" onClick={() => setPlaying((v) => !v)} disabled={deleted}><Play className="mr-1 h-3.5 w-3.5" />{t("player.play")}</Button></> : null}
            />
            {!analysis ? emptySolve : (
              <>
                <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1.55fr)_minmax(320px,.85fr)]">
                  <div className="min-w-0 space-y-6">{boardCard}</div>
                  <div className="min-w-0 space-y-6">{inspector}{stepsCard}</div>
                </div>
                <div className="mt-6">
                  <Card>
                    <CardHeader className="flex-row items-center justify-between space-y-0 py-3.5"><div><CardTitle className="text-sm">{t("history.recentSolves")}</CardTitle><p className="mt-0.5 text-xs text-muted-foreground">{t("history.recentDesc")}</p></div><Button variant="outline" size="sm" onClick={() => setView("history")}>{t("history.openAll")}</Button></CardHeader>
                    <CardContent className="p-0">{entryTable((store?.entries || []).slice(0, 4))}</CardContent>
                  </Card>
                </div>
              </>
            )}
          </>
        )}

        {view === "rules" && (
          <>
            <PageHead title={t("rules.title")} description={analysis ? t("rules.desc", { model: "deepseek-flash" }) : t("empty.solve")}
              actions={analysis ? <Button variant="outline" size="sm" onClick={refreshRules} disabled={busy}><RotateCw className="mr-1 h-3.5 w-3.5" />{t("rules.refresh")}</Button> : null} />
            {!analysis ? emptySolve : (
              <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1.3fr)_minmax(300px,.7fr)]">
                <Card>
                  <CardHeader><CardTitle className="text-sm">{t("rules.title")}</CardTitle><p className="text-xs text-muted-foreground">{t("rules.forced")}</p></CardHeader>
                  <CardContent className="space-y-1 pt-0">
                    {(analysis.rules?.resolved || []).filter((r) => r.kind !== "_ignored").map((rule, i) => (
                      <div key={i} className="flex items-center justify-between border-b py-2 text-sm last:border-0"><span>{ruleLabel(rule)}</span><span className="text-xs text-muted-foreground">× {rule.count || 1}</span></div>
                    ))}
                    {analysis.rules?.warnings?.length ? <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200"><AlertTriangle className="mr-1 inline h-3.5 w-3.5" />{analysis.rules.warnings[0]}</div> : null}
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader><CardTitle className="text-sm">{t("rules.sheet")}</CardTitle><p className="text-xs text-muted-foreground">{t("rules.source")}: {analysis.spec_source || analysis.provenance || "—"}</p></CardHeader>
                  <CardContent>{analysis.rule_sheet ? <img src={analysis.rule_sheet} alt="rule sheet" className="w-full rounded-md border bg-white" /> : <p className="text-xs text-muted-foreground">—</p>}</CardContent>
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
                <Card key={layer}><CardContent className="p-4"><div className="text-xs text-muted-foreground">{t(key)}</div><div className="mt-1 text-lg font-semibold">{store?.info?.counts?.[layer] || 0}</div><div className="text-xs text-muted-foreground">{fmtBytes(store?.info?.sizes?.[layer])}</div></CardContent></Card>
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
                  <DropdownMenuContent align="end"><DropdownMenuLabel>{t("history.sort")}</DropdownMenuLabel><DropdownMenuCheckboxItem checked={sort === "recent"} onCheckedChange={() => setSort("recent")}>{t("history.recent")}</DropdownMenuCheckboxItem><DropdownMenuCheckboxItem checked={sort === "title"} onCheckedChange={() => setSort("title")}>{t("history.byTitle")}</DropdownMenuCheckboxItem></DropdownMenuContent>
                </DropdownMenu>
                <label className="flex items-center gap-1.5 text-xs text-muted-foreground"><input type="checkbox" checked={favOnly} onChange={(e) => setFavOnly(e.target.checked)} />{t("history.favOnly")}</label>
              </div></CardHeader>
              <CardContent className="p-0">{entryTable(filteredEntries)}</CardContent>
            </Card>
            <Card className="mt-4">
              <CardHeader className="py-3.5"><CardTitle className="text-sm">{t("history.settings")}</CardTitle></CardHeader>
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

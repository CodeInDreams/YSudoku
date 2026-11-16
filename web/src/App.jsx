import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpDown, Check, ChevronDown, ChevronLeft, ChevronRight, HelpCircle, Loader2, Moon, Palette, Play, RotateCw, Search, Star, Sun, X } from "lucide-react";
import { Button } from "./components/ui/button";
import { Input } from "./components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "./components/ui/card";
import { Badge } from "./components/ui/badge";
import { Switch } from "./components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./components/ui/tabs";
import { Popover, PopoverContent, PopoverTrigger } from "./components/ui/popover";
import { ScrollArea } from "./components/ui/scroll-area";
import {
  DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent,
  DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from "./components/ui/dropdown-menu";

const STATUS_LABEL = {
  solved: "已解出", "solved-global": "全局求解", "solved-search": "搜索求解",
  stuck: "卡住", unsupported: "不支持", invalid: "规则冲突",
};

const ACCENTS = [
  { value: "blue", label: "Blue", color: "#2563eb" },
  { value: "green", label: "Green", color: "#16a34a" },
  { value: "neutral", label: "Neutral", color: "#404040" },
  { value: "orange", label: "Orange", color: "#ea580c" },
  { value: "red", label: "Red", color: "#dc2626" },
  { value: "rose", label: "Rose", color: "#e11d48" },
  { value: "violet", label: "Violet", color: "#7c3aed" },
  { value: "yellow", label: "Yellow", color: "#eab308" },
];

const HELP = {
  llm: "用大模型把 SudokuPad 的规则文字和图形清单编译成结构化约束。题面若带官方答案，只用于自检，不参与求解；关闭后使用本地启发式规则识别。",
  audit: "求解完成后，对每一步结论做独立穷举验证：假设该结论不成立，如果仍能解出，就把这一步标为异常。较慢，默认关闭。",
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
          if (!set.has(ev.value)) throw new Error(`候选不变量被破坏：第 ${step.index + 1} 步 ${ev.cell} 填 ${ev.value}`);
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

function StatusLine({ analysis }) {
  if (!analysis) return null;
  const status = analysis.status || "";
  const variant = ["solved", "solved-global", "solved-search"].includes(status) ? "success"
    : status === "invalid" ? "destructive" : status === "stuck" ? "warning" : "secondary";
  const text = `${STATUS_LABEL[status] || status}${analysis.steps?.length ? ` · ${analysis.steps.length} 步` : ""}${analysis.solution_check ? ` · ${analysis.solution_check}` : ""}`;
  return <div className={`rounded-lg border px-3 py-2 text-xs ${variant === "success" ? "bg-emerald-50 text-emerald-800 border-emerald-200 dark:bg-emerald-950 dark:text-emerald-200 dark:border-emerald-900" : variant === "warning" ? "bg-amber-50 text-amber-800 border-amber-200 dark:bg-amber-950 dark:text-amber-200 dark:border-amber-900" : variant === "destructive" ? "bg-rose-50 text-rose-800 border-rose-200 dark:bg-rose-950 dark:text-rose-200 dark:border-rose-900" : "bg-muted text-muted-foreground"}`}>{text}</div>;
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
  const [tab, setTab] = useState("steps");
  const [store, setStore] = useState(null);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("recent");
  const [favOnly, setFavOnly] = useState(false);
  const [error, setError] = useState("");
  const [dark, setDark] = useState(() => {
    try { return localStorage.getItem("ysudoku.theme") === "dark"; } catch { return false; }
  });
  const [accent, setAccent] = useState(() => {
    try { return localStorage.getItem("ysudoku.accent") || "neutral"; } catch { return "neutral"; }
  });
  const [settings, setSettings] = useState({ max_rules: 100, max_steps: 100, max_frames: 10, max_mb: 500 });

  const steps = analysis?.steps || [];
  const n = analysis?.puzzle?.size || 9;
  const current = idx >= 0 ? steps[idx] : null;

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    try { localStorage.setItem("ysudoku.theme", dark ? "dark" : "light"); } catch { /* ignore */ }
  }, [dark]);

  useEffect(() => {
    document.documentElement.dataset.accent = accent;
    try { localStorage.setItem("ysudoku.accent", accent); } catch { /* ignore */ }
  }, [accent]);

  useEffect(() => {
    if (!playing) return;
    if (idx >= steps.length - 1) { setPlaying(false); return; }
    const timer = setTimeout(() => setIdx((value) => Math.min(value + 1, steps.length - 1)), speed);
    return () => clearTimeout(timer);
  }, [playing, idx, steps.length, speed]);

  useEffect(() => {
    const onKey = (event) => {
      if (event.target.tagName === "INPUT" || event.target.tagName === "SELECT") return;
      if (event.key === "ArrowRight") { setPlaying(false); setIdx((v) => Math.min(v + 1, steps.length - 1)); }
      if (event.key === "ArrowLeft") { setPlaying(false); setIdx((v) => Math.max(v - 1, -1)); }
      if (event.key === " ") { event.preventDefault(); setPlaying((v) => !v); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [steps.length]);

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

  async function startLive(nextAnalysis) {
    setReady(false);
    setSession(null);
    try {
      const actions = buildStepActions(nextAnalysis);
      let hash = 2166136261;
      const text = "frame-v5:" + JSON.stringify(actions);
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
      setError(`截图构建失败：${err.message}`);
    }
  }

  async function submit(payload) {
    setBusy(true); setError(""); setPlaying(false);
    try {
      const data = await postJson("/api/solve", { url: payload.url, llm, audit, chains: true });
      setAnalysis(data); setTarget(payload.url); setIdx(-1); startLive(data); refreshStore();
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  async function demo() {
    setBusy(true); setError(""); setPlaying(false);
    try {
      const data = await postJson("/api/demo", {});
      setAnalysis(data); setTarget(""); setUrl(""); setIdx(-1); startLive(data); refreshStore();
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  async function refreshLayer(endpoint) {
    if (!analysis) return;
    setBusy(true); setPlaying(false);
    try {
      const data = await postJson(endpoint, { target: target || "", demo: !!analysis.demo });
      setAnalysis(data); setIdx(-1); startLive(data); refreshStore();
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  async function rerender() {
    if (!analysis?.storage?.key) return;
    setBusy(true);
    try {
      await postJson("/api/store/rerender", { key: analysis.storage.key });
      await startLive(analysis);
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  async function toggleFavorite(entry) {
    await postJson("/api/store/favorite", { key: entry.key, favorite: !entry.favorite });
    refreshStore();
  }

  async function removeLayer(entry, layer) {
    const label = { rules: "规则理解", steps: "推理步骤", frames: "截图" }[layer];
    if (!window.confirm(`删除「${entry.title}」的${label}？`)) return;
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
      setAnalysis(data); setTarget(entry.demo ? "" : entry.target); setUrl(entry.demo ? "" : entry.target); setIdx(-1); startLive(data);
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
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
    if (!analysis || idx < 0) return null;
    const state = candidateStateUpTo(analysis, idx);
    const negatives = [];
    for (const [cell, set] of state) {
      if (set.size <= 6) continue;
      const excluded = [];
      for (let v = 1; v <= n; v++) if (!set.has(v)) excluded.push(v);
      if (excluded.length && excluded.length <= 3) negatives.push({ cell, digits: excluded });
    }
    return { visual: steps[idx]?.visual || {}, negatives };
  }, [analysis, idx, n, steps]);

  return (
    <div className="min-h-screen bg-muted/30">
      <header className="border-b bg-background/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-3 px-4 py-3 lg:flex-nowrap">
          <div className="flex items-center gap-2">
            <div className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-primary to-violet-600 text-white shadow">◈</div>
            <div>
              <div className="text-base font-semibold leading-tight">YSudoku</div>
              <div className="hidden text-[11px] text-muted-foreground sm:block">See why every digit is right</div>
            </div>
          </div>
          <form className="flex min-w-[220px] flex-1 items-center gap-2" onSubmit={(e) => { e.preventDefault(); submit({ url }); }}>
            <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="粘贴 SudokuPad 链接，例如 https://sudokupad.app/eynwusqy5l" className="h-9" />
            <Button type="submit" disabled={busy}>{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "解析并求解"}</Button>
            <Button type="button" variant="outline" onClick={demo} disabled={busy}>示例</Button>
          </form>
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground"><Switch checked={llm} onCheckedChange={setLlm} />LLM 规则</label>
            <Popover>
              <PopoverTrigger asChild><Button variant="ghost" size="icon" className="h-7 w-7"><HelpCircle className="h-4 w-4" /></Button></PopoverTrigger>
              <PopoverContent className="text-xs leading-relaxed">{HELP.llm}</PopoverContent>
            </Popover>
            <span className="hidden text-[11px] text-emerald-600 sm:inline">deepseek-flash</span>
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground"><Switch checked={audit} onCheckedChange={setAudit} />反证审计</label>
            <Popover>
              <PopoverTrigger asChild><Button variant="ghost" size="icon" className="h-7 w-7"><HelpCircle className="h-4 w-4" /></Button></PopoverTrigger>
              <PopoverContent className="text-xs leading-relaxed">{HELP.audit}</PopoverContent>
            </Popover>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" title="主题"><Palette className="h-4 w-4" /></Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-44">
                <DropdownMenuLabel>主题</DropdownMenuLabel>
                {ACCENTS.map((item) => (
                  <DropdownMenuItem key={item.value} onClick={() => setAccent(item.value)}>
                    <span className="h-2 w-2 rounded-full" style={{ background: item.color }} />
                    <span className="flex-1">{item.label}</span>
                    {accent === item.value && <Check className="h-4 w-4" />}
                  </DropdownMenuItem>
                ))}
                <DropdownMenuSeparator />
                <DropdownMenuLabel>模式</DropdownMenuLabel>
                <DropdownMenuItem onClick={() => setDark(false)}><Sun className="h-4 w-4" /><span className="flex-1">Light</span>{!dark && <Check className="h-4 w-4" />}</DropdownMenuItem>
                <DropdownMenuItem onClick={() => setDark(true)}><Moon className="h-4 w-4" /><span className="flex-1">Dark</span>{dark && <Check className="h-4 w-4" />}</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </header>

      <main className="mx-auto grid max-w-[1600px] gap-5 px-4 py-4 lg:grid-cols-[minmax(0,1fr)_420px] lg:items-start">
        <section className="flex min-w-0 flex-col gap-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <div>
              <h1 className="text-xl font-semibold">{analysis?.puzzle?.title || "等待题目"}</h1>
              {analysis && <p className="text-xs text-muted-foreground">{analysis.provenance || analysis.puzzle.author} {analysis.source_url && <a className="text-primary hover:underline" href={analysis.source_url} target="_blank" rel="noreferrer">· 在 SudokuPad 打开原题</a>}</p>}
            </div>
            <div className="text-xs text-muted-foreground">{analysis ? `${analysis.puzzle.author} · ${n}×${n} · ${analysis.puzzle.givens.filter(Boolean).length} 个提示数` : ""}</div>
          </div>

          <Card className="overflow-hidden">
            <CardContent className="p-3">
              <div className="relative mx-auto flex aspect-square w-full max-w-[calc(100vh-230px)] items-center justify-center overflow-hidden rounded-lg border bg-white">
                {!ready && <div className="absolute inset-0 z-10 grid place-items-center gap-2 bg-white/80 text-sm text-muted-foreground"><Loader2 className="h-6 w-6 animate-spin text-primary" />正在准备棋盘…</div>}
                {session && (
                  <img
                    key={`${session}-${idx}-${retry}`}
                    src={`/api/live/frame?session=${session}&step=${idx}&t=${retry}`}
                    alt="SudokuPad 题目"
                    className={`h-full w-full object-contain transition-opacity ${ready ? "opacity-100" : "opacity-0"}`}
                    onLoad={() => setReady(true)}
                    onError={() => setTimeout(() => setRetry((v) => v + 1), 450)}
                  />
                )}
                {overlay && ready && (
                  <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox={`0 0 ${n} ${n}`} preserveAspectRatio="none">
                    {(overlay.visual.groups || []).map((group, i) => {
                      if (!group.cells?.length) return null;
                      const rows = group.cells.map((c) => Math.floor(c / n));
                      const cols = group.cells.map((c) => c % n);
                      const color = ["#3b82f6", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6", "#14b8a6"][i % 6];
                      return <rect key={i} x={Math.min(...cols) + 0.03} y={Math.min(...rows) + 0.03} width={Math.max(...cols) - Math.min(...cols) + 0.94} height={Math.max(...rows) - Math.min(...rows) + 0.94} rx="0.08" fill={color} fillOpacity="0.12" stroke={color} strokeOpacity="0.6" strokeWidth="0.05" />;
                    })}
                    {(overlay.visual.focus || []).map((cell) => {
                      const r = Math.floor(cell / n), c = cell % n;
                      return <rect key={`f${cell}`} x={c + 0.03} y={r + 0.03} width="0.94" height="0.94" rx="0.06" fill="rgba(245,158,11,.16)" stroke="#f59e0b" strokeWidth="0.05" />;
                    })}
                    {(overlay.visual.links || []).map((link, i) => (
                      <polyline key={`l${i}`} points={(link.points || []).map(([y, x]) => `${x},${y}`).join(" ")} fill="none" stroke={link.color || "#3b82f6"} strokeWidth="0.08" strokeLinecap="round" />
                    ))}
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
                <span className="pointer-events-none absolute right-1 top-1 rounded bg-white/70 px-1.5 py-0.5 text-[10px] text-slate-500">SudokuPad · 只读</span>
              </div>
            </CardContent>
          </Card>

          <div className="flex flex-wrap items-center justify-center gap-2">
            <Button variant="outline" size="icon" onClick={() => { setPlaying(false); setIdx((v) => Math.max(-1, v - 1)); }} disabled={idx <= -1}><ChevronLeft className="h-4 w-4" /></Button>
            <Button onClick={() => setPlaying((v) => !v)} disabled={!steps.length}>{playing ? "暂停" : <><Play className="mr-1 h-4 w-4" />播放</>}</Button>
            <Button variant="outline" size="icon" onClick={() => { setPlaying(false); setIdx((v) => Math.min(steps.length - 1, v + 1)); }} disabled={idx >= steps.length - 1}><ChevronRight className="h-4 w-4" /></Button>
            <span className="ml-2 text-xs text-muted-foreground">速度</span>
            <input type="range" min="200" max="2400" step="100" value={speed} onChange={(e) => setSpeed(Number(e.target.value))} className="w-36 accent-primary" />
          </div>
          <input type="range" min="-1" max={Math.max(0, steps.length - 1)} value={idx} onChange={(e) => { setPlaying(false); setIdx(Number(e.target.value)); }} className="w-full accent-primary" disabled={!steps.length} />
          {error && <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-200">{error}</div>}
        </section>

        <aside className="min-w-0 lg:max-h-[calc(100vh-100px)] lg:overflow-y-auto">
          <Tabs value={tab} onValueChange={setTab}>
            <TabsList className="h-auto w-full justify-start gap-6 rounded-none border-b bg-transparent p-0">
              <TabsTrigger value="steps" className="rounded-none border-b-2 border-transparent px-0 pb-2 text-sm text-muted-foreground shadow-none data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-foreground data-[state=active]:font-semibold data-[state=active]:shadow-none">推理</TabsTrigger>
              <TabsTrigger value="rules" className="rounded-none border-b-2 border-transparent px-0 pb-2 text-sm text-muted-foreground shadow-none data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-foreground data-[state=active]:font-semibold data-[state=active]:shadow-none">规则</TabsTrigger>
              <TabsTrigger value="history" className="rounded-none border-b-2 border-transparent px-0 pb-2 text-sm text-muted-foreground shadow-none data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-foreground data-[state=active]:font-semibold data-[state=active]:shadow-none">历史</TabsTrigger>
            </TabsList>

            <TabsContent value="steps" className="space-y-3">
              <Card>
                <CardHeader className="pb-2">
                  <div className="flex items-center justify-between gap-2">
                    <CardTitle className="text-sm">{current ? `第 ${idx + 1} 步 · ${current.title}` : "尚无步骤"}</CardTitle>
                    {current && <Badge variant="outline">T{current.tier}</Badge>}
                  </div>
                </CardHeader>
                <CardContent className="space-y-3 pt-0">
                  <p className="whitespace-pre-wrap text-sm leading-7 text-foreground/90">{current?.detail || "加载题目后，点播放或下一步开始。"}</p>
                  {current?.candidates?.length ? (
                    <div className="rounded-lg bg-muted px-3 py-2 font-mono text-xs leading-6 text-foreground">
                      候选：{current.candidates.map((c) => `R${Math.floor(c.cell / n) + 1}C${(c.cell % n) + 1} {${c.digits.join("、")}}`).join("；")}
                    </div>
                  ) : null}
                  {current?.audit === "ok" && <div className="rounded-md bg-emerald-50 px-2 py-1 text-xs text-emerald-700 dark:bg-emerald-950 dark:text-emerald-200">✓ 已用穷举反证校验</div>}
                  {current?.audit === "bad" && <div className="rounded-md bg-rose-50 px-2 py-1 text-xs text-rose-700 dark:bg-rose-950 dark:text-rose-200">✗ 反证失败</div>}
                  <div className="flex justify-end gap-2">
                    <Button size="sm" variant="outline" onClick={() => refreshLayer("/api/store/resolve")} disabled={!analysis || busy}><RotateCw className="mr-1 h-3.5 w-3.5" />重新解题</Button>
                    <Button size="sm" variant="outline" onClick={rerender} disabled={!analysis || busy}>重新渲染</Button>
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-sm">步骤列表</CardTitle></CardHeader>
                <CardContent className="p-2 pt-0">
                  <ScrollArea className="h-[280px]">
                    <div className="space-y-1 pr-2">
                      {steps.map((step, i) => (
                        <button key={i} onClick={() => { setPlaying(false); setIdx(i); }} className={`flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-xs transition-colors ${i === idx ? "bg-primary/10 text-primary" : "hover:bg-muted"}`}>
                          <span className="w-6 text-right font-mono text-muted-foreground">{i + 1}</span>
                          <span className="truncate">{step.title}</span>
                        </button>
                      ))}
                    </div>
                  </ScrollArea>
                </CardContent>
              </Card>
              <StatusLine analysis={analysis} />
            </TabsContent>

            <TabsContent value="rules" className="space-y-3">
              <Card>
                <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
                  <CardTitle className="text-sm">本题规则理解</CardTitle>
                  <Button size="sm" variant="outline" onClick={() => refreshLayer("/api/store/refresh_rules")} disabled={!analysis || busy}><RotateCw className="mr-1 h-3.5 w-3.5" />刷新规则</Button>
                </CardHeader>
                <CardContent className="space-y-2">
                  {(analysis?.rules?.resolved || []).filter((r) => r.kind !== "_ignored").map((rule, i) => (
                    <div key={i} className="flex items-baseline justify-between gap-2 text-xs">
                      <span className="text-foreground">{rule.label || rule.kind}</span>
                      <span className="text-muted-foreground">× {rule.count || 1}</span>
                    </div>
                  ))}
                  {!analysis && <p className="text-xs text-muted-foreground">加载题目后显示。</p>}
                  {analysis?.rules?.warnings?.length ? <div className="rounded-md bg-amber-50 px-2 py-1 text-[11px] text-amber-800 dark:bg-amber-950 dark:text-amber-200">{analysis.rules.warnings[0]}</div> : null}
                </CardContent>
              </Card>
              {analysis?.rule_sheet && <Card><CardHeader className="pb-2"><CardTitle className="text-sm">规则图（视觉）</CardTitle></CardHeader><CardContent><img src={analysis.rule_sheet} alt="rule sheet" className="w-full rounded-lg border bg-white" /></CardContent></Card>}
            </TabsContent>

            <TabsContent value="history" className="space-y-3">
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-sm">历史记录</CardTitle></CardHeader>
                <CardContent className="space-y-3">
                  <div className="space-y-1 text-xs text-muted-foreground">
                    <div className="break-all">位置：{store?.info?.location || "—"}</div>
                    <div>规则 {store?.info?.counts?.rules || 0} · {fmtBytes(store?.info?.sizes?.rules)}｜步骤 {store?.info?.counts?.steps || 0} · {fmtBytes(store?.info?.sizes?.steps)}｜截图 {store?.info?.counts?.frames || 0} · {fmtBytes(store?.info?.sizes?.frames)}</div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <div className="relative min-w-[120px] flex-1"><Search className="absolute left-2 top-2.5 h-3.5 w-3.5 text-muted-foreground" /><Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索标题/作者" className="h-8 pl-7 text-xs" /></div>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="outline" size="sm" className="h-8 gap-1.5 px-2 text-xs"><ArrowUpDown className="h-3.5 w-3.5" />{sort === "recent" ? "最近" : "标题"}<ChevronDown className="h-3 w-3 opacity-60" /></Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuLabel>排序</DropdownMenuLabel>
                        <DropdownMenuCheckboxItem checked={sort === "recent"} onCheckedChange={() => setSort("recent")}>最近</DropdownMenuCheckboxItem>
                        <DropdownMenuCheckboxItem checked={sort === "title"} onCheckedChange={() => setSort("title")}>标题</DropdownMenuCheckboxItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                    <label className="flex items-center gap-1 text-xs text-muted-foreground"><input type="checkbox" checked={favOnly} onChange={(e) => setFavOnly(e.target.checked)} />只看收藏</label>
                  </div>
                  <div className="space-y-2">
                    {filteredEntries.slice(0, 50).map((entry) => (
                      <div key={entry.key} className="cursor-pointer rounded-lg border p-3 transition-colors hover:bg-muted/50" onClick={() => loadEntry(entry)}>
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0">
                            <div className="truncate text-sm font-medium">{entry.title}</div>
                            <div className="text-[11px] text-muted-foreground">{entry.at ? new Date(entry.at * 1000).toLocaleString() : ""} · {STATUS_LABEL[entry.status] || entry.status} · {entry.steps_count || 0} 步</div>
                          </div>
                          <button className={`shrink-0 ${entry.favorite ? "text-amber-500" : "text-muted-foreground"}`} onClick={(e) => { e.stopPropagation(); toggleFavorite(entry); }}><Star className="h-4 w-4" fill={entry.favorite ? "currentColor" : "none"} /></button>
                        </div>
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {["rules", "steps", "frames"].map((layer) => entry.layers?.[layer] && (
                            <span key={layer} className="inline-flex items-center gap-1 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                              {{ rules: "规则", steps: "步骤", frames: "截图" }[layer]} {fmtBytes(entry.sizes?.[layer])}
                              <button className="text-rose-500 hover:text-rose-600" onClick={(e) => { e.stopPropagation(); removeLayer(entry, layer); }}><X className="h-3 w-3" /></button>
                            </span>
                          ))}
                        </div>
                      </div>
                    ))}
                    {store && !filteredEntries.length && <p className="text-xs text-muted-foreground">还没有记录。</p>}
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-sm">存储设置</CardTitle></CardHeader>
                <CardContent className="grid grid-cols-2 gap-2 text-xs">
                  {[["max_rules", "规则"], ["max_steps", "步骤"], ["max_frames", "截图"], ["max_mb", "总量 MB"]].map(([key, label]) => (
                    <label key={key} className="flex items-center justify-between gap-2 rounded-md border px-2 py-1.5">
                      <span className="text-muted-foreground">{label}</span>
                      <input type="number" min="0" value={settings[key] ?? ""} onChange={(e) => setSettings((s) => ({ ...s, [key]: Number(e.target.value) }))} className="w-16 bg-transparent text-right outline-none" />
                    </label>
                  ))}
                  <Button size="sm" className="col-span-2" onClick={saveSettings}>保存存储设置</Button>
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>
        </aside>
      </main>
    </div>
  );
}

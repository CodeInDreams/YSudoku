# YSudoku 技术设计

本文描述 YSudoku 的规则表示、求解器、步骤语义、分层缓存、SudokuPad 只读镜像渲染、Web 前端与 API。实现以仓库当前版本为准。

## 1. 目标与边界

YSudoku 的目标不是只给出答案，而是给出一条**可阅读、可复核、可复现的推理路径**，并把每一步映射到 SudokuPad 原生的 Digit / Centre / Colour / Pen 操作上，生成只读截图。

- 不修改 SudokuPad 题目本身。
- 不把官方答案当作求解输入；有答案时只用于事后校验。
- 规则理解来自题面文字、SudokuPad 图形元素和用户补充描述；不靠猜测题目类型。
- 每一步必须有可检查的规则理由；渲染不能出现“候选显示 A、最终填 B”的情况。
- 允许缓存和重算，但只有“打开谜题”和“重新解析规则”两个入口可以触发强制重解/重渲染。

## 2. 总体架构

```text
SudokuPad link / fixture
        │
        ▼
SudokuPad payload decode (LZW + zipper JSON)
        │
        ▼
Puzzle + rules text + drawn inventory
        │
        ▼
P1 规则理解：LLM 编译 / 本地启发式 / 用户补充
        │
        ▼
规则 Spec ──► Constraint / Technique 列表
        │
        ▼
P2 求解器：状态传播 + 技巧调度 + 逐步解释
        │
        ▼
Step[]：events / pre_dom / visual / detail
        │
        ├──► P3 截图：Playwright + SudokuPad 原生工具
        │
        ▼
Web UI：棋盘帧、叠层、步骤卡、规则、历史、存储
```

后端是 Python 标准库 HTTP 服务，前端是 Vite + React + Tailwind + shadcn 风格组件；Playwright 作为独立的 Node 子进程管理 SudokuPad 页面。

## 3. SudokuPad 数据层

### 3.1 解码

`sudokupad` payload 使用自定义 LZW 压缩，外层再包一层 zipper JSON。`ysudoku/decode.py` 负责解码，并保留单元格占位符 `{}`，避免行列错位。

坐标统一使用 `(row, col)`，0-based；内部格子编号为 `row * n + col`。

### 3.2 Puzzle

`Puzzle` 包含：

- `size`、`givens`、`solution`
- `regions`（混沌题可能不是标准宫）
- 盘外 `clues`
- `rules_text`（题面原文）
- `rule_sheet`（规则图）
- `title`、`author`、`source_url`

### 3.3 图形元素 Inventory

`build_inventory` 把笼、线、箭头、盘外提示等转换为统一元素列表，供 LLM 和本地规则共同使用。元素带编号，规则图也使用同一编号，便于“规则文字 ↔ 图形”对照。

## 4. 规则层（P1）

### 4.1 规则 Spec

Spec 是结构化约束列表：

```json
{
  "rules": [
    {"kind": "cage", "cells": ["R1C1", "R1C2"], "sum": 9},
    {"kind": "class_cover", "cells": ["R1C1", "R1C2", "R2C1", "R2C2"],
     "classes": [[1,2,3],[4,5,6],[7,8,9]]}
  ],
  "warnings": [],
  "globals": []
}
```

规则来源优先级：

1. 用户显式 `spec_override` / 已存 P1
2. LLM 编译（`deepseek-flash`，可带规则图）
3. 本地启发式（LLM 不可用或失败时）

### 4.2 用户补充描述

Rules 页允许填写补充规则。补充文本会以“权威规则文本”的形式附加到 LLM 输入：

```text
=== USER SUPPLEMENT (treat as authoritative rule text) ===
...
```

- 只有点击“保存/重新解析规则”才生效。
- 补充文本随 P1 保存；重新打开无需再次编译。
- 规则缓存指纹包含补充文本，避免不同补充复用同一个缓存。
- 用户补充不直接参与求解；必须先编译成 Constraint。

### 4.3 约束类型

当前实现包括：

- `Cage`：杀手笼；数值和、不重复；笼内只剩一个宿主时直接落子。
- `XV`：SudokuPad 的 X/V overlay/underlay 会解析成 `xv_clues`，再提升为 `xv` 约束；自动补齐 LLM 漏掉的 X/V，支持任意边位置与 X/V 两种值。
- `Thermo`、`Arrow`、`Between`、`SumLine`、`RegionSum`、`XSums`
- `PairRule`（Kropki / XV 等）、`Quadruple`、`Palindrome`、`Renban`
- `Parity`、`Clone`、`Sandwich`、`Skyscraper`
- `ClassCover`：2×2 类覆盖（entropy / modularity）
- `RegionCount`、`AntiPair`、`Custom`
- 盘外 Full Rank / X-Sums / 未知类型配对可由可选 OR-Tools CP-SAT 处理

每个 Constraint 至少提供：

```python
cells() -> list[int]
prune(state) -> bool          # 修改 state.dom / state.vals 并记录 events
check(values) -> bool         # 完整解的合法性
describe() / to_dict()
```

### 4.4 经典技巧

`TECHNIQUES` 按层级排列：

1. `naked_single`、`hidden_single`
2. `forty_five`、`hidden_subset`、`locked`、`subset`
3. `x_wing`、`xy_wing`、`w_wing`、`coloring`、`medusa`、`x_chain`、`als`
4. `forcing_chain`（直接推理卡住后尝试）

技巧不直接修改 UI，只产生 `Event`。`Reason` 保存规则种类、作用域和解释所需数据。

### 4.5 规则校验

- 编译后检查每个 Constraint 是否能覆盖题面/图形元素。
- 盘外提示未被任何规则使用时给出 warning；必要时尝试全局求解。
- 求解结束用 `check_solution` 检查行、列、宫、约束。
- 有官方答案时比较最终值，仅用于校验。
- 可选反证审计：对每步结论假设其不成立并搜索是否仍可解。

## 5. 求解器（P2）

### 5.1 状态

`State` 保存：

- `dom[cell]`：候选位掩码
- `vals[cell]`：已填值
- `peers[cell]`：同行、同列、同宫、对角等 peer
- `events`：本次调用的增量事件

基本操作：

- `elim(cell, value, reason)`
- `place(cell, value, reason)`
- `restrict(cell, mask, reason)`
- `begin()` / `end()` 记录增量

### 5.2 调度顺序

每次 `next_step()`：

1. 显式 `Custom` 约束
2. 单候选：`naked_single`、`hidden_single`
3. 其他 Constraint（按焦点和候选数排序）
4. 其他 Technique（按层级）

Constraint 排序键：

```text
1. 与当前 focus 的交集从大到小
2. 作用域内最小候选数从小到大
```

`focus` 只取本步真正落子或主规则涉及的格子，不包含所有 peer 删除，避免注意力被扩散。

### 5.3 一步的定义

这是本项目的核心语义，必须同时满足：

1. **同一区域 / 同一格 + 同一规则**产生的所有落子和删数属于同一步。
2. **有先后依赖关系的推理不能放在同一步。**

具体规则：

- 一次 Constraint / Technique 调用，对它的作用域产生的全部事件 → 一步。
- 如果 A 落子/删数改变了候选，才推出 B，则 B 是依赖步骤 → 必须另起一步。
- 两个步骤都由同一个上一步直接推出，彼此没有依赖，且规则相同（naked/hidden single）→ 可以作为 sibling 合并为一步。
- sibling 之间可以夹着依赖步骤；合并时把所有直接 sibling 合并到第一个 sibling 步骤，依赖步骤保留在合并步骤之后。
- 跨步骤合并前必须检查中间步骤是否改过 sibling 的格子；改过就说明存在依赖，不能前移合并。
- 不能把 sibling 合并回它们的 origin；origin 与 sibling 之间存在依赖。
- 规则/约束在**自己的作用域内**把某格压成单候选时，直接在该步落子，不再单开 naked-single 步。
- 由本步落子的 peer 删除、作用域外产生的单候选属于依赖步骤，必须另起一步。
- 同一笼内多个独立单候选宿主属于同一规则/区域，可在该笼步骤内一起落子。

示例：

```text
第 36 步  笼 8：R6C6=6 → R6C5=2
第 37 步  R4C4 只剩 3、R6C3 只剩 3
          （两者都由 36 引起，但彼此独立，合并）
```

R4C4/R6C3 不能并回 36，因为它们依赖 36 的 2。

### 5.4 单候选与自动 digit

Centre 只允许一个候选，这是正常状态。单候选在渲染上会被 SudokuPad 画成 digit 大小；这并不代表它已经被正式填入。

求解器对单候选的处理：

- 约束直接产生的单宿主：由该约束直接 `place`（同一规则/区域）。
- 依赖性的单候选：作为下一步 `naked_single`，单独一步。
- 渲染层不再提前把单候选写成正式 digit；必须等 solver 的 `place` 事件。

### 5.5 反证与全局求解

- 网页和命令行在直接推理卡住后均会尝试 `forcing_chain`。
- 全局约束（Full Rank / X-Sums）通过可选 CP-SAT 求解，失败时回退。
- 反证审计只用于标注，不改变求解路径。
- 如果规则技巧仍卡住，不使用整盘搜索补全，而是执行反证步骤：
  - 假设某格为某个候选值；
  - 在假设下传播约束并穷举；
  - 若无解，则排除该候选；若该格只剩另一个值，则直接填入；
  - 然后继续正常解题。
- 反证拆成三个阶段步骤，避免长证明挤在一步：
  - `反证开始`：标出假设格和假设值，不写入正式棋盘；
  - `反证检查`：在假设下继续正常推理，关键强制结果按每步 6 条拆成多个检查步骤；
  - `反证推翻`：所有分支无解，排除候选或填入另一值。
- 三阶段共享同一假设叠加层；标签分别为“反证开始/检查/推翻：假设 R?C?=x”。

## 6. 分层存储（P1/P2/P3）

### 6.1 目录

```text
.cache/store/
  settings.json
  <puzzle-key>/
    meta.json
    rules.json       # P1
    analysis.json    # P2
    frames/          # P3
```

`puzzle-key = sha1(normalized target)[:16]`。

### 6.2 层依赖

```text
P1 rules
  └── P2 analysis (rules_hash)
        └── P3 frames (steps_hash / actions hash)
```

- P1 变化 → P2/P3 失效。
- P2 变化 → P3 失效。
- 打开谜题时：
  - 有有效 P2 → 直接复用。
  - 有 P1 无 P2 → 用 P1 重新求解。
  - 无 P1 → 重新编译规则。
  - 有 P2 无 P3 → 只重建截图。
- 只有“打开谜题”和“重新解析规则”会触发重解/重渲染。

### 6.3 级联删除

- 删除 rules：删除 rules + steps + frames，并清空补充描述。
- 删除 steps：删除 steps + frames。
- 删除 frames：只删除 frames。
- 当前正在查看的谜题不允许从历史中删除。
- 如果当前缓存被外部删除，下一次“下一步”会提示缓存已删除，并停止推进。

### 6.4 清理策略

设置项：

- `max_rules`、`max_steps`、`max_frames`：按**谜题数**限制。
- `max_mb`：总空间上限。

空间不足时：

1. 删除截图（最旧、非收藏优先）
2. 删除步骤
3. **永不自动删除规则**

收藏谜题最后被清理。

## 7. SudokuPad 只读镜像（P3）

### 7.1 浏览器

- 长生命周期 Chromium；每次打开题目新建 context。
- 通过 `#control-normal`、`#control-centre`、`#control-corner`、`#control-colour` 操作原生工具。
- 每个新 context 写入统一设置：
  - `puzzleevents: off`（关闭 3-In-The-Corner Effect 烟花动画）
  - `marksolveddigits: off`（关闭已解数字标记）
  - `toolpen/toolletter: false`（不启用未使用的 Pen/Letter）
  - `largedigits/flipkeypad/outlineson.../dashedgrid: false`
  - `hidetimer: true`、`hidesvenpeek: true`、`hidesupportlinks: true`
  - `showplayinsudokupad: false`、`pauseonstart: false`、`checkonfinish: false`
  - `checkpencilmarks: false`（避免 SudokuPad 自动清候选）
  - `selection: cage` 仅是选择高亮样式，不是多选
  - `uitheme: monolight`（中性界面）
- SVG `viewBox="-16 -16 608 608"`，截取时裁掉 16 单位 padding，只保留 576×576 棋盘。

### 7.2 单元格定位

- 每次动作前按当前 `svg.boardsvg` boundingBox 重算格子中心，避免缓存坐标在布局变化后偏移。
- 点击目标格后再切换工具，防止点击格重置工具状态。
- 每次动作前按 Escape、退出 Select、点击盘面外空白清除选择，避免多格同时输入。

### 7.3 候选写入

`buildStepActions` 不再生成“先标中间候选、再逐个删”的动作，而是：

1. 用 `pre_dom` 同步所有已打开格子的真实候选。
2. 先算本步结束后的最终候选集合。
3. 通过 `{op:"candidates", cell, digits}` 一次性设置该格候选。

Node 端：

- 读取当前 Centre 候选。
- 只对差异做 toggle。
- 遇到已填格直接跳过，绝不写入候选。
- 动作后校验候选集合；不一致就记录错误而不是继续污染。

### 7.4 填数

- Digit 本身会覆盖该格的 digit / corner / centre，无需预清空。
- 填数前清选择、重算坐标、点击目标格、切回 Digit。
- 填数后校验目标格；校验失败记 warning，不中断整条截图链。

### 7.5 帧一致性

每步动作后：

1. 补齐所有“应填但缺失”的数字。
2. 恢复被覆盖的应填数字。
3. 只清除从未登记过的多余值。
4. 清除选择，再截图。

这样已填数字不会被候选刷新或错位点击抹掉。

### 7.6 异步求解与进度

- `/api/solve/start` 创建后台 job，立即返回 job id。
- job 在后台线程执行规则编译与求解，阶段为 `rules → solving → done`：
  - 规则编译完成后推送规则摘要；
  - solver 每产生一个 Step 就追加到 job；
  - 完成后附带完整 analysis payload。
- `/api/job?id=` 返回当前阶段、规则、部分步骤和完成状态。
- 前端轮询 job：
  - 理解规则时显示“理解规则中”与骨架；
  - 求解时逐步追加步骤列表；
  - 完成后开始渲染，轮询 `/api/live/progress` 获取已生成帧数；
  - 盘面上方显示全局阶段进度，规则/步骤/盘面各自显示对应状态。
- 渲染失败时进度接口返回 `error.json` 内容，前端显示失败而不是一直等待。

### 7.7 One-pass filmstrip

- 打开题目一次，应用第 0 步到第 N 步的动作，只向前执行。
- 每步写 `<i>.png`；`-1.png` 是初始盘面。
- 浏览器从不回退；UI 只切换图片。
- 图片按预加载结果切换，旧帧保留到新帧就绪，避免播放闪烁。
- 帧 hash 版本（`frame-vNN`）变化时强制重建。

### 7.7 构建错误

- 构建错误写入目标帧目录的 `error.json`。
- 写帧中断会保留已完成帧；UI 会显示最后一帧。
- 构建必须完整跑完，UI 才能保证每步都有图。

## 8. Web 前端

### 8.1 技术栈

- Vite + React + Tailwind CSS
- shadcn 风格组件：Button、Card、Tabs、Popover、DropdownMenu、Switch、Slider、Textarea
- 图标：lucide-react；GitHub 使用官方 Octicon path
- 无服务端渲染；构建产物在 `web/dist`

### 8.2 布局

- 顶栏：品牌、Solve/Rules/History line tabs、地址/搜索框、Solve/Demo、GitHub Star、主题开关、设置。
- 主区：盘面 + 右侧 inspector（Explain / Candidates / Rules）+ 步骤列表 + 最近解出。
- 历史页：存储统计、搜索/排序/收藏、分层删除、存储设置。
- 浅色/深色使用中性 zinc 色板；深色盘面截图做轻微压暗，保证可读。

### 8.3 国际化

- 中文 / English。
- 默认跟随浏览器语言，可手动切换，localStorage 持久化。
- 后端 narration 为中文；英文模式使用事件摘要（Place / Eliminate）和英文规则名。

### 8.4 单候选显示

SudokuPad 会把“Centre 只剩一个候选”渲染成 digit 大小。前端不把它当作正式值；正式值只来自 solver 的 `place` 事件和截图中的 `cell-values`。

## 9. API

### GET

- `/api/store`：存储统计 + 历史条目
- `/api/live/frame?session&step`：读取一帧
- `/api/health`、`/api/live/health`
- `/api/rulesheet/<name>`

### POST

- `/api/solve`：解析链接，按需复用 P1/P2
- `/api/demo`：示例
- `/api/store/settings`：存储上限
- `/api/store/delete`：分层删除（级联）
- `/api/store/favorite`
- `/api/store/refresh_rules`：强制重新解析规则 + 重解 + 重渲染
- `/api/live/build`：生成帧 filmstrip
- `/api/live/start`、`/api/live/place`：调试/兼容接口

## 10. 失败处理

- 规则编译失败：回退启发式，并记录 warning。
- 求解卡住：返回 `stuck`，保留已走步骤。
- 规则冲突：返回 `invalid`。
- 截图构建失败：写 `error.json`，UI 显示最后一帧；不伪造截图。
- 当前帧缺失/缓存被删：下一次下一步提示“缓存已被删除”。

## 11. 测试

`tests/` 覆盖：

- SudokuPad 解码、LMD 链接、规则清单
- 标准题/变形题求解、混沌区域
- 沙漏、温度计、箭头、Kropki、XV、连续线、克隆、三明治、摩天楼
- 自定义谓词规则、全局线索回退、审计
- narration、规则图、历史、存储设置/清理

运行：

```bash
python3 -m unittest discover -s tests
cd web && npm run build
```

## 12. 已知限制与后续

- 英文步骤目前是事件摘要，不是逐句翻译的中文详细讲解。
- SudokuPad Centre 单候选的 digit 外观容易与正式值混淆；UI 只通过 solver 的 place 事件区分。
- 帧构建是串行截图，长题需要几十秒；失败恢复依赖 `error.json`。
- 规则理解仍可能受 LLM 波动影响，需要原始规则文本和用户补充来兜底。
- 尚未实现完整的多语言叙述后端；i18n 先覆盖 UI。

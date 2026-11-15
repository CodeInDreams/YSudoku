# YSudoku

**See why every digit is right.** / 每一个数字，都有理由。

[![CI](https://github.com/CodeInDreams/ysudoku/actions/workflows/ci.yml/badge.svg)](https://github.com/CodeInDreams/ysudoku/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

> 读音：**WHY-soo-doh-koo**（/ˌwaɪ suːˈdoʊkuː/），即 “why sudoku”。
> 中文可读作 **Y 数独**（“歪·数独”）。

YSudoku 把 [SudokuPad](https://sudokupad.app) 上的变形数独链接，变成**一步一步、可播放、可交互的推理动画**，而不是一个黑箱答案。

- 不是穷举：每一步都说明「根据什么规则、排除了什么、为什么」
- 可机械校验：可选穷举反证，对每一步结论做独立检查
- 可交互：网页里逐步播放高亮、描边、候选数划除、填数动画

## 快速开始

零第三方依赖，Python 3.10+：

```bash
git clone git@github.com:CodeInDreams/ysudoku.git
cd ysudoku
python3 -m ysudoku --web
# 打开 http://127.0.0.1:8765/
```

网页里点「示例」可以先看一道 92 步的完整动画；也可以直接粘贴 SudokuPad 链接。

命令行看文字推理：

```bash
python3 -m ysudoku 7v57yvn5vf
python3 -m ysudoku --allow-chains 7v57yvn5vf        # 卡住时允许反证（步骤标注 T4）
python3 -m ysudoku --audit --json https://sudokupad.app/eynwusqy5l > out.json
```

安装为命令（可选）：

```bash
pip install -e .
ysudoku --web
```

## 它怎么工作

```
链接 → api/puzzle → scl 压缩串 → 自定义 LZW + zipper 解码
     → 网格 / 笼 / 线 / 圆 / 点 / 箭头
     → 元素清单 + 官方 rules 文本
     → LLM 编译成 JSON 约束（用题面答案逐条校验，失败自动回传修正）
     → 约束传播 + 人类技巧 → 每一步：中文解释 + 动画脚本
```

SudokuPad 的 JSON 只保存“画了什么”，真正的规则在 `metadata.rules` 里。例如 kropki 黑点只是一块黑色圆形，`三分圆` 只是一个粗灰圆——所以必须有一层“图形 → 语义”的编译。YSudoku 用 LLM 做这层编译，并用题目自带答案做闭环校验；没有配置 key 时退回颜色/关键词启发式。

### LLM 配置（可选）

默认走 DeepSeek，也可以指向任何 OpenAI 兼容服务（OpenAI / Ollama / vLLM / OneAPI）：

```bash
export SUDOKU_LLM_API_KEY=sk-...
export SUDOKU_LLM_BASE_URL=https://api.deepseek.com   # 或 https://api.openai.com/v1
export SUDOKU_LLM_MODEL=deepseek-chat
```

本地 Ollama 示例（无需付费 key）：

```bash
ollama run qwen2.5:7b
export SUDOKU_LLM_BASE_URL=http://localhost:11434/v1
export SUDOKU_LLM_API_KEY=local
export SUDOKU_LLM_MODEL=qwen2.5:7b
```

没有 key 时网页会把「LLM 规则」置灰，并显示“未配置 key · 本地启发式”。

### 规则缓存

编译结果按「题目 id + 规则文本 + 元素清单」的指纹缓存，换机器/改题都会自动失效：

- `.cache/rules/<id>.json`：本地缓存，LLM 编译成功后自动写入（已 gitignore）
- `rules/<id>.json`：共享缓存，用 `--save-rules` 写入，可随仓库提交、供他人直接复用

```bash
python3 -m ysudoku --save-rules <sudokupad-url>   # 写入共享规则
python3 -m ysudoku --no-cache <sudokupad-url>     # 跳过缓存
```

健康检查：`GET /api/health` 返回 LLM 是否可用、模型名、缓存条目数。

### 卡住后的规则修复

如果规则 spec 编译成功、但求解器半路卡住，YSudoku 会把**诊断信息**（已尝试技巧、未使用的元素、警告）
回传给 LLM，让它重读规则文本并输出一份修正后的完整 spec；新 spec 仍须通过与官方答案的校验才会被采用。
这一步只做“重新理解规则”，不会把答案喂给模型，也不会凭空增加约束。

网页里勾选「允许反证」可以让求解器在卡住时尝试“假设—矛盾”式试探；这类步骤标注为 T4，
并明确提示不是纯直接推理。

关于“让 LLM 自创规则”的边界、类型化 DSL 与可信性护栏，见
[docs/rule-dsl.md](docs/rule-dsl.md)。

## 支持的约束（P1）

| 类别 | 约束 |
|---|---|
| 求和 | 杀手笼（组合 + 逐格匹配）、小杀手、45 法则（innie/outie） |
| 线 | 温度计、箭头（实验性）、回文、Renban、德式/荷式 Whisper、之间线、连续线 |
| 点/提示 | 黑白点（连续 / 1:2）、XV、四格提示（圆圈内数字，支持 `?`） |
| 全局 | 对角线、反骑士、反国王、锯齿区域、6×6 |
| 其他 | 奇偶、克隆、三明治、摩天楼、区域和线 |
| L2 自定义 | 类型化谓词（sum/count/ordered/all_different/…），LLM 可组合，标注「推测」|

技巧分层：T1 约束局部 → T2 唯一候选/隐性唯一/区块排除/数组/45 法则 →
T3 X-Wing / XY-Wing / W-Wing → T4 反证（默认关闭，`--allow-chains` 或网页勾选「允许反证」）。
每一步都带结构化理由与动画脚本；T4 步骤会明确标注“这是反证，不是直接推理”。

## 动画与交互

- 左侧棋盘：候选数、区域边界、约束描边（笼框、箭头线、鱼形连线）
- 右侧解释卡：结论、规则前提、逐步影响；可展开规则理解与步骤列表
- 控制：上一步 / 下一步 / 播放暂停 / 速度 / 进度条 / 键盘方向键
- 每步的 `visual` 字段是一份视觉脚本：`focus`、`groups`、`links`、`chips`，前端据此播放高亮、描线、划除与弹出

## 结构

```
ysudoku/
  decode.py      SudokuPad LZW + zipper 解码（已与官方实现逐字段比对）
  model.py       网格 / 区域 / 笼 / 线 / 圆 / 点 / 箭头
  sudokupad.py   链接解析、API 拉取、本地缓存
  rules.py       元素清单、LLM/启发式规则 spec、约束编译
  rulecache.py   规则缓存（本地 + 共享）
  llm.py         OpenAI 兼容客户端 + 规则编译 prompt
  state.py       候选域、事件日志、单位
  constraints.py 各类约束的传播 + 检查
  techniques.py  人类技巧（含 45 法则）
  solve.py       调度器、审计、答案校验
  search.py      仅作裁判：唯一性、逐步反证、卡住提示
  narrate.py     中文解释 + 动画脚本生成
  server.py      标准库 HTTP 服务
  static/        单页前端（原生 JS/CSS/SVG）
tests/           解码、引擎、纯数独、LLM mock/修复回归
fixtures/        示例题与原始数据
rules/           共享规则 spec（可提交）
docs/            规则 DSL 与可信性设计
```

## 已知限制（P1）

- **混沌构造**：首个版本是搜索求解，不是逐步人类推理；只支持无作者自定义区域语义的题
  （三分圆/不平衡圆等仍不支持）；9×9 默认 8 秒搜索预算
- **雾战 / 带草稿表的题**：暂不支持（网格数据本身不完整）
- 作者自定义画法依赖 LLM 编译；无 key 时启发式可能识别错
- 高难题仍可能卡住：求解器如实报告「卡住」而不是偷偷穷举；反证只能兜底一部分
- 箭头语义仍在验证，标为实验性
- 规则修复依赖 LLM；没有 key 时只有启发式 + 本地求解

## 测试

```bash
python3 -m unittest discover -s tests -v
```

CI 在每次 push 时跑同一套测试。

## 路线图

- **P2（基本完成）**：XY-Wing / W-Wing / 反证、三明治、摩天楼、区域和线、
  克隆、奇偶、6×6 已落地；剩 f-puzzles 导入
- **P2.5（已完成第一版）**：类型化规则 DSL —— LLM 用受控表达式组合出新约束（不写代码），
  所有“自创规则”标注来源、带「推测」徽章、可用官方答案做否证；详见 docs/rule-dsl.md
- **P3（部分完成）**：混沌构造搜索版已落地；下一步是把区域归属做成可解释的逐步推理，
  并支持作者自定义的区域计数规则

## 贡献

欢迎 PR：新增约束/技巧时请附一道可公开访问的 SudokuPad 链接作为回归用例，并确保
`python3 -m unittest discover -s tests` 通过。共享规则放在 `rules/`，格式见
[rules/README.md](rules/README.md)。

## License

MIT，见 [LICENSE](LICENSE)。

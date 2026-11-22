# YSudoku

中文 · [English](README.md)

[![CI](https://github.com/CodeInDreams/YSudoku/actions/workflows/ci.yml/badge.svg)](https://github.com/CodeInDreams/YSudoku/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

YSudoku 把 SudokuPad 变形数独变成可以逐步播放的解题讲解。每一步展示用到的规则、关联区域和候选变化。支持中英文界面和讲解。

## 快速体验

需要 Git、Python 3.10+ 和 Node.js（含 npm）。首次运行时安装依赖并构建网页。如果已经下载仓库，从仓库根目录执行最后两行。

```bash
git clone https://github.com/CodeInDreams/YSudoku.git
cd YSudoku
npm --prefix web ci && npm --prefix web run build
npm --prefix tools ci && (cd tools && npx playwright install chromium)
```

任选一种启动方式，然后打开 [http://127.0.0.1:8765/](http://127.0.0.1:8765/)，点击「示例」即可体验。

### 本地解析

```bash
SUDOKU_LLM_API_KEY= DEEPSEEK_API_KEY= OPENAI_API_KEY= python3 -m ysudoku --web
```

### 启用 LLM

将 `YOUR_DEEPSEEK_API_KEY` 换成自己的 DeepSeek API 密钥。

```bash
SUDOKU_LLM_API_KEY='YOUR_DEEPSEEK_API_KEY' python3 -m ysudoku --web
```

![桌面端解题界面。左侧播放 Route 66 的数独盘面，右侧展示步骤、候选和排除理由](docs/ysudoku-desktop-solve.png)

## 使用

1. 在 **解题** 页粘贴 SudokuPad 链接或题目 ID。也可以打开含 SudokuPad 链接的 Logic Masters 题目页，或点击 **示例**。
2. 提交后先显示原题盘面，再解析规则和求解。用播放按钮、滑条或步骤列表浏览，回到第 0 步即可查看原题。讲解、候选和规则三个面板分别展示推断理由、候选状态和适用规则。
3. 如需修正规则，到 **规则** 页补充题意并重新生成。播放器旁的反证步骤会展示假设、矛盾与回退后的实际结论。
4. **历史** 页可以重新打开共享缓存中的题目。切换语言或求解器版本后，可以保留旧讲解，或重新生成当前版本。缓存读取不消耗求解次数。

![桌面端规则界面，展示原题规则、识别出的约束和规则补充输入框](docs/ysudoku-desktop-rules.png)

## 支持的常见规则与推理

| 类型 | 示例 |
| --- | --- |
| 网格 | 标准行列宫、对角线、反马步、反国王、非连续 |
| 笼、点与箭头 | Killer 和笼、乘积约束、和箭头、Kropki、XV、四角数字、奇偶标记 |
| 线 | 温度计、Renban、德语和荷兰低语线、回文线、Between、克隆、区域和线 |
| 盘外 | Sandwich、Skyscraper、Little Killer、X-Sums（含定向斜线）、Full Rank |
| 复合规则 | 某一区域适用多条候选规则之一，或多个区域按用量分配规则。规则可以从重叠格组传递候选、组合和占位信息 |

支持程度取决于规则文本、图形和组合复杂度。规则能够解析的题目也可能卡在某一步。详见[核心算法与架构](docs/solver-guide.zh-CN.md)。

## 命令行

命令行也可直接解析题目 ID、本地 JSON，以及输出机器可读的讲解。

```bash
python3 -m ysudoku --no-llm --json fixtures/demo-killer.json
```

LLM 可选。设置 `SUDOKU_LLM_API_KEY`、`SUDOKU_LLM_BASE_URL` 和 `SUDOKU_LLM_MODEL` 可接入 OpenAI 兼容接口。发布配置、访问限制和日志见[部署指南](docs/deployment.zh-CN.md)。

### 命令行的可选功能

`--audit` 对适用题目的推断作独立校验。传入 SudokuPad 链接并使用 `--browser` 可让 Playwright 将已求出的答案逐格填入原题页面。

```bash
python3 -m ysudoku --audit --json fixtures/demo-killer.json
python3 -m ysudoku --browser https://sudokupad.app/6uhr6irwvd
```

## 开发

```bash
python3 -m unittest discover -s tests
node tests/native_annotations.mjs
npm --prefix web run build
```

## 特别鸣谢

感谢 [Logic Masters Deutschland e.V.（LMD）](https://logic-masters.de/Verein/index.php) 的谜题社区，以及 Sven Neumann 开发、Cracking The Cryptic 使用的 [Sven’s SudokuPad](https://sudokupad.app/)。

[维护要求](docs/REQUIREMENTS.zh-CN.md) · [规则 DSL](docs/rule-dsl.md) · [贡献指南](CONTRIBUTING.md) · [MIT 许可证](LICENSE)

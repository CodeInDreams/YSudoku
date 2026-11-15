# rules/ — 共享的规则编译结果

这里存放 **已校验** 的规则 spec，可以让没有 LLM key 的用户直接复用。

生成方式：

```bash
python3 -m ysudoku --save-rules https://sudokupad.app/<id>
```

文件名建议直接使用 SudokuPad 的题目 id，例如 `7v57yvn5vf.json`。

## 格式

```json
{
  "version": 1,
  "id": "7v57yvn5vf",
  "title": "Scattered",
  "fingerprint": "<sha1 of rules text + element inventory>",
  "model": "deepseek-chat",
  "created_at": "2026-11-15T23:30:00+0800",
  "spec": {
    "rules": [{"kind": "cage", "elements": ["cage:0", "cage:1"]}],
    "globals": [{"kind": "anti_knight"}],
    "notes": "optional"
  }
}
```

`fingerprint` 必须与当前题目的「规则文本 + 元素清单」一致，否则会被忽略并重新编译。
所以提交前请确认 spec 确实能让题目解出、且与题面自带答案一致。

## 支持的 kind

`cage` `thermo` `arrow` `kropki` `xv` `quadruple` `palindrome` `renban`
`german_whisper` `dutch_whisper` `between` `consecutive` `little_killer`

`globals`: `anti_knight` `anti_king` `diagonal`

参数：`kropki` 用 `variant: "white" | "black"`；`xv` / `little_killer` 用 `sum`。

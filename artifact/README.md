# Artifact 版 Demo

把 Prototype 做成單一 HTML 頁，發布在 claude.ai Artifact：https://claude.ai/artifact/G9jCfB6Jr1McZJgUK96YxF

- 左邊飼主手機、右邊醫院後台；狀態存在瀏覽器 localStorage，各觀看者互不影響。
- AI 走 Artifact 的 `sample` 能力，用觀看者自己的 Claude 帳號（capabilities：`{"sample": {"images": true}}`）。
- `guardrail.js`、`core.js` 是 `vetloop/guardrail.py` 與 `vetloop/flows.py` 純函式的 JS 移植。

## 組裝

```bash
node artifact/build.mjs artifact
```

產出 `artifact/vetloop-demo.html`（把兩支 JS 與 `vomit.b64` 示範照片塞進 `app.src.html`）。`mock.js` 是本機測試用的假 `window.claude`，不會進發布檔。

## 護欄對照測試

```bash
python3 artifact/parity/dump.py . > artifact/parity/fixture.json
node artifact/parity/compare.mjs artifact artifact/parity/fixture.json
```

`dump.py` 從 `tests/` 收集字串輸入，跑 Python 護欄產生 fixture；`compare.mjs` 用 JS 版逐項比對。

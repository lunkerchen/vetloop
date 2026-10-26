# Artifact 版 Demo

把 Prototype 做成單一 HTML 頁，發布在 claude.ai Artifact：https://claude.ai/artifact/G9jCfB6Jr1McZJgUK96YxF

- 左邊飼主手機、右邊醫院後台；狀態存在瀏覽器 localStorage，各觀看者互不影響。
- 不呼叫 AI。飼主和醫師可以點罐頭訊息，也可以自己輸入；原本由 AI 產生的欄位、照片描述、待確認事項與回覆草稿，都寫在 `app.js` 的 `SCRIPTS`。飼主自己輸入、又不是罐頭訊息的內容，轉給醫院人員回覆（原本 AI 失敗時的退路）。
- 照護計畫照醫囑原文逐項列出（原本 AI 失敗時的退路），護欄檢查照常執行。
- `guardrail.js`、`core.js` 是 `vetloop/guardrail.py` 與 `vetloop/flows.py` 純函式的 JS 移植；`app.js` 是畫面與流程。

## 組裝

```bash
node artifact/build.mjs artifact
```

產出 `artifact/vetloop-demo.html`（把三支 JS 與 `vomit.b64` 示範照片塞進 `app.src.html`）。

## 護欄對照測試

```bash
python3 artifact/parity/dump.py . > artifact/parity/fixture.json
node artifact/parity/compare.mjs artifact artifact/parity/fixture.json
```

`dump.py` 從 `tests/` 收集字串輸入，跑 Python 護欄產生 fixture；`compare.mjs` 用 JS 版逐項比對。

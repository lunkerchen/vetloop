# VetLoop Prototype 計畫

AIforPets 2027「獸醫照護」主題的可操作 Prototype。獸醫在環：AI 起草、獸醫核可、飼主照做。
全部使用模擬案例（虛構的「示範動物醫院」「王醫師」、貓「麻糬」、狗「豆豆」）。

## 任務

- [x] T0｜Opus 5.5（主控）｜PLAN.md、.gitignore、vetloop/static/demo/vomit.png｜計畫與規格寫定｜完成
- [x] T1｜implementer（Sonnet 5.5）｜requirements.txt、vetloop/__init__.py、vetloop/db.py、vetloop/llm.py、vetloop/guardrail.py、vetloop/flows.py、tests/test_flows.py｜見「T1 驗收」＋「R1 第 1、2 輪退回」＋「C1 退回（第 3 輪）」｜第 3 輪已修
- [x] T2｜implementer（Sonnet 5.5）｜vetloop/app.py、vetloop/templates/、vetloop/static/（demo/ 除外）、tests/test_app.py、README.md｜見「T2 驗收」＋「R1 第 1 輪退回」T2 項；T1 修完才開始｜第 1 輪已修
- [x] R1｜reviewer（Opus 5.5）｜唯讀｜逐條判定 T1、T2 驗收條件與「規定紅線」｜第 3 次複驗通過
- [x] C1｜gpt-6.1-sol（Codex，唯讀）｜唯讀｜大型改動的獨立驗收｜第 8 次通過（第 6 次缺口由 T3 補上，第 7 次 P1 主控已修）
- [x] T3｜implementer（Sonnet 5.5）｜vetloop/db.py、vetloop/flows.py、vetloop/guardrail.py、vetloop/app.py、vetloop/templates/、vetloop/static/（demo/ 除外）、tests/、README.md｜見「T3 照護中修改醫囑」｜完成
- [x] R2｜reviewer（Opus 5.5）｜唯讀｜逐條判定 T3 驗收與「規定紅線」｜通過（無必修；應修 1–3 由主控補，見「R2 後主控補充」）
- [x] T4｜Opus 5.5（主控）｜video/、README.md「介紹影片」、proposal/deck.html 第 08 頁第三方資源｜片長 ≤ 2:00、無旁白、實機錄影；字卡用簡報第 03 頁流程用字；畫面常駐「模擬案例」；片尾完整提示文字；字卡與入鏡 AI 產出無病名、疑似、診斷、劑量建議、品牌；配樂與字型揭露｜完成（reviewer 9 條中 8 條通過，必修「1.5× 加速未標示」已修；建議項的片尾停留、字卡時機、殘影已修。未做 GPT 驗收：交付物是影片，Codex 唯讀沙箱無法抽格。使用者決定後主控改 app：「系統紀錄」標題拿掉 LINE、緊急固定話術寄件人改「系統」（vetloop/flows.py、vetloop/templates/phone.html、tests/），已重錄並重新渲染）

## 共通規則

- Python 3.12、Flask 3.1、SQLite（標準函式庫 sqlite3）、Jinja、原生 JS/CSS。不加其他執行期套件；測試用標準函式庫 unittest（`python -m unittest`）。
- 虛擬環境放 `.venv/`。`.zshrc` 會 export `PYTHONPATH`，建 venv 與跑測試前先 `unset PYTHONPATH`。
- 所有外部呼叫（Claude CLI）都要有 timeout 和重試上限。
- 程式碼註解與畫面文字用繁體中文（台灣）；識別字用英文。
- 時區一律 Asia/Taipei（`zoneinfo`），時間存 ISO 8601 字串。
- 不 commit（由主控處理）。

## 規定紅線（AIforPets 注意事項，每條都要守）

1. 第 31 條：只用模擬資料。兩個畫面右上角常駐「模擬案例」標籤。
2. 第 33 條：AI 自己寫的內容不得出現病名、疑似／可能是、診斷、嚴重度分級、用藥或劑量建議。獸醫核可的醫囑原樣轉達，並標明來源（「這是王醫師的醫囑」）。
3. 第 34 條：不得出現或推薦任何飼料、產品、品牌（含 Royal Canin／皇家）。
4. 第 35 條：給飼主的照護計畫訊息一律附完整提示文字（`guardrail.DISCLAIMER`），提醒訊息附一行短提示（`guardrail.SHORT_NOTE`）。
5. 給飼主的健康相關內容（照護計畫、追蹤回覆）都要獸醫核可才送出。AI 只會自動送「追問問題」「整理確認」「緊急固定話術」「系統回條」這幾種。

```
DISCLAIMER = 本作品提供之資訊僅供輔助參考，不能取代獸醫師之診斷、治療或專業建議。貓犬之健康與營養需求可能因個體狀況而異，如有健康疑慮或需要調整飲食與照護方式，請諮詢合格獸醫師。
SHORT_NOTE = 提醒內容來自獸醫師醫囑，僅供照護參考；有疑慮請洽獸醫師。
```

## 規格

### 資料表（db.py）

```
cases(id INTEGER PRIMARY KEY, pet_name TEXT, species TEXT, owner_name TEXT,
      clinic_name TEXT, clinic_phone TEXT, vet_name TEXT,
      status TEXT,            -- intake | awaiting_confirm | submitted | ordered | in_care
      fields TEXT DEFAULT '{}',   -- 問診欄位 JSON
      photo_desc TEXT,            -- AI 照片事實描述
      summary TEXT,               -- 摘要卡 JSON
      order_json TEXT,            -- 醫囑 JSON
      created_at TEXT)
messages(id INTEGER PRIMARY KEY, case_id INTEGER REFERENCES cases(id),
         sender TEXT CHECK(sender IN ('owner','ai','vet','system')),
         text TEXT, image TEXT, actions TEXT DEFAULT '[]', created_at TEXT)
reminders(id INTEGER PRIMARY KEY, case_id INTEGER REFERENCES cases(id), kind TEXT,  -- med | recheck
          due_at TEXT, text TEXT, sent_at TEXT, acked_at TEXT)
drafts(id INTEGER PRIMARY KEY, case_id INTEGER REFERENCES cases(id),
       kind TEXT CHECK(kind IN ('plan','reply','handoff')),
       summary TEXT, body TEXT, flags TEXT DEFAULT '[]',
       status TEXT DEFAULT 'pending' CHECK(status IN ('pending','sent')),
       edited INTEGER DEFAULT 0, created_at TEXT, sent_at TEXT)
alerts(id INTEGER PRIMARY KEY, case_id INTEGER REFERENCES cases(id), text TEXT,
       created_at TEXT, seen INTEGER DEFAULT 0)
```

- `connect(path) -> sqlite3.Connection`：`row_factory=sqlite3.Row`、開 foreign keys、沒有表就建表。
- `reset_demo(conn)`：清空全部資料，建兩筆案例：
  - 1：麻糬，貓，林小姐，status=intake
  - 2：豆豆，狗，陳先生，status=intake
  - 兩筆都是 clinic_name「示範動物醫院」、clinic_phone「02-0000-0000」、vet_name「王醫師」。
- `messages.actions` 是快速回覆按鈕 JSON，例如 `[{"label":"正確，送出","action":"confirm"}]`、`[{"label":"已餵","action":"ack","reminder_id":3}]`。

### LLM（llm.py）

- `ask(system: str, user_text: str, schema: dict, image_path: str | None = None, timeout: float = 60) -> dict`，失敗丟 `LLMError`。
- 呼叫 Claude CLI，參數照下面（ai-cs-console 已在正式環境驗證過，CLI 2.1.310 可用）：
  `claude --print --safe-mode --tools "" --strict-mcp-config --mcp-config '{"mcpServers":{}}' --disable-slash-commands --no-session-persistence --no-chrome --permission-mode dontAsk --output-format stream-json --verbose --input-format stream-json --json-schema <schema> --model <model> --effort medium --system-prompt <system>`
- stdin 送一行 JSON：`{"type":"user","message":{"role":"user","content":[...]}}`。有圖就先放 `{"type":"image","source":{"type":"base64","media_type":<image/png 或 image/jpeg>,"data":...}}`，再放 `{"type":"text","text":user_text}`。
- 結果取 stdout 最後一個 `type == "result"` 事件的 `structured_output`；沒有就丟 `LLMError`。
- 子行程只帶 `HOME PATH USER LOGNAME LANG LC_ALL LC_CTYPE TMPDIR CLAUDE_CONFIG_DIR` 這些環境變數（macOS 要 USER/LOGNAME 才找得到登入）。
- `subprocess.run(..., timeout=timeout)`；失敗或逾時最多重試 1 次（共 2 次）。
- 模型：環境變數 `VETLOOP_MODEL`，預設 `claude-haiku-5-5`。

### 護欄（guardrail.py，純函式，不碰資料庫）

- `DISCLAIMER`、`SHORT_NOTE` 常數（原文見上）。
- `is_emergency(text) -> bool`：關鍵字比對，至少涵蓋：誤食、吞了／吞下／吞到、吃到（繩子、線、骨頭、塑膠、巧克力、葡萄、百合；「藥」見 R1 第 1、2 輪）、呼吸困難、喘不過氣、抽搐、昏倒、沒有意識、叫不醒、大量出血、流血不止、尿不出來、中毒、車禍、癱。
- `check_ai_text(text, allowed=()) -> list[str]`：回傳違規原因（空 list 代表通過）。先把 `allowed` 裡的字串（醫囑原文）從 text 移除再檢查。違規類型：
  - 診斷或推測：可能是、疑似、診斷、確診、罹患、病名常見字尾（炎、症、癌、腫瘤、衰竭、結石、感染；「症」不可誤擋「症狀」）
  - 分級：嚴重度、嚴重程度、輕症、重症、危險等級、分級
  - 用藥建議：劑量運算式（數字＋mg／ml／毫克／毫升／錠／顆／cc）、「建議（服用｜吃｜給）…藥」、止吐藥、抗生素、類固醇
  - 產品：飼料品牌、處方飼料、Royal Canin、皇家、推薦…（飼料｜罐頭｜產品｜品牌）
- `check_plan(text, order) -> list[str]`：每個醫囑藥名都要出現在 text；text 裡的劑量運算式都要在醫囑原文裡；再跑 `check_ai_text(text, allowed=醫囑所有字串)`。

### 流程（flows.py）

模組層級 `llm_call = llm.ask`，測試直接替換成假的。所有函式第一個參數是 `conn`，寫入後 `conn.commit()`。

問診欄位（key → 中文）：`chief 狀況、onset 開始時間、frequency 次數、appetite 食慾、energy 精神、diet_change 飲食變化、excretion 排泄、medication 用藥、history 病史`。`history` 選填（有提到才記，不主動問），其他必填。追問分組照順序：`[onset, frequency]`、`[appetite, energy, diet_change]`、`[excretion, medication]`；每次只問第一個還有缺欄位的那一組裡缺的欄位。

- `owner_message(conn, case_id, text, image_path=None)`：
  1. 存飼主訊息。
  2. `is_emergency(text)` 為真：送固定話術「這個狀況需要盡快處理，請立即致電{clinic_name}：{clinic_phone}。我已經通知醫院櫃台。」，建 alert「{pet_name}（{owner_name}）：{text}」，結束。不呼叫 LLM。任何 status 都先做這一步。
  3. 有圖：`llm_call` 描述照片（只寫看得到的顏色、形狀、數量、位置，不推測原因），結果過 `check_ai_text`，通過才存 `photo_desc`。
  4. status 是 intake 或 awaiting_confirm：`llm_call` 抽欄位，回傳 `{"fields": {key: str|null}, "reply": str, "confidence": number}`，`reply` 是針對 ask_keys 的追問（第一次回覆開頭可加「收到，我幫您整理給醫院。」）。合併欄位（新值蓋舊值，null 不蓋）。
     - 必填欄位齊了：status=awaiting_confirm，送確認訊息（固定格式，不經 LLM）：「我整理如下，請確認：」加每個欄位一行、照片描述一行，按鈕「正確，送出」(confirm)、「需要修改」(edit)。
     - 還沒齊：`reply` 過 `check_ai_text` 且 confidence ≥ 0.5 才送；否則改送該組的固定問句（見下）。
     - LLM 失敗或 confidence < 0.5 且抽不到任何欄位：建 `handoff` 草稿，送系統訊息「我請醫院人員回覆您，請稍候。」。
  5. status 是 in_care：送系統回條「收到，我會整理給{vet_name}，醫師確認後回覆您。」，再 `llm_call` 產生 `{"change_summary": str, "reply": str, "confidence": number}`，輸入包含照護計畫、最近提醒的回報（已餵幾次／共送出幾次）和這則訊息。建 `reply` 草稿（summary=change_summary、body=reply、flags=check_ai_text 結果、confidence < 0.5 也加一個 flag）。LLM 失敗就建 `handoff` 草稿。**不自動送出。**
  6. status 是 submitted 或 ordered：送系統回條「收到，已轉給醫院。」並建 `handoff` 草稿。
- 固定問句：onset「從什麼時候開始的？」、frequency「一天大概幾次？」、appetite＋energy「食慾和精神跟平常比起來有變化嗎？」、diet_change「最近有換飼料或零食嗎？」、excretion「排便排尿正常嗎？」、medication「目前有在吃任何藥嗎？」（同組缺幾個就串幾句）。
- `owner_action(conn, case_id, action, reminder_id=None)`：
  - `confirm`（只在 awaiting_confirm）：status=submitted；`llm_call` 產生摘要 `{"timeline": str, "owner_quotes": [str], "open_questions": [str]}`（open_questions 是飼主沒講清楚、需要醫院確認的資訊，不是可能病因）；任何項目沒過 `check_ai_text` 就丟掉那一項，timeline 沒過就改用欄位組出的固定句。存 `summary`（另含 fields 與 photo_desc）。LLM 失敗也照固定句存。送系統訊息「已送到{clinic_name}，醫師看診時會參考這份資料。狀況變嚴重請直接來電：{clinic_phone}。」
  - `edit`：送「請直接告訴我要修改哪裡。」，status 不變。
  - `ack`：該提醒 `acked_at` 記現在時間，送系統訊息「已記錄，謝謝您。」。
  - `problem`：送「請直接描述狀況，我會轉給醫師。」。
- `save_order(conn, case_id, order)`：status 要是 submitted 或 ordered。驗證 order（不合法丟 `ValueError`）：
  ```
  {"meds": [{"name": str, "times_per_day": 1|2|3, "timing": str, "days": 1..60}],  # 至少 1 筆
   "diet": {"text": str, "days": 0..60}, "recheck_days": 0..60, "watch": str, "note": str}
  ```
  字串長度上限 200。存 `order_json`，status=ordered，`llm_call` 產生 `{"steps": [str]}`（白話每日步驟；藥名、次數、天數照醫囑，不得新增任何藥或劑量）。建 `plan` 草稿：body=步驟每行前加「・」、flags=`check_plan` 結果。LLM 失敗就用醫囑組出固定步驟、flags 加「AI 產生失敗，已改用醫囑原文」。同一案例重存醫囑時，舊的 pending plan 草稿刪掉。
- `approve_draft(conn, draft_id, final_text)`：只處理 pending；`final_text` 不可空白；`edited = final_text.strip() != body.strip()`；status=sent。
  - plan：送獸醫訊息「這是{vet_name}的醫囑\n\n{final_text}\n\n{DISCLAIMER}」，依醫囑建提醒，案例 status=in_care。
  - reply／handoff：送獸醫訊息「{final_text}\n（{vet_name}已確認）\n{SHORT_NOTE}」。
- 提醒排程（不經 LLM）：`times_per_day` 1→08:00；2→08:00、20:00；3→08:00、14:00、20:00。從核可時間之後的下一個時段開始，共 `times_per_day × days` 則。文字「該餵{pet_name}吃藥了：{name}，{timing}（{vet_name}醫囑）\n{SHORT_NOTE}」，按鈕「已餵」(ack)、「有問題」(problem)。`recheck_days > 0` 另建一則回診提醒，時間是核可日加 `recheck_days - 1` 天的 10:00，文字「明天是{pet_name}的回診日（{vet_name}醫囑），我會在當天早上再提醒您。」。
- `tick(conn, now=None) -> int`：把 `due_at <= now` 且沒送過的提醒送出（存成 ai 訊息、帶按鈕、記 sent_at），回傳送出數。
- `fast_forward(conn, case_id) -> bool`：Demo 用，馬上送出該案例下一則還沒送的提醒。

### 測試（tests/test_flows.py，用假的 llm_call，不碰網路）

用暫存資料庫、`reset_demo`，假 LLM 依 schema 回固定 JSON。

## T1 驗收

1. `unset PYTHONPATH; .venv/bin/python -m unittest -v` 全部通過，且至少包含以下測試：
   - 緊急字眼（「牠剛剛好像吞了一段繩子」）：送出固定話術、建 alert、`llm_call` 沒被呼叫。
   - 照素材 A 跑完三輪追問：每輪只問該組缺的欄位；第三輪後 status=awaiting_confirm、確認訊息含「正確，送出」按鈕。
   - AI 追問被 `check_ai_text` 擋（例如假 LLM 回「可能是腸胃炎」）時，改送固定問句，且送出的文字不含「可能是」。
   - confirm 之後 status=submitted、summary 有 timeline／open_questions；含「疑似」的 open_question 被丟掉。
   - `save_order` 不合法（times_per_day=5、meds 空）丟 `ValueError`。
   - 照護計畫：plan 草稿 pending、尚未有任何訊息送給飼主；核可後飼主訊息含「這是王醫師的醫囑」與完整 `DISCLAIMER`；`times_per_day=2, days=5` 建 10 則用藥提醒＋1 則回診提醒。
   - `check_plan`：醫囑沒有的劑量（「每次 5mg」）會被標出；漏掉藥名會被標出。
   - in_care 時飼主訊息只建 reply 草稿，不會自動送出 AI 回覆；`approve_draft` 改過字時 edited=1，送出文字含「（王醫師已確認）」。
   - `tick` 只送到期的提醒；`ack` 記下 acked_at。
   - `llm.ask` 逾時會重試一次後丟 `LLMError`（用不存在的或會睡的假執行檔測，不呼叫真的 Claude）。
2. 規定紅線 2–5 在 flows 裡都有對應程式碼路徑。
3. 不新增執行期依賴（requirements.txt 只有 Flask）。

### 網頁（T2）

- `vetloop/app.py`：`create_app(db_path=None, start_ticker=True)`，資料庫預設 `instance/vetloop.db`，空資料庫就 `reset_demo`。`start_ticker` 為真時開一個 daemon thread 每 30 秒呼叫 `flows.tick`（每次自己開連線）。`python -m vetloop.app` 起在 127.0.0.1:5050。
- 路由：
  - `GET /`：三個連結（麻糬的手機、豆豆的手機、醫院後台）。
  - `GET /phone/<id>`：仿 LINE 的手機畫面（不用 LINE 的商標），置中的手機框：頂端「示範動物醫院」，飼主泡泡在右、AI／醫院／系統泡泡在左（醫院訊息標「王醫師」），快速回覆按鈕、附加照片、輸入框，送出後顯示「輸入中…」。手機右側「問診欄位」面板：每個必填欄位一格，有值就打勾並顯示值；照片描述標「AI 輸出」。每 1.5 秒輪詢 `/api/case/<id>`。
  - `GET /api/case/<id>`：JSON（案例、欄位、訊息、提醒）。
  - `POST /api/case/<id>/message`：multipart（text、image）。圖片只收 png／jpg／jpeg、5 MB 以下，存 `instance/uploads/<uuid>.<ext>`；text 與 image 都空就 400。
  - `POST /api/case/<id>/action`：JSON `{action, reminder_id}`。
  - `GET /uploads/<name>`：讀上傳的圖（防路徑穿越）。
  - `GET /clinic`：案例列表（狀態中文）、緊急通知面板（輪詢 `/api/alerts`，新通知要明顯）、待審數量、「重設示範資料」按鈕。
  - `GET /clinic/case/<id>`：摘要卡（時間軸、各欄位、飼主原話、照片＋AI 描述、待確認事項；不放任何病名欄位）、完整對話、醫囑表單（用藥可多筆：藥名、每日次數下拉 1–3、時機、天數；飲食、飲食天數、回診天數、觀察重點、補充；補充欄位有麥克風按鈕，用瀏覽器 Web Speech API zh-TW 口述，不支援就隱藏）、照護計畫左右對照（左：醫囑原文，右：可編輯的計畫草稿、護欄 flags 醒目顯示、「核可並送出」）、提醒列表＋「快轉到下一個提醒」。
  - `POST /clinic/case/<id>/order`、`POST /clinic/draft/<id>/approve`、`POST /clinic/case/<id>/fast-forward`、`POST /clinic/reset`。
  - `GET /clinic/queue`：待審佇列（reply 與 handoff）：案例、變化摘要、可編輯的 AI 回覆、flags、「核可並送出」。
- 兩個畫面右上角常駐「模擬案例」標籤；所有對飼主顯示的照護計畫都看得到完整提示文字。
- 配色：白底、紅色點綴（#D7263D），手機頂端可用綠色。字型 Noto Sans TC、系統字型備援。寬度 1920×1080 錄影時版面要好看，手機寬也不破版。
- `ValueError` 回 400 並顯示訊息；找不到案例 404。只綁 127.0.0.1（本機示範，沒有登入機制，README 要寫明）。

## T2 驗收

1. `unset PYTHONPATH; .venv/bin/python -m unittest -v` 全部通過（含 T1 測試），`tests/test_app.py` 用 Flask test client＋假 `llm_call`，至少涵蓋：
   - 照 Demo 腳本跑完整流程：飼主三輪對話＋照片 → confirm → 醫院摘要卡頁面 200 且含欄位值 → 送醫囑 → 計畫頁含護欄區塊 → 核可 → 飼主 API 看得到含 `DISCLAIMER` 的訊息 → fast-forward 送出提醒 → ack → 飼主回報 → 佇列頁看得到草稿 → 核可送出。
   - 緊急字眼後 `/api/alerts` 有通知。
   - 上傳 .exe 或超過 5 MB 回 400；`/uploads/../PLAN.md` 不能讀到檔案。
2. `python -m vetloop.app` 能啟動，`/`、`/phone/1`、`/clinic` 回 200。
3. README.md：用途、模擬案例聲明、需求（Python 3.12、已登入的 Claude CLI）、安裝與啟動指令、照 Demo 腳本的操作順序、提示文字。

## R1 第 1 輪退回（主控已裁決）

規格補充：**飼主看得到的欄位值也算 AI 輸出**（欄位值是 AI 對飼主原話的轉述）。飼主自己講的品牌、病名、藥名，醫院端照原樣保留，飼主端改顯示中性字樣。

### T1 項（guardrail.py、flows.py、tests/test_flows.py）

1. [必修] 新增 `flows.owner_value(value) -> str`：`check_ai_text(value)` 通過就回原值，否則回「已記錄，醫院會再向您確認」。`_confirm_text` 每個欄位值和照片描述都改用它。`_merge` 照舊保留原值（醫院摘要卡看原值，不重問）。只檢查值，不檢查「病史」等標籤。
2. [必修] `check_plan` 劑量比對：醫囑原文也用同一個劑量運算式抽出劑量，正規化（去空白、全形轉半形、單位小寫）後逐一完全比對，不用子字串。要有測試：醫囑 2.5mg／計畫 5mg、醫囑 15mg／計畫 5mg、醫囑 12 錠／計畫 2 錠都要被標出；醫囑 5mg／計畫 5 mg 不標。
3. [必修] `check_ai_text` 病名規則補：「病」（排除 病史、病歷、生病、看病、病情）、瘟、潰瘍、阻塞；推測句型「應該是／或許是／大概是／看起來像」後面 8 字內接病名字尾才算；照護建議：禁食、益生菌、胃藥、不嚴重、沒什麼大礙。測試：「這看起來像糖尿病」「腎病」「心臟病」「可能有貓瘟」「像是胃潰瘍」「應該是腸阻塞」都要擋；「看起來像是黃色液體」「病史：無」「生病了」不擋。
4. [應修] `is_emergency` 補：吞食；吃下／偷吃＋（繩子、線、骨頭、塑膠、巧克力、葡萄、百合）；「藥」只在「偷吃」後算緊急（主控修正：「吃下藥又吐了」是正常回報）；尿不出（不必接「來」）；吐血、抽筋、癲癇、痙攣、休克、一直流血、張口呼吸。
5. [低] `approve_draft`、`_confirm`、送提醒的 UPDATE 都加狀態條件（`AND status='pending'`、`AND status='awaiting_confirm'`、`AND sent_at IS NULL`），rowcount 不是 1 就不做後續動作（草稿丟 ValueError；提醒略過）。
6. [低] `ack`／`problem` 只接受已送出（`sent_at IS NOT NULL`）的提醒。
7. [低] 回診提醒文字改成「明天是{pet_name}的回診日（{vet_name}醫囑）。」＋換行＋`SHORT_NOTE`（拿掉「當天早上再提醒」的承諾）。
8. [低] 新照片描述沒過護欄時，`photo_desc` 設成 NULL，不保留舊描述。

### T2 項（app.py、templates、static、tests/test_app.py、README.md）

1. [必修] 飼主端（`/api/case/<id>` 給手機面板的欄位值、照片描述）改用 `flows.owner_value`；醫院端頁面照原值。測試：假 LLM 抽出 `diet_change="從皇家換成希爾斯 i/d"`，手機 API 看不到「皇家」，醫院案例頁看得到。
2. [低] 待審佇列的「飼主最近說」改成：該草稿 `created_at` 之前（含）最後一則飼主訊息，排除 `flows.ACTION_LABELS` 的按鈕文字。
3. [低] 所有 POST 路由：有 `Sec-Fetch-Site` 標頭且值不是 `same-origin` 或 `none` 時回 403（擋跨站送出）。測試：帶 `Sec-Fetch-Site: cross-site` 核可草稿回 403、草稿不變。
4. [低] README 第 41 行附近改成：「附上示範照片」會把示範照片放進附件，再按送出。

## R1 第 2 輪退回（主控已裁決）

由 T1 implementer 處理；這一輪 T1 可改範圍另外包含 `vetloop/app.py` 呼叫 `owner_value` 的那兩行（T2 這輪沒有工作，不會同時改）。

1. [必修] 品牌與商品名（主控裁決，不採用「diet_change／medication 一律中性」：那會讓 Demo 的確認訊息看不到「上週換了新零食」，飼主無法核對）：
   - 抽欄位的 prompt 加規則：fields 不寫任何品牌、商品名或藥品商品名，一律寫成類別（例如「換成某牌處方飼料」→「換了新飼料」、「在吃某某藥」→「有在吃藥」）。細節醫院可在完整對話裡看到。
   - `owner_value(value, key=None)`：除了原本的 `check_ai_text`，當 key 是 `diet_change` 或 `medication` 且值含英文字母時，也回中性字樣。`_confirm_text` 和 `app.py` 兩處呼叫都帶 key。
   - 測試：「換成希爾斯 i/d」「Hill's 腸胃處方」「有在吃 Vetmedin」在飼主端都是中性字樣；「上週換了新零食」「沒有吃藥」原樣。
   - 已知殘留：純中文的品牌名（例如「渴望」）若 LLM 沒照規則改寫，仍可能出現在飼主端。README 的限制段落要寫明。
2. [必修] `_DOSE` 支援分數：`1/4 顆`、`1 / 2 錠`、`四分之一顆`。測試：醫囑 1/4 顆／計畫 4 顆、醫囑 1/2 錠／計畫 2 錠、醫囑四分之一顆／計畫一顆都要標出；醫囑 1/4 顆／計畫 1/4顆 不標。
3. [必修] 緊急字眼補毒物：
   - 單獨出現即緊急：老鼠藥、殺蟲劑、除草劑、農藥。
   - （吃到｜吃了｜吃下｜舔）＋6 字內＋（我的藥、人的藥、人吃的、普拿疼、感冒藥、止痛藥、安眠藥）。
   - （舔｜咬｜吃）＋6 字內＋百合。
   - 「吃下藥又吐了」「今天有吃到藥」「吃到一點藥」仍不算緊急。
4. [應修] 「病」不擋：前面是 生／看／過（「生過病」），以及 毛病、病況。病名字尾補：中暑、寄生蟲、過敏。
5. [應修] `check_plan`：照護建議類字眼（禁食、益生菌、胃藥）若出現在醫囑原文，就不標出。
6. [低] `problem` 也必須帶已送出的 reminder_id。

## C1 退回（第 3 輪，3 輪上限的最後一輪；主控已裁決）

gpt-6.1-sol 指出黑名單擋不完 AI 自由文字（例：AI 追問「這是癲癇，屬於高風險，請把今天的藥加倍」完全沒被擋）。主控裁決改架構：**AI 不再自動送出任何自由文字給飼主**。

這一輪由 T1 implementer 處理，可改範圍擴大到：vetloop/flows.py、guardrail.py、db.py、app.py、templates/phone.html、tests/test_flows.py、tests/test_app.py、README.md。T2 沒有同時進行的工作。

1. [P1] 追問改用固定模板：
   - 抽欄位的 LLM 只回 `fields` 和 `confidence`；拿掉 `reply`，schema 和 prompt 同步改。
   - 追問一律用固定問句（現有 `_question`）。
   - 第一次回覆開頭固定加「收到，我幫您整理給醫院。想先確認：」。
   - 自動送給飼主的訊息只剩這幾種：固定問句、確認訊息、緊急話術、系統回條，全部是模板。
2. [P1] 欄位值要能在飼主原話裡找到：
   - 抽欄位的 prompt 改成：欄位值只能從飼主原話中擷取片段，不改寫、不換詞。例如 chief 從「麻糬這兩天一直吐」擷取「一直吐」。
   - 新增 `guardrail.grounded(value, owner_text) -> bool`：比對前正規化（NFKC、去空白與標點），value 是 owner_text 的子字串，或 value 有 80% 以上的雙字組出現在 owner_text，就算找得到。
   - `owner_value(value, owner_text)` 回中性字樣的條件（任一成立）：沒過 `check_ai_text`、含英文字母（所有欄位都算）、`grounded` 不成立。
   - `owner_text` 是該案例所有飼主訊息串起來，排除按鈕文字。新增 `flows.owner_text(conn, case_id)`；`_confirm_text` 和 app.py 都改用新簽名。
   - 醫院端照舊顯示原值。
3. [P1] 照片描述不進飼主聊天室：確認訊息的照片那一行改成「照片：已收到 1 張，醫師會直接看照片」，不放 AI 描述。手機右側面板標題改成「系統紀錄（示意，飼主在 LINE 上看不到）」；面板上的照片描述仍要過 `check_ai_text` 和英文字母檢查（不做 grounded 檢查），沒過就顯示中性字樣。
4. [P1] 草稿 id 不可重複使用：`drafts.id` 改成 `INTEGER PRIMARY KEY AUTOINCREMENT`。測試：重存醫囑後，用舊草稿 id 核可要失敗；新草稿核可後，提醒的藥名與次數要和最新醫囑一致。
5. [P1] AI 回來時案例狀態已經變了：`_intake` 寫回時加條件，案例 status 仍是呼叫 LLM 前的值、而且 fields 還是呼叫前的 JSON 才更新；rowcount 是 0 就不送問句，改建 handoff 草稿。照片描述寫回也加 status 條件。測試：在假 LLM 裡把案例推進到 in_care，回來後 status 仍是 in_care、沒有新的確認按鈕訊息。
6. [P2] tests/test_app.py 的跨執行緒測試：要收集工作執行緒的例外並讓測試失敗，`join` 之後要確認執行緒已結束；再加一個並行 POST 的情境。
7. [應修] `check_ai_text` 補：高風險、低風險、風險等級（嚴重度類）；加倍、減半、停藥、加量、減量（用藥建議類）；癲癇（病名類）。這些只用來在草稿上標 flags。
8. 要用素材 A 證明 Demo 沒有壞：四則飼主訊息照常跑完三輪固定追問，確認訊息的欄位值都是飼主原話片段，不是中性字樣（假 LLM 照新 prompt 回原話片段）。

## C1 第 2 次未通過（超過 3 輪上限，由主控直接修）

gpt-6.1-sol 複驗第 3 輪：前一次的 5 個反例都修好了，但重現 3 項 P1。implementer 已用完 3 輪，這一輪由主控修。

1. [P1] `grounded()` 的雙字組比例會放行拼接出來的用藥指示（例：「今天的藥改成每天三次」）；子字串比對會拿掉「我沒有說」這類否定。
   - 修法：拿掉雙字組比例與子字串比對。欄位值必須和飼主原話中完整的一句（以標點或換行分隔）一字不差，不能半句、不能合併多句。抽欄位 prompt 同步改成「照抄完整的一句」。
   - 用藥欄位另外收緊：只有「沒有吃藥」這類否定說法才回顯給飼主，其餘一律中性字樣（用藥內容只給獸醫看）。
   - 摘要的固定 timeline 改成用標籤串欄位值，不另外接字。
2. [P1] 手機 API 會回傳未經核可的 AI 照片描述；先把「顆」換成「個」再檢查，會讓「每天給2顆藥」變成放行。
   - 修法：`/api/case/<id>` 不再回傳 `photo_desc`，只回照片收件狀態；照片描述只留在醫院端。拿掉量詞替換，照原文檢查（量詞改由 prompt 要求）。
3. [P1] 並行重存醫囑會留下過期草稿，核可後計畫和提醒對不上，也能重複建提醒。
   - 修法：`drafts.order_json` 記錄產生草稿的那一版醫囑。LLM 回來後在 `BEGIN IMMEDIATE` 裡確認案例醫囑仍是這一版才建草稿，否則作廢並回錯誤。核可時在同一個交易內用 `status='ordered' AND order_json=草稿版本` 條件式推進到 in_care（同時消耗這個案例的計畫，第二份計畫無法再核可），提醒照草稿那一版建立。
   - 測試：`OrderVersionTest`（照 gpt-6.1-sol 的 A/B 時序重現、過期草稿不能核可、同案例第二份計畫不能核可）。

## C1 第 3 次未通過（主控直接修）

前一次的 3 個反例都已擋下，另外重現 2 項 P1。

1. [P1] 「完整一句」比對仍可繞過：否定或引用用引號、冒號、換行隔開，後半句本身就是完整一句；用藥內容可以放進「病史」欄位避開用藥限制；`_squash` 去掉標點後，「不！可以」會等於「不可以」。
   - 主控裁決改架構，不再補規則：**飼主端不回顯任何 AI 挑出來的值**。確認訊息只列「已記錄：狀況、開始時間…」和「照片：已收到 N 張」；`/api/case/<id>` 的欄位值一律是「已記錄」或 null。
   - 刪掉 `guardrail.grounded`、`_squash`、`_CLAUSE_END`、`flows.owner_value`、`owner_text`、`_NO_MED`、`NEUTRAL_VALUE`。醫院端照原值顯示。
   - 測試：`ConfirmNoEchoTest`（gpt-6.1-sol 的引號、冒號、換行三種反例，品牌、標點變體，確認訊息不含任何欄位值）、`test_phone_never_shows_field_values_but_clinic_keeps_original`。
2. [P1] Demo 重設後提醒 id 重用：背景 `tick()` 拿著舊資料，會送出舊藥甲，卻把新藥乙標成已送出。
   - 修法：`reminders`、`alerts` 改成 `AUTOINCREMENT`，重設後 id 不重用。`_send_reminder` 用 `UPDATE … RETURNING` 取得這次更新到的那一列，送出的文字和案例都用這一列，不用舊資料。
   - 測試：`OrderVersionTest.test_stale_reminder_snapshot_after_demo_reset_is_skipped`、`test_sent_text_comes_from_the_current_row`。

## C1 第 4 次未通過（主控直接修）

前一次的 2 項 P1 都確認修好，也沒有發現未核可的 AI 文字流到飼主端。這次的問題都來自 Demo 重設後 id 重用。

1. [P1] `messages.id` 重設後重用，手機只用訊息 id 判斷要不要重畫，漏掉中間的輪詢就會一直顯示上一輪的醫囑。
   - 修法：`messages` 改成 `AUTOINCREMENT`。醫院案例頁的 `sig` 加上案例世代。
   - 測試：`ResetTest.test_reset_gives_new_message_ids_and_a_new_sig`、`ResetRaceTest.test_message_ids_are_not_reused_after_reset`。
2. [P2] 重設時還在等 AI 的請求，回來後會把舊欄位、舊摘要或回條寫進新一輪的案例（案例 id 固定是 1、2）。
   - 修法：`cases.gen` 記錄世代，每次 `reset_demo` 換一個新的隨機值。`_ask(conn, case, …)` 在 LLM 回來後先拿寫入鎖再比對世代，不同就丟 `StaleCase`（ValueError 子類別，網頁回 400），什麼都不寫；相同就拿著鎖回去，呼叫端寫完才 commit。`save_order` 拿掉 LLM 之後多餘的 `_begin`，檢查到寫入之間不放鎖。
   - 測試：`ResetRaceTest`（問診、照片、LLM 失敗、確認摘要、照護中回覆、照護計畫六條路徑，都在假 LLM 裡用另一條連線重設）。

## C1 第 5 次未通過（主控直接修）

前幾次的反例都通過回歸。新的 P1：獸醫在計畫裡改了用藥文字（例：停甲改乙、每日兩次改一次）後核可，提醒仍照原本的結構化醫囑建立，飼主會收到互相矛盾的用藥內容。

- 修法：計畫的用藥行由 `_med_steps(order)` 照醫囑原文產生，和提醒用同一份資料；AI 只改寫飲食、回診、觀察重點、補充（`_other_steps` 是 AI 失敗時的退路），送給 AI 的醫囑不含用藥。AI 改寫的部分提到「藥」或醫囑藥名，就整段改用醫囑原文並標 flag。醫囑只有用藥時不叫 AI。
- 計畫文字不能直接改：`approve_draft` 對 plan 草稿要求核可文字和草稿原文相同（前後空白不算），否則丟 ValueError；後台的計畫 textarea 改成唯讀，提示「要修改請改左邊的醫囑，重新產生」。追蹤回覆草稿仍可改字。
- 測試：`ApproveTest.test_plan_text_cannot_be_edited`、`ErrorAndPageTest.test_edited_plan_is_rejected_and_nothing_reaches_the_owner`、`OrderTest.test_ai_lines_that_mention_meds_fall_back_to_order_text`、`test_no_ai_call_when_order_has_only_meds`。

## C1 第 6 次未通過（使用者選做法 1，見 T3）

前 5 次的反例全部通過回歸，也確認沒有未經核可的 AI 文字到飼主端。剩下的 P1 是流程缺口：照護期間獸醫在追蹤回覆裡寫「停藥」或「改成每天一次」並核可，既有提醒仍照舊醫囑送出（`tick` 與快轉都會）。

可選做法：
1. 照護中可「修改醫囑」：重開醫囑表單，產生新計畫草稿；核可時在同一交易內刪掉舊版未送出的提醒、依新版建立提醒。追蹤回覆核可前另外擋下停藥、改次數這類字眼，提示改用「修改醫囑」。
2. 不加流程，在 README 已知限制寫明：照護中改藥要重設案例重開醫囑。
3. 追蹤回覆只要提到用藥就不能核可（會擋到 Demo 的「請依計畫持續用藥」）。


## T3 照護中修改醫囑（使用者選做法 1）

目標：照護中獸醫可以修改醫囑；核可新計畫時，舊版還沒送出的提醒取消、照新版重新排程。追蹤回覆不能用來改藥。

### 資料表
- `cases` 加 `revision_json TEXT`：照護中修改、還沒核可的新版醫囑。`order_json` 一律是「現行」醫囑（提醒和 `_in_care` 用它）。舊的 `instance/vetloop.db` 不會自動升級，README 寫明要刪掉重建。

### save_order
- 狀態 `submitted`／`ordered`：行為不變。
- 狀態 `in_care`：`UPDATE cases SET revision_json = ? WHERE id = ? AND status = 'in_care'`。`order_json`、提醒、飼主訊息都不動，核可前照舊醫囑提醒。
- rowcount 不是 1 的錯誤訊息改成「案例還沒送到醫院，或狀態剛改變，請重新整理後再試」。
- 等完 AI 的版本檢查：`status = 'ordered' AND order_json = 這一版`，或 `status = 'in_care' AND revision_json = 這一版`，其他一律 rollback 並丟 ValueError。世代檢查（`StaleCase`）照舊。
- 草稿摘要：照護中改成「依新版醫囑整理的每日照護步驟」。

### approve_draft（plan）
- `_begin` 之後在同一個交易裡重讀案例狀態，不靠 `_begin` 前讀到的值。
- `ordered`：行為不變。
- `in_care`：`UPDATE cases SET order_json = revision_json, revision_json = NULL WHERE id = ? AND status = 'in_care' AND revision_json = ?`（草稿的 order_json）；rowcount 不是 1 就 rollback 並丟 ValueError「醫囑已經更新，請重新整理」。同一個交易裡：
  - `DELETE FROM reminders WHERE case_id = ? AND sent_at IS NULL`。已送出的提醒保留，它們的「已餵／有問題」照常可按。提醒 id 是 AUTOINCREMENT，背景排程拿著舊資料也送不出被刪掉的提醒（`_send_reminder` rowcount 0）。
  - 給飼主的訊息開頭：「這是{vet}更新後的醫囑。之前排好、還沒送出的提醒已取消，之後照這份醫囑提醒您。」後面接 `\n\n{計畫本文}\n\n{DISCLAIMER}`。
  - 照新版醫囑 `_schedule_reminders`（從 now 開始）；刪掉其他 pending 的 plan 草稿。
- `_plan_text` 改取最新一則醫囑訊息（`ORDER BY id DESC`），`_in_care` 才會拿到現行計畫。其他假設「只有一則醫囑訊息」的地方也要一起改。

### 追蹤回覆擋下改藥字眼
- `guardrail.med_change(text) -> list[str]`（純函式），回傳命中的片段。至少涵蓋：
  - 停藥：停藥、停止給藥、停掉藥、暫停給藥、不用再吃藥、先別餵藥、不必給藥
  - 次數：次數、改成每天一次、改為一天 3 次、一天改兩次、每天改成
  - 劑量：加量、減量、加倍、減半、劑量、藥量、多給、少給、增加／減少（幾個字內接 次 或 藥）
  - 換藥：換藥、改吃藥物 B、改給、改用（幾個字內接 藥）
  - 不可誤擋（要有測試）：素材 E 回覆「謝謝您的回報。麻糬今天沒有再吐，請繼續照王醫師的醫囑給藥和餵食。如果食量沒有慢慢恢復，或又開始吐，請直接來電。」、「請依計畫持續用藥」、「藥都有按時吃，很好」、「請不要自行停藥」「請勿擅自停藥」（前面是 自行／擅自 的不算）。
  - 是 regex 經驗法則，用 `ponytail:` 註解寫明上限。
- `approve_draft` 的 reply／handoff：`med_change(final)` 有命中就丟 ValueError，訊息含命中片段與「提醒是照醫囑排的，要改請到案例頁「修改醫囑」，核可新計畫後提醒會跟著換」。在 `_begin` 前檢查，什麼都不寫，草稿維持 pending。
- `_in_care` 建草稿時，AI 回覆有命中就加 flag「回覆草稿提到改藥：…，這樣送不出去，請改用「修改醫囑」」。

### 醫院後台
- 案例頁狀態 `in_care`：顯示現行醫囑（`order_view`），下面放 `<details>`「修改醫囑」，內含同一份醫囑表單，預填 `revision_json`（有待核可的新版時）或現行醫囑；有待核可新版時預設展開。送出鈕「產生新的照護計畫」；提示加「核可後，還沒送出的提醒會取消，改照新醫囑重新排程；已送出的提醒不受影響。」
- `submitted`／`ordered` 的表單不變。計畫區塊照舊顯示最新一份 plan 草稿與核可鈕。
- 狀態標籤：`in_care` 且有 `revision_json` 時，案例列表與案例頁都顯示「照護中・新醫囑待核可」。
- 待審佇列核可回覆被擋時，錯誤就地顯示（沿用現有 JS），文字要看得懂該去哪裡改。
- 飼主端 API 不可帶出 `revision_json`。

## T3 驗收
1. `unset PYTHONPATH; .venv/bin/python -m unittest` 全過，既有測試的斷言不可改弱；改了哪些既有斷言要逐條列出理由。
2. 測試至少涵蓋：
   - 照護中存新醫囑：`revision_json` 有值，`order_json`、提醒、飼主訊息都沒變；此時飼主回報仍走 `_in_care`、用現行醫囑。
   - 核可新版：`order_json` 換新、`revision_json` 清空；舊版未送出的提醒刪掉、已送出的保留且可 ack；新提醒數量等於新版的次數 × 天數（加回診）；飼主訊息含「更新後的醫囑」和完整 DISCLAIMER；`_plan_text` 回傳新計畫。
   - 版本：連存兩版，第一版的草稿不能核可；等 AI 期間又存了新版，舊請求丟 ValueError、不建草稿；核可時案例狀態或 revision 被改掉就 rollback，什麼都不寫。
   - 背景排程拿著核可前讀到的舊提醒列，核可後送不出去。
   - `med_change` 正反例（上面列的全部）；核可含「停藥」「改成每天一次」的回覆丟 ValueError、草稿仍 pending、沒有新訊息；`_in_care` 的 flag。
   - app：照護中案例頁有「修改醫囑」表單；走 Flask 路由完成「存新醫囑 → 核可 → 提醒換新」；佇列核可含停藥的回覆回 400 且訊息含「修改醫囑」；跨站 POST 仍回 403；完整 Demo 流程測試照過。
3. 破壞測試：拿掉「刪除未送出提醒」「核可時的 revision 版本條件」「核可回覆前的 med_change 檢查」，各自至少有一個測試失敗。
4. README：已知限制拿掉「照護中改藥要重設案例」；Demo 操作順序補一段選用的「照護中修改醫囑」；寫明舊資料庫要刪掉重建。
5. 只動 T3 範圍內的檔案；PLAN.md 只改 T3 那一行的狀態欄。不 commit。

### 主控補充（implementer 完成後）
- `med_change` 的「次數」單獨出現會誤擋「請記錄嘔吐次數」，收窄成「給藥／餵藥／用藥／吃藥／服藥（的）次數」與「次數改／調整／增加／減少」。
- 改醫囑前建的回覆草稿可能寫「請繼續給舊藥」，`med_change` 擋不到：核可新版時對待審的 reply／handoff 加 flag「這份回覆是醫囑更新前寫的，請照現行醫囑確認內容」；核可回覆時在交易內比對，文字含「以前核可過、現行醫囑已經沒有」的藥名（`_norm` 後比對）就 rollback 並丟 ValueError。測試 `ReviseOrderTest.test_reply_written_before_the_revision_cannot_send_the_retired_medicine`，破壞測試已確認會失敗。

### R2 後主控補充
- `med_change(text, med_names)`：比對前把案例出現過的藥名（現行、待核可新版、以前核可過）換成「藥」，「停掉示範藥A」「不要再給示範藥A」才擋得到；停藥規則加「停止用藥」。勸阻豁免（自行／擅自）擴到所有改藥字眼；「多給／少給」要接藥或劑量單位才算。
- 核可回覆時在交易內擋兩種藥名：以前核可過、現行已經沒有的（舊藥），以及待核可新版才有的（新藥，訊息「新版還沒核可」）。比對前先拿掉現行藥名，「示範藥A加強錠」不算提到「示範藥A」。
- 核可新版時，待審的 reply／handoff 草稿作廢，換成新 id 的 handoff（body 空白、flag `STALE_FLAG`、沿用 created_at），舊頁面拿舊 id 核可會 LookupError。取代原本「加註」的做法。
- `_in_care`：`_ask` 回來（拿著寫入鎖）時重讀 `order_json`，和起草前不同就改建 `STALE_FLAG` 的 handoff。
- 沒有提醒可取消時，更新醫囑訊息不寫「提醒已取消」。表單提示補「回診天數從核可當天起算」。
- 不改：回診日從核可當天重算（規格決定）；快轉與核可交錯時回 400；`_in_care` 給 AI 的提醒計數混算新舊藥（只影響 AI 起草參考）；案例頁 sig 不含待核可新版（sig 也在飼主 API，加進去會洩漏有新版）。
- 測試 169 個全過；新檢查各自做破壞測試都會失敗。

## C1 第 7 次未通過（主控直接修）

P1：`_off_order_meds` 先移除現行藥名再找舊藥／待核可新藥，現行短名「示範藥A」會遮掉較長的「示範藥A加強錠」，回覆提到長名的舊藥或未核可新藥會被放行。
修法：現行、以前核可過、待核可新版的藥名合併，由長到短辨識，認到就從文字拿掉，再看命中的名稱屬於哪一類。測試 `test_old_or_pending_medicine_containing_the_current_name_is_refused`、`test_pending_medicine_containing_the_current_name_is_refused`（兩個方向都有，拒絕後草稿 pending、沒有訊息）；改回短名先認有 3 個測試失敗。171 個測試全過。

## C1 第 8 次通過

第 6、7 次反例都修好，沒有打穿紅線的問題。gpt-6.1-sol 在唯讀沙箱用記憶體資料庫跑了 155 項既有測試，另加 9 組交錯情境；主控本機 171 項全過。

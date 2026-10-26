// 畫面與流程，對照 vetloop/flows.py。不呼叫 AI：飼主和醫院可以點罐頭訊息，也可以自己輸入；
// 原本由 AI 產生的欄位、照片描述、待確認事項與回覆草稿，都預先寫在 SCRIPTS 裡。
// 自己輸入、又不是罐頭訊息的內容沒有預先寫好的整理，走原本 AI 失敗時的退路：轉給醫院人員。
(() => {
  "use strict";
  const G = window.VG, C = window.VC;
  const { DISCLAIMER, SHORT_NOTE } = G;
  const { FIELD_LABELS, REQUIRED, UserError } = C;
  const DEMO_PHOTO = "data:image/jpeg;base64,__DEMO_PHOTO__";

  const STATUS_LABELS = { intake: "問診中", awaiting_confirm: "等飼主確認", submitted: "已送出，待開醫囑", ordered: "照護計畫待核可", in_care: "照護中" };
  const KIND_LABELS = { med: "用藥提醒", recheck: "回診提醒" };
  const REVISING_LABEL = "照護中・新醫囑待核可";
  const RECORDED = "已記錄"; // 手機面板只說有沒有記錄，不顯示欄位值
  const CONFIRM_ACTIONS = [{ label: "正確，送出", action: "confirm" }, { label: "需要修改", action: "edit" }];
  // 按鈕的字，飼主按下後照 LINE 的樣子顯示成飼主自己的訊息
  const ACTION_LABELS = { confirm: "正確，送出", edit: "需要修改", ack: "已餵", problem: "有問題" };
  const FIRST_REPLY = "收到，我幫您整理給醫院。想先確認：";
  // 醫囑換了之後，照舊醫囑寫的回覆草稿作廢，改成這個 flag 的 handoff
  const STALE_FLAG = "醫囑已更新：原本照舊醫囑寫的回覆已作廢，請照現行醫囑撰寫";
  const TICK_MS = 30000;
  const NEW_MED = { name: "", times_per_day: 2, timing: "", days: 5 };
  const DEMO_ORDER = { meds: [{ name: "示範藥A", times_per_day: 2, timing: "飯後", days: 5 }],
    diet: { text: "當天少量多餐", days: 2 }, recheck_days: 3, watch: "若持續嘔吐請來電", note: "" };

  // ---- 罐頭訊息 ----
  // intake 每則附上欄位（照抄飼主原句）；care 每則附上變化摘要與回覆草稿（醫師核可後才送出）。都已過護欄檢查。
  // 醫囑是醫師現場填的，回覆草稿只能說「照醫囑」，不寫具體的飲食、用藥或回診內容。
  const EMERGENCY = { text: "牠剛剛突然抽搐，叫牠都沒反應", hint: "示範：緊急狀況", urgent: true };
  const SCRIPTS = {
    1: {
      intake: [
        { text: "麻糬這兩天一直吐", fields: { chief: "麻糬這兩天一直吐" } },
        { text: "前天晚上開始，一天三四次", fields: { onset: "前天晚上開始", frequency: "一天三四次" } },
        { text: "不太吃東西，精神還好", fields: { appetite: "不太吃東西", energy: "精神還好" } },
        { text: "沒有換飼料，大便正常，沒有吃藥", fields: { diet_change: "沒有換飼料", excretion: "大便正常", medication: "沒有吃藥" } },
      ],
      fix: { text: "更正一下，是一天五六次", fields: { frequency: "是一天五六次" } },
      photo: "一灘黃色液體，裡面有幾塊沒消化的飼料",
      openQuestions: ["吐出來的東西裡有沒有毛球或異物？", "最後一次吃東西是什麼時候？"],
      waiting: { text: "請問看診前需要先禁食嗎？" },
      care: [
        { text: "今天早上又吐了一次", summary: "飼主回報照護期間早上又吐了一次",
          reply: "謝謝您告訴我。請照醫囑繼續照顧，留意今天還有沒有再吐；有疑慮請直接來電。" },
        { text: "藥餵不太進去，牠一直吐出來", summary: "飼主回報餵藥困難，藥會被吐出來",
          reply: "謝謝您告訴我。餵藥有困難請直接來電，我們一起看看怎麼處理比較好。" },
        { text: "今天精神好很多，有吃一點東西", summary: "飼主回報精神變好，開始進食",
          reply: "很高興聽到牠有吃東西。請照醫囑繼續餵藥和觀察，有疑慮請隨時來電。" },
      ],
    },
    2: {
      intake: [
        { text: "豆豆從昨天開始拉肚子", fields: { chief: "豆豆從昨天開始拉肚子", onset: "豆豆從昨天開始拉肚子" } },
        { text: "一天大概五次，都是水水的", fields: { frequency: "一天大概五次", excretion: "都是水水的" } },
        { text: "食慾正常，精神也還好", fields: { appetite: "食慾正常", energy: "精神也還好" } },
        { text: "前天換了新的飼料，沒有吃藥", fields: { diet_change: "前天換了新的飼料", medication: "沒有吃藥" } },
      ],
      fix: { text: "更正一下，是一天七八次", fields: { frequency: "是一天七八次" } },
      photo: null, // 示範照片是嘔吐物，只給麻糬用
      openQuestions: ["換飼料之前吃的是哪一種？", "糞便裡有沒有血絲或黏液？"],
      waiting: { text: "請問要帶糞便過去嗎？" },
      care: [
        { text: "今天還是拉了兩次，不過比較成形了", summary: "飼主回報還是拉了兩次，糞便比較成形",
          reply: "謝謝您回報。請照醫囑繼續觀察，飲食先照醫囑的方式；有疑慮請直接來電。" },
        { text: "可以換回原本的飼料嗎？", summary: "飼主詢問能否換回原本的飼料",
          reply: "謝謝您詢問。飲食請先照醫囑，回診時我們再一起確認；有疑慮請直接來電。" },
      ],
    },
  };
  const VET_REPLIES = ["收到，我看一下狀況，稍後回覆您。", "請在方便的時間帶牠來院，我們再檢查一次。", "可以的，請照醫囑繼續，有疑慮請直接來電。"];

  // ---- 狀態：整份存在這個瀏覽器（localStorage）----
  const KEY = "vetloop-demo:v2";
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); return true; } catch { return false; } },
  };

  function fresh(prev) {
    // id 不重複使用（對應原本的 AUTOINCREMENT）：重設後舊頁面拿著舊 id 不會動到新資料
    const seq = prev?.seq ?? { msg: 0, draft: 0, rem: 0, alert: 0 };
    return {
      v: 2, seq, messages: [], reminders: [], drafts: [], alerts: [],
      cases: [[1, "麻糬", "貓", "林小姐"], [2, "豆豆", "狗", "陳先生"]].map(([id, pet, species, owner]) => ({
        id, pet_name: pet, species, owner_name: owner, clinic_name: "示範動物醫院", clinic_phone: "02-0000-0000",
        vet_name: "王醫師", status: "intake", fields: {}, photo_desc: null, summary: null,
        order_json: null, revision_json: null, created_at: Date.now(),
      })),
    };
  }
  function load() {
    try {
      const s = JSON.parse(store.get(KEY));
      if (s && s.v === 2 && Array.isArray(s.cases) && s.cases.length === 2) return s;
    } catch { /* 壞掉的資料就重建 */ }
    return null;
  }
  let S = load() || fresh(null);
  let storageOk = true;
  function save() {
    if (!store.set(KEY, JSON.stringify(S))) storageOk = false;
  }
  function commit() { save(); render(); }

  // ---- 小工具 ----
  const getCase = (id) => {
    const c = S.cases.find((x) => x.id === id);
    if (!c) throw new UserError(`找不到案例 ${id}`);
    return c;
  };
  function say(caseId, sender, text, { image = null, actions = [], at = Date.now() } = {}) {
    S.messages.push({ id: ++S.seq.msg, case_id: caseId, sender, text, image, actions, created_at: at });
  }
  function addDraft(caseId, kind, summary, body, flags, orderJson = null) {
    S.drafts.push({ id: ++S.seq.draft, case_id: caseId, kind, summary, body, flags, status: "pending", edited: 0,
      created_at: Date.now(), sent_at: null, order_json: orderJson });
  }
  function handoff(caseId, text, flag = "沒有預先寫好的回覆，請人員撰寫") {
    addDraft(caseId, "handoff", `需要人員回覆。飼主說：${text || "（傳了一張照片）"}`, "", [flag]);
  }
  const byDue = (a, b) => a.due_at - b.due_at || a.id - b.id;
  const caseMessages = (id) => S.messages.filter((m) => m.case_id === id);
  const pendingCount = () => S.drafts.filter((d) => d.status === "pending" && d.kind !== "plan").length;
  const clinicStatusLabel = (c) => (c.status === "in_care" && c.revision_json ? REVISING_LABEL : STATUS_LABELS[c.status] || c.status);
  const photoOf = (m) => (m.image ? DEMO_PHOTO : null);

  // ---- 問診 ----
  function confirmText(caseId, fields) {
    const lines = ["我整理如下，請確認：", "已記錄：" + Object.keys(FIELD_LABELS).filter((k) => fields[k]).map((k) => FIELD_LABELS[k]).join("、")];
    const n = caseMessages(caseId).filter((m) => m.sender === "owner" && m.image).length;
    if (n) lines.push(`照片：已收到 ${n} 張`);
    lines.push("醫師會看到您傳的完整原話與照片。");
    return lines.join("\n");
  }
  const ownerTexts = (caseId) => caseMessages(caseId)
    .filter((m) => m.sender === "owner" && m.text !== "" && !Object.values(ACTION_LABELS).includes(m.text)).map((m) => m.text);

  /** 自己輸入的字如果剛好是某則罐頭訊息，就照那則處理；否則只有文字。 */
  function itemFor(caseId, text) {
    const sc = SCRIPTS[caseId];
    return [...sc.intake, sc.fix, sc.waiting, ...sc.care, EMERGENCY].find((it) => it.text === text) || { text };
  }

  /** 飼主傳一則訊息（item 來自 SCRIPTS、EMERGENCY 或 itemFor）。 */
  function ownerMessage(caseId, item) {
    const c = getCase(caseId), text = item.text || "";
    say(caseId, "owner", text, { image: item.photo ? "demo" : null });
    if (G.isEmergency(text)) { // 任何狀態都先擋這一關
      say(caseId, "ai", `這個狀況需要盡快處理，請立即致電${c.clinic_name}：${c.clinic_phone}。我已經通知醫院櫃台。`);
      S.alerts.push({ id: ++S.seq.alert, case_id: caseId, text: `${c.pet_name}（${c.owner_name}）：${text}`, created_at: Date.now(), seen: 0 });
      return;
    }
    if (item.photo) c.photo_desc = SCRIPTS[caseId].photo;
    if (c.status === "intake" || c.status === "awaiting_confirm") intake(c, item);
    else if (c.status === "in_care") inCare(c, item);
    else { // submitted / ordered：醫師還在處理，轉給人員
      say(caseId, "system", "收到，已轉給醫院。");
      handoff(caseId, text);
    }
  }

  function intake(c, item) {
    if (!item.fields && !item.photo) { // 自己輸入的字沒有預先整理好的欄位
      say(c.id, "system", "我請醫院人員回覆您，請稍候。");
      return handoff(c.id, item.text);
    }
    const hasReplied = caseMessages(c.id).some((m) => m.sender === "ai");
    C.merge(c.fields, item.fields || {});
    if (!C.missing(c.fields).length) {
      c.status = "awaiting_confirm";
      say(c.id, "ai", confirmText(c.id, c.fields), { actions: CONFIRM_ACTIONS });
    } else { // 追問一律用固定問句
      const q = C.question(c.fields, c.pet_name);
      say(c.id, "ai", hasReplied ? q : FIRST_REPLY + q);
    }
  }

  /** 照護中飼主回報：只建草稿給獸醫審，不自動回覆。 */
  function inCare(c, item) {
    say(c.id, "system", `收到，我會整理給${c.vet_name}，醫師確認後回覆您。`);
    if (!item.reply) return handoff(c.id, item.text);
    const flags = G.checkAiText(item.reply).map((r) => `回覆草稿：${r}`)
      .concat(G.checkAiText(item.summary).map((r) => `變化摘要：${r}`));
    const changes = G.medChange(item.reply, [...medNamesEver(c.id)]);
    if (changes.length) flags.push(`回覆草稿提到改藥：${changes.join("、")}，這樣送不出去，請改用「修改醫囑」`);
    addDraft(c.id, "reply", item.summary, item.reply, flags);
  }

  // ---- 飼主按鈕 ----
  function ownerAction(caseId, action, reminderId) {
    const c = getCase(caseId);
    if (!(action in ACTION_LABELS)) throw new UserError(`未知的操作：${action}`);
    if ((action === "confirm" || action === "edit") && c.status !== "awaiting_confirm") throw new UserError("目前沒有待確認的整理");
    if (action === "confirm") return confirm(c);
    const reminder = S.reminders.find((r) => r.id === reminderId && r.case_id === caseId && r.sent_at);
    if (action === "ack" || action === "problem") {
      if (!reminder) throw new UserError("找不到這則提醒");
      if (reminder.acked_at) throw new UserError("這則提醒已經回報過了");
    }
    say(caseId, "owner", ACTION_LABELS[action]);
    if (action === "edit") say(caseId, "system", "請直接告訴我要修改哪裡。");
    else if (action === "problem") say(caseId, "system", "請直接描述狀況，我會轉給醫師。");
    else {
      reminder.acked_at = reminder.acked_at ?? Date.now();
      say(caseId, "system", "已記錄，謝謝您。");
    }
  }

  function confirm(c) {
    c.status = "submitted";
    say(c.id, "owner", ACTION_LABELS.confirm);
    const fields = { ...c.fields }, get = (k) => fields[k] || "未提供";
    // 經過紀錄用欄位組固定句（原本 AI 失敗時的退路），飼主原話照抄
    c.summary = {
      timeline: `開始時間：${get("onset")}；狀況：${get("chief")}；次數：${get("frequency")}。食慾：${get("appetite")}；精神：${get("energy")}。`,
      owner_quotes: ownerTexts(c.id).slice(0, 3), open_questions: SCRIPTS[c.id].openQuestions, fields, photo_desc: c.photo_desc,
    };
    say(c.id, "system", `已送到${c.clinic_name}，醫師看診時會參考這份資料。狀況變嚴重請直接來電：${c.clinic_phone}。`);
  }

  // ---- 醫囑與照護計畫 ----
  const medNames = (orderJson) => new Set(orderJson ? JSON.parse(orderJson).meds.map((m) => m.name) : []);
  function approvedMedNames(caseId) {
    const out = new Set();
    for (const d of S.drafts) if (d.case_id === caseId && d.kind === "plan" && d.status === "sent") for (const n of medNames(d.order_json)) out.add(n);
    return out;
  }
  /** 這個案例出現過的所有藥名（現行、待核可新版、以前核可過的），給 medChange 用。 */
  function medNamesEver(caseId) {
    const c = getCase(caseId);
    return new Set([...medNames(c.order_json), ...medNames(c.revision_json), ...approvedMedNames(caseId)]);
  }
  /** 回覆提到、但不在現行醫囑裡的藥名：[以前核可過的舊藥, 待核可新版的新藥]。藥名由長到短認，短名不會從長名裡比對出來。 */
  function offOrderMeds(caseId, text) {
    const c = getCase(caseId);
    const current = medNames(c.order_json);
    const retired = [...approvedMedNames(caseId)].filter((n) => !current.has(n));
    const pending = [...medNames(c.revision_json)].filter((n) => !current.has(n));
    let t = G.norm(text);
    const found = new Set();
    const all = [...new Set([...current, ...retired, ...pending])].sort((a, b) => G.cpLen(G.norm(b)) - G.cpLen(G.norm(a)));
    for (const name of all) {
      const key = G.norm(name);
      if (key && t.includes(key)) { found.add(name); t = t.split(key).join("\0"); }
    }
    return [retired.filter((n) => found.has(n)).sort(), pending.filter((n) => found.has(n)).sort()];
  }

  /** 存醫囑、產生計畫草稿（不送給飼主）。照護中改醫囑時新版先放在 revision_json，核可新計畫時才換上去。 */
  function saveOrder(caseId, raw) {
    const c = getCase(caseId);
    const order = C.validateOrder(raw);
    const orderText = JSON.stringify(order);
    const revising = c.status === "in_care";
    if (c.status === "submitted" || c.status === "ordered") { c.order_json = orderText; c.status = "ordered"; }
    else if (revising) c.revision_json = orderText;
    else throw new UserError("案例還沒送到醫院，或狀態剛改變，請重新整理後再試");
    S.drafts = S.drafts.filter((d) => !(d.case_id === caseId && d.kind === "plan" && d.status === "pending"));
    // 每一行都照醫囑原文（和提醒同一份資料），不經改寫
    const body = C.medSteps(order).concat(C.otherSteps(order)).map((s) => `・${s}`).join("\n");
    addDraft(caseId, "plan", revising ? "依新版醫囑整理的每日照護步驟" : "依醫囑整理的每日照護步驟", body, G.checkPlan(body, order), orderText);
  }

  function scheduleReminders(c, order, at) {
    const pet = c.pet_name, vet = c.vet_name, rows = [];
    for (const m of order.meds) {
      const text = `該餵${pet}吃藥了：${m.name}${m.timing ? `，${m.timing}` : ""}（${vet}醫囑）\n${SHORT_NOTE}`;
      for (const t of C.reminderTimes(m.times_per_day, m.days, at)) rows.push(["med", t, text]);
    }
    if (order.recheck_days > 0) { // 回診前一天早上 10:00 提醒
      const t = C.taipei(at);
      rows.push(["recheck", C.taipeiAt(t.y, t.mo, t.d + order.recheck_days - 1, 10), `明天是${pet}的回診日（${vet}醫囑）。\n${SHORT_NOTE}`]);
    }
    for (const [kind, due, text] of rows) S.reminders.push({ id: ++S.seq.rem, case_id: c.id, kind, due_at: due, text, sent_at: null, acked_at: null });
  }

  /** 獸醫核可：把選定的文字送給飼主。所有檢查都先做完才寫入（對應原本交易裡的 rollback）。 */
  function approveDraft(draftId, finalText, at = Date.now()) {
    const d = S.drafts.find((x) => x.id === draftId);
    if (!d) throw new UserError(`找不到草稿 ${draftId}`);
    if (d.status !== "pending") throw new UserError("這份草稿已經送出");
    const fin = (finalText || "").trim();
    if (!fin) throw new UserError("內容不可空白");
    const c = getCase(d.case_id), vet = c.vet_name, body = (d.body || "").trim();
    if (d.kind === "plan" && !d.order_json) throw new UserError("這份計畫沒有對應的醫囑");
    // 計畫和提醒都從同一份醫囑產生；改了計畫文字，提醒就會和飼主看到的計畫對不上
    if (d.kind === "plan" && fin !== body) throw new UserError("照護計畫不能直接改字；用藥、飲食或回診要修改，請改醫囑重新產生計畫");
    // 追蹤回覆不能用來改藥：提醒是照醫囑排的
    if (d.kind !== "plan") {
      const changes = G.medChange(fin, [...medNamesEver(c.id)]);
      if (changes.length) throw new UserError(`回覆提到改藥（${changes.join("、")}）。提醒是照醫囑排的，要改請到案例頁「修改醫囑」，核可新計畫後提醒會跟著換`);
    }
    const revising = d.kind === "plan" && c.status === "in_care";
    if (d.kind === "plan") {
      const ok = revising ? c.revision_json === d.order_json : c.status === "ordered" && c.order_json === d.order_json;
      if (!ok) throw new UserError(revising ? "醫囑已經更新，請重新整理" : "醫囑已經更新，或這個案例的計畫已經核可，請重新整理");
    } else {
      const [retired, pending] = offOrderMeds(c.id, fin);
      if (retired.length) throw new UserError(`回覆提到現行醫囑已經沒有的藥（${retired.join("、")}），醫囑已更新，請照現行醫囑改寫`);
      if (pending.length) throw new UserError(`回覆提到新版醫囑的藥（${pending.join("、")}），新版還沒核可；請先到案例頁核可新的照護計畫，提醒才會跟著換`);
    }
    d.status = "sent";
    d.edited = fin !== body ? 1 : 0;
    d.sent_at = at;
    if (d.kind === "plan") {
      if (revising) { c.order_json = c.revision_json; c.revision_json = null; } else c.status = "in_care";
      S.drafts = S.drafts.filter((x) => !(x.case_id === c.id && x.kind === "plan" && x.status === "pending"));
      let head = `這是${vet}的醫囑`;
      if (revising) {
        // 舊版還沒送出的提醒取消；已送出的留著，「已餵／有問題」照常可按
        const before = S.reminders.length;
        S.reminders = S.reminders.filter((r) => !(r.case_id === c.id && !r.sent_at));
        const cancelled = before - S.reminders.length;
        // 待審的回覆是照舊醫囑寫的：換成新 id 的 handoff 請人員照現行醫囑重寫（created_at 沿用）
        const stale = S.drafts.filter((x) => x.case_id === c.id && (x.kind === "reply" || x.kind === "handoff") && x.status === "pending");
        S.drafts = S.drafts.filter((x) => !stale.includes(x));
        for (const r of stale) {
          S.drafts.push({ id: ++S.seq.draft, case_id: c.id, kind: "handoff", summary: r.summary, body: "", flags: [STALE_FLAG],
            status: "pending", edited: 0, created_at: r.created_at, sent_at: null, order_json: null });
        }
        head = `這是${vet}更新後的醫囑。` + (cancelled ? "之前排好、還沒送出的提醒已取消，" : "") + "之後照這份醫囑提醒您。";
      }
      say(c.id, "vet", `${head}\n\n${fin}\n\n${DISCLAIMER}`, { at });
      scheduleReminders(c, JSON.parse(d.order_json), at);
    } else {
      say(c.id, "vet", `${fin}\n（${vet}已確認）\n${SHORT_NOTE}`, { at });
    }
  }

  // ---- 提醒 ----
  function sendReminder(r, at) {
    if (r.sent_at || !S.reminders.includes(r)) return false;
    r.sent_at = at;
    const actions = r.kind === "med"
      ? [{ label: "已餵", action: "ack", reminder_id: r.id }, { label: "有問題", action: "problem", reminder_id: r.id }] : [];
    say(r.case_id, "ai", r.text, { actions, at });
    return true;
  }
  function tick(at = Date.now()) {
    let sent = 0;
    for (const r of S.reminders.filter((x) => !x.sent_at && x.due_at <= at).sort(byDue)) sent += sendReminder(r, at);
    if (sent) commit();
  }
  /** Demo 用：馬上送出該案例下一則還沒送的提醒。 */
  function fastForward(caseId) {
    const next = S.reminders.filter((r) => r.case_id === caseId && !r.sent_at).sort(byDue)[0];
    if (!next) throw new UserError("沒有尚未送出的提醒");
    sendReminder(next, Date.now());
  }

  /** 飼主目前可以挑的罐頭訊息：照狀態給，已傳過的不再出現；緊急狀況一直都在。 */
  function cannedFor(c) {
    const sc = SCRIPTS[c.id], msgs = caseMessages(c.id);
    const sent = new Set(msgs.filter((m) => m.sender === "owner").map((m) => m.text));
    const unsent = (it) => !sent.has(it.text);
    let items;
    if (c.status === "intake" || c.status === "awaiting_confirm") {
      items = sc.intake.filter(unsent);
      if (sc.photo && !msgs.some((m) => m.image)) items.push({ text: "", label: "傳一張照片", hint: "示範照片", photo: true });
      if (c.status === "awaiting_confirm" && unsent(sc.fix)) items.push(sc.fix);
    } else if (c.status === "in_care") items = sc.care.filter(unsent);
    else items = [sc.waiting].filter(unsent);
    return items.concat(EMERGENCY);
  }

  // ================= 畫面 =================
  const $ = (sel, root = document) => root.querySelector(sel);
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  };
  // 後台用字串模板組 HTML：插進去的值一律跳脫，只有 h`` 本身產生的片段原樣放入
  const RAW = Symbol("raw");
  const esc = (s) => String(s).replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);
  const val = (v) => (v == null || v === false || v === true ? "" : Array.isArray(v) ? v.map(val).join("") : v[RAW] !== undefined ? v[RAW] : esc(v));
  const h = (strings, ...vals) => ({ [RAW]: strings.reduce((out, s, i) => out + val(vals[i - 1]) + s) });

  // ---------- 飼主手機 ----------
  const chat = $("#chat"), list = $("#messages"), toast = $("#toast"), tray = $("#canned"), input = $("#text");
  let phoneId = 1, lastSig = "", firstRender = true, toastTimer = 0, panelSig = "";
  const seenFields = {}, typed = {};

  function showToast(message) {
    toast.textContent = message;
    toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toast.hidden = true; }, 6000);
  }

  function phoneState(id) {
    const c = getCase(id);
    const messages = caseMessages(id);
    return {
      c, messages, reminders: S.reminders.filter((r) => r.case_id === id).sort(byDue),
      photo: messages.some((m) => m.image),
      fields: Object.keys(FIELD_LABELS).filter((k) => REQUIRED.includes(k) || c.fields[k])
        .map((k) => ({ key: k, label: FIELD_LABELS[k], value: c.fields[k] ? RECORDED : null, required: REQUIRED.includes(k) })),
    };
  }

  function renderPick() {
    $("#phone-pick").replaceChildren(...S.cases.map((c) => {
      const b = el("button");
      b.type = "button";
      b.dataset.phone = c.id;
      b.setAttribute("aria-pressed", String(c.id === phoneId));
      b.append(`${c.pet_name}的手機`, el("small", null, `${c.owner_name} · ${c.species}`));
      return b;
    }));
  }

  function textBlock(text) {
    const box = el("div", "text");
    const note = [DISCLAIMER, SHORT_NOTE].find((n) => text.includes(n)); // 提示文字用小字，但一個字都不省略
    if (!note) { box.append(el("div", null, text)); return box; }
    const i = text.indexOf(note);
    const before = text.slice(0, i).trimEnd(), after = text.slice(i + note.length).trim();
    if (before) box.append(el("div", null, before));
    box.append(el("div", "note", note));
    if (after) box.append(el("div", null, after));
    return box;
  }

  function renderChat(st) {
    const lastConfirm = [...st.messages].reverse().find((m) => m.actions.some((a) => a.action === "confirm"))?.id;
    const isLive = (a, m) => (a.action === "confirm" || a.action === "edit")
      ? st.c.status === "awaiting_confirm" && m.id === lastConfirm
      : !!st.reminders.find((r) => r.id === a.reminder_id && !r.acked_at);
    const sig = phoneId + "|" + st.messages.map((m) => m.id + ":" + m.actions.map((a) => +isLive(a, m)).join("")).join("|");
    if (sig === lastSig) return;
    lastSig = sig;
    const who = { ai: "AI 問診助理", vet: st.c.vet_name, system: "系統" };
    list.replaceChildren(...st.messages.map((m) => {
      const row = el("div", `row ${m.sender}`);
      if (m.sender !== "owner") row.append(el("div", "who", who[m.sender]));
      const line = el("div", "line"), b = el("div", "bubble");
      if (m.image) {
        const img = el("img", "photo");
        img.src = photoOf(m);
        img.alt = "飼主上傳的照片";
        img.addEventListener("load", () => { chat.scrollTop = chat.scrollHeight; });
        b.append(img);
      }
      if (m.text) b.append(textBlock(m.text));
      line.append(b, el("span", "time", C.hm(m.created_at)));
      row.append(line);
      if (m.actions.length) {
        const quick = el("div", "quick");
        for (const a of m.actions) {
          const btn = el("button", `chip${a.action === "confirm" || a.action === "ack" ? " primary" : ""}`, a.label);
          btn.type = "button";
          btn.disabled = !isLive(a, m);
          btn.addEventListener("click", () => act(a));
          quick.append(btn);
        }
        row.append(quick);
      }
      return row;
    }));
    chat.scrollTo({ top: chat.scrollHeight, behavior: firstRender ? "instant" : "smooth" });
    firstRender = false;
  }

  function renderCanned(st) {
    tray.replaceChildren(...cannedFor(st.c).map((it) => {
      const b = el("button", `canned-msg${it.urgent ? " urgent" : ""}`, it.label || it.text);
      b.type = "button";
      if (it.hint) b.append(el("small", null, it.hint));
      b.addEventListener("click", () => send(it));
      return b;
    }));
    tray.scrollTop = 0;
  }

  function renderPanel(st) {
    const sig = JSON.stringify([phoneId, st.fields, st.photo, st.c.status]);
    if (sig === panelSig) return; // 沒變就不重畫，剛記錄到欄位的標示動畫才不會被打斷
    panelSig = sig;
    const required = st.fields.filter((f) => f.required);
    const done = required.filter((f) => f.value).length;
    $("#count").textContent = `${done} / ${required.length}`;
    $("#bar-fill").style.width = `${(done / Math.max(required.length, 1)) * 100}%`;
    $("#phase").textContent = STATUS_LABELS[st.c.status] || st.c.status;
    const seen = (seenFields[phoneId] ??= {});
    $("#fields").replaceChildren(...st.fields.map((f) => {
      const li = el("li", f.value ? "done" : "");
      if (f.value && seen[f.key] !== undefined && seen[f.key] !== f.value) li.classList.add("fresh");
      seen[f.key] = f.value;
      li.title = f.value || "尚未取得";
      li.append(el("span", "mark"), f.label);
      return li;
    }));
    // 照片描述沒有獸醫核可，只放在醫院端
    $("#photo-note").textContent = st.photo ? "照片：已收到（照片描述只給醫院看）" : "照片：尚未上傳";
  }

  let cannedSig = "";
  function renderPhone() {
    const st = phoneState(phoneId);
    $("#clinic-name").textContent = st.c.clinic_name;
    $("#clinic-sub").textContent = `${st.c.owner_name} · ${st.c.pet_name}（${st.c.species}）`;
    renderPick();
    renderChat(st);
    renderPanel(st);
    const sig = phoneId + st.c.status + st.messages.length;
    if (sig !== cannedSig) { cannedSig = sig; renderCanned(st); }
  }

  function switchPhone(id) {
    if (id === phoneId) return;
    typed[phoneId] = input.value;
    phoneId = id;
    input.value = typed[id] || "";
    lastSig = panelSig = cannedSig = "";
    firstRender = true;
    toast.hidden = true;
    renderPhone();
  }

  function report(e) {
    if (e instanceof UserError) showToast(e.message);
    else { console.error(e); showToast("發生錯誤，請重新整理後再試"); }
  }
  function send(item) {
    try { ownerMessage(phoneId, item); } catch (e) { report(e); }
    commit();
  }
  function act(a) {
    try { ownerAction(phoneId, a.action, a.reminder_id ?? null); } catch (e) { report(e); }
    commit();
  }

  $("#composer").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    send(itemFor(phoneId, text));
    input.focus();
  });
  input.addEventListener("keydown", (e) => {
    // 注音／拼音選字時的 Enter 是選字，不是送出
    if (e.key === "Enter" && (e.isComposing || e.keyCode === 229)) e.preventDefault();
  });
  $("#phone-pick").addEventListener("click", (e) => {
    const b = e.target.closest("[data-phone]");
    if (b) switchPhone(Number(b.dataset.phone));
  });

  // ---------- 醫院後台 ----------
  const clinicBody = $("#clinic-body"), pill = $("#update-pill");
  let view = { page: "list" }, lastClinicHtml = "", dirty = false, scrollTo = null;
  const errors = {};

  const errBox = (key) => (errors[key] ? h`<p class="form-error" role="alert">${errors[key]}</p>` : "");
  const guardrailBox = (flags, okText = "通過：藥名都有出現、劑量與醫囑一致，沒有病名、診斷用語或嚴重度分級。") => h`
    <div class="guardrail ${flags.length ? "warn" : "ok"}"><div class="g-title">護欄檢查</div>
    ${flags.length ? h`<ul>${flags.map((f) => h`<li>${f}</li>`)}</ul>` : h`<p>${okText}</p>`}</div>`;

  function orderView(o) {
    return h`<div class="order-view"><h4>用藥</h4><ul>${o.meds.map((m) =>
      h`<li><strong>${m.name}</strong>　每日 ${m.times_per_day} 次${m.timing ? `，${m.timing}` : ""}，連續 ${m.days} 天</li>`)}</ul>
      ${o.diet.text ? h`<h4>飲食</h4><p>${o.diet.text}${o.diet.days ? `（${o.diet.days} 天）` : ""}</p>` : ""}
      ${o.recheck_days ? h`<h4>回診</h4><p>${o.recheck_days} 天後回診</p>` : ""}
      ${o.watch ? h`<h4>觀察重點</h4><p>${o.watch}</p>` : ""}
      ${o.note ? h`<h4>補充</h4><p>${o.note}</p>` : ""}</div>`;
  }
  const medRow = (m) => h`<div class="med-row">
    <label>藥名<input name="med_name" value="${m.name}" maxlength="200" autocomplete="off"></label>
    <label>每日次數<select name="med_times">${[1, 2, 3].map((n) => h`<option value="${n}"${Number(m.times_per_day) === n ? h` selected` : ""}>${n} 次</option>`)}</select></label>
    <label>時機<input name="med_timing" value="${m.timing}" maxlength="200" placeholder="例如：飯後" autocomplete="off"></label>
    <label>天數<input type="number" name="med_days" min="1" max="60" value="${m.days}"></label>
    <button type="button" class="icon-btn" data-remove-med title="移除這筆用藥" aria-label="移除這筆用藥">×</button></div>`;

  function orderForm(c, o, label, extra) {
    const key = `order-${c.id}`;
    return h`<form data-form="order" data-key="${key}" data-case="${c.id}">
      <h3 class="f-title">用藥</h3>
      <div class="meds">${(o ? o.meds : [NEW_MED]).map(medRow)}</div>
      <div class="form-tools">
        <button type="button" class="btn small" data-add-med>＋ 新增一筆用藥</button>
        ${o ? "" : h`<button type="button" class="btn small" data-demo-order>填入示範醫囑</button>`}
      </div>
      <div class="f-row">
        <label class="grow">飲食<input name="diet_text" value="${o ? o.diet.text : ""}" maxlength="200" autocomplete="off"></label>
        <label class="narrow">飲食天數<input type="number" name="diet_days" min="0" max="60" value="${o ? o.diet.days : 0}"></label>
        <label class="narrow">回診（幾天後）<input type="number" name="recheck_days" min="0" max="60" value="${o ? o.recheck_days : 0}"></label>
      </div>
      <label class="block">觀察重點<textarea name="watch" rows="2" maxlength="200">${o ? o.watch : ""}</textarea></label>
      <label class="block">補充<textarea name="note" rows="2" maxlength="200">${o ? o.note : ""}</textarea></label>
      ${errBox(key)}
      <button type="submit" class="btn primary big">${label}</button>
      <p class="hint">照護計畫照醫囑原文逐項列出，不會新增藥物或劑量；產生後要由${c.vet_name}核可才會送給飼主。${extra}</p>
    </form>`;
  }

  function topbar() {
    const pending = pendingCount(), unseen = S.alerts.filter((a) => !a.seen).length;
    return h`<header class="topbar">
      <span class="clinic-title">示範動物醫院　後台</span>
      <nav>
        <button type="button" data-nav="list" class="${view.page !== "queue" ? "on" : ""}">案例列表${unseen ? h`<span class="alert-badge">緊急 ${unseen}</span>` : ""}</button>
        <button type="button" data-nav="queue" class="${view.page === "queue" ? "on" : ""}">待審佇列${pending ? h`<span class="pending-badge">${pending}</span>` : ""}</button>
      </nav>
      <span class="sim-tag">模擬案例</span>
    </header>`;
  }

  function listPage() {
    // 已讀的只留最近 20 則；未讀的全部列出，上方的緊急數字才按得掉
    const alerts = [...S.alerts].sort((a, b) => b.id - a.id).filter((a, i) => !a.seen || i < 20), unseen = alerts.filter((a) => !a.seen).length;
    const pending = pendingCount();
    return h`<div class="list-grid">
      <div class="stack">
        <section class="card">
          <div class="card-head"><h2>案例列表</h2></div>
          <div class="table-wrap"><table class="cases">
            <thead><tr><th>寵物</th><th>飼主</th><th>狀態</th><th>最後訊息</th><th></th></tr></thead>
            <tbody>${S.cases.map((c) => {
              const last = Math.max(0, ...caseMessages(c.id).map((m) => m.created_at));
              return h`<tr>
                <td><strong>${c.pet_name}</strong> <span class="muted">${c.species}</span></td>
                <td>${c.owner_name}</td>
                <td><span class="badge s-${c.status}">${clinicStatusLabel(c)}</span></td>
                <td class="muted">${last ? C.mdhm(last) : "—"}</td>
                <td class="actions"><button type="button" class="btn small primary" data-open-case="${c.id}">開啟案例</button>
                  <button type="button" class="btn small" data-show-phone="${c.id}">飼主手機</button></td></tr>`;
            })}</tbody>
          </table></div>
        </section>
        <div class="two">
          <button type="button" class="card stat" data-nav="queue">
            <span class="stat-num">${pending}</span>
            <span class="stat-label">待審回覆<small>飼主照護期間傳來、等醫師核可的訊息</small></span>
          </button>
          <section class="card reset-card">
            <h3>示範資料</h3>
            <p class="muted">清空所有對話、醫囑與提醒，回到兩個全新的模擬案例。</p>
            <form data-form="reset" data-key="reset" data-confirm="再按一次確認重設（對話與醫囑都會清除）">
              ${errBox("reset")}<button type="submit" class="btn">重設示範資料</button>
            </form>
          </section>
        </div>
      </div>
      <section class="alerts${unseen ? " has-new" : ""}" aria-live="assertive">
        <div class="alerts-head"><h2>緊急通知</h2>${unseen ? h`<span class="count">${unseen} 則未讀</span>` : ""}</div>
        ${alerts.length ? alerts.map((a) => h`<div class="alert-item${a.seen ? "" : " new"}">
          <strong>${a.seen ? "已讀" : "緊急"}</strong><time>${C.mdhm(a.created_at)}</time>
          <div class="alert-text">${a.text}</div>
          <div class="alert-actions"><button type="button" class="btn small" data-open-case="${a.case_id}">開啟案例</button>
            ${a.seen ? "" : h`<button type="button" class="btn small" data-alert-seen="${a.id}">知道了</button>`}</div>
        </div>`) : h`<p class="alert-empty">目前沒有緊急通知</p>`}
      </section>
    </div>`;
  }

  function casePage(id) {
    const c = getCase(id), vet = c.vet_name;
    const st = phoneState(id);
    const order = c.order_json ? JSON.parse(c.order_json) : null;
    const revision = c.revision_json ? JSON.parse(c.revision_json) : null;
    const planDraft = S.drafts.filter((d) => d.case_id === id && d.kind === "plan").sort((a, b) => b.id - a.id)[0];
    // 計畫左邊的「醫囑原文」要是產生這份草稿的那一版
    const plan = planDraft && { ...planDraft, order: planDraft.order_json ? JSON.parse(planDraft.order_json) : order };
    const sm = c.summary, unsent = st.reminders.filter((r) => !r.sent_at);
    const sender = { owner: "飼主", ai: "AI", vet, system: "系統" };
    const label = clinicStatusLabel(c);

    let orderCard;
    if (c.status === "submitted" || c.status === "ordered") orderCard = orderForm(c, order, c.status === "ordered" ? "重新產生照護計畫" : "送出醫囑，產生照護計畫", "");
    else if (c.status === "in_care") {
      orderCard = h`${order ? orderView(order) : ""}
        <details class="revise"${revision ? h` open` : ""}><summary>修改醫囑${revision ? "（新版待核可）" : ""}</summary>
        ${orderForm(c, revision || order, "產生新的照護計畫", "核可後，還沒送出的提醒會取消，改照新醫囑重新排程；已送出的提醒不受影響。")}</details>`;
    } else orderCard = order ? orderView(order) : h`<p class="empty">飼主還沒送出問診，暫時不能開醫囑。</p>`;

    let planCard = "";
    if (plan) {
      const key = `approve-${plan.id}`;
      const head = c.status === "in_care" ? `這是${vet}更新後的醫囑。之前排好、還沒送出的提醒已取消，之後照這份醫囑提醒您。` : `這是${vet}的醫囑`;
      planCard = h`<section class="card wide" id="plan">
        <div class="card-head"><h2>照護計畫</h2>${plan.status === "pending" ? h`<span class="badge s-ordered">待${vet}核可</span>` : h`<span class="badge s-in_care">已核可並送出</span>`}</div>
        <div class="compare">
          <div class="pane"><h3>醫囑原文<span class="muted">${vet}填寫</span></h3>${orderView(plan.order)}</div>
          <div class="pane edit">
            <h3>照護計畫草稿${plan.status === "pending" ? h`<span class="muted">要修改請改左邊的醫囑，重新產生</span>` : ""}</h3>
            ${guardrailBox(plan.flags)}
            ${plan.status === "pending" ? h`<form data-form="approve" data-key="${key}" data-draft="${plan.id}"${plan.flags.length ? h` data-confirm="護欄有 ${plan.flags.length} 項提醒，再按一次仍要核可並送出"` : ""}>
              <div class="msg-preview">
                <div class="preview-head">${head}</div>
                <textarea name="final_text" rows="${Math.max(plan.body.split("\n").length + 2, 7)}" readonly aria-label="照護計畫內容">${plan.body}</textarea>
                <div class="preview-foot">${DISCLAIMER}</div>
              </div>
              ${errBox(key)}<button type="submit" class="btn primary big">核可並送出</button>
              <p class="hint">飼主會在手機上看到上方的內容，並依醫囑開始收到提醒。${c.status === "in_care" ? "核可後，還沒送出的提醒會取消，改照這份新醫囑重新排程；回診天數從核可當天起算。" : ""}</p>
            </form>` : h`<p class="sent-note">已於 ${C.mdhm(plan.sent_at)} 核可並送出給飼主。完整內容見下方對話。</p>`}
          </div>
        </div>
      </section>`;
    }

    return h`<div class="page-head">
        <button type="button" class="linkish" data-nav="list">← 案例列表</button>
        <h1>${c.pet_name}<span class="muted">（${c.species}）</span></h1>
        <span class="muted">飼主 ${c.owner_name}</span>
        <span class="badge s-${c.status}">${label}</span>
        <button type="button" class="btn small" data-show-phone="${c.id}">看飼主手機</button>
      </div>
      <div class="case-grid">
        <section class="card" id="summary">
          <div class="card-head"><h2>問診摘要</h2><span class="tag-ai">AI 整理，供醫師參考</span></div>
          ${sm ? h`<p class="timeline">${sm.timeline}</p>
            <dl class="kv">${Object.entries(FIELD_LABELS).filter(([k]) => sm.fields[k] || k !== "history").map(([k, l]) => h`<dt>${l}</dt><dd>${sm.fields[k] || "未提供"}</dd>`)}</dl>
            ${sm.owner_quotes.length ? h`<h3>飼主原話</h3>${sm.owner_quotes.map((q) => h`<blockquote>${q}</blockquote>`)}` : ""}
            ${st.photo || sm.photo_desc ? h`<h3>照片</h3><figure class="photo-fig">${st.photo ? h`<img src="${DEMO_PHOTO}" alt="飼主上傳的照片">` : ""}
              <figcaption><span class="tag-ai">AI 描述</span> ${sm.photo_desc || "（沒有描述）"}</figcaption></figure>` : ""}
            ${sm.open_questions.length ? h`<h3>待確認事項</h3><ul class="open-q">${sm.open_questions.map((q) => h`<li>${q}</li>`)}</ul>` : ""}`
          : h`<p class="empty">飼主還沒送出問診。目前狀態：${label}。</p>`}
        </section>
        <section class="card" id="order"><div class="card-head"><h2>醫囑</h2><span class="muted">由${vet}填寫</span></div>${orderCard}</section>
        ${planCard}
        <section class="card" id="conversation">
          <div class="card-head"><h2>完整對話</h2></div>
          ${st.messages.length ? h`<ul class="log">${st.messages.map((m) => h`<li class="log-${m.sender}"><span class="who">${sender[m.sender]}</span>
              <div class="log-body">${m.image ? h`<img src="${photoOf(m)}" alt="飼主上傳的照片">` : ""}${m.text ? h`<div class="log-text">${m.text}</div>` : ""}</div>
              <time>${C.hm(m.created_at)}</time></li>`)}</ul>` : h`<p class="empty">還沒有對話。</p>`}
        </section>
        <section class="card" id="reminders">
          <div class="card-head"><h2>提醒</h2>
            ${st.reminders.length ? h`<button type="button" class="btn small primary" data-ff="${c.id}"${unsent.length ? "" : h` disabled`}>快轉到下一個提醒</button>` : ""}</div>
          ${errBox(`ff-${c.id}`)}
          ${st.reminders.length ? h`<div class="table-wrap"><table class="rem">
            <thead><tr><th>預定時間</th><th>類型</th><th>送出</th><th>飼主回報</th></tr></thead>
            <tbody>${st.reminders.map((r) => h`<tr class="${r.sent_at ? "done" : ""}"><td>${C.mdhm(r.due_at)}</td><td>${KIND_LABELS[r.kind] || r.kind}</td>
              <td>${r.sent_at ? `已送出 ${C.mdhm(r.sent_at)}` : "尚未送出"}</td><td>${r.acked_at ? `已餵 ${C.hm(r.acked_at)}` : "—"}</td></tr>`)}</tbody>
          </table></div>` : h`<p class="empty">核可照護計畫後，才會建立用藥與回診提醒。</p>`}
        </section>
      </div>`;
  }

  /** 醫師可以挑的罐頭回覆：預先寫好的草稿、通用回覆，再加一則故意改藥、示範護欄會擋下。 */
  function replyOptions(d, c) {
    const opts = d.body ? [{ label: "預先寫好的草稿", text: d.body }] : [];
    for (const t of VET_REPLIES) opts.push({ label: t, text: t });
    const med = c.order_json && JSON.parse(c.order_json).meds[0]?.name;
    if (med) opts.push({ label: "示範：回覆裡改藥（會被擋下）", text: `請把${med}改成一天三次。` });
    return opts;
  }

  function queuePage() {
    const labels = Object.values(ACTION_LABELS);
    const drafts = S.drafts.filter((d) => d.status === "pending" && d.kind !== "plan").sort((a, b) => a.id - b.id);
    return h`<div class="page-head"><h1>待審佇列</h1><p class="muted">飼主在照護期間傳來的訊息。回覆都要醫師核可後才會送給飼主。</p></div>
      ${drafts.length ? drafts.map((d) => {
        const c = getCase(d.case_id), key = `approve-${d.id}`;
        // 「飼主最近說」：草稿建立當下（含）最後一則飼主訊息，不算「已餵」這類按鈕文字
        const said = caseMessages(c.id).filter((m) => m.sender === "owner" && m.created_at <= d.created_at && !labels.includes(m.text)).at(-1);
        return h`<article class="card draft">
          <header class="draft-head"><strong>${c.pet_name}</strong><span class="muted">${c.owner_name}</span>
            <span class="badge ${d.kind === "reply" ? "s-ordered" : "s-awaiting_confirm"}">${d.kind === "reply" ? "回覆草稿" : "需人員回覆"}</span>
            <time class="muted">${C.mdhm(d.created_at)}</time></header>
          <div class="compare">
            <div class="pane">
              <h3>飼主最近說</h3><blockquote>${said?.text || "（傳了一張照片）"}</blockquote>
              <h3>變化摘要<span class="tag-ai">AI 整理</span></h3><p>${d.summary}</p>
              ${guardrailBox(d.flags, "通過：沒有發現病名、診斷用語、嚴重度分級、用藥建議或產品推薦。")}
            </div>
            <form class="pane edit" data-form="approve" data-key="${key}" data-draft="${d.id}"${d.flags.length ? h` data-confirm="護欄有 ${d.flags.length} 項提醒，再按一次仍要核可並送出"` : ""}>
              <h3>回覆<span class="muted">挑一則罐頭回覆，或直接修改</span></h3>
              <div class="reply-opts">${replyOptions(d, c).map((o) => h`<button type="button" class="btn small" data-fill="${o.text}">${o.label}</button>`)}</div>
              <div class="msg-preview">
                <textarea name="final_text" rows="4" placeholder="輸入要送給飼主的回覆" aria-label="回覆內容">${d.body}</textarea>
                <div class="preview-foot">送出時會自動附上：（${c.vet_name}已確認）<br>${SHORT_NOTE}</div>
              </div>
              ${errBox(key)}<button type="submit" class="btn primary big">核可並送出</button>
            </form>
          </div>
        </article>`;
      }) : h`<section class="card empty-card"><p>目前沒有待審項目。</p><p class="muted">飼主在照護期間傳來訊息時，回覆草稿會出現在這裡。</p></section>`}`;
  }

  function renderClinic(force = false) {
    const page = view.page === "case" ? casePage(view.id) : view.page === "queue" ? queuePage() : listPage();
    const html = val(h`${topbar()}<div class="content">${page}</div>`);
    if (html === lastClinicHtml) return;
    if (dirty && !force) { pill.hidden = false; return; } // 正在填的表單不要被新動態蓋掉
    dirty = false;
    pill.hidden = true;
    clinicBody.innerHTML = html;
    lastClinicHtml = html;
    const log = $(".log", clinicBody);
    if (log) log.scrollTop = log.scrollHeight;
    if (scrollTo) { document.getElementById(scrollTo)?.scrollIntoView({ block: "start", behavior: "smooth" }); scrollTo = null; }
  }

  function go(next) {
    view = next;
    dirty = false;
    renderClinic(true);
    clinicBody.closest(".clinic").scrollIntoView({ block: "start" });
  }

  function arm(btn, text) {
    btn.dataset.armed = "1";
    btn.dataset.label = btn.textContent;
    btn.textContent = text;
    btn.classList.add("armed");
    setTimeout(() => {
      if (btn.isConnected && btn.dataset.armed === "1") {
        btn.dataset.armed = "";
        btn.textContent = btn.dataset.label;
        btn.classList.remove("armed");
      }
    }, 6000);
  }

  function readOrder(form) {
    const meds = [...form.querySelectorAll(".med-row")].map((row) => ({
      name: $("[name=med_name]", row).value, times_per_day: $("[name=med_times]", row).value,
      timing: $("[name=med_timing]", row).value, days: $("[name=med_days]", row).value,
    })).filter((m) => m.name.trim() || m.timing.trim()); // 整列空白的跳過
    const f = (n) => form.elements[n].value.replace(/\r\n/g, "\n");
    return { meds, diet: { text: f("diet_text"), days: f("diet_days") || "0" }, recheck_days: f("recheck_days") || "0", watch: f("watch"), note: f("note") };
  }

  clinicBody.addEventListener("submit", (e) => {
    const form = e.target.closest("form[data-form]");
    if (!form) return;
    e.preventDefault();
    const key = form.dataset.key, btn = $("button[type=submit]", form);
    if (form.dataset.confirm && btn.dataset.armed !== "1") { arm(btn, form.dataset.confirm); return; }
    errors[key] = "";
    try {
      if (form.dataset.form === "order") {
        saveOrder(Number(form.dataset.case), readOrder(form));
        scrollTo = "plan";
      } else if (form.dataset.form === "approve") {
        approveDraft(Number(form.dataset.draft), form.elements.final_text.value.replace(/\r\n/g, "\n"));
      } else if (form.dataset.form === "reset") {
        S = fresh(S);
        view = { page: "list" };
        for (const k of Object.keys(errors)) delete errors[k];
      }
    } catch (err) {
      if (err instanceof UserError) errors[key] = err.message;
      else { console.error(err); errors[key] = "發生錯誤，請重新整理後再試"; }
    }
    dirty = false;
    save();
    render(true);
  });

  clinicBody.addEventListener("click", (e) => {
    const t = e.target.closest("button");
    if (!t) return;
    if (t.dataset.nav) go({ page: t.dataset.nav });
    else if (t.dataset.openCase) go({ page: "case", id: Number(t.dataset.openCase) });
    else if (t.dataset.showPhone) { switchPhone(Number(t.dataset.showPhone)); setPane("phone"); }
    else if (t.dataset.fill !== undefined) {
      t.form.elements.final_text.value = t.dataset.fill;
      dirty = true;
    } else if (t.dataset.alertSeen) {
      const a = S.alerts.find((x) => x.id === Number(t.dataset.alertSeen));
      if (a) { a.seen = 1; commit(); }
    } else if (t.dataset.ff) {
      const id = Number(t.dataset.ff);
      errors[`ff-${id}`] = "";
      try { fastForward(id); } catch (err) { errors[`ff-${id}`] = err.message; }
      save();
      render(true);
    } else if ("addMed" in t.dataset) {
      const meds = $(".meds", t.form);
      meds.insertAdjacentHTML("beforeend", val(medRow(NEW_MED)));
      $("input", meds.lastElementChild).focus();
      dirty = true;
    } else if ("removeMed" in t.dataset) {
      const meds = t.closest(".meds");
      if (meds.children.length > 1) { t.closest(".med-row").remove(); dirty = true; }
    } else if ("demoOrder" in t.dataset) {
      const form = t.form, o = DEMO_ORDER, m = o.meds[0], row = $(".med-row", form);
      $("[name=med_name]", row).value = m.name;
      $("[name=med_times]", row).value = String(m.times_per_day);
      $("[name=med_timing]", row).value = m.timing;
      $("[name=med_days]", row).value = String(m.days);
      form.elements.diet_text.value = o.diet.text;
      form.elements.diet_days.value = String(o.diet.days);
      form.elements.recheck_days.value = String(o.recheck_days);
      form.elements.watch.value = o.watch;
      form.elements.note.value = o.note;
      dirty = true;
    }
  });
  clinicBody.addEventListener("input", (e) => { if (e.target.closest("form[data-form=order], form[data-form=approve]")) dirty = true; });
  pill.addEventListener("click", () => { dirty = false; renderClinic(true); });

  // ---------- 窄螢幕切換 ----------
  function setPane(p) {
    document.body.dataset.pane = p;
    for (const b of document.querySelectorAll("[data-pane-btn]")) b.setAttribute("aria-pressed", String(b.dataset.paneBtn === p));
  }
  for (const b of document.querySelectorAll("[data-pane-btn]")) b.addEventListener("click", () => setPane(b.dataset.paneBtn));

  function render(forceClinic = false) {
    renderPhone();
    renderClinic(forceClinic);
    $("#store-note").hidden = storageOk;
  }

  setPane("phone");
  render(true);
  tick();
  setInterval(() => tick(), TICK_MS); // 每 30 秒送出到期的提醒
})();

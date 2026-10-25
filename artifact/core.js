// 流程用到的純函式與固定文字，對照 vetloop/flows.py。不碰狀態，方便和 Python 版對照測試。
window.VC = (() => {
  const FIELD_LABELS = {
    chief: "狀況", onset: "開始時間", frequency: "次數", appetite: "食慾", energy: "精神",
    diet_change: "飲食變化", excretion: "排泄", medication: "用藥", history: "病史",
  };
  const REQUIRED = Object.keys(FIELD_LABELS).filter((k) => k !== "history"); // 病史有提到才記，不主動問
  // 追問分組（依序）；chief 自成一組，沒抓到狀況就先問狀況
  const GROUPS = [["chief"], ["onset", "frequency"], ["appetite", "energy", "diet_change"], ["excretion", "medication"]];
  const QUESTIONS = {
    chief: "請問{pet}目前是什麼狀況？", onset: "從什麼時候開始的？", frequency: "一天大概幾次？",
    appetite: "食慾和精神跟平常比起來有變化嗎？", energy: "食慾和精神跟平常比起來有變化嗎？",
    diet_change: "最近有換飼料或零食嗎？", excretion: "排便排尿正常嗎？",
    medication: "目前有在吃任何藥嗎？",
  };
  const REMINDER_SLOTS = { 1: [8], 2: [8, 20], 3: [8, 14, 20] };
  // ponytail: Asia/Taipei 沒有日光節約，固定 +08:00；時間一律存 epoch 毫秒
  const TZ_MS = 8 * 3600 * 1000;

  const pad = (n) => String(n).padStart(2, "0");
  function taipei(ms) {
    const d = new Date(ms + TZ_MS);
    return { y: d.getUTCFullYear(), mo: d.getUTCMonth(), d: d.getUTCDate(), h: d.getUTCHours(), mi: d.getUTCMinutes(), s: d.getUTCSeconds() };
  }
  /** 台北時間 y/mo/d h:00 的 epoch 毫秒；日期超過月底會自動進位。 */
  const taipeiAt = (y, mo, d, h) => Date.UTC(y, mo, d, h) - TZ_MS;
  const hm = (ms) => { if (!ms) return ""; const t = taipei(ms); return `${pad(t.h)}:${pad(t.mi)}`; };
  const mdhm = (ms) => { if (!ms) return ""; const t = taipei(ms); return `${pad(t.mo + 1)}/${pad(t.d)} ${pad(t.h)}:${pad(t.mi)}`; };
  const iso = (ms) => { const t = taipei(ms); return `${t.y}-${pad(t.mo + 1)}-${pad(t.d)}T${pad(t.h)}:${pad(t.mi)}:${pad(t.s)}+08:00`; };

  const missing = (fields) => REQUIRED.filter((k) => !fields[k]);
  function missingGroups(fields) {
    const miss = missing(fields);
    return GROUPS.map((g) => g.filter((k) => miss.includes(k))).filter((g) => g.length);
  }

  /** 固定問句：只問第一個還有缺欄位的那一組裡缺的欄位。 */
  function question(fields, pet) {
    const groups = missingGroups(fields);
    const sentences = [];
    for (const key of groups[0] || []) {
      const s = QUESTIONS[key].replace("{pet}", pet);
      if (!sentences.includes(s)) sentences.push(s); // 食慾和精神共用一句
    }
    return sentences.join("");
  }

  /** 新值蓋舊值，null 不蓋。回傳這次抽到幾個欄位。 */
  function merge(fields, incoming) {
    let count = 0;
    if (!incoming || typeof incoming !== "object" || Array.isArray(incoming)) return 0;
    for (const [key, value] of Object.entries(incoming)) {
      if (key in FIELD_LABELS && typeof value === "string" && value.trim()) {
        fields[key] = [...value.trim()].slice(0, 200).join("");
        count++;
      }
    }
    return count;
  }

  function confidence(result) {
    const c = result.confidence;
    return typeof c === "number" && c >= 0 && c <= 1 ? c : 0;
  }

  // ---- 醫囑 ----
  class UserError extends Error {}

  function text(value, name, required = false) {
    if (typeof value !== "string") throw new UserError(`${name}必須是文字`);
    value = value.trim();
    if ([...value].length > 200) throw new UserError(`${name}不可超過 200 字`);
    if (required && !value) throw new UserError(`${name}不可空白`);
    return value;
  }

  function int(value, name, low, high) {
    if (typeof value === "string" && /^\p{Nd}+$/u.test(value.trim())) value = parseInt(value.trim().normalize("NFKC"), 10); // 表單送來的是字串
    if (!Number.isInteger(value) || value < low || value > high) throw new UserError(`${name}必須是 ${low} 到 ${high} 的整數`);
    return value;
  }

  function validateOrder(order) {
    if (!order || typeof order !== "object" || Array.isArray(order)) throw new UserError("醫囑格式不正確");
    const meds = order.meds;
    if (!Array.isArray(meds) || !meds.length) throw new UserError("至少要有一筆用藥");
    const diet = "diet" in order ? order.diet : { text: "", days: 0 };
    if (!diet || typeof diet !== "object" || Array.isArray(diet) || meds.some((m) => !m || typeof m !== "object" || Array.isArray(m))) {
      throw new UserError("醫囑格式不正確");
    }
    return {
      meds: meds.map((m) => ({
        name: text(m.name, "藥名", true),
        times_per_day: int(m.times_per_day, "每日次數", 1, 3),
        timing: text(m.timing ?? "", "服藥時機"),
        days: int(m.days, "用藥天數", 1, 60),
      })),
      diet: { text: text(diet.text ?? "", "飲食"), days: int(diet.days ?? 0, "飲食天數", 0, 60) },
      recheck_days: int(order.recheck_days ?? 0, "回診天數", 0, 60),
      watch: text(order.watch ?? "", "觀察重點"),
      note: text(order.note ?? "", "補充"),
    };
  }

  /** 計畫裡的用藥行照醫囑原文產生，和提醒用同一份資料，兩邊才不會對不上。 */
  const medSteps = (order) => order.meds.map((m) =>
    `${m.name}：每天 ${m.times_per_day} 次${m.timing ? `，${m.timing}` : ""}，連續 ${m.days} 天`);

  /** 用藥以外的項目照醫囑原文；AI 失敗時的退路。 */
  function otherSteps(order) {
    const steps = [];
    const diet = order.diet;
    if (diet.text) steps.push(`飲食：${diet.text}` + (diet.days ? `（${diet.days} 天）` : ""));
    if (order.recheck_days) steps.push(`${order.recheck_days} 天後回診`);
    if (order.watch) steps.push(`請留意：${order.watch}`);
    if (order.note) steps.push(order.note);
    return steps;
  }

  /** 從 now 之後的下一個時段開始，共 timesPerDay × days 個。 */
  function reminderTimes(timesPerDay, days, now) {
    const total = timesPerDay * days, t = taipei(now), out = [];
    for (let day = 0; out.length < total; day++) {
      for (const h of REMINDER_SLOTS[timesPerDay]) {
        const at = taipeiAt(t.y, t.mo, t.d + day, h);
        if (at > now) out.push(at);
      }
    }
    return out.slice(0, total);
  }

  return {
    FIELD_LABELS, REQUIRED, UserError, taipei, taipeiAt, hm, mdhm, iso, missing, question, merge, confidence,
    validateOrder, medSteps, otherSteps, reminderTimes,
  };
})();

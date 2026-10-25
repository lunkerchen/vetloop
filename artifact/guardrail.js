// 護欄：純函式，對照 vetloop/guardrail.py 逐條移植。AI 自己寫的內容都要先過這裡。
// regex 一律加 u 旗標，才會像 Python 一樣以字元（code point）計數；\d 改用 \p{Nd}，和 Python 的 \d 一致。
window.VG = (() => {
  const DISCLAIMER = "本作品提供之資訊僅供輔助參考，不能取代獸醫師之診斷、治療或專業建議。"
    + "貓犬之健康與營養需求可能因個體狀況而異，如有健康疑慮或需要調整飲食與照護方式，請諮詢合格獸醫師。";
  const SHORT_NOTE = "提醒內容來自獸醫師醫囑，僅供照護參考；有疑慮請洽獸醫師。";

  // 緊急字眼寧可誤報（例如「沒有誤食」也會觸發），不可漏報。
  const FOREIGN = "繩子|線|骨頭|塑膠|巧克力|葡萄|百合";
  const EMERGENCY = new RegExp([
    "誤食", "誤吞", "吞了", "吞下", "吞到", "吞進",
    // 「吃了／吃下／吃到藥」是正常的用藥回報，只有「偷吃」接藥才算
    `(?:吃到|吃下|吃了).{0,6}(?:${FOREIGN})`, `偷吃.{0,6}(?:${FOREIGN}|藥)`,
    // 毒物：這幾種單獨出現就算；人吃的藥與百合要看動作
    "老鼠藥", "殺蟲劑", "除草劑", "農藥",
    "(?:吃到|吃了|吃下|舔).{0,6}(?:我的藥|人的藥|人吃的|普拿疼|感冒藥|止痛藥|安眠藥)",
    "(?:舔|咬|吃).{0,6}百合",
    "吞食", "呼吸困難", "喘不過氣", "張口呼吸", "抽搐", "抽筋", "癲癇", "痙攣", "昏倒", "休克",
    "沒有意識", "叫不醒", "大量出血", "流血不止", "一直流血", "吐血", "尿不出", "中毒", "車禍", "癱",
  ].join("|"), "u");

  // 數量：5、2.5、1/4、1 / 2、四分之一、半、一
  const NUM = String.raw`\p{Nd}+(?:\.\p{Nd}+)?`;
  const ZH = "一二兩三四五六七八九十百";
  const AMOUNT = String.raw`(?:${NUM}(?:\s*/\s*${NUM})?|[${ZH}]+分之[${ZH}]+|[${ZH}半]+)`;
  const DOSE_SRC = AMOUNT + String.raw`\s*(?:mg|ml|cc|毫克|毫升|錠|顆)`;
  const DOSE = new RegExp(DOSE_SRC, "giu");

  // 病名字尾。「症」不擋「症狀」；「病」不擋病史、病歷、病情、病況、生病、生過病、看病、毛病
  const DISEASE = "(?:炎|症(?!狀)|癌|腫瘤|衰竭|結石|感染|中暑|寄生蟲|過敏"
    + "|(?<![生看過毛])病(?![史歷情況])|瘟|潰瘍|阻塞|癲癇)";
  const RULES = [
    // 推測句型要放在單獨的病名字尾前面，同一段只報一次
    ["診斷或推測", new RegExp("可能是|疑似|診斷|確診|罹患|(?:應該是|或許是|大概是|看起來像).{0,8}?" + DISEASE
      + "|" + DISEASE, "gu")],
    ["嚴重度分級", /嚴重度|嚴重程度|輕症|重症|危險等級|分級|不嚴重|沒什麼大礙|高風險|低風險|風險等級/gu],
    ["用藥建議", /建議(?:服用|吃|給).{0,12}藥|止吐藥|抗生素|類固醇|胃藥|益生菌|禁食|加倍|減半|停藥|加量|減量/gu],
    ["劑量", DOSE],
    ["產品或品牌", /飼料品牌|處方飼料|royal\s*canin|皇家|推薦.{0,10}(?:飼料|罐頭|產品|品牌)/giu],
  ];

  // 追蹤回覆裡的改藥字眼：提醒是照醫囑排的，回覆寫「停藥」「改成每天一次」只會讓飼主收到互相矛盾的指示。
  // ponytail: regex 經驗法則，不是語意判斷（上限與 Python 版相同：擋不到沒出現這些字眼的說法，也會誤擋少數正常句子）
  const CLAUSE = "[^，。,.；;！!？?\\n]"; // 同一句之內
  const STOP = "[暫先]?停(?:止|用|掉)?(?:給|吃|餵|服|使用|用)?藥";
  const MED_CHANGE_SRC = [
    STOP,
    "(?:不用|不必|不需要?|不要|先別|勿|(?<![特分])別)再?(?:給|吃|餵|服用?)藥",
    "(?:給藥|餵藥|用藥|吃藥|服藥)的?次數|次數(?:改|調整|增加|減少)", // 單獨的「次數」太常見（嘔吐次數），不算
    "改(?:成|為|到)?(?:每天|每日|每次|每餐|一天|一日|早晚)", "(?:每天|每日|一天|一日)改",
    "加量|減量|加倍|減半|劑量|藥量",
    `[多少]給${CLAUSE}{0,4}(?:藥|顆|錠|粒|包|cc|ml|mg|毫升)`, // 「多給麻糬喝水」不算
    `(?:增加|減少)${CLAUSE}{0,4}[次藥]`,
    `換${CLAUSE}{0,6}藥`, `改(?:給|用|吃|服|餵)${CLAUSE}{0,6}藥`,
    String.raw`改(?:成|為|給|用)?\s*` + DOSE_SRC, // 「改給半顆」沒提到藥字也算
  ].join("|");
  const MED_CHANGE = new RegExp(MED_CHANGE_SRC, "giu");
  // 「請不要自行停藥」「請勿自行調整劑量」是在勸阻，不算
  const SELF = new RegExp(`(?:自行|擅自)${CLAUSE}{0,4}?(?:${MED_CHANGE_SRC})`, "giu");

  const nfkc = (s) => String(s ?? "").normalize("NFKC");
  const cpLen = (s) => [...s].length;
  const byLenDesc = (a, b) => cpLen(b) - cpLen(a);
  const replaceAll = (text, s, to) => text.split(s).join(to);

  function isEmergency(text) {
    return EMERGENCY.test(text || "");
  }

  /** 回傳違規原因；空陣列代表通過。allowed 是獸醫醫囑原文，先從 text 移除再檢查。 */
  function checkAiText(text, allowed = []) {
    text = nfkc(text); // 全形英數轉半形，免得「５ｍｇ」躲過劑量規則
    const keep = [...new Set(allowed.filter((a) => typeof a === "string" && a).map(nfkc))].sort(byLenDesc);
    // 用 \0 取代而不是刪掉，避免前後文接在一起湊出新的違規字串
    for (const s of keep) text = replaceAll(text, s, "\0");
    const reasons = [];
    for (const [label, pattern] of RULES) {
      for (const m of text.matchAll(pattern)) {
        const reason = `${label}：「${m[0]}」`;
        if (!reasons.includes(reason)) reasons.push(reason);
      }
    }
    return reasons;
  }

  /** 回覆文字裡提到停藥、改次數、改劑量或換藥的片段（不重複，依出現順序）。medNames 先換成「藥」再比對。 */
  function medChange(text, medNames = []) {
    text = nfkc(text);
    for (const name of [...new Set(medNames.filter(Boolean).map(nfkc))].sort(byLenDesc)) {
      text = replaceAll(text, name, "藥");
    }
    text = text.replace(SELF, "\0");
    const hits = [];
    for (const m of text.matchAll(MED_CHANGE)) if (!hits.includes(m[0])) hits.push(m[0]);
    return hits;
  }

  function* strings(obj) {
    if (typeof obj === "string") yield obj;
    else if (Array.isArray(obj)) for (const v of obj) yield* strings(v);
    else if (obj && typeof obj === "object") for (const v of Object.values(obj)) yield* strings(v);
  }

  // 醫囑自己寫了這幾個字，計畫就可以用（它們在 checkAiText 裡是照護建議）
  const ADVICE_WORDS = ["禁食", "益生菌", "胃藥"];

  /** 去空白、全形轉半形、轉小寫，拿來比對藥名與劑量。 */
  const norm = (s) => nfkc(s).replace(/\s+/gu, "").toLowerCase();
  const doses = (text) => [...nfkc(text).matchAll(DOSE)].map((m) => norm(m[0]));

  /** 照護計畫草稿要忠於醫囑：藥名不能漏、劑量不能憑空出現，其餘照 checkAiText。 */
  function checkPlan(text, order) {
    const flags = [];
    const textN = norm(text);
    for (const med of order.meds || []) {
      const name = med.name || "";
      if (name && !textN.includes(norm(name))) flags.push(`漏掉醫囑藥名：${name}`);
    }
    const orderStrings = [...strings(order)];
    // 醫囑裡的劑量也用同一個運算式抽出來，正規化後逐一完全比對（2.5mg 不能放行 5mg）
    const ordered = new Set(orderStrings.flatMap(doses));
    const shown = [];
    for (const m of nfkc(text).matchAll(DOSE)) {
      if (!shown.includes(m[0])) {
        shown.push(m[0]);
        if (!ordered.has(norm(m[0]))) flags.push(`醫囑沒有這個劑量：${m[0]}`);
      }
    }
    // 劑量已在上面逐一判斷，這裡一併放行，避免同一個劑量被標兩次
    const orderText = nfkc(orderStrings.join(" "));
    const advice = ADVICE_WORDS.filter((w) => orderText.includes(w));
    return flags.concat(checkAiText(text, orderStrings.concat(shown, advice)));
  }

  return { DISCLAIMER, SHORT_NOTE, isEmergency, checkAiText, medChange, checkPlan, norm, cpLen };
})();

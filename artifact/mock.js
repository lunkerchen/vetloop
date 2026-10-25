// 本機測試用：假的 window.claude.sample，依 prompt 的任務回固定格式
(() => {
  const KEYS = { chief: /吐|拉|咳/, onset: /開始/, frequency: /次/, appetite: /吃|食慾/, energy: /精神|活力/, diet_change: /換|飼料/, excretion: /便|尿/, medication: /藥/ };
  window.__calls = [];
  const json = async (text, opts = {}) => {
    window.__calls.push({ text, opts });
    await new Promise((r) => setTimeout(r, 300));
    if (window.__fail) throw { code: window.__fail, message: "mock" };
    const input = (() => { try { return JSON.parse(text.split("輸入（JSON）：\n")[1].split("\n\n只回覆")[0]); } catch { return null; } })();
    if (text.includes("任務：從 message 抽出問診欄位")) {
      const fields = {};
      for (const s of input.message.split(/[，。,！!？?\n]/).map((x) => x.trim()).filter(Boolean))
        for (const [k, re] of Object.entries(KEYS)) if (re.test(s) && !fields[k]) fields[k] = s;
      return { fields, confidence: 0.9 };
    }
    if (text.includes("任務：描述照片")) return { description: opts.images?.length ? "地上一灘黃色液體，有幾塊未消化的飼料" : "?" };
    if (text.includes("任務：把問診內容整理成給獸醫看的摘要"))
      return { timeline: "前天晚上開始嘔吐，一天三四次，食慾下降。", owner_quotes: input.owner_messages.slice(0, 2), open_questions: ["嘔吐物裡有沒有毛球？"] };
    if (text.includes("任務：飼主在照護期間傳來新訊息"))
      return window.__reply || { change_summary: "飼主回報今天又吐了一次", reply: "謝謝您回報。請先照醫囑讓牠少量多餐，有疑慮請直接來電。", confidence: 0.8 };
    if (text.includes("任務：把獸醫醫囑中")) return { steps: ["當天少量多餐，連續 2 天", "3 天後回診", "若持續嘔吐請來電"] };
    throw { code: "invalid_json", message: "unknown task" };
  };
  const sample = Object.assign(async () => ({ text: "", truncated: false }), { json, limits: async () => ({ maxPromptBytes: 262144, images: { maxCount: 5, maxInputBytes: 2e7, mediaTypes: ["image/jpeg", "image/png"] } }) });
  window.claude = { use: async (n) => (n === "sample" ? sample : null) };
})();

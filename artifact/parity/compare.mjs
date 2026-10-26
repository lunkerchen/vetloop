// 用 Python 版的輸出逐條對照 JS 版護欄與純函式。
import fs from "node:fs";
import vm from "node:vm";
const [demo, fixture] = process.argv.slice(2);
const ctx = { window: {} };
vm.createContext(ctx);
for (const f of ["guardrail.js", "core.js"]) vm.runInContext(fs.readFileSync(`${demo}/${f}`, "utf8"), ctx);
const { VG, VC } = ctx.window;
const fx = JSON.parse(fs.readFileSync(fixture, "utf8"));
const names = ["示範藥A", "示範藥B", "示範藥A加強錠"];
const orders = [
  { meds: [{ name: "示範藥A", times_per_day: 2, timing: "飯後 2.5mg", days: 5 }], diet: { text: "當天少量多餐", days: 2 }, recheck_days: 3, watch: "若持續嘔吐請來電", note: "" },
  { meds: [{ name: "示範藥B", times_per_day: 1, timing: "半顆", days: 3 }], diet: { text: "禁食 12 小時", days: 1 }, recheck_days: 0, watch: "", note: "可給益生菌" },
];
let fail = 0, n = 0;
const eq = (label, got, want, input) => {
  n++;
  if (JSON.stringify(got) !== JSON.stringify(want)) {
    fail++;
    if (fail <= 25) console.log(`✗ ${label}\n  輸入：${JSON.stringify(input)}\n  JS：${JSON.stringify(got)}\n  Py：${JSON.stringify(want)}`);
  }
};
for (const c of fx.cases) {
  eq("isEmergency", VG.isEmergency(c.t), c.e, c.t);
  eq("checkAiText", VG.checkAiText(c.t), c.a, c.t);
  eq("checkAiText(allowed)", VG.checkAiText(c.t, ["示範藥A", "飯後", "2.5mg"]), c.aa, c.t);
  eq("medChange(names)", VG.medChange(c.t, names), c.m, c.t);
  eq("medChange", VG.medChange(c.t), c.m0, c.t);
  orders.forEach((o, i) => eq(`checkPlan#${i}`, VG.checkPlan(c.t, o), c.p[i], c.t));
  eq("norm", VG.norm(c.t), c.n, c.t);
}
for (const r of fx.rem) {
  eq("reminderTimes", VC.reminderTimes(r.tpd, r.days, Date.parse(r.now)).map(VC.iso), r.out, r);
}
for (const o of fx.orders) {
  let got;
  try { const v = VC.validateOrder(o.in); got = { ok: v, med: VC.medSteps(v), other: VC.otherSteps(v) }; }
  catch (e) { got = { err: e.message }; }
  eq("validateOrder", got, o.err ? { err: o.err } : { ok: o.ok, med: o.med, other: o.other }, o.in);
}
for (const q of fx.q) eq("question", VC.question(q.f, "麻糬"), q.q, q.f);
console.log(`${n - fail}/${n} 項一致，${fx.cases.length} 個字串輸入`);
process.exit(fail ? 1 : 0);

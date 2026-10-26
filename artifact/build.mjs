// 組裝：把 guardrail.js、core.js、app.js、示範照片塞進 app.src.html → vetloop-demo.html
import { readFileSync, writeFileSync } from "node:fs";
const d = process.argv[2];
const r = (f) => readFileSync(`${d}/${f}`, "utf8");
const out = r("app.src.html")
  .replace("/*__GUARDRAIL__*/", () => r("guardrail.js"))
  .replace("/*__CORE__*/", () => r("core.js"))
  .replace("/*__APP__*/", () => r("app.js"))
  .replace("__DEMO_PHOTO__", () => r("vomit.b64").trim());
if (/__(GUARDRAIL|CORE|APP|DEMO_PHOTO)__/.test(out)) throw new Error("placeholder left");
writeFileSync(`${d}/vetloop-demo.html`, out);
console.log(out.length, "bytes");

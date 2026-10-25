// 照 README 的 Demo 腳本，用真的 Claude CLI 跑一遍，三個畫面各自截流（CDP screencast，高畫質 JPEG）。
// 解析度：screencast 只出 CSS 像素大小的畫格，所以視窗開成兩倍大、body 用 zoom:2 排版，畫格就是 2 倍清晰度。
// 用法：先在另一個終端起 app（預設 http://127.0.0.1:5051），再 `node record.mjs [輸出目錄]`。
// 產出：<out>/<page>/NNNNN.jpg、<out>/<page>/frames.json（每張的 wall-clock 秒數）、<out>/events.json（步驟時間與元素位置，後製用來剪接與推鏡）。
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const BASE = process.env.VETLOOP_URL || 'http://127.0.0.1:5051';
const OUT = path.resolve(process.argv[2] || 'raw');
const AI_TIMEOUT = 150_000; // 每次 LLM 約 5–12 秒，含一次重試仍遠低於此
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(OUT, { recursive: true });

const events = [];
const now = () => Date.now() / 1000;

// 假游標：screencast 不會畫滑鼠，自己畫一個跟著 mousemove 走，按下時有漣漪
const CURSOR = `
addEventListener('DOMContentLoaded', () => {
  const c = document.createElement('div');
  c.innerHTML = '<svg width="56" height="56" viewBox="0 0 24 24"><path d="M4 2l15 9.5-6.6 1.4 3.9 7.3-2.6 1.4-3.9-7.3L4 19z" fill="#1B1F24" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
  Object.assign(c.style, { position: 'fixed', left: '-60px', top: '-60px', zIndex: 2147483647, pointerEvents: 'none', filter: 'drop-shadow(0 2px 3px rgba(0,0,0,.35))' });
  document.documentElement.append(c);
  addEventListener('mousemove', (e) => { c.style.left = e.clientX - 8 + 'px'; c.style.top = e.clientY - 4 + 'px'; }, true);
  addEventListener('mousedown', (e) => {
    const r = document.createElement('div');
    Object.assign(r.style, { position: 'fixed', left: e.clientX - 44 + 'px', top: e.clientY - 44 + 'px', width: '88px', height: '88px', borderRadius: '50%', border: '6px solid #D7263D', zIndex: 2147483646, pointerEvents: 'none', transition: 'transform .45s ease-out, opacity .45s ease-out' });
    document.documentElement.append(r);
    requestAnimationFrame(() => { r.style.transform = 'scale(1.8)'; r.style.opacity = '0'; });
    setTimeout(() => r.remove(), 600);
  }, true);
});`;

const ZOOM = 2;

async function openPage(browser, name, url, layout) {
  const viewport = { width: layout.width * ZOOM, height: layout.height * ZOOM };
  const ctx = await browser.newContext({ viewport, deviceScaleFactor: 1, locale: 'zh-TW', timezoneId: 'Asia/Taipei' });
  await ctx.addInitScript(CURSOR);
  // 每個 HTML 回應都先注入 zoom，第一個畫格就是放大後的排版
  await ctx.route('**/*', async (route) => {
    if (route.request().resourceType() !== 'document') return route.continue();
    const resp = await route.fetch({ timeout: 30_000 });
    const body = (await resp.text()).replace('<head>', `<head><style>body{zoom:${ZOOM}}</style>`);
    await route.fulfill({ response: resp, body });
  });
  const page = await ctx.newPage();
  page.setDefaultTimeout(AI_TIMEOUT);
  const dir = path.join(OUT, name);
  fs.mkdirSync(dir);
  const frames = [];
  const cdp = await ctx.newCDPSession(page);
  cdp.on('Page.screencastFrame', async ({ data, metadata, sessionId }) => {
    const file = String(frames.length).padStart(5, '0') + '.jpg';
    fs.writeFileSync(path.join(dir, file), Buffer.from(data, 'base64'));
    frames.push({ file, t: metadata.timestamp });
    await cdp.send('Page.screencastFrameAck', { sessionId }).catch(() => {});
  });
  await page.goto(url);
  await cdp.send('Page.startScreencast', {
    format: 'jpeg', quality: 92, everyNthFrame: 1,
    maxWidth: viewport.width, maxHeight: viewport.height,
  });
  page.mouse.move(viewport.width * 0.6, viewport.height * 0.6);
  return { name, page, cdp, frames, dir, viewport, zoom: ZOOM };
}

async function mark(p, label, sel) {
  const e = { t: now(), page: p.name, label };
  if (sel) {
    const box = await p.page.locator(sel).first().boundingBox().catch(() => null);
    if (box) e.rect = box; // 視窗座標＝畫格像素
  }
  events.push(e);
  console.log(new Date().toISOString().slice(11, 19), p.name, label);
}

// 滑鼠平滑移過去再按，畫面上看得到游標移動
async function click(p, locator) {
  const loc = typeof locator === 'string' ? p.page.locator(locator).first() : locator;
  await loc.scrollIntoViewIfNeeded();
  const b = await loc.boundingBox();
  await p.page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 28 });
  await p.page.waitForTimeout(220);
  await p.page.mouse.down();
  await p.page.waitForTimeout(90);
  await p.page.mouse.up();
}

async function type(p, sel, text, delay = 95) {
  await click(p, sel);
  await p.page.locator(sel).first().pressSequentially(text, { delay });
}

const rows = (p) => p.page.locator('#messages .row').count();

// 飼主傳一則訊息，等到回覆（AI、系統或固定話術）出現
async function ownerSay(p, text, label) {
  const before = await rows(p);
  await type(p, '#text', text);
  await p.page.waitForTimeout(300);
  await click(p, '#send');
  await mark(p, `${label}:sent`);
  await p.page.waitForFunction((n) => document.querySelectorAll('#messages .row').length >= n + 2, before, { timeout: AI_TIMEOUT });
  await p.page.locator('#typing').waitFor({ state: 'hidden' }).catch(() => {});
  await p.page.waitForTimeout(600);
  await mark(p, `${label}:replied`, '#messages .row:last-child');
}

const pause = (p, ms) => p.page.waitForTimeout(ms);

const browser = await chromium.launch();
try {
  // 從乾淨的示範資料開始
  const r = await fetch(`${BASE}/clinic/reset`, { method: 'POST', signal: AbortSignal.timeout(15_000) });
  if (!r.ok) throw new Error(`reset failed: ${r.status}`);

  const phone = await openPage(browser, 'phone1', `${BASE}/phone/1`, { width: 1440, height: 1080 });
  const clinic = await openPage(browser, 'clinic', `${BASE}/clinic`, { width: 1600, height: 900 });
  const phone2 = await openPage(browser, 'phone2', `${BASE}/phone/2`, { width: 1440, height: 1080 });
  await pause(phone, 1500);

  // 1. 飼主問診
  await mark(phone, 'intake:start');
  await ownerSay(phone, '麻糬今天一直在吐', 'intake1');
  await pause(phone, 1200);
  await click(phone, '#demo-photo');
  await pause(phone, 700);
  await ownerSay(phone, '從昨天晚上開始，吐了三次', 'intake2');
  await pause(phone, 1200);
  await ownerSay(phone, '不太想吃，精神還好，最近沒換飼料', 'intake3');
  await pause(phone, 1200);
  await ownerSay(phone, '排便正常，沒有吃藥', 'intake4');
  await pause(phone, 1800);
  await mark(phone, 'confirm:before', '#messages .row:last-child');
  const beforeConfirm = await rows(phone);
  await click(phone, phone.page.locator('.quick .chip', { hasText: '正確，送出' }).last());
  await phone.page.waitForFunction((n) => document.querySelectorAll('#messages .row').length > n, beforeConfirm);
  await pause(phone, 1500);
  await mark(phone, 'confirm:done', '#messages .row:last-child');

  // 2. 獸醫看摘要
  await clinic.page.reload();
  await pause(clinic, 1200);
  await mark(clinic, 'list');
  await click(clinic, clinic.page.locator('tr', { hasText: '麻糬' }).locator('a', { hasText: '開啟案例' }));
  await clinic.page.waitForLoadState('load');
  // 摘要是送出後才由 LLM 產生：還在整理就等「有新動態」提示再點（和真實操作一樣）
  await mark(clinic, 'summary:pending'); // 已經整理好也要記，剪輯表用它當分界
  if ((await clinic.page.locator('#summary').innerText()).includes('正在整理')) {
    await clinic.page.locator('#update-pill').waitFor({ state: 'visible', timeout: AI_TIMEOUT });
    await pause(clinic, 900);
    await click(clinic, '#update-pill');
    await clinic.page.waitForLoadState('load');
    await clinic.page.waitForFunction(() => !document.querySelector('#summary')?.innerText.includes('正在整理'));
  }
  await pause(clinic, 1500);
  await mark(clinic, 'summary', '#summary');
  await pause(clinic, 1500);
  // 慢慢捲到摘要卡底部，讓照片描述與待確認事項入鏡
  await clinic.page.evaluate(() => document.querySelector('#summary').scrollIntoView({ behavior: 'smooth', block: 'end' }));
  await pause(clinic, 2500);
  await mark(clinic, 'summary:scrolled', '#summary');
  await pause(clinic, 1500);
  await clinic.page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }));
  await pause(clinic, 1500);

  // 3. 開醫囑
  await clinic.page.locator('#order').scrollIntoViewIfNeeded();
  await pause(clinic, 800);
  await mark(clinic, 'order:start', '#order');
  await type(clinic, 'input[name=med_name]', '示範藥A', 70);
  await clinic.page.locator('select[name=med_times]').first().selectOption('2');
  await type(clinic, 'input[name=med_timing]', '飯後', 70);
  await clinic.page.locator('input[name=med_days]').first().fill('');
  await type(clinic, 'input[name=med_days]', '5', 70);
  await type(clinic, 'input[name=diet_text]', '當天少量多餐', 70);
  await clinic.page.locator('input[name=diet_days]').fill('');
  await type(clinic, 'input[name=diet_days]', '2', 70);
  await clinic.page.locator('input[name=recheck_days]').fill('');
  await type(clinic, 'input[name=recheck_days]', '3', 70);
  await type(clinic, 'textarea[name=watch]', '若持續嘔吐請來電', 70);
  await pause(clinic, 600);
  await mark(clinic, 'order:filled', '#order');
  await click(clinic, '#order button[type=submit]');
  await mark(clinic, 'order:submitted');
  await clinic.page.locator('#final-text').waitFor({ state: 'visible', timeout: AI_TIMEOUT });
  await pause(clinic, 1800);
  await mark(clinic, 'plan', '#plan');
  await pause(clinic, 2500);

  // 4. 核可，飼主收到醫囑
  const phoneBefore = await rows(phone);
  await click(clinic, clinic.page.locator('#plan button', { hasText: '核可並送出' }));
  await mark(clinic, 'plan:approved');
  await phone.page.waitForFunction((n) => document.querySelectorAll('#messages .row').length > n, phoneBefore);
  await pause(phone, 1500);
  await mark(phone, 'plan:received', '#messages .row:last-child');
  await pause(clinic, 1500);

  // 5. 提醒與已餵
  const beforeRem = await rows(phone);
  await click(clinic, clinic.page.locator('button', { hasText: '快轉到下一個提醒' }));
  await mark(clinic, 'remind:ff');
  await phone.page.waitForFunction((n) => document.querySelectorAll('#messages .row').length > n, beforeRem);
  await pause(phone, 1500);
  await mark(phone, 'remind:received', '#messages .row:last-child');
  await click(phone, phone.page.locator('.quick .chip', { hasText: '已餵' }).last());
  await pause(phone, 1800);
  await mark(phone, 'remind:acked', '#messages .row:last-child');

  // 6. 照護期間回報 → 待審佇列 → 獸醫改字核可
  await ownerSay(phone, '吃完藥又吐了一次', 'followup');
  await pause(phone, 1000);
  await click(clinic, clinic.page.locator('nav a', { hasText: '待審佇列' }));
  await clinic.page.waitForLoadState('load');
  // 草稿是 LLM 產生的，可能還沒好：等「新動態」提示或直接重新整理
  const deadline = Date.now() + AI_TIMEOUT;
  while (!(await clinic.page.locator('form.pane.edit textarea[name=final_text]').count())) {
    if (Date.now() > deadline) throw new Error('reply draft did not arrive');
    await pause(clinic, 2500);
    if (await clinic.page.locator('#update-pill').isVisible()) await click(clinic, '#update-pill');
    else await clinic.page.reload();
  }
  await pause(clinic, 1500);
  await mark(clinic, 'queue', 'form.pane.edit');
  const ta = clinic.page.locator('form.pane.edit textarea[name=final_text]').first();
  await click(clinic, ta);
  await ta.press('End');
  await ta.pressSequentially('今晚若再吐，請直接來電。', { delay: 80 });
  await pause(clinic, 900);
  await mark(clinic, 'queue:edited', 'form.pane.edit');
  const beforeReply = await rows(phone);
  await click(clinic, clinic.page.locator('form.pane.edit button', { hasText: '核可並送出' }));
  await mark(clinic, 'queue:approved');
  await phone.page.waitForFunction((n) => document.querySelectorAll('#messages .row').length > n, beforeReply);
  await pause(phone, 1800);
  await mark(phone, 'reply:received', '#messages .row:last-child');

  // 7. 緊急分流
  await click(clinic, clinic.page.locator('nav a', { hasText: '案例列表' }));
  await clinic.page.waitForLoadState('load');
  await pause(clinic, 1000);
  await ownerSay(phone2, '牠剛剛好像吞了一段繩子', 'emergency');
  await clinic.page.locator('#alert-list .alert-item').first().waitFor({ state: 'visible', timeout: 20_000 });
  await pause(clinic, 2500);
  await mark(clinic, 'emergency:alert', '#alerts');
  await pause(clinic, 3500); // 最後一個鏡頭用到 emergency:alert 後 5.2 秒（片段會多留 2 秒）
  await mark(clinic, 'end');

  // 先停錄，下面切到案例頁收文字時才不會錄進去
  for (const p of [phone, clinic, phone2]) await p.cdp.send('Page.stopScreencast').catch(() => {});

  // 收尾：把最後的文字存下來，後製前人工檢查有沒有病名或診斷用語
  const texts = {};
  for (const p of [phone, phone2]) texts[p.name] = await p.page.locator('#messages').innerText();
  texts.clinic_alerts = await clinic.page.locator('#alerts').innerText();
  await clinic.page.goto(`${BASE}/clinic/case/1`);
  texts.clinic_case = await clinic.page.locator('#case-page').innerText();
  fs.writeFileSync(path.join(OUT, 'texts.json'), JSON.stringify(texts, null, 2));

  for (const p of [phone, clinic, phone2]) {
    fs.writeFileSync(path.join(p.dir, 'frames.json'), JSON.stringify({ zoom: p.zoom, viewport: p.viewport, frames: p.frames }));
  }
  fs.writeFileSync(path.join(OUT, 'events.json'), JSON.stringify(events, null, 2));
  console.log('done', OUT);
} finally {
  await browser.close();
}

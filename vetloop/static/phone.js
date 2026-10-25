// 飼主手機畫面：每 1.5 秒輪詢案例狀態。訊息是不可信的資料：一律用 textContent 組 DOM。
(() => {
  const app = document.getElementById('phone-app');
  const caseId = app.dataset.caseId;
  const $ = (id) => document.getElementById(id);
  const chat = $('chat'), list = $('messages'), typing = $('typing'), toast = $('toast');
  const input = $('text'), sendBtn = $('send'), fileInput = $('file'), demoBtn = $('demo-photo');
  const POLL_MS = 1500;
  const POST_TIMEOUT_MS = 240000; // 後端同步呼叫 LLM，最壞情況照片加抽欄位各重試一次；POST 不自動重送，免得訊息重複

  let state = null;     // 最近一次的 /api/case/<id>
  let sending = false;  // 有 POST 在等 LLM：暫停輪詢，免得跟本地泡泡重複
  let pending = null;   // {text, image}：先畫上去的飼主泡泡
  let attached = null;  // 選好、還沒送的照片 File
  let lastSig = '';
  let epoch = 0;        // 每次送出加 1：送出前就發出去的輪詢，回來時資料已過期，要丟掉
  let stick = true;     // 內容變長（例如照片載入）時是否維持捲在最底
  let firstRender = true;
  let toastTimer = 0;
  const seen = {};      // 問診欄位上一次的值，用來標出剛抽到的欄位

  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  };

  async function api(url, opts = {}, timeout = 5000) {
    const res = await fetch(url, { ...opts, signal: AbortSignal.timeout(timeout) });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `發生錯誤（${res.status}）`);
    return data;
  }

  function showToast(message) {
    toast.textContent = message;
    toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toast.hidden = true; }, 6000);
  }

  // ---- 按鈕是否還能按 ----
  function lastConfirmId() {
    for (let i = state.messages.length - 1; i >= 0; i--) {
      if (state.messages[i].actions.some((a) => a.action === 'confirm')) return state.messages[i].id;
    }
    return null;
  }
  function isLive(action, msg) {
    if (action.action === 'confirm' || action.action === 'edit') {
      return state.case.status === 'awaiting_confirm' && msg.id === lastConfirmId();
    }
    const reminder = state.reminders.find((r) => r.id === action.reminder_id);
    return !!reminder && !reminder.acked_at;
  }

  // ---- 聊天 ----
  function textBlock(text) {
    const box = el('div', 'text');
    const note = state.notes.find((n) => text.includes(n)); // 提示文字用小字，但完整顯示
    if (!note) { box.append(el('div', null, text)); return box; }
    const i = text.indexOf(note);
    const before = text.slice(0, i).replace(/\s+$/, ''), after = text.slice(i + note.length).trim();
    if (before) box.append(el('div', null, before));
    box.append(el('div', 'note', note));
    if (after) box.append(el('div', null, after));
    return box;
  }

  function whoLabel(sender) {
    return { ai: 'AI 問診助理', vet: state.case.vet_name, system: '系統' }[sender];
  }

  function bubble(m) {
    const row = el('div', `row ${m.sender}`);
    if (m.sender !== 'owner') row.append(el('div', 'who', whoLabel(m.sender)));
    const line = el('div', 'line');
    const b = el('div', 'bubble');
    if (m.image) {
      const img = el('img', 'photo');
      img.src = m.image;
      img.alt = '飼主上傳的照片';
      img.addEventListener('load', () => { if (stick) chat.scrollTop = chat.scrollHeight; });
      b.append(img);
    }
    if (m.text) b.append(textBlock(m.text));
    line.append(b, el('span', 'time', m.time || ''));
    row.append(line);
    if (m.actions.length) {
      const quick = el('div', 'quick');
      for (const a of m.actions) {
        const btn = el('button', `chip${a.action === 'confirm' || a.action === 'ack' ? ' primary' : ''}`, a.label);
        btn.type = 'button';
        btn.disabled = sending || !isLive(a, m);
        btn.addEventListener('click', () => act(a));
        quick.append(btn);
      }
      row.append(quick);
    }
    return row;
  }

  function renderChat() {
    if (!state) return;
    const sig = state.messages.map((m) => m.id + ':' + m.actions.map((a) => +isLive(a, m)).join('')).join('|')
      + '#' + (pending ? pending.text + (pending.image ? '+img' : '') : '') + sending;
    if (sig === lastSig) return;
    lastSig = sig;
    const nearBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 90;
    const rows = state.messages.map(bubble);
    if (pending) {
      const b = el('div', 'bubble');
      if (pending.image) { const img = el('img', 'photo'); img.src = pending.image; b.append(img); }
      if (pending.text) b.append(textBlock(pending.text));
      const row = el('div', 'row owner');
      const line = el('div', 'line');
      line.append(b);
      row.append(line);
      rows.push(row);
    }
    list.replaceChildren(...rows);
    typing.hidden = !sending;
    stick = nearBottom || sending || firstRender;
    if (stick) chat.scrollTo({ top: chat.scrollHeight, behavior: firstRender ? 'instant' : 'smooth' });
    firstRender = false;
  }

  // ---- 問診欄位面板 ----
  let panelSig = '';
  function renderPanel() {
    if (!state) return;
    const sig = JSON.stringify([state.fields, state.photo, state.case.status_label]);
    if (sig === panelSig) return; // 沒變就不重畫，剛抽到欄位的標示動畫才不會被打斷
    panelSig = sig;
    const required = state.fields.filter((f) => f.required);
    const done = required.filter((f) => f.value).length;
    $('count').textContent = `${done} / ${required.length}`;
    $('bar-fill').style.width = `${(done / Math.max(required.length, 1)) * 100}%`;
    $('phase').textContent = state.case.status_label;
    $('fields').replaceChildren(...state.fields.map((f) => {
      const li = el('li', f.value ? 'done' : '');
      if (f.value && seen[f.key] !== undefined && seen[f.key] !== f.value) li.classList.add('fresh');
      seen[f.key] = f.value;
      li.append(el('span', 'mark'), el('span', 'label', f.label), el('span', 'value', f.value || '尚未取得'));
      return li;
    }));
    const desc = $('photo-desc');
    desc.textContent = state.photo ? '已收到照片。AI 的照片描述只給醫院看。' : '尚未上傳照片';
    desc.classList.toggle('empty', !state.photo);
    const photo = $('panel-photo');
    photo.hidden = !state.photo;
    if (state.photo && photo.getAttribute('src') !== state.photo) photo.src = state.photo;
  }

  function update(next) {
    state = next;
    renderPanel();
    renderChat();
  }

  async function poll() {
    if (sending) return;
    const mine = epoch;
    try {
      const next = await api(`/api/case/${caseId}`);
      if (!sending && mine === epoch) update(next);
    } catch { /* 下一輪再試 */ }
  }

  // ---- 送出 ----
  function setBusy(busy) {
    sending = busy;
    for (const e of [input, sendBtn, demoBtn, $('attach-btn')]) e.disabled = busy;
  }

  // 先把飼主泡泡畫上去並顯示「輸入中…」，等後端（同步呼叫 LLM）回來再換成真資料
  async function run(pendingMsg, request, onError) {
    setBusy(true);
    epoch++;
    pending = pendingMsg;
    lastSig = '';
    renderChat();
    let next = null;
    try {
      next = await request();
    } catch (e) {
      showToast(e.name === 'TimeoutError' ? '等太久了，請稍後再看看對話是否已更新' : e.message);
      onError?.();
    }
    pending = null;
    lastSig = '';
    epoch++;
    setBusy(false);
    if (next) update(next); else renderChat();
    if (!input.disabled) input.focus();
  }

  function setAttachment(file) {
    attached = file;
    $('attach-chip').hidden = !file;
    if (file) {
      $('attach-thumb').src = URL.createObjectURL(file);
      $('attach-name').textContent = file.name;
    }
  }

  async function send(file = attached) {
    const text = input.value.trim();
    if (sending || (!text && !file)) return;
    const form = new FormData();
    form.append('text', text);
    if (file) form.append('image', file, file.name);
    const preview = file ? URL.createObjectURL(file) : null;
    input.value = '';
    setAttachment(null);
    await run({ text, image: preview },
      () => api(`/api/case/${caseId}/message`, { method: 'POST', body: form }, POST_TIMEOUT_MS),
      () => { input.value = text; setAttachment(file); });
    if (preview) URL.revokeObjectURL(preview);
  }

  async function act(action) {
    if (sending) return;
    await run({ text: action.label },
      () => api(`/api/case/${caseId}/action`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: action.action, reminder_id: action.reminder_id ?? null }),
      }, POST_TIMEOUT_MS));
  }

  $('composer').addEventListener('submit', (e) => { e.preventDefault(); send(); });
  input.addEventListener('keydown', (e) => {
    // 注音／拼音選字時的 Enter 是選字，不是送出
    if (e.key === 'Enter' && (e.isComposing || e.keyCode === 229)) e.preventDefault();
  });
  $('attach-btn').addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', () => {
    setAttachment(fileInput.files[0] || null);
    fileInput.value = '';
  });
  $('attach-remove').addEventListener('click', () => setAttachment(null));

  // 錄影用：不用從檔案選，直接把示範照片放進附件，再按送出
  demoBtn.addEventListener('click', async () => {
    if (sending) return;
    try {
      const res = await fetch('/static/demo/vomit.png', { signal: AbortSignal.timeout(5000) });
      if (!res.ok) throw new Error();
      setAttachment(new File([await res.blob()], 'vomit.png', { type: 'image/png' }));
    } catch {
      showToast('讀不到示範照片');
    }
  });

  poll();
  setInterval(poll, POLL_MS);
})();

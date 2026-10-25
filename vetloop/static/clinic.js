// 醫院後台：表單用 fetch 送出（錯誤就地顯示）、醫囑表單互動、新動態與緊急通知輪詢。
(() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const POLL_MS = 2000;
  const POST_TIMEOUT_MS = 240000; // 後端同步呼叫 LLM；POST 不自動重送，免得重複核可

  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  };

  async function request(url, opts = {}, timeout = 5000) {
    const res = await fetch(url, { ...opts, signal: AbortSignal.timeout(timeout) });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `發生錯誤（${res.status}）`);
    return data;
  }

  function formError(form, message) {
    const box = $('.form-error', form);
    if (!box) { alert(message); return; }
    box.textContent = message;
    box.hidden = !message;
  }

  // 目標是同一頁（例如只差 #plan）時瀏覽器不會重新載入，要自己 reload
  function go(next) {
    const url = new URL(next, location.href);
    if (url.pathname === location.pathname) {
      history.replaceState(null, '', url.pathname + url.search + url.hash);
      location.reload();
    } else {
      location.href = url.href;
    }
  }

  // 送出醫囑後以 #plan reload：瀏覽器會還原舊的捲動位置，要自己捲到錨點
  if (location.hash) {
    history.scrollRestoration = 'manual';
    addEventListener('load', () => document.getElementById(location.hash.slice(1))?.scrollIntoView({ block: 'start' }));
  }

  // ---- data-async 表單 ----
  document.addEventListener('submit', async (e) => {
    const form = e.target.closest('form[data-async]');
    if (!form) return;
    e.preventDefault();
    if (form.dataset.confirm && !confirm(form.dataset.confirm)) return;
    const button = $('button[type=submit]', form);
    const label = button.textContent;
    formError(form, '');
    button.disabled = true;
    button.textContent = form.dataset.busy || '處理中…';
    try {
      const data = await request(form.action, { method: 'POST', body: new FormData(form) }, POST_TIMEOUT_MS);
      go(data.next || location.href);
    } catch (err) {
      formError(form, err.name === 'TimeoutError' ? '等待逾時，請重新整理頁面確認結果' : err.message);
      button.disabled = false;
      button.textContent = label;
    }
  });
  // 從上一頁回來時，別讓按鈕卡在「處理中」
  addEventListener('pageshow', (e) => { if (e.persisted) location.reload(); });

  // ---- 醫囑表單 ----
  const meds = $('#meds');
  if (meds) {
    $('#add-med').addEventListener('click', () => {
      meds.append($('#med-tpl').content.cloneNode(true));
      meds.lastElementChild.querySelector('input').focus();
    });
    meds.addEventListener('click', (e) => {
      const remove = e.target.closest('[data-remove]');
      if (remove && meds.children.length > 1) remove.closest('.med-row').remove();
    });
  }

  // 補充欄位的語音輸入：瀏覽器有 Web Speech API 才顯示麥克風
  const mic = $('#mic');
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (mic && Recognition) {
    const note = $('#note');
    let rec = null;
    mic.hidden = false;
    mic.addEventListener('click', () => {
      if (rec) { rec.stop(); return; }
      rec = new Recognition();
      rec.lang = 'zh-TW';
      rec.continuous = true;
      rec.interimResults = false;
      rec.onresult = (ev) => {
        let said = '';
        for (let i = ev.resultIndex; i < ev.results.length; i++) {
          if (ev.results[i].isFinal) said += ev.results[i][0].transcript;
        }
        if (said.trim()) note.value = (note.value ? note.value.trimEnd() + ' ' : '') + said.trim();
      };
      rec.onerror = (ev) => formError(note.form, `語音輸入失敗（${ev.error}），請改用鍵盤輸入`);
      rec.onend = () => { rec = null; mic.classList.remove('on'); };
      try { rec.start(); mic.classList.add('on'); } catch { rec = null; }
    });
  }

  // ---- 新動態提示 ----
  const pill = $('#update-pill');
  pill.addEventListener('click', () => location.reload());
  const poll = (fn) => setInterval(() => fn().catch(() => {}), POLL_MS); // 失敗就等下一輪

  const navBadge = $('[data-pending]');
  const setPending = (n) => {
    navBadge.textContent = n;
    navBadge.hidden = !n;
    for (const e of document.querySelectorAll('[data-pending-num]')) e.textContent = n;
  };

  const casePage = $('#case-page');
  if (casePage) {
    poll(async () => {
      const s = await request(`/api/case/${casePage.dataset.caseId}`);
      if (s.sig !== casePage.dataset.sig) pill.hidden = false;
    });
  }

  const queuePage = $('#queue-page');
  if (queuePage) {
    poll(async () => {
      const s = await request('/api/clinic');
      setPending(s.pending);
      if (String(s.pending) !== queuePage.dataset.count) pill.hidden = false;
    });
  }

  // ---- 案例列表與緊急通知 ----
  const listPage = $('#clinic-list');
  if (listPage) {
    const box = $('#alerts'), listEl = $('#alert-list'), count = $('#alert-count');
    const baseTitle = document.title;
    let alertSig = null;

    function alertItem(a) {
      const item = el('div', `alert-item${a.seen ? '' : ' new'}`);
      const actions = el('div', 'alert-actions');
      const open = el('a', 'btn small', '開啟案例');
      open.href = `/clinic/case/${a.case_id}`;
      actions.append(open);
      if (!a.seen) {
        const ok = el('button', 'btn small', '知道了');
        ok.type = 'button';
        ok.addEventListener('click', async () => {
          try { renderAlerts(await request(`/api/alerts/${a.id}/seen`, { method: 'POST' })); } catch { /* 下一輪輪詢會更新 */ }
        });
        actions.append(ok);
      }
      item.append(el('strong', null, a.seen ? '已讀' : '緊急'), el('time', null, a.time), el('div', 'alert-text', a.text), actions);
      return item;
    }

    function renderAlerts(data) {
      const sig = JSON.stringify(data.alerts.map((a) => [a.id, a.seen]));
      if (sig === alertSig) return;
      alertSig = sig;
      box.classList.toggle('has-new', data.unseen > 0);
      count.hidden = !data.unseen;
      count.textContent = `${data.unseen} 則未讀`;
      document.title = (data.unseen ? '(!) 緊急通知　' : '') + baseTitle;
      listEl.replaceChildren(...(data.alerts.length
        ? data.alerts.map(alertItem)
        : [el('p', 'alert-empty', '目前沒有緊急通知')]));
    }

    renderAlerts(JSON.parse($('#boot').textContent));
    poll(async () => {
      renderAlerts(await request('/api/alerts'));
      const s = await request('/api/clinic');
      setPending(s.pending);
      for (const c of s.cases) {
        const badge = $(`[data-status-for="${c.id}"]`);
        if (badge) { badge.textContent = c.status_label; badge.className = `badge s-${c.status}`; }
      }
    });
  }
})();

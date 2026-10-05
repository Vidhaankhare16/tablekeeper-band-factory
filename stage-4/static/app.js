/* Tablekeeper core: DOM helper, session, API client, header, formatting, router. */
(function () {
  'use strict';
  const TK = (window.TK = { pages: {} });

  /* ---------- DOM helper ---------- */
  TK.h = function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'testid') el.setAttribute('data-testid', v);
      else if (k === 'text') el.textContent = v;
      else if (k.slice(0, 2) === 'on') el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? '' : String(v));
    }
    (function add(list) {
      for (const kid of list) {
        if (kid == null || kid === false) continue;
        if (Array.isArray(kid)) add(kid);
        else el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
      }
    })(kids);
    return el;
  };
  const h = TK.h;
  TK.clear = (el) => { while (el.firstChild) el.removeChild(el.firstChild); return el; };

  /* ---------- session (token survives reloads and server upgrades) ---------- */
  const SKEY = 'tk.session';
  let memSession = null;
  const listeners = [];
  TK.onSession = (fn) => listeners.push(fn);
  const notify = () => listeners.forEach((fn) => { try { fn(TK.session.get()); } catch (e) { /* keep going */ } });
  TK.session = {
    get() {
      try { const raw = localStorage.getItem(SKEY); return raw ? JSON.parse(raw) : memSession; }
      catch (e) { return memSession; }
    },
    set(s) {
      memSession = s;
      try { localStorage.setItem(SKEY, JSON.stringify(s)); } catch (e) { /* memory fallback */ }
      notify();
    },
    clear() {
      memSession = null;
      try { localStorage.removeItem(SKEY); } catch (e) { /* ignore */ }
      notify();
    },
  };

  /* ---------- API client ---------- */
  TK.NetworkError = class NetworkError extends Error {};
  /* Resolves {status, ok, data, code, message}. Rejects with NetworkError when no
     complete response arrived (offline, aborted, timeout, body cut off). */
  TK.api = async function api(path, opts) {
    const { method = 'GET', body, headers = {}, auth = true, timeout = 10000 } = opts || {};
    const hdr = Object.assign({ Accept: 'application/json' }, headers);
    const sess = TK.session.get();
    if (auth && sess) hdr.Authorization = 'Bearer ' + sess.token;
    let payload;
    if (body !== undefined) { hdr['Content-Type'] = 'application/json'; payload = JSON.stringify(body); }
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), timeout);
    let status, text;
    try {
      const res = await fetch(path, { method, headers: hdr, body: payload, signal: ctl.signal, cache: 'no-store' });
      status = res.status;
      text = await res.text();
    } catch (e) {
      throw new TK.NetworkError(String(e && e.message));
    } finally {
      clearTimeout(timer);
    }
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (e) { data = null; }
    const err = data && data.error ? data.error : {};
    // Only the server saying 401 for the token we sent ends the session.
    if (status === 401 && auth && sess && (TK.session.get() || {}).token === sess.token) TK.session.clear();
    return { status, ok: status >= 200 && status < 300, data, code: err.code || null, message: err.message || null };
  };

  TK.newKey = function newKey() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    const a = new Uint8Array(16);
    if (window.crypto && crypto.getRandomValues) crypto.getRandomValues(a);
    else for (let i = 0; i < 16; i++) a[i] = Math.floor(Math.random() * 256);
    return Array.from(a, (b) => b.toString(16).padStart(2, '0')).join('');
  };

  /* ---------- formatting ---------- */
  const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
  const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  TK.fmtDate = function (ymd) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(ymd || '');
    if (!m) return ymd || '';
    const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
    return `${DAYS[d.getUTCDay()]} ${+m[3]} ${MONTHS[+m[2] - 1]} ${m[1]}`;
  };
  TK.fmtTime = (local) => (local || '').slice(11, 16);
  TK.fmtWhen = (local) => `${TK.fmtDate(local)} at ${TK.fmtTime(local)}`;
  TK.tableWord = (labels) => (labels.length > 1 ? 'Tables ' : 'Table ') + labels.join(' + ');
  TK.labelsFor = function (restaurant, ids) {
    const by = {};
    ((restaurant && restaurant.tables) || []).forEach((t) => { by[t.id] = t.label; });
    return (ids || []).map((id) => (by[id] != null ? String(by[id]) : String(id)));
  };
  TK.tableIdsOf = (r) => (Array.isArray(r.table_ids) ? r.table_ids : r.table_id ? [r.table_id] : []);

  /* ---------- shared message boxes ---------- */
  TK.notice = function (kind, text, attrs) {
    return h('div', Object.assign({ class: 'notice notice-' + kind, role: kind === 'error' ? 'alert' : 'status' }, attrs), text);
  };

  /* ---------- header ---------- */
  function renderHeader() {
    const host = document.getElementById('site-header');
    const path = TK.path();
    const sess = TK.session.get();
    const link = (href, text) => h('a', { href, 'aria-current': path === href ? 'page' : null }, text);
    const account = sess
      ? [
          h('span', { class: 'user' },
            h('span', { class: 'avatar', 'aria-hidden': 'true' }, (sess.display_name || '?').trim().charAt(0).toUpperCase()),
            h('span', { testid: 'current-user' }, sess.display_name || '')),
          h('button', { type: 'button', class: 'btn secondary', testid: 'logout-button', onclick: () => TK.session.clear() }, 'Log out'),
        ]
      : [link('/login', 'Log in'), h('a', { class: 'btn primary', href: '/signup' }, 'Sign up')];
    TK.clear(host).append(
      h('header', { class: 'site-header' },
        h('div', { class: 'wrap' },
          h('a', { class: 'brand', href: '/' }, h('span', { class: 'brand-mark', 'aria-hidden': 'true' }), 'Tablekeeper'),
          h('nav', { class: 'nav', 'aria-label': 'Main' }, link('/', 'Book a table'), link('/lookup', 'Find a booking')),
          h('div', { class: 'account' }, account))));
  }

  /* ---------- router ---------- */
  TK.path = function () {
    const p = location.pathname.replace(/\.html$/, '').replace(/\/+$/, '');
    return p === '' || p === '/index' ? '/' : p;
  };
  TK.start = function () {
    renderHeader();
    TK.onSession(renderHeader);
    const main = document.getElementById('main');
    const page = { '/': 'search', '/signup': 'signup', '/login': 'login', '/lookup': 'lookup' }[TK.path()] || 'search';
    TK.pages[page](main);
  };
})();

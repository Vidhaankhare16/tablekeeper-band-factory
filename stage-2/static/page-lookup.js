/* Look up a reservation by reference; cancel it. */
(function () {
  'use strict';
  const { h, api } = TK;

  const ERRORS = {
    not_found: 'We could not find a booking with that reference on your account. Check the code and try again.',
    cutoff_passed: 'This booking is too close to its start time to cancel online. Please contact the restaurant.',
    unauthenticated: 'Please log in to look up your booking.',
  };

  TK.pages.lookup = function (main) {
    let seq = 0;
    const input = h('input', { id: 'lk-ref', type: 'text', testid: 'lookup-reference-input', autocomplete: 'off', autocapitalize: 'characters', spellcheck: 'false' });
    const out = h('div', { 'aria-live': 'polite' });
    const hintHost = h('div');
    const form = h('form', { class: 'inline-form', novalidate: true },
      h('div', { class: 'field' }, h('label', { for: 'lk-ref' }, 'Confirmation reference'), input),
      h('button', { type: 'submit', class: 'btn primary', testid: 'lookup-submit' }, 'Find booking'));
    main.append(h('section', { class: 'panel' },
      h('p', { class: 'eyebrow' }, 'Your reservation'), h('h1', null, 'Find a booking'),
      h('p', { class: 'muted' }, 'Enter the reference from your confirmation to see or cancel a booking.'), hintHost, form), out);

    const showHint = () => {
      TK.clear(hintHost);
      if (!TK.session.get()) hintHost.append(TK.notice('info', h('span', null, 'Bookings are private. ', h('a', { href: '/login' }, 'Log in'), ' to look yours up.')));
    };
    showHint();
    TK.onSession((s) => { showHint(); if (!s) { seq++; TK.clear(out); } });

    const showError = (code, fallback) => out.append(TK.notice('error', ERRORS[code] || fallback || 'Something went wrong. Please try again.', { 'data-testid': 'reservation-error' }));

    async function restaurantOf(id) {
      try { const r = await api('/restaurants/' + encodeURIComponent(id), { auth: false }); return r.ok ? r.data : null; }
      catch (e) { return null; }
    }

    function detail(res, rest) {
      const labels = TK.labelsFor(rest, TK.tableIdsOf(res));
      const status = h('span', { class: 'status status-' + res.status, testid: 'reservation-status' }, res.status);
      const cancelHost = h('div', { class: 'actions' });
      const msgs = h('div', { 'aria-live': 'polite' });
      const box = h('section', { class: 'panel', testid: 'reservation-detail' },
        h('div', { class: 'detail-head' }, h('h2', null, rest ? rest.name : 'Your reservation'), status),
        h('dl', { class: 'kv' },
          h('dt', null, 'Reference'), h('dd', null, res.reference),
          h('dt', null, 'Table'), h('dd', { testid: 'reservation-tables' }, TK.tableWord(labels)),
          h('dt', null, 'When'), h('dd', null, TK.fmtWhen(res.starts_at_local)),
          h('dt', null, 'Party size'), h('dd', null, res.party_size)),
        msgs, cancelHost);
      if (res.status === 'confirmed') {
        const btn = h('button', { type: 'button', class: 'btn danger', testid: 'reservation-cancel-button' }, 'Cancel reservation');
        let busy = false;
        const mine = seq;
        btn.addEventListener('click', async () => {
          if (busy) return;
          busy = true; btn.disabled = true; btn.textContent = 'Cancelling…';
          TK.clear(msgs);
          try {
            const r = await api('/reservations/' + encodeURIComponent(res.reference) + '/cancel', { method: 'POST' });
            if (mine !== seq) return;
            if (r.ok && r.data && r.data.status) {
              status.textContent = r.data.status;
              status.className = 'status status-' + r.data.status;
              if (r.data.status === 'cancelled') { btn.remove(); msgs.append(TK.notice('ok', 'This booking is cancelled and the table is free again.')); return; }
            }
            showErrorIn(msgs, r.code, r.status === 401 ? null : r.message);
          } catch (e) {
            if (mine !== seq) return;
            showErrorIn(msgs, null, 'We could not reach the server, so we cannot tell if the booking was cancelled. Please try again.');
          }
          busy = false; btn.disabled = false; btn.textContent = 'Cancel reservation';
        });
        cancelHost.append(btn);
      }
      return box;
    }
    function showErrorIn(host, code, fallback) {
      host.append(TK.notice('error', ERRORS[code] || fallback || 'Something went wrong. Please try again.', { 'data-testid': 'reservation-error' }));
    }

    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const ref = input.value.trim().toUpperCase();
      const mine = ++seq;
      TK.clear(out);
      if (!ref) { showError(null, 'Enter the reference from your confirmation.'); return; }
      out.append(h('div', { class: 'skeleton', role: 'status', 'aria-label': 'Looking up booking' }, h('span')));
      try {
        const r = await api('/reservations/' + encodeURIComponent(ref));
        if (mine !== seq) return;
        TK.clear(out);
        if (!r.ok || !r.data) { showError(r.code, r.status === 401 ? null : r.message); return; }
        const rest = await restaurantOf(r.data.restaurant_id);
        if (mine !== seq) return;
        out.append(detail(r.data, rest));
      } catch (e) {
        if (mine !== seq) return;
        TK.clear(out);
        showError(null, 'We could not reach the server. Please try again.');
      }
    });
  };
})();

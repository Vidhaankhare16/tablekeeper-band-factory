/* Search + availability grid + booking form + confirmation. */
(function () {
  'use strict';
  const { h, api, clear } = TK;
  const enc = encodeURIComponent;

  const BOOK_ERRORS = {
    table_unavailable: 'Sorry, that table was just taken. We have refreshed the times: change your choice below or pick another slot.',
    party_exceeds_capacity: 'That party is too large for the selected table(s). Lower the party size or choose a bigger table.',
    not_on_slot_grid: 'That start time is not one of the restaurant\'s booking times.',
    outside_opening_hours: 'The restaurant is not open for that whole booking.',
    invalid_local_time: 'That local time does not exist on that date.',
    combination_not_allowed: 'Those tables cannot be combined.',
    unauthenticated: 'Your session has ended. Please log in again to book.',
    validation_failed: 'Please check the party size and try again.',
  };

  const pad = (n) => String(n).padStart(2, '0');
  const today = () => { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };
  const pairKey = (ids) => ids.slice().sort().join('+');

  TK.pages.search = function (main) {
    const st = { seq: 0, rseq: 0, last: null, view: null, form: null, restaurants: [] };

    /* ----- search card ----- */
    const select = h('select', { id: 's-rest', testid: 'restaurant-select' }, h('option', { value: '' }, 'Loading restaurants…'));
    const date = h('input', { id: 's-date', type: 'date', testid: 'date-input', value: today() });
    const party = h('input', { id: 's-party', type: 'number', min: '1', step: '1', inputmode: 'numeric', testid: 'party-size-input', value: '2' });
    const cardMsg = h('div', { 'aria-live': 'polite' });
    const form = h('form', { class: 'form-grid search-grid', novalidate: true },
      h('div', { class: 'field' }, h('label', { for: 's-rest' }, 'Restaurant'), select),
      h('div', { class: 'field' }, h('label', { for: 's-date' }, 'Date'), date),
      h('div', { class: 'field' }, h('label', { for: 's-party' }, 'Guests'), party),
      h('button', { type: 'submit', class: 'btn primary', testid: 'search-button' }, 'Find tables'));
    const results = h('div', { id: 'results', 'aria-live': 'polite' });
    const booking = h('div', { id: 'booking' });
    main.append(
      h('section', { class: 'hero' },
        h('p', { class: 'eyebrow' }, 'Reserve a table'), h('h1', null, 'Where are you dining?'),
        h('p', null, 'Pick a restaurant, a day and your party size to see every table and time at a glance.')),
      h('section', { class: 'panel' }, form, cardMsg), results, booking);

    async function loadRestaurants() {
      clear(cardMsg);
      try {
        const r = await api('/restaurants', { auth: false });
        if (!r.ok || !r.data) throw new Error('bad');
        st.restaurants = r.data.restaurants || [];
        clear(select);
        if (!st.restaurants.length) select.append(h('option', { value: '' }, 'No restaurants yet'));
        st.restaurants.forEach((x) => select.append(h('option', { value: x.id }, x.name)));
      } catch (e) {
        clear(select).append(h('option', { value: '' }, 'Unavailable'));
        cardMsg.append(TK.notice('error', h('span', null, 'We could not load the restaurants. ',
          h('button', { type: 'button', class: 'btn secondary', onclick: loadRestaurants }, 'Try again'))));
      }
    }

    form.addEventListener('submit', (ev) => { ev.preventDefault(); search(); });

    function readParams() {
      const p = { restaurant_id: select.value, date: date.value, party: party.value.trim() };
      if (!p.restaurant_id) return { error: 'Choose a restaurant.' };
      if (!p.date) return { error: 'Choose a date.' };
      if (!/^\d+$/.test(p.party) || +p.party < 1) return { error: 'Enter a whole number of guests, 1 or more.' };
      return { params: p };
    }

    function search() {
      clear(cardMsg);
      const { params, error } = readParams();
      if (error) { cardMsg.append(TK.notice('error', error, { 'data-testid': 'search-error' })); return; }
      run(params, false);
    }

    function fetchView(p) {
      const q = `restaurant_id=${enc(p.restaurant_id)}&date=${enc(p.date)}&party_size=${enc(p.party)}`;
      return Promise.all([api('/restaurants/' + enc(p.restaurant_id), { auth: false }), api('/availability?' + q, { auth: false })])
        .then(([rest, av]) => {
          if (!rest.ok || !av.ok || !rest.data || !av.data) { const e = new Error('bad'); e.res = !av.ok ? av : rest; throw e; }
          return { restaurant: rest.data, slots: av.data.slots || [], params: p };
        });
    }

    /* Late responses never win: every user search takes a new sequence number and only the
       latest may render. A background refresh additionally yields to any newer user search. */
    async function run(params, refresh) {
      let mySeq, myR;
      if (refresh) { mySeq = st.seq; myR = ++st.rseq; }
      else { mySeq = ++st.seq; st.rseq++; st.form = null; st.view = null; renderBooking(); renderResults('loading'); }
      try {
        const view = await fetchView(params);
        if (mySeq !== st.seq || (refresh && myR !== st.rseq)) return;
        st.view = view; st.last = params;
        renderResults();
      } catch (e) {
        if (mySeq !== st.seq || (refresh && myR !== st.rseq)) return;
        if (refresh) { renderResults(null, 'We could not refresh the times just now. Search again to see the latest.'); return; }
        renderResults('error');
      }
    }

    /* ----- results ----- */
    function renderResults(mode, note) {
      clear(results);
      results.setAttribute('aria-busy', mode === 'loading' ? 'true' : 'false');
      if (mode === 'loading') {
        results.append(h('section', { class: 'panel' }, h('div', { class: 'skeleton', role: 'status', 'aria-label': 'Finding tables' }, h('span'), h('span'), h('span'))));
        return;
      }
      if (mode === 'error') {
        results.append(h('section', { class: 'panel' }, TK.notice('error', h('span', null, 'We could not load availability. ',
          h('button', { type: 'button', class: 'btn secondary', onclick: search }, 'Try again')), { 'data-testid': 'search-error' })));
        return;
      }
      const v = st.view;
      if (!v) {
        results.append(h('section', { class: 'panel empty' }, h('span', { class: 'glyph', 'aria-hidden': 'true' }, '🍽'),
          h('p', null, 'Choose a restaurant, date and guests, then press “Find tables”.')));
        return;
      }
      const head = h('div', { class: 'results-head' },
        h('h2', null, v.restaurant.name),
        h('span', { class: 'muted' }, `${TK.fmtDate(v.params.date)} · party of ${v.params.party} · local time ${v.restaurant.timezone || ''}`));
      const noteEl = note ? TK.notice('info', note) : null;
      if (!v.slots.length) {
        results.append(h('section', { class: 'panel' }, head, noteEl,
          h('div', { class: 'empty', testid: 'no-slots' }, h('span', { class: 'glyph', 'aria-hidden': 'true' }, '🕯'),
            h('p', null, 'No tables to show for this day. The restaurant may be closed, so try another date.'))));
        return;
      }
      results.append(h('section', { class: 'panel' }, head, noteEl,
        h('ul', { class: 'legend', 'aria-label': 'Legend' },
          h('li', null, h('i', { class: 'lg-av' }), 'Available'), h('li', null, h('i', { class: 'lg-un' }), 'Not available'), h('li', null, h('i', { class: 'lg-se' }), 'Your choice')),
        h('div', { testid: 'availability-grid' }, v.slots.map(slotRow))));
    }

    function slotRow(slot) {
      const v = st.view;
      const time = TK.fmtTime(slot.starts_at_local);
      const party = +v.params.party;
      const singles = new Set(slot.available_table_ids || []);
      const combos = new Set((slot.available_options || []).filter((o) => o.table_ids.length === 2).map((o) => pairKey(o.table_ids)));
      const tables = v.restaurant.tables || [];
      const byId = {}; tables.forEach((t) => { byId[t.id] = t; });
      const pairs = (v.restaurant.combinable || []).filter((p) => Array.isArray(p) && p.length === 2 && byId[p[0]] && byId[p[1]]);
      const cells = tables.map((t) => cell([t.id], singles.has(t.id), t.capacity, slot, time));
      const comboCells = pairs.map((p) => cell(p, combos.has(pairKey(p)), byId[p[0]].capacity + byId[p[1]].capacity, slot, time));
      return h('div', { class: 'slot-row' }, h('div', { class: 'slot-time' }, time),
        h('div', { class: 'cells' }, cells, comboCells.length ? [h('div', { class: 'cell-group-label' }, 'Combined tables for larger parties'), comboCells] : null));
    }

    function cell(ids, available, capacity, slot, time) {
      const v = st.view;
      const labels = TK.labelsFor(v.restaurant, ids);
      const combo = ids.length > 1;
      const selected = !!st.form && st.form.key === ids.join('+') + '@' + slot.starts_at_local;
      const state = available ? 'Available' : capacity < +v.params.party ? 'Too small' : 'Taken';
      return h('button', {
        type: 'button', class: 'cell ' + (combo ? 'combo' : 'single'),
        testid: `slot-${ids.join('+')}-${time}`, 'data-available': available ? 'true' : 'false',
        'aria-pressed': selected ? 'true' : 'false',
        'aria-label': `${TK.tableWord(labels)}, seats ${capacity}${combo ? ' together' : ''}, ${time}, ${state}`,
        onclick: () => choose(ids, labels, capacity, slot, available),
      }, h('span', { class: 'cell-name' }, TK.tableWord(labels)),
        h('span', { class: 'cell-meta' }, combo ? `Seats ${capacity} together` : `Seats ${capacity}`),
        h('span', { class: 'cell-state' }, selected ? 'Selected' : state));
    }

    function choose(ids, labels, capacity, slot, available) {
      if (!available) return;
      if (!TK.session.get()) {
        clear(booking).append(h('section', { class: 'panel' }, TK.notice('error',
          h('span', null, 'Please ', h('a', { href: '/login' }, 'log in'), ' or ', h('a', { href: '/signup' }, 'sign up'), ' to book this table.'),
          { 'data-testid': 'auth-error' })));
        return;
      }
      const key = ids.join('+') + '@' + slot.starts_at_local;
      if (st.form && st.form.key === key) { renderResults(); focusForm(); return; }
      st.form = {
        key, ids, labels, capacity, local: slot.starts_at_local, restaurant: st.view.restaurant,
        party: st.view.params.party, attempts: {}, lastCanon: null, busy: false,
      };
      renderResults();
      renderBooking();
      focusForm();
    }
    const focusForm = () => { const el = booking.querySelector('input'); if (el) el.focus({ preventScroll: false }); };
    TK.onSession((s) => { if (s) { const e = booking.querySelector('[data-testid="auth-error"]'); if (e) clear(booking); } });

    /* ----- booking form ----- */
    function renderBooking() {
      clear(booking);
      const f = st.form;
      if (!f) return;
      const input = h('input', { id: 'b-party', type: 'number', min: '1', step: '1', inputmode: 'numeric', testid: 'booking-party-size', value: f.party });
      const msgs = h('div', { 'aria-live': 'polite' });
      const confirmHost = h('div');
      const submit = h('button', { type: 'submit', class: 'btn primary', testid: 'booking-submit' }, 'Confirm reservation');
      const formEl = h('form', { testid: 'booking-form', novalidate: true },
        h('h2', null, 'Reserve your table'),
        h('p', { class: 'summary', testid: 'booking-summary' },
          `${TK.tableWord(f.labels)} at ${f.restaurant.name} · ${TK.fmtWhen(f.local)}`),
        h('div', { class: 'row' },
          h('div', { class: 'field' }, h('label', { for: 'b-party' }, 'Party size'), input,
            h('span', { class: 'hint' }, `Seats up to ${f.capacity}`)),
          submit),
        msgs);
      booking.append(h('section', { class: 'panel booking' }, formEl, confirmHost));

      const setMsg = (kind, text) => {
        clear(msgs);
        if (kind === 'error') msgs.append(TK.notice('error', text, { 'data-testid': 'booking-error' }));
        if (kind === 'uncertain') msgs.append(TK.notice('uncertain', text, { 'data-testid': 'booking-uncertain' }));
      };

      formEl.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        if (f.busy) return;
        if (!/^\d+$/.test(input.value.trim()) || +input.value < 1) {
          setMsg('error', 'Enter a whole party size of 1 or more.');
          return;
        }
        const body = { restaurant_id: f.restaurant.id, starts_at_local: f.local, party_size: +input.value.trim() };
        if (f.ids.length === 1) body.table_id = f.ids[0]; else body.table_ids = f.ids;
        const canon = JSON.stringify(body);
        const prev = f.attempts[canon];
        // Same request identity only for an unresolved attempt or an unchanged resubmission of a success.
        const reuse = prev && (prev.outcome === 'uncertain' || (canon === f.lastCanon && prev.outcome === 'ok'));
        const attempt = reuse ? prev : (f.attempts[canon] = { key: TK.newKey(), outcome: null });
        const replay = reuse && prev.outcome === 'ok';
        f.lastCanon = canon;
        f.busy = true; submit.disabled = true; submit.textContent = prev && prev.outcome === 'uncertain' ? 'Retrying…' : 'Booking…';
        setMsg(null);
        if (!replay) clear(confirmHost);

        let outcome, res = null;
        try {
          res = await api('/reservations', { method: 'POST', body, headers: { 'Idempotency-Key': attempt.key } });
          if (res.ok && res.data && typeof res.data.reference === 'string') outcome = 'ok';
          else if (res.status >= 400 && res.status < 500) outcome = 'rejected';
          else outcome = 'uncertain';
        } catch (e) { outcome = 'uncertain'; }
        attempt.outcome = outcome;
        if (outcome === 'rejected') delete f.attempts[canon];
        if (st.form !== f) return; // the diner moved on; never touch newer intent
        f.busy = false; submit.disabled = false;
        submit.textContent = outcome === 'uncertain' ? 'Try again safely' : 'Confirm reservation';

        if (outcome === 'ok') {
          setMsg(null);
          clear(confirmHost).append(confirmation(f, res.data));
          run(st.last, true);
        } else if (outcome === 'uncertain') {
          setMsg('uncertain', 'We did not get a reply from the server, so we cannot tell whether your table is booked. Press “Try again safely”: we will resend the very same request, so you will not be booked twice.');
        } else {
          clear(confirmHost);
          setMsg('error', BOOK_ERRORS[res.code] || res.message || 'We could not complete this booking.');
          if (res.code === 'table_unavailable' && st.last) run(st.last, true);
        }
      });
    }

    function confirmation(f, r) {
      const labels = TK.labelsFor(f.restaurant, TK.tableIdsOf(r));
      const shown = labels.length ? labels : f.labels;
      return h('div', { class: 'confirmation', testid: 'confirmation', role: 'status' },
        h('h3', null, 'You are booked. See you soon!'),
        h('span', { class: 'label' }, 'Confirmation reference'),
        h('span', { class: 'ref', testid: 'confirmation-reference' }, r.reference),
        h('p', { testid: 'confirmation-details' }, `${f.restaurant.name} · ${TK.tableWord(shown)} · ${TK.fmtWhen(r.starts_at_local || f.local)} · party of ${r.party_size}`),
        h('p', { class: 'muted' }, 'Tables: ', h('span', { testid: 'confirmation-tables' }, TK.tableWord(shown))),
        h('p', null, h('a', { href: '/lookup' }, 'Look up or cancel this booking')));
    }

    renderResults();
    loadRestaurants();
  };
})();

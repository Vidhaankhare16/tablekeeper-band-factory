/* Signup and login screens. */
(function () {
  'use strict';
  const { h, api } = TK;

  const MESSAGES = {
    email_taken: 'That email is already registered. Try logging in instead.',
    unauthenticated: 'Email or password is not right. Please check and try again.',
    validation_failed: 'Please check your details: use a valid email address and a password of at least 8 characters.',
  };

  function field(id, label, type, testid, extra) {
    return h('div', { class: 'field' },
      h('label', { for: id }, label),
      h('input', Object.assign({ id, type, testid, required: true }, extra)),
      extra && extra.hint ? h('span', { class: 'hint' }, extra.hint) : null);
  }

  function authPage(main, cfg) {
    const err = h('div', { 'aria-live': 'polite' });
    const submit = h('button', { type: 'submit', class: 'btn primary', testid: cfg.submitId }, cfg.button);
    const form = h('form', { class: 'stack', novalidate: true }, cfg.fields, err, submit);
    let busy = false;
    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      if (busy) return;
      busy = true; submit.disabled = true; submit.textContent = cfg.busy;
      TK.clear(err);
      try {
        const res = await api(cfg.endpoint, { method: 'POST', auth: false, body: cfg.body() });
        if (res.ok && res.data && res.data.token) {
          TK.session.set({ token: res.data.token, user_id: res.data.user_id, display_name: res.data.display_name });
          location.assign('/');
          return;
        }
        const text = MESSAGES[res.code] || (res.status >= 500 ? 'Something went wrong on our side. Please try again.' : res.message) || 'That did not work. Please try again.';
        err.append(TK.notice('error', text, { 'data-testid': 'auth-error' }));
      } catch (e) {
        err.append(TK.notice('error', 'We could not reach the server. Check your connection and try again.', { 'data-testid': 'auth-error' }));
      }
      busy = false; submit.disabled = false; submit.textContent = cfg.button;
    });
    main.append(h('section', { class: 'panel auth-card' },
      h('p', { class: 'eyebrow' }, cfg.eyebrow), h('h1', null, cfg.title), h('p', { class: 'muted' }, cfg.lead), form,
      h('p', { class: 'muted', style: 'margin-top:16px' }, cfg.alt)));
  }

  const val = (id) => document.getElementById(id).value;

  TK.pages.signup = (main) => authPage(main, {
    eyebrow: 'Welcome', title: 'Create your account', lead: 'Book in seconds and manage your reservations in one place.',
    fields: [
      field('su-name', 'Your name', 'text', 'signup-display-name', { autocomplete: 'name' }),
      field('su-email', 'Email', 'email', 'signup-email', { autocomplete: 'email' }),
      field('su-pass', 'Password', 'password', 'signup-password', { autocomplete: 'new-password', hint: 'At least 8 characters.' }),
    ],
    submitId: 'signup-submit', button: 'Create account', busy: 'Creating account…', endpoint: '/auth/signup',
    body: () => ({ email: val('su-email').trim(), password: val('su-pass'), display_name: val('su-name').trim() }),
    alt: h('span', null, 'Already have an account? ', h('a', { href: '/login' }, 'Log in')),
  });

  TK.pages.login = (main) => authPage(main, {
    eyebrow: 'Welcome back', title: 'Log in', lead: 'Pick up where you left off.',
    fields: [
      field('li-email', 'Email', 'email', 'login-email', { autocomplete: 'email' }),
      field('li-pass', 'Password', 'password', 'login-password', { autocomplete: 'current-password' }),
    ],
    submitId: 'login-submit', button: 'Log in', busy: 'Logging in…', endpoint: '/auth/login',
    body: () => ({ email: val('li-email').trim(), password: val('li-pass') }),
    alt: h('span', null, 'New here? ', h('a', { href: '/signup' }, 'Create an account')),
  });
})();

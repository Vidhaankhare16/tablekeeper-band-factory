# Tablekeeper browser UI (stage 2)

Plain HTML/CSS/JS, no build step, nothing loaded from the network (system font stack, inline SVG favicon).

- `index.html`, `signup.html`, `login.html`, `lookup.html`: identical shells; `app.js` picks the screen from the URL path.
- `app.js` core (DOM helper, session in `localStorage` key `tk.session`, API client, header/nav, formatting).
- `page-search.js` search grid, booking form, confirmation. `page-auth.js` signup/login. `page-lookup.js` lookup and cancel.
- Late responses: each search takes a sequence number, only the latest renders; a post-booking refresh yields to any newer search.
- Booking identity: one Idempotency-Key per request body. Reused for an unresolved (uncertain) attempt and for an unchanged resubmission after success; a changed field or a confirmed 4xx rejection gets a fresh key. Network failures, timeouts and 5xx show `booking-uncertain`; 4xx show `booking-error`.
- Token is only dropped when the server answers 401 to it.
- Grid: one cell per table and per declared pair for every slot; `data-available` is derived from `available_table_ids` (singles) and `available_options` (pairs).
- Browser checks used for delivery: `evidence/stage-2/e2e_flows.py`, `e2e_combo_upgrade.py` (Playwright, run against a live service).

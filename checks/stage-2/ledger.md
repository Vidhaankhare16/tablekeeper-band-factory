# Acceptance ledger — Tablekeeper stage 2 (work order S2.W1)

Run: `bash checks/stage-2/run.sh <stage-2 base url> [pytest args]` (service running; the script starts the accepted
stage-1 image from git revision 52137c09… on :8081 for the upgrade checks; browser = headless Chromium at
`/opt/pw-browsers/chromium-1194`, driven with Playwright; nothing is installed beyond `pytest` and `playwright` python
packages). API checks: `checks/stage-2/test_*.py`; browser checks: `checks/stage-2/ui/test_ui_*.py`. Failure messages
start with `[L2.<n>]` (or the stage-1 id `[L1.<n>]`).

**Stage-1 items L1.1–L1.113** (see `checks/stage-1/ledger.md`) are re-checked unchanged against the stage-2 service by
the copied files `test_core/catalog/reservations/idempotency/dst/export_import/moves/concurrency.py` (one adaptation:
availability slots now also carry `available_options`, so the exact-slot assertion compares the stage-1 keys only).

## Readings
- **S1** Booking-response order of `table_ids` is not asserted (a pair is a set); `available_options` order is (singles in
  fixture order, then pairs in `combinable` order, ids within a pair in `combinable` order) and so are the UI cell ids.
- **S2** `table_ids: []`, and `table_ids` given neither with nor without `table_id`, are 422 `validation_failed`; a non-array
  `table_ids` or non-string members are 400 `malformed_request` (§5 wrong JSON type).
- **S3** `available_options` lists every pair with summed capacity ≥ party, even for party sizes a single table fits
  (literal text: "every single table and every declared pair with `capacity >= party_size`").
- **S4** Combination grid cell: must exist with `data-available="true"` when the pair is in `available_options`; when a
  declared pair is busy the cell may be absent or `false`, never `true`; no cell for undeclared pairs or reversed ids.
- **S5** Lost response = the request is aborted at the network layer (`connectionreset`) after the server committed (or
  before it). "Unchanged form retries with the same key and body" is checked on the wire (header + parsed body).
- **S6** Upgrade, UI session: the UI's session storage is discovered by signing in through the UI and inspecting
  localStorage/sessionStorage; the stage-1-issued token is substituted into the same entries. The booking lost "before
  export" is committed on the accepted stage-1 container (the intercepted request is forwarded there, then dropped), the
  world is exported from it and imported into the stage-2 service, then the unchanged form is retried.
- **S7** A replayed receipt created at stage 1 has `table_id` and no `table_ids` (stored response preserved verbatim); the API check
  accepts that, and the UI must fall back to `table_id` (lead's note).
- **S8** Quality requirements are checked as measurable proxies: no horizontal page scroll at 375px and 1280px on every
  screen/state; every visible input has a label; keyboard focus changes style; WCAG-AA contrast (4.5:1 / 3:1 large) of all
  visible text; available/unavailable/selected/refused/uncertain/successful states differ in computed style; loading and failure
  states appear; cells/summary/confirmation use human labels (no `t_1` ids); `<title>`, heading and `lang` per screen.

## Ledger (stage 2 new items)

| id | requirement (verbatim) | observable behaviour | checks |
|---|---|---|---|
| L2.1 | "The following screens must be reachable by URL." / "A screen route returns HTML" (`/`, `/signup`, `/login`, `/lookup`) | GET of each route = 200 `text/html`; page shows its anchor control | ui/test_ui_routes_auth::L2_1_* |
| L2.2 | "Other screens must be reachable through the UI." | every screen links to the other three; links work | test_ui_routes_auth::L2_2 |
| L2.3 | "If search A starts before search B but finishes after it, the grid, table labels and booking form must describe B. A late response must not restore A's results." | held A response released after B: grid, labels, date/restaurant inputs, open booking form and what gets booked all stay B (party size, other restaurant, closed day, combination options) | test_ui_competing::L2_3_* |
| L2.4 | "a `409 table_unavailable` response shows `booking-error` and refreshes availability. Preserve the selected form and its inputs… Do not show a confirmation for that attempt." | booking-error text; cells refreshed to false; form, summary, edited party size preserved; no confirmation/uncertain; can then choose another table and succeed; same for combinations | test_ui_competing::L2_4_* |
| L2.5 | "If a booking response is lost, including after the booking commits, show nonempty `booking-uncertain` text, without `booking-error` or a new confirmation. The unchanged form must retry with the same idempotency key and body. A successful retry removes the uncertainty/error elements and shows the original reference." | abort after commit/before commit/twice in a row; wire-level same key+body; original reference; one booking; changed field after uncertainty = new key | test_ui_competing::L2_5_* |
| L2.6 | "A confirmed rejection uses `booking-error`." | 422 (capacity) → booking-error not uncertain; uncertain → rejected retry swaps to booking-error | test_ui_competing::L2_6_* |
| L2.7 | "These rules apply to combination bookings too." | combos: 409 refresh, lost-response retry, double submit, changed field, rejection | test_ui_competing::L2_7_*, L2_3_combo, L2_4_combination |
| L2.8 | "No background polling… The server remains authoritative; the browser must not manufacture a successful result from cached data." | after a lost response and a second of waiting no confirmation appears | test_ui_competing::L2_8 |
| L2.9 | `signup-*`, `login-*`, `auth-error` ("Present only when there is one"), `current-user` ("Visible on every screen when signed in. Text contains the display name"), `logout-button` | signup/login/logout flows, errors (duplicate, short password, bad email, wrong password), persistence across reload/tabs, current-user on all four routes | test_ui_routes_auth::L2_9_* |
| L2.10 | grid testids; "A cell is `true` exactly when its `table_id` is in that slot's `available_table_ids`… and `false` otherwise"; `no-slots` "instead of the grid" | 3×8 cells for 9 party sizes match the API; other restaurant; closed day; grid↔no-slots switching | test_ui_booking::L2_10_* |
| L2.11 | "Clicking an available cell opens the booking form for that table and slot. Clicking an unavailable cell does nothing. …signed out shows `auth-error` or navigates to `/login`" | as stated | test_ui_booking::L2_11_* |
| L2.12 | booking form testids; `booking-summary` "table label and the local start time"; `booking-party-size` "pre-filled from the search" | flow to confirmation; edited party size is the one booked; slot unavailable on the next search | test_ui_booking::L2_12_* |
| L2.13 | "Keep the booking form on screen after success. Submitting it again without changing a field must return the same `confirmation-reference`, without `booking-error` or another booking. Changing a field makes the next submission a new booking request." | repeated submit: same reference, same key+body on the wire, one reservation; changed party size → new key → refused (slot taken); another slot = new booking | test_ui_booking::L2_13_* |
| L2.14 | "`confirmation-reference`: Text is exactly the reference, no surrounding words"; `confirmation-details` "restaurant name, table label and local start time" | regex-exact reference equals API reference; details text | test_ui_booking::L2_12_booking_flow |
| L2.15 | lookup testids; `reservation-status` "exactly `confirmed` or `cancelled`"; cancel button "Absent once cancelled"; `reservation-error` "when not found, or when a cancel is refused" | found/cancel/free slot/relookup; unknown, foreign reference; cancel refused (cutoff) keeps status confirmed; error/detail clearing | test_ui_booking::L2_15_* |
| L2.16 | "A stage-2 service must accept an export produced by the same team's stage-1 service. A browser signed in before that export/import upgrade must remain signed in afterwards. A retained booking reference still works through the lookup screen. A booking whose response was lost before export remains retryable after import with the same body and key; the UI must recover the original confirmation… The form and pending retry identity must survive the upgrade." | stage-1 container (accepted rev) → export → stage-2 import (204); UI session carrying the stage-1 token shows current-user and looks up a stage-1 booking; lost-response booking committed on the old service, upgrade, unchanged form retried → original reference | ui/test_ui_upgrade::L2_16_* |
| L2.17 | "Product and visual direction": 375px and desktop without horizontal page scrolling; "Inputs need visible labels, keyboard focus must be apparent, and text and controls need sufficient contrast"; "Available, unavailable, selected, loading, successful, refused and uncertain states must be visually distinct"; "human-readable restaurant and table labels"; "empty, loading and error states"; consistent navigation | proxies S8 | ui/test_ui_quality::L2_17_* |
| L2.20 | "The restaurant fixture gains one field: `combinable`" | `GET /restaurants/{id}` exposes it; absent ⇒ no combinations | test_combined::L2_20 |
| L2.21 | "**Pairs only** — never three or more. A pair not listed cannot be combined, whatever the table sizes are. Combining is not transitive" | unlisted/transitive pair, 3 tables, no `combinable` at all ⇒ 422 `combination_not_allowed`; reversed order of a listed pair accepted | test_combined::L2_21, L2_26_combination_not_allowed |
| L2.22 | "A combination's capacity is the sum of its tables' capacities." | 6/10 accepted, 7/11 ⇒ `party_exceeds_capacity` | test_combined::L2_26_party_exceeds |
| L2.23 | "Seeded `reservations` are `confirmed` unless they carry a `status` of `cancelled`, and may hold either `table_id` or `table_ids`." | all four seed shapes; cancelled seed frees tables; combo seed occupies both | test_combined::L2_23 |
| L2.24 | "`available_table_ids` stays exactly as it was — single tables only." / `available_options` "lists every single table and every declared pair with `capacity >= party_size` and no overlapping confirmed reservation on any member. Singles first in fixture order, then pairs in `combinable` order. `table_ids` within a pair is in `combinable` order." | shapes, order, capacity boundary (5/6/7/10/11), busy-member exclusion, half-open edges | test_combined::L2_24_* |
| L2.25 | "`table_id` is still accepted and means a set of one. Sending both is 422 `validation_failed`. Responses always carry `table_ids`. They also carry `table_id` when the set has exactly one member, and omit it otherwise." | create/get/list/replay shapes | test_combined::L2_25_* |
| L2.26 | error table: not listed / more than two ⇒ 422 `combination_not_allowed`; any table taken ⇒ 409 `table_unavailable`; over summed capacity ⇒ 422 `party_exceeds_capacity`; duplicate id ⇒ 422 `validation_failed` | each case + unknown/foreign table 404, shape errors (S2), other stage-1 rules on combos, failed key reusable, refused combo books nothing | test_combined::L2_26_* |
| L2.27 | "`PATCH /reservations/{reference}` accepts `table_ids` under the same rules. Cancelling frees every table in the set." | single↔combo conversions, 11 error cases leave the original intact, member checks on time moves, cancel frees all, cancelled/cutoff apply | test_combined::L2_27_* |
| L2.28 | "Atomic reservation moves from stage 1 also accept `table_ids` per move. No table may belong to overlapping resulting bookings." | combos in moves, shared member ⇒ 409, rotation/swap valid, atomic failure, replay | test_combined::L2_28_* |
| L2.29 | "The booking occupies both tables for its full duration." | each member blocked over the whole [start, start+duration), free at the end instant | test_combined::L2_29_* |
| L2.30 | "Concurrent requests must produce the same results as executing them one at a time in some order, and the requirements above hold at every read." | 50 mixed combo/single bookings: no overlap on any member, availability agrees; 50 identical combo requests ⇒ one booking; 30 amendments racing for a pair | test_combined::L2_30_* |
| L2.31 | UI: `slot-{t_a}+{t_b}-{HH:MM}` ("Ids in `combinable` order. Carries `data-available`"), `confirmation-tables`, `reservation-tables`, "`booking-summary` must name every table in the selection. A single-table booking's cell testid, confirmation and lookup are unchanged." | combination flow end to end, request body carries both tables, single unchanged, cancel frees both, busy member ⇒ not available, no undeclared/reversed cells | test_ui_booking::L2_31_* |
| L2.32 | "must accept an export produced by the same team's stage-1 service" (API level) | stage-1 tokens, accounts, bookings (incl. cancelled), receipts (booking + moves), failed keys, occupancy, defaults after import | ui/test_ui_upgrade::L2_32 |
| L2.34 | stage-1 §10 for stage-2 state | export/import preserves combinations, `combinable`, receipts | test_combined::L2_34 |

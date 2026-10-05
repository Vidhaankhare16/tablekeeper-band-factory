# Acceptance ledger — Tablekeeper stage 4 (work order S4.W1)

Run: `bash checks/stage-4/run.sh <stage-4 base url> [pytest args]`. The script builds and starts the accepted stage-1 (`52137c09…` :8081),
stage-2 (`a1706213…` :8082) and stage-3 (`b5f097dc…` :8083) images from git history for the upgrade checks; browser checks use headless
Chromium from `/opt/pw-browsers`. Failure messages start with the ledger id. One check (`L4_61`, the accepted-cutoff check) waits ~3 minutes
for a real cancellation cutoff to pass; everything else is fast.

**Re-checked, unchanged:** stage-1 (L1.*), stage-2 (L2.*, incl. browser) and stage-3 (L3.*, incl. upgrades) items — the whole `checks/stage-3` folder is copied here.

## Readings
- **Q1** Wrong JSON types in a replan body (`table_id` number, `from` number/null) may be 400 `malformed_request` (§5) or 422; a missing field, a naive timestamp, `from >= to`, or a non-RFC-3339 instant is strictly 422.
- **Q2** Wrong JSON types for `expected_revision`/`from_index`/`local_time` in a series amendment may be 400 or 422; booleans, floats, out-of-range numbers and malformed times are strictly 422. Input validation (422) is evaluated before the revision comparison (409); the 409 precedes any per-occurrence work.
- **Q3** Whether an *unapplied preview* survives an export/import is not asserted (it must either apply or answer a clean 409 `stale_plan`); applied plans, receipts, closures, revisions and series state must survive.
- **Q4** "Consider every confirmed booking at this restaurant overlapping that interval" is read literally: considered = all confirmed bookings (on any table) whose occupancy `[start,end)` overlaps `[from,to)`. Fixed bookings are the other confirmed ones.
- **Q5** `restaurant_revision` in a *preview* response is the current revision; in an *apply* response it is the revision after application. It is observed through a throw-away preview of a closure in year 2001 (`rev()` in `replan_kit.py`); previews are specified to add nothing.
- **Q6** Option rank = index in [singles in fixture order, pairs in declared order] over all options of the restaurant; a pair's `table_ids` are listed in the declared order of its `combinable` entry.
- **Q7** A `reassigned` entry always names `table_ids` (complete before/after lists), even single-to-single; it carries `plan_id`, `revision` and `accepted_terms` like every entry.
- **Q8** `planning_limit`: "may return" — within 6 tables / 4 pairs / 6 bookings a plan is required; above, either a valid plan or 422 `planning_limit`, within 5 s.
- **Q9** Series amendments: eligible = `index >= from_index`, not cancelled, not exception-marked; the target date is the occurrence's original scheduled date (anchor date + index × interval × 7 days); identical resulting fields = no-op (no cutoff check, terms kept).
- Not asserted: relative order of two simultaneous field faults; textual messages; the exact value of an imported restaurant's revision (only that it is a non-negative integer and then counts exactly).

## Ledger

| id | requirement (verbatim) | observable behaviour | checks |
|---|---|---|---|
| L4.1 | "`POST /restaurants/{id}/replans` requires a manager" / unknown table 404 | 401 / 404 (restaurant) / 403 / 404 (unknown or foreign table) matrix; r_two managed separately | test_replans::L4_1 |
| L4.2 | "…and an idempotency key" | 400 missing/empty, 422 length (255 ok, 256 not), 400 bad body, unknown fields ignored | L4_2 |
| L4.3 | "The instants have explicit offsets and `from < to`; invalid interval is 422 `validation_failed`" | 11 invalid intervals, missing fields, wrong types (Q1), `Z` accepted | L4_3_* |
| L4.4 | stage-1 idempotency rules | replay 200 same plan, reorder/whitespace, reuse 409 (even invalid body), failed key = first use, per-user | L4_4 |
| L4.5 | "Among feasible plans minimize, in order: 1. Number of bookings whose table set changes. 2. Total unused seats… 3. The vector of option ranks in ascending reservation-reference order." | 30 random seeded scenarios compared with a brute-force oracle (assignments, moved_count, unused_seats; 409 exactly when the oracle finds none); scenario mix asserted | L4_5_* |
| L4.6 | the three levels, each isolated | fewest moves beats fewer unused seats; fewest unused seats beats lower rank; rank vector decides ties (singles before pairs) | L4_6_* |
| L4.7 | "Singles are ranked first in fixture order, then pairs in declared order, starting at 0." / "enough capacity under **its own accepted terms**" | declared pair order and `table_ids` order; bookings accepted under different policies use their own capacities | L4_7_* |
| L4.8 | "No feasible plan gives 409 `no_feasible_plan`, changing nothing." / cancelled bookings not considered | refusal changes nothing (state, revision) | L4_8_* |
| L4.9 | "Consider every confirmed booking at this restaurant overlapping that interval. … The proposed closure is the half-open interval `[from,to)`." / "Assignments include every considered booking in reference order." / response shape | half-open boundaries on both ends, exact key set, reference order, only overlapping confirmed bookings | L4_9_* |
| L4.10 | "without conflicts with fixed bookings, other assignments, previously applied closures or the proposed closure" | closed table never used; pairwise non-overlap; fixed bookings overlapping a considered booking's interval constrain it; earlier closures constrain later plans | L4_10_* |
| L4.11 | "Diners' cancellation cutoffs do not prevent an operator repair." / "Customers must keep their booking times, party sizes and accepted terms." | a booking inside its cutoff is repaired; every field but tables unchanged | L4_11 |
| L4.12 | "Preview stores only a plan: no closure, occupancy, reservation revision or history changes." | state, availability and restaurant revision identical before/after previews; table still bookable | L4_12 |
| L4.13 | "Planning must support up to 6 tables, 4 declared pairs and 6 considered bookings; larger inputs may return 422 `planning_limit`." | Q8 | L4_13 |
| L4.20 | "`POST …/apply`, body `{}`, requires a manager and an idempotency key… Unknown plan or one from another restaurant is 404." | 401/403/400/422/404 matrix, other restaurant's plan 404, bad bodies 400, unknown fields ignored | test_replans_apply::L4_20 |
| L4.21 | "Return 201 with `{"plan_id", "restaurant_revision": 5, "reservations": [...]}`; reservations include every considered booking in reference order." | exact key set; revision = preview's + 1; equals stored records | L4_21 |
| L4.22 | "Each moved booking increments its revision once and gains one `reassigned` history entry with a `table_ids` change and `plan_id`; accepted terms and times remain identical. Unmoved bookings gain nothing." | revision +1, exactly one new entry (seq, revision, terms, plan_id), earlier entries unchanged; unmoved identical; decision revision | L4_22 |
| L4.23 | "A plan already applied under a different key gives 409 `plan_already_applied`; replay of the successful key returns the original response with 200, even after later changes." | replay after unrelated changes, reuse 409, different key 409 | L4_23 |
| L4.24 | "Any intervening restaurant revision invalidates the plan: 409 `stale_plan`, changing nothing." | booking, cancellation, amendment, policy publication, batch move, another applied plan each make it stale; no-ops/failures/previews do not | L4_24_* |
| L4.25 | "A closure at another restaurant does not invalidate this plan." | per-restaurant revisions | L4_25 |
| L4.26 | "Application records the closure and all assignments together." | empty plan can be applied and still records the closure | L4_26 |
| L4.30 | "Closures thereafter exclude singles and pairs from availability… In explanations, `no_overlap` is false for a closure as for a conflicting booking." | slot-by-slot with half-open edges: `available_table_ids`, `available_options` (pairs), `explain` | L4_30 |
| L4.31 | "…and reject creates/amendments with 409 `table_unavailable`." | single, pair, PATCH, moves; free outside the closure | L4_31 |
| L4.32 | closure scope | other restaurant and other days unaffected | L4_32 |
| L4.33 | closures vs series generation | adoption refused with `table_unavailable`, nothing created | L4_33 |
| L4.34 | cutoffs still bind diners | diner cancel still `cutoff_passed`; closed table gone from availability | L4_34 |
| L4.40 | "A restaurant revision starts at 0 after reset and increments once for each successful new booking, real amendment, cancellation, policy publication or plan application. No-op writes, failures, previews and replays do not increment it." + earlier "once per batch / once for the whole operation" sentences | ~40-step accounting script over bookings, replays, failures, amendments (real/no-op/failed/stale), cancels (repeat), publications (replay/failed/refused), batch moves (real/no-op/failed/replay), series adoption (3 new bookings = +1) and amendment, occurrence edits/cancels, previews, applies, reads; per-restaurant | L4_40 |
| L4.41 | "Seating repairs may move series occurrences. They preserve their exception flags, scheduled dates, identities and accepted terms. Each affected series revision increases once per plan application if at least one member moved." | one member moved ⇒ +1; three members moved by one plan ⇒ +1; flags kept | L4_41 |
| L4.42 | same | series without moved members untouched | L4_42 |
| L4.43 | "retaining … current table selection" | series amend after a repair keeps the repaired tables | L4_43 |
| L4.45 | "Concurrent applications must not leave partially moved bookings." / "Application is atomic." | 20 concurrent applies ⇒ one 201; same key ⇒ one 201 + replays; two plans from one revision ⇒ one stale; applies racing bookings/amendments leave no overlap and nothing on the closed table | L4_45_* |
| L4.50 | "`POST /series/{series_id}/amend` is an owner-only idempotent write. Unknown or another owner's series is 404; no token is 401." | access/key/body matrix | test_series_amend::L4_50 |
| L4.51 | "Revision must be a positive integer; from_index an integer in 0..count-1; local_time exactly HH:MM in 00:00..23:59. Booleans are invalid integers. Invalid input gives 422 `validation_failed`; a mismatched series revision gives 409 `stale_revision` before any occurrence's cutoff or booking validation." | 25 invalid inputs (Q2); boundaries; stale beats cutoff/grid/hours faults | L4_51_* |
| L4.52 | "Consider indices at or after from_index, excluding cancelled occurrences and those marked exception. Change their clock time on their original scheduled local dates, retaining each reference, owner, party size and current table selection." / "On success return 201 with the current series response. Each changed occurrence gains one ordinary changed history entry and one reservation revision. The series and restaurant revisions each increase once for the entire operation if anything changed. Series amendments do not mark exceptions." | eligible set, dates, identity, history entry, series/restaurant revision once, flags unchanged | L4_52 |
| L4.53 | "A change with identical resulting fields is a no-op and retains its terms. … All-no-op or empty eligible sets succeed without changing revisions." | no-op, empty set, mixed, repeat | L4_53 |
| L4.54 | "Each real change checks its old accepted cutoff, then adopts the policy for its resulting start date, just like an individual PATCH." | terms/end time replaced per occurrence date; policy hours/grid of the resulting date can refuse | L4_54_* |
| L4.55 | "The resulting occurrences must not conflict with unchanged occurrences, other bookings or applied closures. On failure, histories, idempotency records and all revisions remain unchanged. Non-occupancy errors take precedence in occurrence-index order; otherwise an occupancy conflict returns `table_unavailable`." | conflicts with others / unchanged exception occurrence / closure ⇒ 409 and atomic; failed key reusable; non-occupancy beats an earlier occupancy conflict; index order between two non-occupancy errors | L4_55_* |
| L4.56 | DST for amendments | nonexistent local time ⇒ `invalid_local_time` (all-or-nothing); repeated ⇒ first occurrence, absolute duration | L4_56 |
| L4.57 | "Replay returns the original response with 200 even after further edits or cancellations." | replay ×2, no counter change, reuse 409, per-user keys | L4_57 |
| L4.58 | no exception marks | amend never marks; individual PATCH after does; exception skipped by later amendments | L4_58 |
| L4.59 | combined selections | pair series amended, time-only history | L4_59 |
| L4.60 | "Concurrent amendments from the same expected revision may not both make a real change." | 24 concurrent ⇒ revision +1 once, one winning clock time; 20 identical keyed ⇒ one 201; races with edits/bookings keep revision == history | L4_60_* |
| L4.61 | "Each real change checks its old accepted cutoff" (real cutoff, ~3 min wait) | `cutoff_passed` for the near occurrence in index order before an `outside_opening_hours` of a later one; stale first; later occurrences still editable | L4_61 |
| L4.70 | "Existing availability, confirmation and lookup screens must reflect an applied plan." | lookup shows the new table labels after an applied plan, status and time unchanged | ui/test_ui_replan::L4_70 |
| L4.71 | same | grid cells (single and both pairs containing the closed table) are `data-available="false"` exactly for slots overlapping the closure, others true; grid == API for 3 party sizes | L4_71 |
| L4.72 | stage-2 409 rules with closures | an open booking form meets the closure: booking-error, refreshed cells, form preserved | L4_72 |
| L4.73 | confirmation reference stays valid | a UI booking repaired by a plan resolves in lookup; revision 2, history `reassigned` with plan_id | L4_73 |
| L4.80 | "A stage-4 service must accept exports produced by the same team's stages 1–3. … Earlier booking and series receipts, histories and retries remain valid." | stage-1 and stage-2 images populated, exported, imported: receipts verbatim, adoption + series amend on imported reservations | test_upgrade4::L4_80 |
| L4.81 | "These operations must support imported series, including moved and cancelled occurrences." | stage-3 image with a series whose anchor and one occurrence are exceptions (one moved) and one occurrence cancelled: series read identical, receipts, amend skips them, scheduled dates and policy adoption | L4_81 |
| L4.82 | restaurant revision on imported state; replans on imported state | counts exactly from the imported value; a plan moves an imported series member keeping flags | L4_82 |
| L4.83 | stage-1 §10 for stage-4 state | own export/import: revision, reservations, series, histories, apply/preview/amend receipts, closures survive (Q3) | L4_83 |

# Acceptance ledger — Tablekeeper stage 1 (work order S1.W1)

Checks: `bash checks/stage-1/run.sh <base-url> [pytest args]` (service must already be running; `docker run -e PORT=8080 -p 8080:8080 <image>`).
Each check is `test_L1_<n>_...` in `checks/stage-1/test_*.py`; failure messages start with `[L1.<n>]`.
Quotes are from the stage-1 requirements (§ numbers are the requirement sections).

## Readings chosen (ambiguous text)
- **R1** 401 before 400: "After the body has been parsed as a JSON object and the caller authenticated, idempotency is resolved…" ⇒ unauthenticated is checked before the Idempotency-Key header.
- **R2** Unknown restaurant/table (404) is reported before time/capacity rules (§8 table lists 404 for "Unknown restaurant, unknown table…" as the resource-resolution step).
- **R3** Unparseable / non-object body (400 `malformed_request`) precedes the key check ("After the body has been parsed as a JSON object…").
- **R4** "an invalid state" on import ⇒ a state object of the wrong inner shape (e.g. `{"unexpected":1}`) is 422 and changes nothing.
- **R5** `moves` that is not an array, or items that are not objects with a string `reference`, are "Invalid shape" ⇒ 422 `validation_failed` (endpoint rule wins over §5's generic wrong-type 400). A request *body* that is not a JSON object stays 400.
- **R6** Cutoff: "within `cancellation_cutoff_minutes` of `starts_at`, or later" ⇒ blocked when `now >= starts_at − cutoff`. Boundary tests use a 10-minute margin because the exact instant cannot be hit black-box.
- **R7** Slot grid is anchored at `opens` (§4: "grid of this many minutes from opening time"); a time before opening / after closing that is a multiple of the step is `outside_opening_hours`, an in-hours time off the grid is `not_on_slot_grid`. Combinations of both faults are not asserted.
- **R8** A day with no `opening_hours` entry: availability `slots: []`; booking it ⇒ `outside_opening_hours`.
- **R9** `display_name` presence at signup is not asserted (spec example shows it, no rule says it is required).
- **R10** "Same body" (§7) is the entire parsed JSON value, so an added unknown field is a different body (⇒ 409 reuse).
- Not asserted (ambiguous or unobservable): precedence between two simultaneous field faults on POST; cancel of an already-cancelled booking that is inside the cutoff; empty `{}` PATCH; an exact-to-the-second cutoff instant; `forbidden` (403) — stage 1 uses 404 for foreign resources.

## Ledger

| id | § | requirement (verbatim) | observable behaviour | check |
|---|---|---|---|---|
| L1.1 | 1 | "Two `confirmed` reservations must never occupy the same table at overlapping times, including during concurrent requests." | never two confirmed overlapping on a table; 50 concurrent bookings on one table/slot ⇒ exactly one 201 rest 409; invariant check after burst | test_concurrency::L1_1_*, test_reservations::L1_61 |
| L1.2 | 1 | "Occupancy is the half-open interval `[starts_at, starts_at + reservation_duration)`. A 90-minute booking at 19:00 therefore does not overlap a booking starting at 20:30." | start==other's end is free (both sides), 1 minute inside conflicts; availability agrees | test_reservations::L1_61, test_catalog::L1_2_L1_55 |
| L1.3 | 1 | "Retries and rejected requests must not create duplicate or partial bookings." | after any 4xx no reservation/occupancy exists; replays add none | test_reservations::L1_3, test_idempotency::L1_44, test_concurrency |
| L1.4 | 1 | "Each restaurant has its own table capacities, opening hours and cancellation policy." | per-restaurant slot/duration/hours/tables independent | test_catalog::L1_4 |
| L1.5 | 3.1 | "Listen on `0.0.0.0` using the `PORT` environment variable, default `8080`." | service reachable on PORT | covered by the runner / `check-stage` start check (no separate check) |
| L1.6 | 3.2 | "`GET /health -> 200 {"status": "ok"}`" | exact body | test_core::L1_6 |
| L1.7 | 3.3 | "Replace all service state with the fixture in the request body (§4). When reset returns 204, subsequent requests must see only that fixture. Repeated resets are supported." | 204 empty; old restaurants/users/tokens/reservations/receipts gone; repeatable | test_core::L1_7_*, test_export_import::L1_95 |
| L1.8 | 3.3 | "This test endpoint must be enabled in the delivered image and requires no authentication." | reset with no token ⇒ 204 | test_core::L1_8 |
| L1.9 | 3.4 | "Requests and responses are `application/json; charset=utf-8`." | response content type on 2xx and 4xx | test_core::L1_9 |
| L1.10 | 3.4 | "Timestamps in responses are RFC 3339 with an explicit offset" | starts_at/ends_at/created_at/slot starts_at match RFC 3339 with offset | test_core::L1_10 |
| L1.11 | 3.4 | "Unknown fields in a request body are ignored, never an error." | extra fields on signup, login, POST, PATCH ⇒ success | test_core::L1_11 |
| L1.12 | 3.4 | "Unknown query parameters are ignored." | extra params on GETs ⇒ 200 | test_core::L1_12 |
| L1.13 | 3.4 | "IDs are opaque strings of at most 64 characters… This limit also applies to IDs supplied in reset fixtures." | 64-char fixture ids work; generated ids ≤64 | test_core::L1_13 |
| L1.14 | 2 | "Concurrent requests: up to 50 in flight"; "Per-request timeout 5 s" | 50 simultaneous mixed requests/signups/logins succeed within timeout | test_concurrency::L1_14_* |
| L1.15 | 4 | "Seeded users must be able to log in with the given password immediately." | login of fixture users ⇒ 200 with fixture id/display name | test_core::L1_15 |
| L1.16 | 4 | "`opening_hours`… Per weekday. A day with no entry is closed" | no entry ⇒ closed (slots [] / outside_opening_hours); per-weekday hours | test_catalog::L1_54_per_weekday…, test_reservations::L1_63_closed_day |
| L1.17 | 4 | "`reservations` may seed confirmed bookings, with the same fields as a `POST /reservations` body plus `id`, `reference` and `user_id`." | seeded bookings visible to owner only, occupy tables, keep id/reference | test_reservations::L1_17 |
| L1.18 | 4 | "A booking must not be rejected solely because its start is in the past; the cancellation and amendment cutoff rules still apply." | past booking 201; then cancel/patch ⇒ 409 cutoff_passed | test_reservations::L1_18 |
| L1.19 | 5 | "Every 4xx and 5xx response carries this body: `{ "error": { "code": …, "message": … } }`" | shape on a sample of errors, incl. unknown routes/methods | test_core::L1_19, L1_31 |
| L1.20 | 5 | "400 `malformed_request` — Unparseable body, or a field of the wrong JSON type" | bad JSON, non-object body, wrong types of ids/starts_at_local/credentials ⇒ 400 | test_core::L1_20_* |
| L1.21 | 5/7 | "400 `missing_idempotency_key` — Required `Idempotency-Key` header absent or empty" | absent or empty on POST /reservations and /reservation-moves | test_idempotency::L1_21 |
| L1.22 | 5 | "401 `unauthenticated` — Missing, malformed or unknown bearer token" | no/Basic/empty/garbage token ⇒ 401 (R1: before key check) | test_core::L1_22_* |
| L1.23 | 5 | "403 `forbidden`" | not exercised: stage 1 reports foreign resources as 404 | none (by design) |
| L1.24 | 5 | "404 `not_found` — No such resource, or not visible to this caller" | see L1.50, L1.67, L1.69, L1.74, L1.100 | those checks |
| L1.25 | 5/7 | "409 `idempotency_key_reuse` — Key already used by this caller with a different request body" | changed body, same user ⇒ 409 | test_idempotency::L1_44, L1_45 |
| L1.26 | 5 | "422 `validation_failed` — A required field or query parameter is missing, or a stated rule is violated with no more specific code" | each missing body field / query param ⇒ 422 | test_core::L1_26, test_catalog::L1_51 |
| L1.27 | 5 | "A field of the correct JSON type with an invalid format or out-of-range value gives 422 `validation_failed`… This includes invalid dates, negative counts…" | impossible dates (Feb 30, month 13), negative/zero counts ⇒ 422; leap day valid | test_catalog::L1_27_* |
| L1.28 | 5 | "invalid `party_size` values (including strings and booleans) and `starts_at_local` strings that are not a bare local `YYYY-MM-DDTHH:MM` are 422… Other wrong JSON types follow the rule below." | party "4"/true/false/0/-1/2.5 ⇒ 422; 16 malformed starts_at_local strings (seconds, Z, offset, space, spaces…) ⇒ 422; non-string starts_at_local ⇒ 400 | test_core::L1_28_* |
| L1.29 | 5 | "An integer-valued query parameter is written as plain decimal digits: `1e9`, `4.0` and `+4` are 422" | availability party_size variants ⇒ 422 | test_core::L1_29, test_catalog::L1_27_party |
| L1.30 | 5 | "`Idempotency-Key` 1 to 255 characters, otherwise 422 `validation_failed`" | 1 and 255 ok; 256 ⇒ 422 on both endpoints | test_idempotency::L1_30 |
| L1.31 | 5 | "Requests must not produce 5xx responses, including under concurrent load." | garbage inputs on every endpoint ⇒ <500; no 5xx in all concurrency tests | test_core::L1_31, test_concurrency |
| L1.32 | 6 | "`POST /auth/signup` -> 201 `{ "user_id", "display_name", "token" }`" | shape; token works | test_core::L1_32 |
| L1.33 | 6 | "`POST /auth/login` -> 200 `{ "user_id", "display_name", "token" }`" | shape; same user_id as signup | test_core::L1_32, helper login |
| L1.34 | 6 | "Email already registered — 409 `email_taken`" | duplicate (incl. seeded email, other password); concurrent duplicate signups: exactly one 201 | test_core::L1_34, L1_39_concurrent_duplicate |
| L1.35 | 6 | "Password shorter than 8 characters — 422 `validation_failed`" | 7 ⇒ 422, 8 ⇒ 201, empty; characters not bytes; rejected signup does not consume email | test_core::L1_35_* |
| L1.36 | 6 | "`email` not of the form `local@domain` — 422 `validation_failed`" | plain, `a@`, `@b.com`, empty, space, double @ | test_core::L1_36 |
| L1.37 | 6 | "Wrong password or unknown email on login — 401 `unauthenticated`" | wrong/unknown/case-changed/padded password | test_core::L1_37 |
| L1.38 | 6 | "Every other endpoint requires a bearer token, except `/health`, `/_test/reset`, the two above, and the three public endpoints" | 6 protected endpoints ⇒ 401 without token; public ones open (even with junk token) | test_core::L1_38_* |
| L1.39 | 6 | "Tokens do not expire. An account may have multiple valid tokens and concurrent sessions." | repeated/concurrent logins give distinct, all-valid tokens; earlier tokens stay valid | test_core::L1_39_* |
| L1.40 | 6 | "Plaintext password storage is not permitted." | exported state does not contain plaintext passwords; login still works | test_export_import::L1_40 |
| L1.41 | 7 | "The key is scoped to **the authenticated user**. Two different users may use the same key string with no interaction between them." | same key+body from another user is first use (hits table_unavailable, not a replay); own replays return own body; keys case-sensitive; also on moves | test_idempotency::L1_41_*, test_moves::L1_41 |
| L1.42 | 7 | "The same key with the same body on a different path is a different request, not a replay, and must succeed normally." | key used on /reservations then /reservation-moves (and reverse) ⇒ 201 | test_idempotency::L1_42 |
| L1.43 | 7 | "…idempotency is resolved before endpoint-specific field validation or current-resource checks. Thus a used key with a different JSON body returns `409 idempotency_key_reuse` even when that new body would otherwise be invalid." | used key + invalid/empty/other body ⇒ 409; missing key beats field errors; parse errors first (R3) | test_idempotency::L1_43_*, test_moves::L1_110 |
| L1.44 | 7 | "First use: 201 · Replay: 200, body identical… · Same key, different body: 409 · Key reused after the original request failed with 4xx: treated as a first use" | 201, replay 200 identical (repeat ×4), failed (422/404/409) key reusable even with the same failed body again | test_idempotency::L1_44_* |
| L1.45 | 7 | "'Same body' means the same JSON value after parsing — key order and whitespace do not matter." | reordered/whitespace body ⇒ 200; extra field ⇒ 409 (R10) | test_idempotency::L1_45 |
| L1.46 | 7 | "For concurrent identical requests with an unused key, exactly one returns 201. The others return 200 with the same body. The operation takes effect only once." | 50 identical in flight ⇒ 1×201 + 49×200, identical bodies, one reservation; same for moves; mixed bodies ⇒ one winner, others 200/409 | test_idempotency::L1_46_*, test_moves::L1_46, test_concurrency::L1_46 |
| L1.47 | 7 | "A successful replay returns the original response, even after the resource changes or is cancelled. It makes no further state change." | replay after PATCH, cancel, other user taking the slot ⇒ 200 original; no rebooking | test_idempotency::L1_47 |
| L1.48 | 8 | "`GET /restaurants` → `{ "restaurants": [ { id, name, timezone } ] }`" | list in fixture order, empty list shape | test_catalog::L1_48 |
| L1.49 | 8 | "`GET /restaurants/{id}` The restaurant with its `slot_minutes`, … `opening_hours` and `tables`, in the fixture's shape." | all fields equal fixture; tables ordered | test_catalog::L1_49_* |
| L1.50 | 8 | "404 if unknown." | restaurant and availability with unknown restaurant ⇒ 404 | test_catalog::L1_50_* |
| L1.51 | 8 | "All three parameters are required; a missing one is 422 `validation_failed`." | each missing param (and none) ⇒ 422 | test_catalog::L1_51 |
| L1.52 | 8 | availability response shape (`restaurant_id`, `date`, `timezone`, `slots[{starts_at_local, starts_at, available_table_ids}]`); "`date` is a local calendar date at the restaurant." | exact first slot; zone per restaurant; offsets | test_catalog::L1_52_* |
| L1.53 | 8 | "`starts_at_local` is the full `YYYY-MM-DDTHH:MM` and goes into `POST /reservations` unchanged." | slot value posted verbatim ⇒ 201 with same starts_at | test_catalog::L1_53 |
| L1.54 | 8 | "A slot appears for every `slot_minutes` step from `opens` such that `slot + reservation_duration_minutes <= closes`." | 9 parameter sets (odd grids 7/45/20 min, equality at closes, 1 minute short) | test_catalog::L1_54_* |
| L1.55 | 8 | "`available_table_ids` lists the tables of that restaurant with `capacity >= party_size` and no overlapping confirmed reservation, in fixture order." | party 1…7 boundaries, fixture (not sorted) order, overlap windows, other days/tables unaffected, cancelled not counted | test_catalog::L1_55_*, L1_2 |
| L1.56 | 8 | "A slot with no available table still appears, with an empty list." | party 7 ⇒ all slots, empty lists | test_catalog::L1_55_availability_by_party_size |
| L1.57 | 8 | "A closed day returns `"slots": []`." | closed weekday ⇒ 200 with `[]` | test_catalog::L1_54_per_weekday |
| L1.58 | 8 | POST /reservations 201 body (all fields incl. `status: confirmed`, `ends_at`, `created_at`) | shape and values; ends_at = starts_at + duration | test_reservations::L1_58 |
| L1.59 | 8 | "`starts_at_local` is wall-clock at the restaurant… Resolve it against the restaurant's `timezone`." | NY/Berlin/Kolkata offsets (+05:30) | test_dst::L1_59 |
| L1.60 | 8 | "`reference` is 6 to 12 characters of `A-Z0-9`, unique across all reservations, and never changes." | regex on 9+ refs, uniqueness (also under 50 concurrent), stable over patch/cancel, no collision with seeds | test_reservations::L1_60, test_concurrency::L1_46_fifty |
| L1.61 | 8 | "The table is taken for an overlapping interval — 409 `table_unavailable`" | every overlapping start (-90..+89 min) ⇒ 409; other table/day free | test_reservations::L1_61_* |
| L1.62 | 8 | "`starts_at_local` is not on the slot grid — 422 `not_on_slot_grid`" | off-grid minutes; grid anchored at opens (18:15 grid) | test_reservations::L1_62_* |
| L1.63 | 8 | "Slot outside opening hours, or the reservation would end after `closes` — 422 `outside_opening_hours`" | before opens, ends at closes ok, ends 30 min after closes ⇒ 422, closed day | test_reservations::L1_63_* |
| L1.64 | 8 | "`party_size` exceeds the table's `capacity` — 422 `party_exceeds_capacity`" | cap±1 on each table; huge party | test_reservations::L1_64 |
| L1.65 | 8 | "`party_size` below 1, or not an integer — 422 `validation_failed`" | 0,-1,-100,1.5,"2",true | test_reservations::L1_65, test_core::L1_28 |
| L1.66 | 8/9 | "`starts_at_local` is a local time that does not exist (see §9) — 422 `invalid_local_time`" | POST and PATCH into the skipped hour | test_dst::L1_82, test_reservations::L1_66 |
| L1.67 | 8 | "Unknown restaurant, unknown table, or the table belongs to another restaurant — 404 `not_found`" | all three, both directions; precedence R2 | test_reservations::L1_67, L1_66_67 |
| L1.68 | 8 | "The caller's reservations, `starts_at` descending, confirmed and cancelled alike… An empty list is `{"reservations": []}`" | order by instant incl. cross-timezone, cancelled included, only own, same shape as create | test_reservations::L1_68_* |
| L1.69 | 8 | "**404 if it is not the caller's** — do not leak the existence of other people's bookings." | other user / unknown reference ⇒ 404 | test_reservations::L1_69 |
| L1.70 | 8 | cancel ⇒ 200 `{reference, status: cancelled, …}` | all other fields unchanged | test_reservations::L1_70 |
| L1.71 | 8 | "Frees the table immediately: the next `GET /availability` must offer that slot again." | availability and rebooking right after cancel; concurrent cancel/rebook | test_reservations::L1_70, test_concurrency::L1_71 |
| L1.72 | 8 | "Already cancelled — 200 with the current state — cancelling twice is not an error" | second cancel ⇒ 200, identical | test_reservations::L1_72 |
| L1.73 | 8 | "Now is within `cancellation_cutoff_minutes` of `starts_at`, or later — 409 `cutoff_passed`" | past ⇒ 409 (cutoff 120 and 0); ±10 min around the cutoff instant (R6) | test_reservations::L1_73_*, L1_18 |
| L1.74 | 8 | "Not the caller's reservation — 404 `not_found`" | foreign cancel ⇒ 404 and untouched | test_reservations::L1_74 |
| L1.75 | 8 | "Any subset of `table_id`, `starts_at_local`, `party_size`. No idempotency key is required here." | each field alone, all three; unlisted fields keep; no key header | test_reservations::L1_75, L1_76_patch_no_key |
| L1.76 | 8 | "Validation is identical to `POST /reservations`" | same codes: grid, hours (ends at closes ok), capacity (incl. via table change), party types, wrong types ⇒ 400, 404 table, 409 taken, unknown reference 404 | test_reservations::L1_76_* |
| L1.77 | 8 | "the same cutoff rule as cancel applies (409 `cutoff_passed`), measured against the **current** start time." | near booking can't move far; far booking may be moved *into* the window, then is frozen | test_reservations::L1_77, L1_18 |
| L1.78 | 8 | "A cancelled reservation is 409 `reservation_cancelled`." | patch of cancelled ⇒ 409, not revived | test_reservations::L1_78 |
| L1.79 | 8 | "A successful amendment releases the old slot and reserves the new one together." | old slot offered again, new taken; may overlap own old interval; 50 concurrent amendments onto one slot ⇒ one winner | test_reservations::L1_79_*, test_concurrency::L1_80_L1_79 |
| L1.80 | 8 | "A failed amendment leaves the original booking and its occupancy unchanged." | 8 failure kinds + mixed valid/invalid fields ⇒ unchanged record and availability; concurrent losers unchanged | test_reservations::L1_80, test_concurrency |
| L1.81 | 8 | "`reference` and `reservation_id` survive a change." | also created_at, status | test_reservations::L1_81 |
| L1.82 | 9 | "**Spring forward.** Local times in the skipped hour do not exist. They never appear in availability, and booking one is 422 `invalid_local_time`." | Berlin 2026-03-29 and NY 2026-03-08: 02:00/02:30 absent, 43 slots in Berlin, 422 on POST | test_dst::L1_82_* |
| L1.83 | 9 | "**Fall back.** … **Always resolve to the first occurrence — the one before the clocks change.** The slot appears once in availability, and the second occurrence is not bookable." | Berlin 2026-10-25 02:00/02:30, NY 2026-11-01 01:00/01:30: once, first offset; booked as first occurrence; rebooking the same string conflicts | test_dst::L1_83_* |
| L1.84 | 9 | "`reservation_duration_minutes` is **absolute time**, not wall-clock. A 90-minute reservation starting at 01:30 on a fall-back night ends 90 real minutes later, and its local `ends_at` will read 02:00, not 03:00." | exact ends_at for 4 transitions; occupancy computed in absolute time (overlap/touch tests) | test_dst::L1_84_* |
| L1.85 | 9 | transitions table (Berlin, New York, both directions) | ordinary days unaffected; all 4 dates used | test_dst::L1_85, L1_86 |
| L1.86 | 9 | "Offsets must follow the IANA rules for the specified zone and date." | offsets before/after each transition; US/EU gap weeks; winter/summer | test_dst::L1_86_*, test_catalog::L1_52 |
| L1.87 | 10 | "Return 200 from export with a JSON object containing `track: "tablekeeper"`, `format_version: 1` and `state`… unauthenticated" | shape, no auth | test_export_import::L1_87 |
| L1.88 | 10 | "Import takes that entire object and atomically replaces the service's state, returning 204. It must accept an unchanged export produced by this service." | round trip restores everything; few hundred reservations within the 10 s limit | test_export_import::L1_88_* |
| L1.89 | 10 | "Import is replacement, not merge; repeating it restores the exported state without duplicating anything." | 3× import identical; re-export stable | test_export_import::L1_89 |
| L1.90 | 10 | "Invalid JSON follows §5; missing fields, wrong track/version or an invalid state give 422 `validation_failed` without changing the destination." | 13 invalid objects ⇒ 422; bad JSON ⇒ 400; destination unchanged; foreign/tampered state (R4) | test_export_import::L1_90_* |
| L1.91 | 10 | "Preserve accounts and hashed-password login, existing bearer tokens, fixture configuration, reservations, references, all completed idempotent request bodies and original responses. Identities, statuses and timestamps must not be regenerated." | after import: lists byte-equal, logins (seeded + signed-up), config, cancelled status | test_export_import::L1_88_roundtrip |
| L1.92 | 10 | "Failed request keys remain reusable." | key of a 409 request ⇒ 201 after import | test_export_import::L1_93_L1_92 |
| L1.93 | 10 | "Existing receipts, references, tokens and retries must remain valid after import; replacing the state with a fresh fixture does not satisfy this requirement." | old tokens work, replay ⇒ 200 original, reuse ⇒ 409, new refs unique | test_export_import::L1_93_L1_92 |
| L1.94 | 10 | "Import removes all previous destination data and credentials." | destination's extra users/tokens/restaurants gone; works into a different fixture | test_export_import::L1_94_* |
| L1.95 | 10 | "Reset continues to clear all state, including imported state." | tokens, logins, receipts gone after reset | test_export_import::L1_95 |
| L1.96 | 10 | "Export is an atomic, read-only snapshot; subsequent source writes do not change it." | export doesn't alter state/receipts; 6 exports during 20 concurrent bookings are each consistent (every booking present has its receipt) | test_export_import::L1_96_* |
| L1.97 | 10 | "No dependency on the source process, files, volume, port or network address is allowed." | import after an unrelated reset reproduces the exported state | test_export_import::L1_94_different_fixture |
| L1.98 | 11 | "`POST /reservation-moves` requires authentication and an idempotency key." | 401 (no/bad token), 400 missing key | test_moves::L1_98, test_idempotency::L1_21 |
| L1.99 | 11 | "`moves` contains 1..8 objects with distinct string references. Invalid shape or duplicate references gives 422 `validation_failed`." | 0, 9 items ⇒ 422; 1 and 8 ok; duplicates, non-string refs, missing fields (R5) | test_moves::L1_99_* |
| L1.100 | 11 | "Every booking must belong to the caller and the same restaurant. Unknown/another owner's reference gives 404 `not_found`; different restaurants give 422 `validation_failed`." | 404 variants (nothing applied), 422 mixed restaurants | test_moves::L1_100_* |
| L1.101 | 11 | "Each item accepts the ordinary PATCH fields `table_id`, `starts_at_local`, `party_size`; omitted fields retain their current values and unknown fields are ignored." | partials; ignored `status`/`user_id`/`created_at`; 8 ordinary error codes | test_moves::L1_101_* |
| L1.102 | 11 | "The booking's identity, owner and creation time never change." | reference, id, created_at, owner | test_moves::L1_102, L1_101 |
| L1.103 | 11 | "Cancelled bookings give 409 `reservation_cancelled`." | alone and with other valid moves ⇒ nothing applied | test_moves::L1_103 |
| L1.104 | 11 | "Each booking's existing cutoff applies." | past booking in position 1 or 2 ⇒ 409, rest not applied | test_moves::L1_104 |
| L1.105 | 11 | "Non-occupancy errors use ordinary amendment codes and take precedence in input order, with cutoff errors preceding other changes for that booking." | first failing item decides; per-booking cutoff before field errors | test_moves::L1_105 |
| L1.106 | 11 | "An overlap among resulting bookings or with an unlisted booking gives 409 `table_unavailable`." | overlap within batch, with own/other users' unlisted bookings, partial overlap; touching ok; non-occupancy errors beat occupancy errors; 20 competing batches ⇒ one winner | test_moves::L1_106_*, L1_1 |
| L1.107 | 11 | "Unchanged listed bookings retain their occupancy." | moving onto an unchanged listed booking ⇒ 409 | test_moves::L1_107 |
| L1.108 | 11 | "Either every move commits or nothing changes: occupancy, reservation records and retry keys." | failed batch leaves records/availability intact; same key then succeeds with corrected body | test_moves::L1_108, L1_1_competing |
| L1.109 | 11 | "On success return 201 with `{"reservations": [...]}` in input order, including unchanged items." | order, unchanged items, equals stored state | test_moves::L1_109 |
| L1.110 | 11 | "Replays return that original response with 200, even after amendments or cancellations." | replay after patch/cancel, reordered JSON, reuse ⇒ 409, invalid new body ⇒ 409 | test_moves::L1_110 |
| L1.111 | 11 | "No-op moves retain all existing values." | `{reference}` only; explicit same values | test_moves::L1_111 |
| L1.112 | 11 | "Export/import preserves successful batch receipts as well as the resulting bookings." | replay of a move key after import ⇒ 200 original | test_export_import::L1_112 |
| L1.113 | 11 | (implied by 106/107: validation is on the *resulting* set) | swap tables, 3-way rotation, swap times on one table, slide-to-touch | test_moves::L1_113 |

## Earlier-stage behaviours this stage could break
Stage 1 is the first stage; nothing earlier. (Checks for stage 2+ regressions will rerun this folder.)

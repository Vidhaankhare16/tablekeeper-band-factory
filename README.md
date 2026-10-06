# Tablekeeper, built by a five-seat dark factory

Entry for the **WeAreDevelopers × BAND "AI Dark Factory" hackathon**, **tablekeeper** track.
Team: Vidhaan Khare ([@Vidhaankhare16](https://github.com/Vidhaankhare16)).

A restaurant reservation service, built stage by stage by five coding agents. They worked in one
BAND room from **a single dispatched message**. No human wrote or changed any code under
`stage-N/`, `checks/` or `evidence/`.

**Result:**
- All four stages were accepted by the band in 2 h 49 min.
- On a fresh clone in the judges' isolated mode, every folder `stage-1/`…`stage-4/` claims its
  stage on the shipped checks (120/120, 25/25, 7/7, 6/6), and none overshoots.
- Behind that, the examiner seat's own suites reach 700 passing checks.

**Live demo** (the band's `stage-4/` code, unchanged, hosted on Cloud Run with two demo restaurants loaded at start): https://tablekeeper-demo-896860697904.us-central1.run.app (log in as `demo@example.com` / `correct horse`, or sign up). State is in memory, as the spec allows, so the demo resets when the instance restarts.

## Demo tour (about 5 minutes)

**In the browser.** Log in first, from the top right. Signed out you can search, but booking asks you
to sign in. The demo sleeps when idle: if the first login fails, wait a few seconds and try again.
1. **Book a table.** Choose *The Lantern Room*, a date and a party size, then **Find tables**. Each
   time slot lists every table, plus a group of "Combined tables for larger parties". Each cell says
   *Available*, *Taken* or *Too small*. Try a party of 7: no single table fits, so the only offer is Window 2 + 3 together. Click an
   available cell, then **Confirm reservation**, and you get a reference.
2. **An uncertain outcome.** Before confirming, set DevTools → Network to *Offline* and press
   **Confirm reservation**. The UI says it cannot tell whether the table is booked and offers
   **Try again safely**. Go back online and press it: the same request is resent, and you get one
   booking, never two.
3. **Find a booking** (main navigation). Paste the reference to see the booking and cancel it. Try it
   at phone width too.

**Stages 3–4 through the API.** The spec adds no new screens for these; their effects show up in the
grid and in **Find a booking**. Paste this into a terminal with `curl` and `python3`. It picks a random
winter date, so runs by different people rarely collide.

```sh
B=https://tablekeeper-demo-896860697904.us-central1.run.app
J='content-type: application/json'
py() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
login() { curl -s -X POST $B/auth/login -H "$J" -d "{\"email\":\"$1\",\"password\":\"correct horse\"}" | py 'd["token"]'; }
until DINER=$(login demo@example.com 2>/dev/null) && [ -n "$DINER" ]; do sleep 2; done   # waits out a cold start
MGR=$(login manager@example.com)
DATE=$(python3 -c "import datetime as t,random; d=[t.date(2026,11,9)+t.timedelta(days=i) for i in range(136)]; print(random.choice([x for x in d if x.weekday()<4]))")

# 1. Book Window 2 for four at 19:00
REF=$(curl -s -X POST $B/reservations -H "authorization: Bearer $DINER" -H "Idempotency-Key: tour-$RANDOM$RANDOM" -H "$J" \
  -d "{\"restaurant_id\":\"r_lantern\",\"table_id\":\"t_2\",\"starts_at_local\":\"${DATE}T19:00\",\"party_size\":4}" | py 'd["reference"]')
echo "booked $REF on $DATE"; [ -n "$REF" ] || echo "An earlier run took that slot: paste the block again for a new date."

# 2. Make it weekly for four weeks, then move weeks 3 and 4 to 20:00
SERIES=$(curl -s -X POST $B/series -H "authorization: Bearer $DINER" -H "Idempotency-Key: tour-$RANDOM$RANDOM" -H "$J" \
  -d "{\"anchor_reference\":\"$REF\",\"count\":4,\"interval_weeks\":1}")
SID=$(echo "$SERIES" | py 'd["series_id"]'); REV=$(echo "$SERIES" | py 'd["revision"]')
curl -s -X POST $B/series/$SID/amend -H "authorization: Bearer $DINER" -H "Idempotency-Key: tour-$RANDOM$RANDOM" -H "$J" \
  -d "{\"expected_revision\":$REV,\"from_index\":2,\"local_time\":\"20:00\"}" | py '[o["reservation"]["starts_at_local"] for o in d["occurrences"]]'

# 3. Why each table is or isn't free at 19:00: (table, available, rules that fail)
curl -s "$B/availability?restaurant_id=r_lantern&date=$DATE&party_size=4&explain=true" \
  | py '[(e["table_id"], e["available"], [r["rule"] for r in e["rules"] if not r["holds"]]) for s in d["slots"] if s["starts_at_local"].endswith("19:00") for e in s["explain"]]'

# 4. The manager closes Window 2 that evening: preview the replan, then apply it atomically
PLAN=$(curl -s -X POST $B/restaurants/r_lantern/replans -H "authorization: Bearer $MGR" -H "Idempotency-Key: tour-$RANDOM$RANDOM" -H "$J" \
  -d "{\"table_id\":\"t_2\",\"from\":\"${DATE}T18:00:00+01:00\",\"to\":\"${DATE}T22:00:00+01:00\"}")
echo "$PLAN" | py 'd["assignments"]'
curl -s -X POST $B/restaurants/r_lantern/replans/$(echo "$PLAN" | py 'd["plan_id"]')/apply -H "authorization: Bearer $MGR" \
  -H "Idempotency-Key: tour-$RANDOM$RANDOM" -H "$J" -d '{}' | py '[(r["reference"], r["table_ids"]) for r in d["reservations"]]'

# 5. The booking's own history, oldest first: created, then reassigned by the plan
curl -s $B/reservations/$REF/history -H "authorization: Bearer $DINER" | py '[(e["event"], e["changes"]) for e in d["entries"]]'
```

Then, logged in as `demo@example.com`, open **Find a booking** with the printed reference: it now
shows the table the plan moved it to. Searching that date shows Window 2 taken during the closure.

## How to read this repository

| Path | What it is |
|---|---|
| [`FACTORY.md`](FACTORY.md) | **Start here.** The factory: seats, design, how to stand it up, how it catches bad work, what failed while we built it, measured cost and time, and our verification |
| [`mandates/`](mandates/) | One generic standing instruction per seat (`Harness:` and `Model:` first) |
| [`room.json`](room.json) | The full BAND room export of the judged run, as downloaded (Download full session) |
| [`stage-1/`](stage-1/) … [`stage-4/`](stage-4/) | One complete, buildable service per stage. Each has a `Dockerfile` and a `RUN.md`; stage N+1 began as a copy of the accepted stage N |
| [`checks/`](checks/) | The examiner seat's requirement ledgers (`ledger.md`, every normative sentence quoted with an id) and black-box checks, written from the spec without reading product code |
| [`evidence/`](evidence/) | Screenshots the surface seat took at 375 px and 1280 px |
| [`CLAUDE.md`](CLAUDE.md), [`.claude/settings.json`](.claude/settings.json), [`factory/bin/`](factory/bin/) | The seat runtime: rules every seat loads, narrow permission rules, room poster, check runner, Docker start hook |

## Run a stage

```sh
cd stage-4                       # or stage-1, stage-2, stage-3: see that folder's RUN.md
docker build -t tablekeeper-stage-4 .
docker run --rm -e PORT=8080 -p 8080:8080 tablekeeper-stage-4
curl localhost:8080/health       # {"status": "ok"}
# Stage 2 and later serve the browser product at http://localhost:8080/
```

State lives in memory. Load data with `POST /_test/reset`, using a fixture in the format of the
stage-1 spec.

## Trace the work

- Every commit under `stage-N/`, `checks/` and `evidence/` is authored by a seat (`builder`,
  `surface`, `examiner`), and every commit message names its work order (`S3.W2: …`).
- The room shows each step with a fixed header (`WORK ORDER`, `DELIVERY`, `LEDGER`,
  `REVIEW REQUEST`, `VERDICT`, `FINAL REPORT`), with the same work-order ids and revisions.
- The only human messages and commits are:
  - the factory setup commit before the dispatch;
  - the dispatch itself;
  - this README, `FACTORY.md` and `room.json`, after the final report.

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

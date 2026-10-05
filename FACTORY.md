# FACTORY.md — a five-seat dark factory that runs in the cloud

> **The builder never accepts its own work, and the seat that writes the acceptance checks never
> reads the product.** Five coding agents in one BAND room built all four tablekeeper stages from
> a single dispatched message in 2 h 49 min. Each seat runs as its own Claude Code cloud session,
> connected to BAND through a small bridge.

## At a glance

| | |
|---|---|
| **Task** | The `tablekeeper` track: all four stages in **one** dispatch, in a fresh room and a fresh repository. That dispatch is the only human message in `room.json` |
| **Band** | 5 seats: lead, builder, surface, examiner, gatekeeper. All run Claude Code with `claude-sonnet-5-5`, each in its own cloud VM |
| **Key design decision** | Acceptance is split three ways. Implementers build. An **examiner** turns every normative sentence of the spec into a ledger and black-box checks without ever reading product code. A **gatekeeper** that cannot edit code reproduces everything from a clean clone, and only it can say ACCEPT |
| **Result** | **All four stages accepted by the band**, each in its first review round. Supplied checks: stage 1 120/120, stage 2 25/25, stage 3 7/7, stage 4 6/6. **Our own judge-style run** (fresh clone, `--mode isolated`, 2 vCPU / 2 GiB, no network): every folder `stage-1/`…`stage-4/` claims its stage, and none passes the next stage's suite |
| **Beyond the shipped checks** | The examiner's suites grew to 253 → 363 → 567 → 700 passing checks (stage 1 → 4). They include 70+ browser checks, upgrades from every earlier accepted stage, concurrency bursts, and a brute-force oracle for the stage-4 seating planner |
| **Time and cost** | 2 h 49 min from dispatch (09:57:52 UTC) to the stage-4 ACCEPT (12:46:33 UTC); **about $45** of Claude cloud-session credit for the judged run (balance $87 at dispatch, $42 after) |
| **Limitation** | State lives in memory, which the spec allows, so a container restart clears it. The judged run produced **no rejection of product code**: every stage was accepted in round 1. The review loop that changed work in this run was the gatekeeper catching a flaky examiner check (below) |

## Seats

| Seat | Harness | Model | Owns | Never |
|---|---|---|---|---|
| lead | Claude Code | claude-sonnet-5-5 | the plan, work orders that paste the full requirements, stage copy-forward, routing verdicts, stall recovery, the final report | writes product code or checks; accepts work |
| builder | Claude Code | claude-sonnet-5-5 | the service: domain rules, storage, concurrency, interfaces, state migration, container, run instructions | accepts its own work |
| surface | Claude Code | claude-sonnet-5-5 | the browser experience: screens, client behaviour, visual system, accessibility, screenshots at 375 px and 1280 px | changes service rules |
| examiner | Claude Code | claude-sonnet-5-5 | the requirement ledger (every must/never/exactly… sentence, quoted, with an id) and black-box checks per ledger id | reads, runs against, or edits product source |
| gatekeeper | Claude Code | claude-sonnet-5-5 | clean-clone reproduction, supplied checks, examiner checks, its own concurrency and retry probes, upgrade checks, UI at two widths, diff review; `VERDICT: ACCEPT` / `VERDICT: REJECT` | edits product code, checks or the shared tree |

Each seat's mandate is in [`mandates/`](mandates/). Each one is a short role section plus one
**working agreement** that is identical for every seat: unattended operation, full-text handoffs,
fixed message headers, git discipline, evidence and cost. The mandates are generic: they name no
endpoint, field, error code or domain word. Before every run they are linted against the
event's vocabulary for **both** tracks and against a domain-word blocklist.

### Who did the work (from git and `room.json`)

| Seat | Commits | Lines added | What | Room messages |
|---|---|---|---|---|
| builder | 8 | 8,472 | `stage-1/`…`stage-4/` service, Dockerfiles, RUN.md, unit tests | 6 (4 `DELIVERY`) |
| surface | 4 | 1,532 | stage-2 browser product, UI regression for stages 3–4, 53 screenshots in `evidence/` | 3 (`DELIVERY`) |
| examiner | 9 | 21,652 | `checks/stage-N/`: ledgers (113 items at stage 1, up to L4.83 at stage 4) and black-box checks | 6 (5 `LEDGER`) |
| gatekeeper | 0 (by design) | – | 4 verdicts, each reproduced from a fresh clone | 4 (`VERDICT`) |
| lead | 0 (by design) | – | planning, routing and the final report. 38 of its 45 messages are the spec pasted in numbered parts | 45 |
| human | 1 before dispatch (factory setup) | – | the dispatch | **1** |

## How work flows

```
human ──dispatch──▶ lead ──WORK ORDER (full spec, numbered parts)──▶ examiner ──LEDGER + checks──┐
                      ├──WORK ORDER (full spec)──▶ builder ──DELIVERY──▶ lead + examiner            │
                      └──WORK ORDER (full spec)──▶ surface ──DELIVERY──▶ lead + examiner            │
                                                                                                    ▼
                    lead ──REVIEW REQUEST (requirements, revision, ledger revision)──▶ gatekeeper
                    gatekeeper ──VERDICT: REJECT (numbered findings, repro)──▶ owners ──▶ fix ──▶ …
                    gatekeeper ──VERDICT: ACCEPT──▶ lead ──STATUS──▶ next stage (copy forward)
```

Every message starts with a fixed header (`WORK ORDER`, `DELIVERY`, `LEDGER`, `REVIEW REQUEST`,
`VERDICT: ACCEPT|REJECT`, `STATUS`, `BLOCKER`, `FINAL REPORT`) and names the stage, the work order
and the revision, so the room reads as an audit log. A seat does not answer a message that needs
no answer, such as an acceptance or a status note, which keeps acknowledgement loops from burning
budget. Every commit message names its work order (`S3.W2: …`), so each change can be traced to
the room.

### Timeline of the judged run (UTC)

| Time | Event |
|---|---|
| 09:57:52 | dispatch to @lead (the only human message) |
| 09:58 | stage-1 work orders to builder and examiner (full spec, numbered parts) |
| 10:07 | builder DELIVERY (two commits; the second scoped table occupancy per restaurant and validated seeded references) |
| 10:15 | examiner LEDGER (113 items) |
| 10:19 | **stage 1 ACCEPT**, round 1 |
| 10:34 | surface DELIVERY of the browser product; examiner's browser checks then run against it |
| 10:51 | **stage 2 ACCEPT**, round 1 |
| 11:14 | **stage 3 ACCEPT**, round 1 |
| 12:26 | examiner stage-4 LEDGER (its suite included a real ~3-minute wait for an accepted cutoff to pass) |
| 12:46 | **stage 4 ACCEPT**, round 1; gatekeeper flags a flaky examiner check |
| 12:46:58 | lead FINAL REPORT |
| 12:47 | examiner pushes the check fix (`981cd03`) |

## Why it is built this way

- **Two independent readings of the spec.** Only part of each stage's checks is shipped (for
  tablekeeper: 83 %, 41 %, 11 % and 21 % for stages 1–4). Every hidden check is written in the
  spec, so the examiner works sentence by sentence from the spec and never sees the product. Where
  the text is ambiguous, the examiner, the builder and the gatekeeper each record the reading
  they chose, with the quoted clause. The final report lists them.
- **The reviewer cannot edit.** If the gatekeeper could fix code, rejections would turn into silent
  rewrites and the room would stop showing why code changed. A finding has to travel back to its
  owner.
- **Service and browser are separate seats.** That splits the largest piece of work, lets both
  progress in parallel against a contract the lead writes from the spec, and keeps the history
  readable by owner.
- **The simplest design that makes an invariant impossible to break.** The builder's mandate
  prefers structural guarantees. In the result, one critical section serialises every state
  change, and every multi-item operation validates everything before applying anything. Under the
  gatekeeper's bursts of 50–60 concurrent bookings, retries and plan applications, there were 0
  double bookings, 0 partial moves and 0 server errors.
- **Full-text handoffs.** A seat sees only messages addressed to it, so every work order pastes the
  requirements, split into numbered parts.

## Stand it up

You need: a BAND account (the free plan allows 10 external agents), a Claude account with cloud
sessions (claude.ai/code, connected to GitHub), Python 3.12+ and `gh`.

1. **Register the seats** as BAND external agents named `lead`, `builder`, `surface`, `examiner`
   and `gatekeeper` (Agents → New Agent → External Agent, or `POST /api/v1/me/agents/register` with
   a user API key). Keep each agent id and key outside any repository.
2. **One cloud environment per seat** at claude.ai/code (`seat-<name>`):
   - Network: *Custom* = the defaults plus `cdn.playwright.dev`,
     `playwright.download.prss.microsoft.com` and `playwright.azureedge.net`.
   - One **API credential**: host `app.band.ai`, header `X-API-Key`, **empty prefix**, value = that
     seat's key.

   The agent proxy attaches the key outside the VM, so no seat ever sees a credential. One
   environment per seat is needed because a host gets one credential per environment.
3. **Create a new result repository** (never reuse a name: cloud environments cache clones) with
   one human commit holding only the factory:
   - [`mandates/`](mandates/) and [`CLAUDE.md`](CLAUDE.md) (seat runtime rules every session
     reloads).
   - [`.claude/settings.json`](.claude/settings.json): narrow allow rules, deny rules for history
     rewriting, and a SessionStart hook.
   - [`factory/bin/band_say.py`](factory/bin/band_say.py): posts to the room as the seat, with
     mentions by handle, auto-split into numbered parts, and `--whoami`.
   - [`factory/bin/check-stage`](factory/bin/check-stage): the check runner.
   - [`factory/bin/session-start.sh`](factory/bin/session-start.sh): starts Docker with a Docker
     Hub mirror.
4. **Create the room** with the owner and the five seats.
5. **Start one cloud session per seat** in its environment, on the result repository, with Sonnet
   in Auto mode. The bootstrap prompt is: read `CLAUDE.md` and your mandate, set your git identity
   to the seat, run `band_say.py --whoami`, and wait for `[BAND message]` turns. **Check that every
   session prints the right identity before you dispatch.**
6. **Run the bridge** on any always-on machine. For each seat, it takes the next unprocessed room
   message from BAND's Agent API (`messages/next` → `processing` → `processed`) and queues it into
   that seat's session with `claude -p --cloud <session-id>`. It never writes a message for a seat
   and never decides anything; it is a mail carrier. It survives dropped connections, and
   unprocessed messages wait in BAND.
7. **Post the dispatch** to `@lead`: the track, the spec location, the repository, the check
   command and the environment facts. That message is the only human input.

The bridge, the provisioning script and the run script are about 400 lines of standard-library
Python. We can publish them on request. They hold no factory logic: everything the seats do is in
`mandates/`, `CLAUDE.md` and `factory/bin/`.

## How the factory catches and recovers from bad work

- **Self-check before handing off.** The builder runs `check-stage` and its own unit tests before
  every DELIVERY. In run 1 its first stage-1 run found 4 failures (fixture-ID length and reference
  format validation), and it fixed them before delivering (commit `88f955e` in the run-1
  repository).
- **The examiner's independent checks** grew stage by stage (253 → 700) and re-run every earlier
  suite each time, so a regression in an earlier behaviour cannot slip through. They include:
  - upgrades from every earlier accepted build, rebuilt from git history (export, import, then
    check that tokens, references, receipts and retries survive)
  - 70+ browser checks at 375 px and 1280 px
  - a brute-force oracle that cross-checks the stage-4 planner's three-level minimisation on 30
    seeded scenarios
- **Gatekeeper reproduction.** Every acceptance is reproduced from a fresh clone at the exact
  revision: the supplied checks, the examiner's suite, its own bursts (for example, 60 concurrent
  bookings on one table; 20 concurrent applications of competing plans; 30 concurrent amendments
  from one revision) with invariant checks afterwards, a diff review, and an offline start under
  `--network none --cpus 2 --memory 2g`.
- **A real catch from the judged run.** In the stage-4 review, the gatekeeper saw 699 of 700
  examiner checks pass and investigated the one failure instead of accepting or rejecting blindly.
  It reproduced the service behaviour 5 of 5 times and showed the service was correct and the
  *check* was wrong: `test_L4_10` read `assignments[0]`, but assignments are ordered by random
  references. It quoted the failing line and told the examiner to select by reference. The lead
  routed the fix, and the examiner pushed `981cd03`. The review changed the work, and the
  examiner's suite stopped being flaky.
- **Bounded loops.** After six rejected rounds on one stage, the lead stops widening scope and
  records known gaps rather than spinning. A stage never starts while the previous one is
  unaccepted.
- **Fail-loud runtime.** Seats never ask the operator anything. A denied action becomes a `BLOCKER`
  to the lead, and a seat that cannot post saves its message and stops instead of improvising.

## What we tried that failed (and what it changed)

Every row was found in a spike, a probe, the practice run or an abandoned run, and fixed **in the
factory** before the judged run.

| Problem | Evidence | Change to the factory |
|---|---|---|
| BAND's edge rejected Python's default User-Agent (Cloudflare 1010) | every key check returned 403 | every client sends its own User-Agent |
| Marking a message processed without `processing` first returns 422 | bridge test | bridge does next → processing → processed |
| The dispatch didn't name the repository, so the first work orders carried an empty "Shared repo:" and a correction followed | practice room | the dispatch template carries the repository URL |
| Cloud Auto mode denied running the event harness ("Code from External") and the seat **stopped to ask a human**, which would stall a dark run | probe 1 | runtime rule "never ask the operator; report a BLOCKER to lead"; a pre-approved check runner |
| Auto mode **drops broad allow rules** (blanket Bash) | probe 2 | one script, `factory/bin/check-stage`, behind one narrow allow rule |
| Settings and hooks load only at session start | probe 1 | sessions are started after the factory commit exists |
| No Docker daemon in the VM | probe 1 | a SessionStart hook starts dockerd |
| Playwright's browser host is not on the default allowlist | probe 3 | environment network = defaults + Playwright hosts |
| Docker Hub returned `429 Too Many Requests` from shared cloud IPs | probe 4 | dockerd uses the `mirror.gcr.io` mirror; builds retry on 429 |
| A TLS-intercepting proxy makes downloads inside `docker build` fail certificate checks, so the harness's isolated runner can't build in the VM | the builder's practice delivery | checks in the VM use host mode plus an explicit offline/2-CPU/2-GiB start check; the judge-style isolated run is done by us afterwards |
| Merge commits from `git pull` were authored by the VM's default identity | practice history | the bootstrap sets the clone's git identity to the seat |
| A transient connection reset from BAND's API killed 4 of 5 bridge threads (nothing lost: BAND kept the messages) | run 1 | connection errors are retried; each seat loop survives errors |
| **Run 1 deadlocked:** one environment's API credential was mis-entered, so the examiner got 401 when posting its LEDGER. Its BLOCKER used the same broken channel, and the lead waited forever. The run was abandoned without any steering | run 1 room and examiner session | `band_say.py --whoami`: every session prints its BAND identity at bootstrap, and all five are checked before the dispatch |
| **Reusing run 1's repository name** gave fresh sessions a cached clone of run 1 | run 2 bootstrap | every run gets a never-used repository name |

## Measured cost and time

| Run | Stages | Wall-clock | Cloud credit (Claude cloud sessions) | Review rounds | Rejections |
|---|---|---|---|---|---|
| Spike (2 seats, one-file task) | – | 51 s | ~$2 incl. 4 probe sessions | 1 | 0 |
| Practice (5 seats) | 1 (partial; checks blocked before the fixes above) | ~30 min | ~$6 | – | – |
| Run 1 (abandoned: credential deadlock) | 1 delivered, not reviewed | ~1 h | ~$5 | – | – |
| **Judged run (run 2)** | **1–4, all accepted** | **2 h 49 min** | **~$45** | **4** | **0 product rejections; 1 check fixed after review** |

Per stage (dispatch → ACCEPT): stage 1 21 min, stage 2 +32 min, stage 3 +23 min, stage 4 +1 h
32 min. Stage 4 is dominated by the examiner's 700-check suite, including a real ~3-minute cutoff
wait.

## Verification we did ourselves (not part of the band's run)

After the run, the repository was cloned fresh and checked in the judges' configuration, with the
event harness in isolated mode (internal network, 2 vCPU, 2 GiB):
`python -m harness run --track tablekeeper --repo <clone> --all --mode isolated`.

| Folder | stage 1 suite | stage 2 suite | stage 3 suite | stage 4 suite | claims |
|---|---|---|---|---|---|
| `stage-1/` | 120/120 | 0/25 | | | **1** |
| `stage-2/` | 120/120 | 25/25 | 0/7 | | **2** |
| `stage-3/` | 120/120 | 25/25 | 7/7 | 4/6 (not the whole suite: no overshoot) | **3** |
| `stage-4/` | 120/120 | 25/25 | 7/7 | 6/6 | **4** |

`python -m harness check` on the fresh clone: **ok** (gates 1 and 2, mandate vocabulary for both tracks, and the credential scan, room.json included). We also searched room.json by hand for every credential format we used (BAND agent and user keys, GitHub and Anthropic tokens): none found. Nothing in `stage-N/`, `checks/` or
`evidence/` was written or changed by a human. The only human commits are the factory setup before
the dispatch and README.md, FACTORY.md and `room.json` after the final report.

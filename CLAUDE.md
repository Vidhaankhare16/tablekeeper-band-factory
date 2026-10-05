# Seat runtime

This repository is worked on by a band of coding-agent seats in a BAND room. Each seat runs as
its own Claude Code cloud session. If you are one of them, these rules apply for the whole
session, including after your context has been compacted.

- **Who you are.** Your first message named your seat. Your standing instructions are in
  `mandates/<your seat>.md`. Re-read that file whenever you are unsure, and always after
  compaction.
- **Input.** Room messages addressed to you arrive as turns that start with `[BAND message]`.
  They are your only input. Nobody reads your replies in this chat; the room is the only channel.
- **Speaking.** Write the message to a file outside the repository, then run
  `python3 factory/bin/band_say.py --room <room id from the message header> --to <seat names,
  comma-separated> --file <file>`. Long messages are split into numbered parts automatically.
  Address only seats, by name: lead, builder, surface, examiner, gatekeeper.
- **Turns.** When you have handled a message (work done and committed, reply sent), end your
  turn. Do not sleep, poll or wait for answers; the next message arrives as a new turn.
- **Git.** Work on `main`. Before you start work: `git fetch origin && git checkout main &&
  git pull --no-rebase origin main`. Your clone's git identity must be your seat (`git config user.name <seat>`,
  `git config user.email <seat>@band.local`), so that commits *and merges* are yours. Check it
  with `git config user.name` before you commit. Push after every commit:
  `git push origin main`. If the push is rejected, run `git pull --no-rebase origin main` and push
  again. Never force-push, rebase, amend or squash. Your machine can be paused and replaced
  between turns, so anything not pushed can be lost.
- **Nobody answers questions in this chat.** Never ask the operator to approve, allow or decide
  anything, and never stop to wait for one. If a tool action is denied, use another way that the
  rules allow. If there is none, send @lead a `BLOCKER` with the exact error and continue with
  whatever else you can do.
- **Checks.** Run the event's supplied checks with exactly
  `bash factory/bin/check-stage --track <track> --stage <N> [--rev <revision>]`. Run it as its own
  command, not chained with `&&` or `;`, because it is pre-approved only in that form. It sets
  up the kit and a browser on first use, tests a clean clone at that revision, and does an offline
  start check of the stage's container.
- **Docker** is started automatically when the session starts. If `docker info` fails, run
  `bash factory/bin/session-start.sh` once, then check again.
- **Never** put credentials in files, commits or messages.

#!/usr/bin/env python3
"""Post a message to a BAND room as this seat, addressing other seats by @handle.

    python3 band_say.py --room <room-id> --to builder,gatekeeper --file message.md
    echo "text" | python3 band_say.py --room <room-id> --to lead

Runs inside a seat's cloud session. Standard library only. Authentication: in a cloud
session the agent proxy attaches the seat's BAND key to requests for the BAND host, so no
key is needed here. For local testing, set BAND_API_KEY.

Long messages are split into numbered parts ("PART 1/3" ... "FINAL PART 3/3"), each
addressed to the same seats, so that handoffs can carry complete requirements.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

REST = os.environ.get("BAND_REST_URL", "https://app.band.ai").rstrip("/")
OWNER = os.environ.get("BAND_OWNER", "vidhankhare16")
MAX_CHARS = int(os.environ.get("BAND_MAX_CHARS", "20000"))


def request(method, path, body=None):
    headers = {"content-type": "application/json", "accept": "application/json", "user-agent": "df-seat/1.0"}
    if os.environ.get("BAND_API_KEY"):
        headers["X-API-Key"] = os.environ["BAND_API_KEY"]
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(6):
        req = urllib.request.Request(f"{REST}/{path.lstrip('/')}", data=data, method=method,
                                     headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            if e.code in (429, 500, 502, 503, 504) and attempt < 5:
                time.sleep(2 ** attempt)
                continue
            sys.exit(f"band_say: HTTP {e.code} on {method} {path}: {detail}")
        except urllib.error.URLError as e:
            if attempt < 5:
                time.sleep(2 ** attempt)
                continue
            sys.exit(f"band_say: cannot reach {REST}: {e}")


def split(text):
    if len(text) <= MAX_CHARS:
        return [text]
    parts, current = [], ""
    for para in text.split("\n\n"):
        while len(para) > MAX_CHARS:  # a single huge paragraph: hard-wrap it
            if current:
                parts.append(current)
                current = ""
            parts.append(para[:MAX_CHARS])
            para = para[MAX_CHARS:]
        if len(current) + len(para) + 2 > MAX_CHARS:
            parts.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        parts.append(current)
    n = len(parts)
    return [f"{'FINAL PART' if i == n else 'PART'} {i}/{n}\n\n{p}" for i, p in enumerate(parts, 1)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--whoami", action="store_true", help="check this seat's BAND identity and exit")
    ap.add_argument("--room", help="BAND chat room id")
    ap.add_argument("--to", help="comma-separated seat names, e.g. builder,lead")
    ap.add_argument("--file", help="read the message from this file (default: stdin)")
    args = ap.parse_args()
    if args.whoami:
        me = (request("GET", "api/v1/agent/me").get("data") or {})
        print(f"BAND identity: {me.get('handle')} ({me.get('name')})")
        return
    if not args.room or not args.to:
        ap.error("--room and --to are required")

    text = open(args.file, encoding="utf-8").read() if args.file else sys.stdin.read()
    text = text.strip()
    if not text:
        sys.exit("band_say: empty message")
    seats = [s.strip().lstrip("@").split("/")[-1] for s in args.to.split(",") if s.strip()]
    mentions = [{"handle": f"{OWNER}/{s}"} for s in seats]
    prefix = " ".join(f"@{OWNER}/{s}" for s in seats)

    for part in split(text):
        out = request("POST", f"api/v1/agent/chats/{args.room}/messages",
                      {"message": {"content": f"{prefix} {part}", "mentions": mentions}})
        msg_id = (out.get("data") or {}).get("id", "?")
        print(f"sent {msg_id} to {','.join(seats)} ({len(part)} chars)")


if __name__ == "__main__":
    main()

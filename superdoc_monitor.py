#!/usr/bin/env python3
"""
Watches both locations of a superdoc.bg doctor and alerts you when a free
appointment hour appears on or before the cutoff date (default: end of October).

Data source: Superdoc's own calendar endpoint, one per location:
  https://superdoc.bg/calendar/<ID>/today/7
Each response includes "earliestSlot" (the earliest free hour at that location)
and the next 7 days with a "bookable" flag per hour.

Alerts (all optional, combine freely):
  FAIL_ON_ALERT=1   exit with an error when a slot is found. On GitHub Actions
                    this makes GitHub email you automatically. No password.
  NTFY_TOPIC=...    push notification to the free ntfy app (no account).
  EMAIL_USER / EMAIL_PASS / EMAIL_TO   classic Gmail SMTP email.

Other:
  ALERT_BEFORE=2026-10-31   last date you care about (default 2026-10-31)

A slot only triggers an alert once; if it disappears and comes back, you are
alerted again. State is kept in state.json.
"""

import json
import os
import smtplib
import sys
from datetime import datetime, date
from email.message import EmailMessage
from pathlib import Path

import requests

BASE = "https://superdoc.bg/calendar/{id}/today/7"
PAGE_URL = "https://superdoc.bg/lekar/dimitar-georgiev"
LOCATIONS = {
    "12446": "Private practice (ул. Захари Княжевски 2)",
    "2453": "МЦ 1 Пловдив (бул. Васил Априлов 20)",
}
STATE_FILE = Path(__file__).with_name("state.json")


def cutoff() -> date:
    return date.fromisoformat(os.environ.get("ALERT_BEFORE") or "2026-10-31")


def fetch_calendar(cal_id: str) -> dict:
    resp = requests.get(
        BASE.format(id=cal_id),
        headers={
            "User-Agent": "Mozilla/5.0 (personal appointment watcher)",
            "Accept": "application/json",
            "Referer": PAGE_URL,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def find_slots(data: dict, limit: date) -> set:
    """Return {'YYYY-MM-DD HH:MM', ...} of free hours on or before `limit`."""
    cal = data.get("calendar", {})
    found = set()

    # 1) the earliest free hour at this location, whenever it is
    earliest = cal.get("earliestSlot")
    if earliest and earliest.get("date") and earliest.get("time"):
        if date.fromisoformat(earliest["date"]) <= limit:
            found.add(f"{earliest['date']} {earliest['time']}")

    # 2) any bookable hour in the 7-day window (double check)
    for day in cal.get("output", []):
        if date.fromisoformat(day["date"]) > limit:
            continue
        for s in day.get("slots_list", []):
            if s.get("bookable"):
                found.add(f"{day['date']} {s['time']}")
    return found


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text()).get("alerted", {})
        except Exception:
            return {}
    return {}


def save_state(alerted: dict):
    STATE_FILE.write_text(json.dumps({"alerted": alerted}, indent=1, sort_keys=True))


def notify(lines: list):
    subject = "Free appointment hour available"
    body = "\n".join(lines) + f"\n\nBook here: {PAGE_URL}\n"

    topic = os.environ.get("NTFY_TOPIC")
    if topic:
        requests.post(
            f"https://ntfy.sh/{topic}",
            data=body.encode("utf-8"),
            headers={"Title": subject, "Click": PAGE_URL},
            timeout=30,
        )
        print("ntfy notification sent.")

    user, pw, to = (os.environ.get(k) for k in ("EMAIL_USER", "EMAIL_PASS", "EMAIL_TO"))
    if user and pw and to:
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = subject, user, to
        msg.set_content(body)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(user, pw)
            server.send_message(msg)
        print("Email sent.")


def main():
    limit = cutoff()
    old_state = load_state()
    new_state = dict(old_state)  # keep old data for a location that fails to load
    alert_lines = []

    for cal_id, name in LOCATIONS.items():
        try:
            data = fetch_calendar(cal_id)
            slots = find_slots(data, limit)
        except Exception as exc:
            print(f"{datetime.now():%Y-%m-%d %H:%M} {name}: fetch failed: {exc}", file=sys.stderr)
            continue

        earliest = (data.get("calendar", {}).get("earliestSlot") or {}).get("text", "none")
        print(f"{datetime.now():%Y-%m-%d %H:%M} {name}: earliest={earliest}, slots<=cutoff={sorted(slots)}")

        fresh = slots - set(old_state.get(cal_id, []))
        for s in sorted(fresh):
            alert_lines.append(f"{name}: free hour on {s}")
        new_state[cal_id] = sorted(slots)

    save_state(new_state)

    if alert_lines:
        notify(alert_lines)
        for line in alert_lines:
            print("ALERT:", line)
        if os.environ.get("FAIL_ON_ALERT") == "1":
            sys.exit(1)  # makes GitHub send its built-in failure email


if __name__ == "__main__":
    main()

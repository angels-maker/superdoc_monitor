#!/usr/bin/env python3
"""
Watches a superdoc.bg doctor page and alerts you when an earlier
appointment slot appears.

It reads the line "Най-ранен час: 6 януари 13:00" (earliest slot) from the
page, compares it with the last value seen (state.json), and alerts if the
slot got earlier or appeared where there were none.

Alert options (all optional, combine freely):
  FAIL_ON_ALERT=1   exit with an error when a slot is found. On GitHub Actions
                    this makes GitHub email you automatically. No password.
  NTFY_TOPIC=...    push notification to the free ntfy app (no account).
  EMAIL_USER / EMAIL_PASS / EMAIL_TO   classic Gmail SMTP email.

Other:
  ALERT_BEFORE=2026-12-31   only alert for slots before this date
"""

import json
import os
import re
import smtplib
import sys
from datetime import datetime, date
from email.message import EmailMessage
from pathlib import Path

import requests

URL = "https://superdoc.bg/lekar/dimitar-georgiev"
STATE_FILE = Path(__file__).with_name("state.json")

MONTHS = {
    "януари": 1, "февруари": 2, "март": 3, "април": 4, "май": 5, "юни": 6,
    "юли": 7, "август": 8, "септември": 9, "октомври": 10, "ноември": 11,
    "декември": 12,
}

SLOT_RE = re.compile(
    r"Най-ранен час:\s*(\d{1,2})\s+([а-я]+)\s+(\d{1,2}):(\d{2})", re.IGNORECASE
)


def fetch_page() -> str:
    resp = requests.get(
        URL,
        headers={"User-Agent": "Mozilla/5.0 (personal appointment watcher)"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.text


def parse_earliest(html: str):
    """Return the earliest slot as a datetime, or None if no slot is shown."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    m = SLOT_RE.search(text)
    if not m:
        return None
    day, month_name, hour, minute = m.groups()
    month = MONTHS.get(month_name.lower())
    if not month:
        return None
    today = date.today()
    slot = datetime(today.year, month, int(day), int(hour), int(minute))
    # The page omits the year: if the date already passed, it means next year.
    if slot.date() < today:
        slot = slot.replace(year=today.year + 1)
    return slot


def load_state():
    if STATE_FILE.exists():
        raw = json.loads(STATE_FILE.read_text()).get("earliest")
        return datetime.fromisoformat(raw) if raw else None
    return None


def save_state(slot):
    STATE_FILE.write_text(json.dumps({"earliest": slot.isoformat() if slot else None}))


def notify(current: datetime):
    subject = "Earlier appointment available"
    body = f"Earliest slot is now {current:%d %B %Y, %H:%M}.\nBook here: {URL}\n"

    topic = os.environ.get("NTFY_TOPIC")
    if topic:
        requests.post(
            f"https://ntfy.sh/{topic}",
            data=body.encode("utf-8"),
            headers={"Title": subject, "Click": URL},
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
    try:
        current = parse_earliest(fetch_page())
    except Exception as exc:  # network error, site down, etc.
        print(f"{datetime.now():%Y-%m-%d %H:%M} fetch failed: {exc}", file=sys.stderr)
        return

    previous = load_state()
    print(f"{datetime.now():%Y-%m-%d %H:%M} earliest now={current} previous={previous}")

    if current is None:
        save_state(None)
        return

    should_alert = previous is None or current < previous

    limit = os.environ.get("ALERT_BEFORE")
    if limit and current.date() > date.fromisoformat(limit):
        should_alert = False

    save_state(current)

    if should_alert:
        notify(current)
        print(f"ALERT: earliest slot is {current:%d %B %Y, %H:%M}")
        if os.environ.get("FAIL_ON_ALERT") == "1":
            sys.exit(1)  # makes GitHub send its built-in failure email


if __name__ == "__main__":
    main()

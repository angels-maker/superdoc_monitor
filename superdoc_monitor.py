#!/usr/bin/env python3
"""
Watches a superdoc.bg doctor page and emails you when an earlier
appointment slot appears.

How it works: the page shows a line like "Най-ранен час: 6 януари 13:00"
(earliest slot). We read that, compare it with the last value we saw
(saved in state.json), and send an email if it got earlier or if a slot
appeared where there were none.

Setup:
  pip install requests
  export EMAIL_USER="you@gmail.com"
  export EMAIL_PASS="your-gmail-app-password"   # NOT your normal password
  export EMAIL_TO="you@gmail.com"
  # optional: only alert for slots before this date
  export ALERT_BEFORE="2026-12-31"

Run once:   python superdoc_monitor.py
Schedule:   cron, e.g. every 10 minutes:
  */10 * * * * cd /path/to/folder && /usr/bin/python3 superdoc_monitor.py >> monitor.log 2>&1
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
    year = today.year
    slot = datetime(year, month, int(day), int(hour), int(minute))
    # The page omits the year: if the date already passed, it means next year.
    if slot.date() < today:
        slot = slot.replace(year=year + 1)
    return slot


def load_state():
    if STATE_FILE.exists():
        data = json.loads(STATE_FILE.read_text())
        raw = data.get("earliest")
        return datetime.fromisoformat(raw) if raw else None
    return None


def save_state(slot):
    STATE_FILE.write_text(json.dumps({"earliest": slot.isoformat() if slot else None}))


def send_email(subject: str, body: str):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ["EMAIL_USER"]
    msg["To"] = os.environ["EMAIL_TO"]
    msg.set_content(body)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(os.environ["EMAIL_USER"], os.environ["EMAIL_PASS"])
        server.send_message(msg)


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

    if should_alert:
        send_email(
            "Earlier appointment available",
            f"Earliest slot is now {current:%d %B %Y, %H:%M}.\n\nBook here: {URL}\n",
        )
        print("Email sent.")

    save_state(current)


if __name__ == "__main__":
    main()

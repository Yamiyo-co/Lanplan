"""
Live session timer.

Run a stopwatch while you work: when the timer stops, the REAL duration is logged (session_logs), optionally with a quality score.
This is what makes the tracking reflect reality instead of plans, and lets the adaptive rotation know how long you really worked.
"""

from __future__ import annotations

import time
from datetime import date, datetime


def _duration_of(event):
    sh, sm = map(int, event["start_time"].split(":"))
    eh, em = map(int, event["end_time"].split(":"))
    return eh * 60 + em - sh * 60 - sm


def format_minutes(seconds):
    minutes = int(seconds // 60)
    return f"{minutes // 60:02d}:{minutes % 60:02d}" if minutes >= 60 \
        else f"{minutes} min"


def run_timer(db, event_date=None, allow_planned_only=True):
    """Interactive CLI timer for the sessions of a given day.

    Returns the log dict when a session was timed, None otherwise.
    """
    if event_date is None:
        event_date = date.today().isoformat()

    done = db.logged_uids(event_date)

    events = [e for e in db.planned_events(event_date)
              if e["uid"] not in done]

    if allow_planned_only and not events:
        # Free session: nothing planned or already logged.
        languages = {row["id"]: dict(row)
                      for row in db.languages(active_only=True)}
        print(f"No planned session left for {event_date}.")
        print("Free session: pick a language to time anyway.")

        items = list(languages.values())
        if not items:
            print("No active language.")
            return None

        for index, lang in enumerate(items, 1):
            print(f"  {index}. {lang['name']}")

        answer = input("Language number (empty = cancel): ").strip()
        if not answer:
            return None
        language = items[int(answer) - 1]

        return _time_session(
            db,
            uid=f"free:{event_date}:{language['id']}:"
               f"{datetime.now().strftime('%H%M')}",
            event_date=event_date,
            language_id=language["id"],
            task_id=None,
            kind="free",
            summary=f"{language['name']} - Free session",
        )

    print()
    print(f"SESSIONS - {event_date}")
    print("-" * 50)

    for index, event in enumerate(events, 1):
        print(f"  {index}. {event['start_time']} {event['summary']}"
              f" (planned {_duration_of(event)} min)")

    answer = input("Session number (empty = cancel): ").strip()
    if not answer:
        return None

    event = events[int(answer) - 1]
    return _time_session(
        db,
        uid=event["uid"],
        event_date=event["event_date"],
        language_id=event["language_id"],
        task_id=event["task_id"],
        kind=event["kind"],
        summary=event["summary"],
    )


def _time_session(db, uid, event_date, language_id, task_id,
                  kind, summary):
    print()
    print(f"Timing: {summary}")
    print("Press Ctrl+C (or Enter) to stop the timer.")

    started = time.monotonic()
    try:
        input()
    except (KeyboardInterrupt, EOFError):
        pass
    elapsed = time.monotonic() - started

    minutes = max(1, round(elapsed / 60))
    print(f"Duration: {format_minutes(elapsed)} ({minutes} min)")

    raw = input("Quality [0-5, empty = unrated]: ").strip()
    quality = int(raw) if raw else None
    note = input("Note (empty = none): ").strip()

    db.log_session(
        uid=uid,
        event_date=event_date,
        language_id=language_id,
        task_id=task_id,
        kind=kind,
        minutes=minutes,
        quality=quality,
        skipped=0,
        note=note,
    )
    print("Session logged.")

    return {
        "uid": uid,
        "minutes": minutes,
        "quality": quality,
    }
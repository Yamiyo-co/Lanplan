"""
Command-line entry point.

Usage:
    python -m Planner.cli <command> [options]

Commands:
    init        create/upgrade the database (idempotent)
    editor      interactive editor
    languages   list languages
    tasks       list tasks
    plan        generate the schedule locally
    sync        generate + push to CalDAV (--dry-run first!)
    log         mark a session done/skipped + quality
    timer       run a live-timed session (records real minutes)
    load        cognitive-load report (guards alerts)
    stats       weekly report (--weeks N) / HTML dashboard
    anki        Anki routine sub-commands (run/quotas/set/add/remove)
    web         launch the web GUI (version 2)
    check       integrity check + overview
    backup      copy the database to backups/
"""

from __future__ import annotations

import argparse
import shutil
from collections import defaultdict
from datetime import date, timedelta

from . import anki, config, stats, timer
from .database import Database
from .caldav_sync import from_environment
from .editor import Editor
from .scheduler import Scheduler


def get_db():
    return Database()


def _events_to_rows(events):
    return [(e.uid, e.event_date, e.start_time, e.end_time,
             e.language_id, e.task_id, e.kind, e.summary)
            for e in events]


def _generate(db, months=None):
    settings = db.settings()
    if months is None:
        months = int(settings.get("planning_horizon_months", "3"))

    scheduler = Scheduler(db)
    events = scheduler.generate(start_date=date.today(), months=months)

    db.replace_planned_events(_events_to_rows(events))
    return events


# -- Commands -----------------------------------------------------------

def command_init():
    db = get_db()
    db.initialize()
    db.close()
    print(f"Database ready: {config.DB_PATH}")


def command_editor():
    db = get_db()
    Editor(db).run()
    db.close()


def command_languages():
    db = get_db()
    for row in db.languages():
        print(f"{row['id']:>2} {row['name']:<15} "
              f"{row['level']} -> {row['objective']:<5} "
              f"{row['status']:<12} {row['target_minutes_week']} min")
    db.close()


def command_tasks():
    db = get_db()
    for row in db.tasks():
        print(f"{row['id']:>2} {row['name']:<25} "
              f"{row['duration_min']} min "
              f"min={row['min_per_week']} max={row['max_per_week']}")
    db.close()


def command_plan(months=None):
    db = get_db()
    events = _generate(db, months)

    print(f"\n{len(events)} events generated.\n")
    for event in events[:50]:
        print(event.event_date, event.start_time, "-",
              event.end_time, event.summary)
    if len(events) > 50:
        print(f"... {len(events) - 50} more")
    db.close()


def command_sync(dry_run=False):
    db = get_db()
    events = _generate(db)

    settings = db.settings()
    client = from_environment(
        calendar_name=(config.CALDAV_USERNAME
                       and settings.get("calendar_name")),
        timezone=settings.get("timezone"),
    )
    result = client.sync(events, dry_run=dry_run)

    print()
    print(f"Created  : {result['created']}")
    print(f"Existing: {result['existing']}")
    print(f"Deleted  : {result['deleted']}")
    db.close()


def command_log(event_date=None):
    """Mark a session done or skipped, with optional quality."""
    db = get_db()
    if event_date is None:
        event_date = date.today().isoformat()

    done = db.logged_uids(event_date)
    events = [e for e in db.planned_events(event_date)
              if e["uid"] not in done]

    if not events:
        print(f"Nothing to log for {event_date}.")
        db.close()
        return

    print(f"\nSESSIONS - {event_date}")
    print("-" * 50)
    for index, event in enumerate(events, 1):
        print(f"{index:>2}. {event['start_time']} {event['summary']}")

    answer = input("Session number (empty = quit): ").strip()
    if not answer:
        db.close()
        return

    event = events[int(answer) - 1]

    def duration(event):
        sh, sm = map(int, event["start_time"].split(":"))
        eh, em = map(int, event["end_time"].split(":"))
        return eh * 60 + em - sh * 60 - sm

    skipped = input("Skipped? [y/N]: ").strip().lower() == "y"
    quality = None
    if not skipped:
        raw = input("Quality [0-5, empty = unrated]: ").strip()
        quality = int(raw) if raw else None
    note = input("Note (empty = none): ").strip()

    db.log_session(
        uid=event["uid"], event_date=event["event_date"],
        language_id=event["language_id"],
        task_id=event["task_id"], kind=event["kind"],
        minutes=duration(event), quality=quality,
        skipped=1 if skipped else 0, note=note,
    )
    print("Logged.")
    db.close()


def command_timer(event_date=None):
    db = get_db()
    timer.run_timer(db, event_date)
    db.close()


def command_load(weeks=None):
    """Cognitive-load report: minutes and languages per day,
    with overload alerts against the guards."""
    db = get_db()
    settings = db.settings()

    def setting_int(key, default):
        try:
            return int(settings.get(key, default))
        except (TypeError, ValueError):
            return default

    max_minutes = setting_int("max_minutes_per_day", 110)
    max_languages = setting_int("max_languages_per_day", 2)

    names = {row["id"]: row["name"] for row in db.languages()}
    events = db.planned_events()

    if not events:
        print("Nothing planned yet. Run: plan")
        db.close()
        return

    by_day = defaultdict(list)
    for event in events:
        by_day[event["event_date"]].append(event)

    days = sorted(by_day)
    if weeks:
        cutoff = (date.today()
                  - timedelta(weeks=weeks)).isoformat()
        days = [d for d in days if d >= cutoff]

    alerts = 0
    print("\nCOGNITIVE LOAD")
    print("-" * 70)
    print(f"  limits: {max_languages} languages / "
          f"{max_minutes} min per day\n")

    for day in days:
        day_events = by_day[day]
        minutes = sum(
            (lambda e: (int(e["end_time"][:2]) * 60
                        + int(e["end_time"][3:])
                        - int(e["start_time"][:2]) * 60
                        - int(e["start_time"][3:])))(e)
            for e in day_events)

        langs = {e["language_id"] for e in day_events
                 if e["language_id"] is not None}

        flags = []
        if len(langs) > max_languages:
            flags.append(f"{len(langs)} languages")
        if minutes > max_minutes:
            flags.append(f"{minutes} min")
        if flags:
            alerts += 1

        marker = ("  !! " + ", ".join(flags)) if flags else ""
        label = ", ".join(names.get(lid, f"#{lid}")
                          for lid in sorted(langs))

        print(f"  {day}  {minutes:>3} min  "
              f"{len(langs)} lang(s)  {label:<32}{marker}")

    print(f"\n  {len(days)} days, {alerts} overload alert(s).")
    db.close()


def command_stats(weeks=None, html_path=None):
    db = get_db()
    data = stats.build_stats(db, weeks=weeks)

    if html_path:
        output = stats.render_dashboard(data, html_path)
        print(f"Dashboard written: {output}")
    else:
        stats.print_report(data)
    db.close()


def command_check():
    db = get_db()
    print("SQLite:",
          db.execute("PRAGMA integrity_check").fetchone()[0])
    print("\nLanguages:")
    for row in db.languages():
        print(f"  - {row['name']} ({row['status']})")
    print("\nTasks:")
    for row in db.tasks():
        print(f"  - {row['name']}")
    db.close()


def command_backup():
    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    destination = (config.BACKUP_DIR
                   / f"planner-{date.today().isoformat()}.sqlite")
    db = get_db()
    db.close()
    shutil.copy2(config.DB_PATH, destination)
    print(f"Backup: {destination}")


def command_web(host="127.0.0.1", port=5000, debug=False):
    from . import webapp
    webapp.app.run(host=host, port=port, debug=debug)


# -- Argument parsing ------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Language Planner (pedagogical scheduler)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init")
    sub.add_parser("editor")
    sub.add_parser("languages")
    sub.add_parser("tasks")
    sub.add_parser("check")
    sub.add_parser("backup")

    plan = sub.add_parser("plan")
    plan.add_argument("--months", type=int, default=None)

    sync = sub.add_parser("sync")
    sync.add_argument("--dry-run", action="store_true")

    log = sub.add_parser("log")
    log.add_argument("--date", default=None)

    timer_p = sub.add_parser("timer")
    timer_p.add_argument("--date", default=None)

    load = sub.add_parser("load")
    load.add_argument("--weeks", type=int, default=None)

    stats_p = sub.add_parser("stats")
    stats_p.add_argument("--weeks", type=int, default=None)
    stats_p.add_argument("--html", default=None,
                         help="write an HTML dashboard to this path")

    anki_p = sub.add_parser("anki")
    anki_p.add_argument("anki_args", nargs=argparse.REMAINDER)

    web = sub.add_parser("web")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=5000)
    web.add_argument("--debug", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "init":
        command_init()
    elif args.command == "editor":
        command_editor()
    elif args.command == "languages":
        command_languages()
    elif args.command == "tasks":
        command_tasks()
    elif args.command == "check":
        command_check()
    elif args.command == "backup":
        command_backup()
    elif args.command == "plan":
        command_plan(args.months)
    elif args.command == "sync":
        command_sync(args.dry_run)
    elif args.command == "log":
        command_log(args.date)
    elif args.command == "timer":
        command_timer(args.date)
    elif args.command == "load":
        command_load(args.weeks)
    elif args.command == "stats":
        command_stats(args.weeks, args.html)
    elif args.command == "anki":
        anki.main(args.anki_args)
    elif args.command == "web":
        command_web(args.host, args.port, args.debug)


if __name__ == "__main__":
    main()
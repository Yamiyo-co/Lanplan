"""
Anki new-card routine (integrated, planner-aligned).

One all-day calendar event per day tells you how many NEW cards to add per language:

- PRIMARY: the language of the planner's main session that day (fallback: date-based rotation of active languages, 2 days each).
- SECONDARY: the next active language in rotation, half quota, only when the primary quota stays light.
- MAINTENANCE: one maintenance language per day (quarter quota), only on configured maintenance days.

Reviews are ALWAYS every day, all languages (Anki's spacing algorithm decides, we never filter).

Event summary example:
    Anki: reviews (all) - new: Japanese +8, Farsi +4, Korean +1
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import sqlite3
import unicodedata

import requests

from . import config

# Guard rails of the hybrid model.
MAX_NEW_CARDS_PER_DAY = 40          # global cap, all languages
MAINTENANCE_DAYS = {1, 4}            # 0=Mon: Tue + Fri only
SECONDARY_IF_PRIMARY_UNDER = 20      # cognitive-load gating


# -- Anki routine DB (table anki_langues inside planner.sqlite) --------

def _connect():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _normalize(text):
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.strip().lower()


def list_languages():
    conn = _connect()
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM anki_langues ORDER BY status, name").fetchall()]
    conn.close()
    return rows


def show_quotas():
    print()
    print("ANKI QUOTAS")
    print("-" * 44)
    for row in list_languages():
        print(f"  {row['name']:<12} {row['status']:<12}"
              f" {row['lv_daily']} cards/day")


def set_quota(name, quota):
    conn = _connect()
    cur = conn.execute(
        "UPDATE anki_langues SET lv_daily = ? "
        "WHERE name = ? OR code = ?",
        (quota, name, name),
    )
    if cur.rowcount == 0:
        print(f"Unknown language: {name}")
    else:
        conn.commit()
        print(f"Quota of {name} -> {quota} new cards/day")
    conn.close()


def add_language(name, code, status, quota):
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO anki_langues (name, code, status, lv_daily)"
            " VALUES (?, ?, ?, ?)",
            (name, code, status, quota),
        )
        conn.commit()
        print(f"Added: {name} ({status}, {quota} cards/day)")
    except sqlite3.IntegrityError:
        print(f"Error: {name} or {code} already exists")
    finally:
        conn.close()


def remove_language(name):
    conn = _connect()
    cur = conn.execute(
        "DELETE FROM anki_langues WHERE name = ? OR code = ?",
        (name, name),
    )
    if cur.rowcount == 0:
        print(f"Unknown language: {name}")
    else:
        conn.commit()
        print(f"Removed: {name}")
    conn.close()


# -- Planner alignment (read-only) --------------------------------------

def main_language_of_day(langues, day):
    """The planner's main-session language for this day, matched by
    name (accent-insensitive), then code, then id. None if absent."""
    if not langues:
        return None

    try:
        conn = sqlite3.connect(
            f"file:{config.DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        return None

    name_planner = None
    id_planner = None
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT l.name AS name, pe.language_id AS lid
            FROM planned_events pe
            LEFT JOIN languages l ON l.id = pe.language_id
            WHERE pe.event_date = ? AND pe.kind = 'main'
            ORDER BY pe.start_time LIMIT 1
            """,
            (day.isoformat(),),
        )
        row = cur.fetchone()
        if row is not None:
            name_planner = row["name"] if "name" in row.keys() else None
            id_planner = row["lid"]
    except sqlite3.Error:
        pass
    finally:
        conn.close()

    if id_planner is None:
        return None

    if name_planner:
        target = _normalize(name_planner)
        for langue in langues:
            if _normalize(langue["name"]) == target:
                return langue
        for langue in langues:
            if _normalize(langue["code"]) == target:
                return langue

    for langue in langues:
        if langue["id"] == id_planner:
            return langue
    return None


# -- Rotation ------------------------------------------------------------

def rotations(langues, day):
    """Returns (primary, secondary, maintenance) for the day."""
    actives = [l for l in langues if l["status"] == "active"]
    maintenance = [l for l in langues
                   if l["status"] == "maintenance"]
    if not actives and not maintenance:
        return None, None, None

    ordinal = day.toordinal()

    primary = main_language_of_day(langues, day)
    if primary is None and actives:
        # Date-based fallback: each active keeps the lead 2 days.
        primary = actives[(ordinal // 2) % len(actives)]

    secondary = None
    if actives and len(actives) > 1:
        for offset in range(1, len(actives)):
            candidate = actives[
                (ordinal // 2 + offset) % len(actives)]
            if primary is None \
                    or candidate["id"] != primary["id"]:
                secondary = candidate
                break

    entretien = None
    if maintenance and day.weekday() in MAINTENANCE_DAYS:
        entretien = maintenance[ordinal % len(maintenance)]
        if primary is not None \
                and entretien["id"] == primary["id"]:
            entretien = maintenance[
                (ordinal + 1) % len(maintenance)]

    return primary, secondary, entretien


def quotas(primary, secondary, maintenance):
    parts = []

    if primary:
        parts.append((primary, primary["lv_daily"]))

    if (secondary and primary
            and primary["lv_daily"]
            <= SECONDARY_IF_PRIMARY_UNDER):
        parts.append((secondary,
                      max(2, secondary["lv_daily"] // 2)))

    if maintenance:
        parts.append((maintenance,
                      max(1, maintenance["lv_daily"] // 4)))

    # Global cap: scale down proportionally if exceeded.
    total = sum(n for _, n in parts)
    if total > MAX_NEW_CARDS_PER_DAY and total > 0:
        factor = MAX_NEW_CARDS_PER_DAY / total
        parts = [(l, max(1, int(n * factor))) for l, n in parts]

    return parts


def summary(parts):
    details = ", ".join(f"{l['name']} +{n}" for l, n in parts)
    return f"Anki: reviews (all) - new: {details}"


# -- CalDAV (direct PUT, dedicated calendar) ------------------------------

def uid_for(day):
    raw = f"anki-routine:{day.isoformat()}"
    return f"ankiroutine-{hashlib.sha1(raw.encode()).hexdigest()}"

def build_ics(day, summary, uid):
    dtstart = day.strftime("%Y%m%d")
    dtend = (day + datetime.timedelta(days=1)).strftime("%Y%m%d")
    stamp = datetime.datetime.now(
        datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return (
        "BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\n"
        f"UID:{uid}\nDTSTAMP:{stamp}\n"
        f"DTSTART;VALUE=DATE:{dtstart}\n"
        f"DTEND;VALUE=DATE:{dtend}\n"
        f"SUMMARY:{summary}\n"
        "END:VEVENT\nEND:VCALENDAR\n"
    )


def send_event(ics, uid):
    url = config.ANKI_CALDAV_URL.rstrip("/") + f"/{uid}.ics"
    try:
        r = requests.put(
            url, data=ics.encode("utf-8"),
            auth=(config.CALDAV_USERNAME, config.CALDAV_PASSWORD),
            headers={"Content-Type": "text/calendar"},
            timeout=15,
        )
        if r.status_code not in (200, 201, 204):
            print(f"Error {r.status_code}: {r.text[:200]}")
    except requests.RequestException as e:
        print(f"Network error: {e}")


# -- Commands -------------------------------------------------------------

def command_run(horizon=None, dry_run=False):
    if not config.ANKI_CALDAV_URL:
        raise RuntimeError("ANKI_CALDAV_URL missing in .env")

    langues = list_languages()
    today = datetime.date.today()
    end = today + datetime.timedelta(days=30 * (horizon
                                                or config.ANKI_HORIZON_MONTHS))

    day = today
    while day <= end:
        parts = quotas(*rotations(langues, day))
        if parts:
            text = summary(parts)
            if dry_run:
                print(f"[dry-run] {day} : {text}")
            else:
                send_event(build_ics(day, text, uid_for(day)),
                           uid_for(day))
                print(f"{day} : {text}")
        day += datetime.timedelta(days=1)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Anki new-card routine")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="generate calendar events")
    run.add_argument("--horizon", type=int, default=None)
    run.add_argument("--dry-run", action="store_true")

    sub.add_parser("quotas", help="show quotas per language")

    set_p = sub.add_parser("set", help="change a language quota")
    set_p.add_argument("langue")
    set_p.add_argument("quota", type=int)

    add = sub.add_parser("add", help="add a language")
    add.add_argument("name")
    add.add_argument("code")
    add.add_argument("status",
                     choices=["active", "maintenance", "waiting"])
    add.add_argument("quota", type=int)

    remove = sub.add_parser("remove", help="remove a language")
    remove.add_argument("langue")

    args = parser.parse_args(argv)

    if args.command == "run":
        command_run(args.horizon, args.dry_run)
    elif args.command == "set":
        set_quota(args.langue, args.quota)
    elif args.command == "add":
        add_language(args.name, args.code, args.status, args.quota)
    elif args.command == "remove":
        remove_language(args.langue)
    else:
        show_quotas()


if __name__ == "__main__":
    main()
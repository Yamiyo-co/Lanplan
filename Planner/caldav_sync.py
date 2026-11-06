"""
Idempotent CalDAV synchronization.

- Deterministic UIDs: an existing event is updated, never duplicated.
- Purge: events that belong to us but left the plan are deleted.
- Only our own events are ever touched (prefix or legacy sha1 UID).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import caldav

from . import config


class CalDAVSync:
    def __init__(self, url, username, password, calendar_name,
                 timezone=None):
        self.url = url
        self.username = username
        self.password = password
        self.calendar_name = calendar_name
        self.timezone = ZoneInfo(timezone or config.TIMEZONE)

    def connect(self):
        client = caldav.DAVClient(
            url=self.url,
            username=self.username,
            password=self.password,
        )
        principal = client.principal()
        calendars = principal.calendars()

        # Exact match first, then fuzzy (case/substring).
        for calendar in calendars:
            try:
                if calendar.name == self.calendar_name:
                    return calendar
            except Exception:
                continue

        wanted = self.calendar_name.strip().lower()
        for calendar in calendars:
            try:
                name = calendar.name
            except Exception:
                continue
            if name and wanted in name.strip().lower():
                return calendar

        available = []
        for calendar in calendars:
            try:
                available.append(str(calendar.name))
            except Exception:
                continue

        raise RuntimeError(
            f"Calendar not found: {self.calendar_name}\n"
            f"Available calendars: "
            f"{', '.join(available) or '(none)'}"
        )

    def find_event(self, calendar, uid):
        """Locate an event by UID (search API, then manual scan)."""
        try:
            events = calendar.search(event=True, uid=uid)
            if events:
                return events[0]
        except Exception:
            pass

        try:
            for event in calendar.search(event=True):
                try:
                    if str(event.component.get("UID")) == uid:
                        return event
                except Exception:
                    continue
        except Exception:
            pass
        return None

    def create_event(self, calendar, event):
        dtstart = datetime.fromisoformat(
            f"{event.event_date}T{event.start_time}"
        ).replace(tzinfo=self.timezone)
        dtend = datetime.fromisoformat(
            f"{event.event_date}T{event.end_time}"
        ).replace(tzinfo=self.timezone)

        calendar.add_event(
            uid=event.uid,
            dtstart=dtstart,
            dtend=dtend,
            summary=event.summary,
        )

    @staticmethod
    def _is_ours(uid):
        """Our events: langplan- prefix, or legacy bare sha1."""
        if not uid:
            return False
        if uid.startswith("langplan-"):
            return True
        if (len(uid) == 40
                and all(c in "0123456789abcdef" for c in uid)):
            return True
        return False

    def sync(self, events, dry_run=False):
        calendar = self.connect()

        created = 0
        existing = 0
        deleted = 0
        planned_uids = {event.uid for event in events}

        for event in events:
            remote = self.find_event(calendar, event.uid)

            if remote:
                existing += 1
                if not dry_run:
                    try:
                        with remote.edit_icalendar_instance() as cal:
                            for component in cal.subcomponents:
                                if component.name == "VEVENT":
                                    component["SUMMARY"] = (
                                        event.summary)
                        remote.save()
                    except Exception:
                        pass
                continue

            if dry_run:
                print(f"[dry-run] + {event.event_date} "
                      f"{event.start_time} {event.summary}")
            else:
                self.create_event(calendar, event)
            created += 1

        # Purge our own events that left the plan.
        try:
            remote_events = calendar.search(event=True)
        except Exception:
            remote_events = []

        for remote in remote_events:
            try:
                uid = str(remote.component.get("UID"))
            except Exception:
                continue

            if not self._is_ours(uid) or uid in planned_uids:
                continue

            try:
                summary = str(remote.component.get("SUMMARY"))
            except Exception:
                summary = "?"

            if dry_run:
                print(f"[dry-run] - obsolete {summary}")
            else:
                try:
                    remote.delete()
                    print(f"- deleted: {summary}")
                except Exception:
                    pass
            deleted += 1

        return {
            "created": created,
            "existing": existing,
            "deleted": deleted,
        }


def from_environment(calendar_name=None, timezone=None):
    """Build a sync client from environment variables, with
    fallbacks on the settings table values passed by the caller."""
    name = config.CALDAV_URL and calendar_name
    if not name:
        raise RuntimeError(
            "Calendar name missing: set NEXTCLOUD_CALENDAR in .env "
            "or calendar_name in settings"
        )

    if not (config.CALDAV_URL and config.CALDAV_USERNAME
            and config.CALDAV_PASSWORD):
        raise RuntimeError(
            "Missing CalDAV credentials: NEXTCLOUD_CALDAV_URL, "
            "NEXTCLOUD_USERNAME, NEXTCLOUD_APP_PASSWORD"
        )

    return CalDAVSync(
        url=config.CALDAV_URL,
        username=config.CALDAV_USERNAME,
        password=config.CALDAV_PASSWORD,
        calendar_name=name,
        timezone=timezone or config.TIMEZONE,
    )
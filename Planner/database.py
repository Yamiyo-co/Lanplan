"""SQLite data layer: schema bootstrap + typed accessors."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from . import config


class Database:
    def __init__(self, path: str | Path = None):
        self.path = Path(path or config.DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    def close(self):
        self.conn.close()

    def execute(self, sql, params=()):
        return self.conn.execute(sql, params)

    def executemany(self, sql, rows):
        return self.conn.executemany(sql, rows)

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def executescript(self, script):
        self.conn.executescript(script)

    def initialize(self):
        """Create the schema and seed default data (idempotent)."""
        self.executescript(config.SCHEMA_FILE.read_text(encoding="utf-8"))
        self.executescript(config.SEED_FILE.read_text(encoding="utf-8"))
        self.commit()

    # -- Reference data ------------------------------------------------

    def languages(self, active_only=False):
        sql = "SELECT * FROM languages"
        if active_only:
            sql += " WHERE status IN ('active', 'maintenance')"
        sql += " ORDER BY priority DESC, name"
        return self.execute(sql).fetchall()

    def tasks(self, active_only=True):
        sql = "SELECT * FROM tasks"
        if active_only:
            sql += " WHERE active = 1"
        sql += " ORDER BY priority DESC, name"
        return self.execute(sql).fetchall()

    def weekdays(self):
        return self.execute(
            "SELECT * FROM weekdays ORDER BY weekday"
        ).fetchall()

    def settings(self):
        return {
            row["key"]: row["value"]
            for row in self.execute(
                "SELECT key, value FROM settings"
            ).fetchall()
        }

    def set_setting(self, key, value):
        self.execute(
            """
            INSERT INTO settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, str(value)),
        )
        self.commit()

    # -- Planned events -------------------------------------------------

    def replace_planned_events(self, events):
        self.execute("DELETE FROM planned_events")
        self.executemany(
            """
            INSERT INTO planned_events
            (uid, event_date, start_time, end_time,
             language_id, task_id, kind, summary)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            events,
        )
        self.commit()

    def planned_events(self, event_date=None):
        sql = "SELECT * FROM planned_events"
        params = ()
        if event_date:
            sql += " WHERE event_date = ?"
            params = (event_date,)
        sql += " ORDER BY event_date, start_time"
        return self.execute(sql, params).fetchall()

    # -- Session logs (what really happened) ----------------------------

    def log_session(
        self, uid, event_date, language_id, task_id, kind,
        minutes, quality=None, skipped=0, note="",
    ):
        self.execute(
            """
            INSERT OR REPLACE INTO session_logs
            (uid, event_date, language_id, task_id, kind,
             minutes, quality, skipped, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (uid, event_date, language_id, task_id, kind,
             minutes, quality, skipped, note),
        )
        self.commit()

    def logged_uids(self, event_date=None):
        sql = "SELECT uid FROM session_logs"
        params = ()
        if event_date:
            sql += " WHERE event_date = ?"
            params = (event_date,)
        return {row["uid"] for row in self.execute(sql, params).fetchall()}

    def session_logs(self, before=None, after=None):
        """Logs ordered by date; bounds are ISO dates."""
        sql = "SELECT * FROM session_logs WHERE 1 = 1"
        params = []
        if before:
            sql += " AND event_date < ?"
            params.append(before)
        if after:
            sql += " AND event_date >= ?"
            params.append(after)
        sql += " ORDER BY event_date"
        return self.execute(sql, params).fetchall()
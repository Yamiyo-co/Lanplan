PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS languages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    code TEXT NOT NULL UNIQUE,
    level TEXT NOT NULL,
    objective TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'maintenance', 'waiting', 'paused')),
    priority INTEGER NOT NULL DEFAULT 1,
    weight REAL NOT NULL DEFAULT 1.0,
    target_minutes_week INTEGER NOT NULL DEFAULT 60,
    min_contacts_week INTEGER NOT NULL DEFAULT 2,
    max_contacts_week INTEGER NOT NULL DEFAULT 7,
    preferred_session_minutes INTEGER NOT NULL DEFAULT 45,
    notes TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    duration_min INTEGER NOT NULL,
    min_per_week INTEGER NOT NULL DEFAULT 0,
    max_per_week INTEGER NOT NULL DEFAULT 7,
    priority INTEGER NOT NULL DEFAULT 1,
    requires_main_session INTEGER NOT NULL DEFAULT 0,
    language_id INTEGER,
    active INTEGER NOT NULL DEFAULT 1,
    description TEXT DEFAULT '',
    FOREIGN KEY (language_id) REFERENCES languages(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS weekdays (
    weekday INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    available_minutes INTEGER NOT NULL DEFAULT 60,
    main_session_allowed INTEGER NOT NULL DEFAULT 1,
    micro_sessions_allowed INTEGER NOT NULL DEFAULT 1,
    start_time TEXT NOT NULL DEFAULT '18:00',
    notes TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS planned_events (
    uid TEXT PRIMARY KEY,
    event_date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    language_id INTEGER,
    task_id INTEGER,
    kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (language_id) REFERENCES languages(id) ON DELETE SET NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL
);

-- What the user actually did: real minutes (from timer or log),
-- quality self-assessment, skipped flag. This feeds the adaptive
-- rotation and every statistic.
CREATE TABLE IF NOT EXISTS session_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid TEXT NOT NULL UNIQUE,
    event_date TEXT NOT NULL,
    language_id INTEGER,
    task_id INTEGER,
    kind TEXT NOT NULL,
    minutes INTEGER NOT NULL,
    quality INTEGER CHECK (quality BETWEEN 0 AND 5 OR quality IS NULL),
    skipped INTEGER NOT NULL DEFAULT 0,
    note TEXT DEFAULT '',
    logged_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (language_id) REFERENCES languages(id) ON DELETE SET NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL
);

-- Anki routine languages (independent from planner languages:
-- you decide which languages receive a new-card flow).
CREATE TABLE IF NOT EXISTS anki_langues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    code TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('active', 'maintenance', 'waiting')),
    lv_daily INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_events_date ON planned_events(event_date);
CREATE INDEX IF NOT EXISTS idx_events_language ON planned_events(language_id);
CREATE INDEX IF NOT EXISTS idx_tasks_language ON tasks(language_id);
CREATE INDEX IF NOT EXISTS idx_logs_language ON session_logs(language_id);
CREATE INDEX IF NOT EXISTS idx_logs_date ON session_logs(event_date);
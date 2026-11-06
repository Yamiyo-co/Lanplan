"""Paths, environment and tunable defaults for Language Planner."""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # optional dependency
    load_dotenv = None

# Package layout: lanplan/ is the package root.
PKG_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PKG_DIR.parent

# Load .env from the project root (LANPLAN_ENV can override).
ENV_FILE = Path(os.getenv("LANPLAN_ENV", PROJECT_ROOT / "Conf" / ".env"))

if load_dotenv is not None:
    load_dotenv(ENV_FILE)

# Data locations (overridable through environment variables).
DATA_DIR = Path(os.getenv("LANPLAN_DATA", PROJECT_ROOT / "data"))
DB_PATH = Path(os.getenv("LANPLAN_DB", DATA_DIR / "planner.sqlite"))
BACKUP_DIR = DATA_DIR / "backups"

SCHEMA_FILE = PKG_DIR / "sql" / "schema.sql"
SEED_FILE = PKG_DIR / "sql" / "seed.sql"

# CalDAV / Nextcloud credentials come from the environment only:
# URL, username, app password, calendar name.
CALDAV_URL = os.environ.get("NEXTCLOUD_CALDAV_URL", "")
CALDAV_USERNAME = os.environ.get("NEXTCLOUD_USERNAME", "")
CALDAV_PASSWORD = os.environ.get("NEXTCLOUD_APP_PASSWORD", "")
TIMEZONE = os.environ.get("TIMEZONE", "Europe/Paris")

# Anki routine URL: dedicated calendar (see README for why the planner and the routine should not share one calendar).
ANKI_CALDAV_URL = os.environ.get("ANKI_CALDAV_URL", "")
ANKI_HORIZON_MONTHS = 2

# Cognitive-load guards: defaults used when a key is missing from the settings table. Everything is overridable at runtime.
DEFAULT_GUARDS = {
    # Max distinct languages planned per day.
    "max_languages_per_day": 2,
    # Hard cap of planned minutes per day, all languages included.
    "max_minutes_per_day": 110,
    # 0 = Monday ... 5 = Saturday: flexible catch-up day.
    "flex_weekday": 5,
    # Duration of the Sunday Anki block (0 disables it).
    "anki_minutes": 20,
    # Score penalty when an interfering language is already placed on the same day.
    "interference_penalty": 40,
}

# Groups of languages that interfere with each other, separated by "|", members separated by ",".
# Two members of one group are never scheduled on the same day. Default: logographically close pair.
DEFAULT_INTERFERENCE_GROUPS = "japanese,chinese"
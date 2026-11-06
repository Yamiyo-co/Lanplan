# Language Planner

A pedagogically-driven multilingual study planner. It distributes main
sessions and micro-sessions across **the languages you learn** based on **real needs**
*(deficits, spacing, self-assessed quality)* rather than mechanical
rotation. Also performs the following actions : 
* syncs to a CalDAV calendar (Nextcloud);
* manages Anki new-card quotas;
* tracks what you actually did;
* visualizes everything.

## Features

- **Need-based scheduling** — hierarchical: \
  Active languages get most main sessions (weighted by `weight`),
  maintenance languages share one main session per week, in cumulative rotation.
- **Cognitive-load guards** (all configurable in `settings`):
  - `max_languages_per_day` (default 2)
  - `max_minutes_per_day` (default 110)
  - `flex_weekday` — flexible catch-up day (default Saturday)
  - `interference_groups` — e.g. `japanese,chinese` never
    scheduled the same day
- **Session tracking** — `log` what you did (or skipped) with a quality
  score 0–5; the scheduler reads the history and adapts the rotation.
- **Live timer** — `timer` runs a stopwatch per session; the real
  duration is recorded, so your tracking reflects reality, not plans.
- **Anki integration** — `anki run` creates one calendar event per day:
  full new-card quota for the planner's main-session language, half
  for one secondary in rotation, quarter for one maintenance language
  (only on `maintenance_days` days). Reviews are always every day, all
  languages.
- **Idempotent sync** — deterministic UIDs: re-running `sync` never
  duplicates; events that left the plan are deleted remotely.
- **Dashboard** — `stats --html` generates a standalone HTML dashboard
  (Chart.js) with daily/weekly/monthly minutes, per-language progress,
  completion rate and quality trends.
- **Web GUI** — `planner web` serves a local Flask interface:
  dashboard, calendar, editor, timer, one-click sync.

## Install

```bash
#Clone
git clone <repo> && cd language-planner

#Inside /Lanplan/Planner/sql/seed.sql
#Or, after installation through :
python -m Planner.cli editor
# Modify languages, ID, default times, cards, ...
#Default seed.sql is already filled with few languages as an example.

#Inside /Lanplan/Conf
cp .env.example .env   # then edit credentials

#Inside /Lanplan
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m Planner.cli init
```

## Daily workflow

For more informations, you can consult `/Lanplan/COMMANDS.md`

```bash
#Working session
#I-Plan
python -m Planner.cli sync --dry-run   # preview
python -m Planner.cli sync             # apply to Nextcloud

#II-Save (Don't do both)
python -m Planner.cli timer            # run a session, timed             --> If you consider doing less or more than default time
python -m Planner.cli log              # mark done/skipped + quality      --> If you consider doing the exact default time

#For web interface and stats
python -m Planner.cli stats --weeks 4  # text report
python -m Planner.cli stats --html dashboard.html
python -m Planner.cli web              # GUI on http://127.0.0.1:5000
```

## Anki sub-commands

```bash
python -m Planner.cli anki run --dry-run
python -m Planner.cli anki quotas
python -m Planner.cli anki add <language_name language_ID language_status number_card> #eg: Japanse ja active 8
python -m Planner.cli anki remove <language_ID> #eg: jp
python -m Planner.cli anki set <language_ID number_card> #eg: jp 6
```

## Architecture

### Folder

```Lanplan/
├── README.md
├── COMMANDS.md
├── requirements.txt
└── Conf/           # conf for nextcloud sync
    ├── .env.example
└── Planner/           # main package
    ├── __init__.py
    ├── config.py          
    ├── database.py        
    ├── scheduler.py       
    ├── caldav_sync.py   
    ├── anki.py           
    ├── timer.py         
    ├── stats.py        
    ├── editor.py         
    ├── webapp.py         
    ├── cli.py            
    └── sql/              # database with schema.sql and seed.sql
```

### Description

| Module | Role |
|---|---|
| `config.py` | Paths (DB, schema, seed), environment, guard defaults |
| `database.py` | SQLite wrapper: languages, tasks, weekdays, settings, planned events, session logs |
| `scheduler.py` | Pedagogical engine: history, scores, guards, flex day, interference, weekly generation |
| `caldav_sync.py` | CalDAV upsert + purge of our own obsolete events |
| `anki.py` | Independent Anki routine DB + planner-aligned new-card quotas |
| `timer.py` | Interactive stopwatch; records real session duration |
| `stats.py` | Aggregates logs; text report + HTML dashboard |
| `editor.py` | Interactive CLI editor (English) |
| `webapp.py` | Flask GUI (version 2 of the planner) |
| `cli.py` | Command dispatch |

## Data model

See `Planner/sql/schema.sql`. Key tables: `languages`, `tasks`,
`weekdays`, `planned_events`, `session_logs` (what you really did:
minutes, quality, skipped), `settings` (including all cognitive-load
guards), plus `anki_langues` in the same SQLite file for the routine.

## Pedagogical principles

- **Spacing**: every language is touched at spaced intervals; Anki
  reviews are never filtered by "language of the day".
- **Interleaving**: languages rotate within sessions, never blocked.
- **Minimum effective dose**: maintenance languages get small, spaced
  top-ups (Bahrick-style maintenance), active languages get
  acquisition-level volume.
- **Cognitive load**: hard caps on languages/day and minutes/day.
- **Adaptive**: skipped or poorly-rated sessions raise a language's
  urgency automatically on the next `plan`/`sync`.
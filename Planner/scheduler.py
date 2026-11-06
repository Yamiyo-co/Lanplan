"""
Pedagogical scheduling engine.

Principles:
- Hierarchical allocation: active > maintenance for main sessions, weighted by language weight inside each group (Sainte-Lague).
- Need-based micro sessions: minimum contacts first, then deficit score (minutes, spacing, quality), corrected by interference.
- Cognitive-load guards: max languages/day, max minutes/day, flexible catch-up day.
- History-aware: session logs (real minutes, quality, skipped) modulate urgency, so the rotation adapts to what you actually did.
"""

from __future__ import annotations

import hashlib
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from . import config


@dataclass
class PlannedEvent:
    uid: str
    event_date: str
    start_time: str
    end_time: str
    language_id: int | None
    task_id: int | None
    kind: str
    summary: str


def uid_for(event_date, language_id, task_id, kind):
    """Deterministic UID: re-syncing never duplicates events."""
    raw = f"language-planner:{event_date}:{language_id}:{task_id}:{kind}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return f"langplan-{digest}"


def add_minutes(time_string, minutes):
    hour, minute = map(int, time_string.split(":"))
    total = hour * 60 + minute + minutes
    return f"{total // 60:02d}:{total % 60:02d}"


def normalize_name(name):
    """Accent-insensitive, case-insensitive name normalization."""
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.strip().lower()


class _WeekState:
    """Tracks planned quantities for the week being scheduled."""

    def __init__(self):
        self.minutes = defaultdict(int)
        self.contacts = defaultdict(int)
        self.last_contact = {}
        self.task_counts = defaultdict(int)
        self.last_task_kind = {}
        self.tasks_today = defaultdict(set)
        self.languages_today = defaultdict(set)

    def record(self, language_id, day, duration,
               task_id=None, task_kind=None):
        self.minutes[language_id] += duration
        self.contacts[language_id] += 1
        self.last_contact[language_id] = day
        self.languages_today[day.isoformat()].add(language_id)

        if task_id is not None:
            self.task_counts[task_id] += 1
            self.last_task_kind[language_id] = task_kind
            self.tasks_today[day.isoformat()].add(
                (language_id, task_id)
            )


class Scheduler:
    def __init__(self, db):
        self.db = db
        self.history = {}
        self.guards = dict(config.DEFAULT_GUARDS)
        self.languages_by_id = {}
        self._interference = None

    # -- Data loading ----------------------------------------------------

    def active_languages(self):
        return [dict(l) for l in self.db.languages(active_only=True)]

    def weekdays(self):
        return {row["weekday"]: dict(row)
                for row in self.db.weekdays()}

    def tasks(self):
        return [dict(t) for t in self.db.tasks(active_only=True)]

    @staticmethod
    def _safe_get(obj, key, default):
        if hasattr(obj, "get"):
            return obj.get(key, default)
        return getattr(obj, key, default) if hasattr(obj, key) else default

    # -- History (what was really done) ----------------------------------

    def prepare_history(self, start_date):
        """Build per-language history from session logs (7-day window).

        Tolerates a missing session_logs table (fresh database).
        """
        try:
            logs = self.db.session_logs(before=start_date.isoformat())
        except Exception:
            logs = []

        cutoff = (start_date - timedelta(days=7)).isoformat()

        recent = [log for log in logs
                  if log["skipped"] == 0
                  and log["language_id"] is not None
                  and log["event_date"] >= cutoff]

        done_minutes = defaultdict(int)
        done_contacts = defaultdict(int)
        qualities = defaultdict(list)
        last_done = {}

        for log in logs:
            if log["skipped"] == 0 and log["language_id"]:
                lid = log["language_id"]
                if (lid not in last_done
                        or log["event_date"] > last_done[lid]):
                    last_done[lid] = log["event_date"]

        for log in recent:
            lid = log["language_id"]
            done_minutes[lid] += log["minutes"]
            done_contacts[lid] += 1
            if log["quality"] is not None:
                qualities[lid].append(log["quality"])

        self.history = {}
        for lid, last in last_done.items():
            qs = qualities.get(lid, [])
            self.history[lid] = {
                "done_minutes_7d": done_minutes[lid],
                "done_contacts_7d": done_contacts[lid],
                "days_since_done": (
                    (start_date - date.fromisoformat(last)).days
                ),
                "avg_quality": (sum(qs) / len(qs)) if qs else None,
            }

    def effective_weight(self, language):
        """Base weight amplified by real urgency.

        - Long absence -> stronger pull (spacing).
        - Low quality scores -> consolidation urgency.
        - Recent volume above target -> slight relief.
        """
        base = language["weight"]
        info = self.history.get(language["id"])
        if not info:
            return base

        urgency = 1.0
        urgency += min(1.0, info["days_since_done"] / 10)

        if info["avg_quality"] is not None:
            urgency += max(0.0, (3 - info["avg_quality"]) / 6)

        target = language["target_minutes_week"]
        if target > 0 and info["done_minutes_7d"] > 0:
            urgency -= min(0.3,
                           (info["done_minutes_7d"] / target) * 0.3)

        return base * max(0.5, urgency)

    # -- Cognitive guards --------------------------------------------------

    def _guard_settings(self, settings):
        guards = {}
        for key, default in config.DEFAULT_GUARDS.items():
            raw = self._safe_get(settings, key, str(default))
            try:
                guards[key] = int(raw)
            except (TypeError, ValueError):
                guards[key] = default
        return guards

    def interference_map(self):
        """{normalized name: set of names forbidden the same day}."""
        if self._interference is not None:
            return self._interference

        try:
            settings = self.db.settings()
        except Exception:
            settings = {}

        raw = self._safe_get(settings, "interference_groups",
                             config.DEFAULT_INTERFERENCE_GROUPS)

        mapping = {}
        for group in str(raw).split("|"):
            members = [normalize_name(m)
                       for m in group.split(",") if m.strip()]
            for member in members:
                mapping[member] = set(members) - {member}

        self._interference = mapping
        return mapping

    def _interferes(self, language, other):
        mapping = self.interference_map()
        return normalize_name(other["name"]) in mapping.get(
            normalize_name(language["name"]), set())

    def _interference_penalty(self, language, state, day):
        today_ids = state.languages_today.get(day.isoformat(), set())
        if not today_ids:
            return 0
        others = [self.languages_by_id[lid]
                  for lid in today_ids if lid in self.languages_by_id]
        if any(self._interferes(language, o) for o in others):
            return self.guards["interference_penalty"]
        return 0

    # -- Main session allocation ------------------------------------------

    def choose_main_languages(self, languages, cum, number):
        """
        Hierarchical weighted allocation (Sainte-Lague).

        Maintenance languages share ONE main session per week (cumulative alternation).
        Active languages fill the rest, proportional to their effective weight.
        Duplicates of a same language are spread across the week.
        """
        if not languages or number <= 0:
            return []

        actives = [l for l in languages if l["status"] == "active"]
        maintenance = [l for l in languages
                       if l["status"] == "maintenance"]

        chosen = []

        if maintenance and number >= 2:
            best = max(
                maintenance,
                key=lambda lang: self.effective_weight(lang)
                / (2 * cum[lang["id"]] + 1),
            )
            chosen.append(best)
            cum[best["id"]] += 1

        pool = actives or maintenance
        while len(chosen) < number:
            best = max(
                pool,
                key=lambda lang: self.effective_weight(lang)
                / (2 * cum[lang["id"]] + 1),
            )
            chosen.append(best)
            cum[best["id"]] += 1

        # Spread: rotate distinct languages first so a language
        # never appears on two consecutive days when avoidable.
        by_language = defaultdict(list)
        for language in chosen:
            by_language[language["id"]].append(language)

        order = []
        while any(by_language.values()):
            for lid in list(by_language):
                if by_language[lid]:
                    order.append(by_language[lid].pop(0))
        return order[:number]

    def _needs_main(self, language):
        """A language that already reached its real 7-day minutes target yields its main slot to another language."""
        info = self.history.get(language["id"])
        if not info:
            return True
        target = language["target_minutes_week"]
        if target <= 0:
            return False
        return info["done_minutes_7d"] < target

    # -- Micro session selection -------------------------------------------

    def language_score(self, language, state, today):
        """Need score: deficits (real + planned), spacing, quality."""
        lid = language["id"]
        info = self.history.get(lid)
        done_minutes = info["done_minutes_7d"] if info else 0
        done_contacts = info["done_contacts_7d"] if info else 0

        time_deficit = max(0, language["target_minutes_week"]
                           - done_minutes - state.minutes[lid])
        contact_deficit = max(0, language["min_contacts_week"]
                               - done_contacts - state.contacts[lid])

        last = state.last_contact.get(lid)
        spacing = 7 if last is None else min((today - last).days, 7)

        quality_urgency = 0
        if info and info["avg_quality"] is not None:
            quality_urgency = max(0, (3 - info["avg_quality"]) * 15)

        return (language["priority"] * 100 + time_deficit
                + contact_deficit * 30 + spacing * 5 + quality_urgency)

    def language_needs_work(self, language, state):
        lid = language["id"]
        if state.contacts[lid] >= language["max_contacts_week"]:
            return False
        if state.contacts[lid] < language["min_contacts_week"]:
            return True
        return state.minutes[lid] < language["target_minutes_week"]

    def pick_language(self, languages, state, day, allowed_ids=None):
        """Two-phase pick: guarantee min contacts, then fill by score.

        allowed_ids: when the daily language cap is reached, only
        languages already present on that day may be consolidated.
        """
        workable = [l for l in languages
                    if self.language_needs_work(l, state)]

        if allowed_ids is not None:
            restricted = [l for l in workable
                          if l["id"] in allowed_ids]
            if restricted:
                workable = restricted

        if not workable:
            return None

        needy = [l for l in workable
                 if state.contacts[l["id"]]
                 < l["min_contacts_week"]]

        if needy:
            needy.sort(key=lambda lang: (
                state.contacts[lang["id"]],
                -self._days_since(state, lang["id"], day),
            ))
            return needy[0]

        workable.sort(key=lambda lang: -(
            self.language_score(lang, state, day)
            - self._interference_penalty(lang, state, day)
        ))
        return workable[0]

    def pick_language_flex(self, languages, state, day,
                           allowed_ids=None):
        """Catch-up day: serve the lowest coverage ratio first."""
        pool = [l for l in languages
                if self.language_needs_work(l, state)]

        if allowed_ids is not None:
            restricted = [l for l in pool
                          if l["id"] in allowed_ids]
            if restricted:
                pool = restricted

        if not pool:
            return None

        def coverage(language):
            info = self.history.get(language["id"])
            done = info["done_minutes_7d"] if info else 0
            target = language["target_minutes_week"]
            if target <= 0:
                return 1.0
            return (done + state.minutes[language["id"]]) / target

        pool.sort(key=lambda lang: (
            coverage(lang), state.contacts[lang["id"]]))
        return pool[0]

    @staticmethod
    def _days_since(state, language_id, day):
        last = state.last_contact.get(language_id)
        return 99 if last is None else (day - last).days

    def choose_micro_task(self, micro_tasks, language, state,
                           day, remaining):
        """Variety-aware task pick honoring min/max weekly quotas."""
        lid = language["id"]
        today = day.isoformat()

        candidates = []
        for task in micro_tasks:
            if task["duration_min"] > remaining:
                continue
            if state.task_counts[task["id"]] >= task["max_per_week"]:
                continue
            if (lid, task["id"]) in state.tasks_today[today]:
                continue

            below_min = (state.task_counts[task["id"]]
                         < task["min_per_week"])
            last_kind = state.last_task_kind.get(lid)
            same_kind = (last_kind is not None
                        and last_kind == task["kind"])

            candidates.append((
                0 if below_min else 1,
                1 if same_kind else 0,
                -task["priority"],
                task["duration_min"],
                task["id"],
                task,
            ))

        if not candidates:
            return None
        candidates.sort()
        return candidates[0][-1]

    # -- Week scheduling -----------------------------------------------------

    def schedule_week(self, week_start, cum):
        languages = self.active_languages()
        weekdays = self.weekdays()
        tasks = self.tasks()

        if not languages:
            return []

        state = _WeekState()
        settings = self.db.settings()
        self.guards = self._guard_settings(settings)
        self.languages_by_id = {l["id"]: l for l in languages}

        anki_only_sunday = (
            self._safe_get(settings, "sunday_anki_only", "1") == "1")

        main_task = next((t for t in tasks
                          if t["requires_main_session"]), None)
        micro_tasks = [t for t in tasks
                       if not t["requires_main_session"]]

        enabled_days = [
            d for d in range(7)
            if weekdays.get(d, {}).get("enabled", 0)
            and weekdays[d]["available_minutes"] > 0
        ]
        main_days = [
            d for d in enabled_days
            if weekdays[d]["main_session_allowed"]
            and not (d == 6 and anki_only_sunday)
        ]

        events = []

        # 1. Main sessions — weighted hierarchical allocation.
        main_languages = self.choose_main_languages(
            languages, cum, len(main_days))

        for day_index, language in zip(main_days, main_languages):
            day = week_start + timedelta(days=day_index)
            weekday = weekdays[day_index]

            duration = min(
                language["preferred_session_minutes"],
                weekday["available_minutes"],
                self.guards["max_minutes_per_day"],
            )

            events.append(self._make_event(
                day, weekday["start_time"], duration, language,
                main_task, "main",
                f"{language['name']} - Main session"))
            state.record(language["id"], day, duration,
                         main_task["id"] if main_task else None,
                         "main" if main_task else None)

        # 2. Micro sessions — capped in languages AND minutes.
        for day_index in enabled_days:
            weekday = weekdays[day_index]
            if not weekday["micro_sessions_allowed"]:
                continue

            day = week_start + timedelta(days=day_index)
            if day_index == 6 and anki_only_sunday:
                continue

            used = sum(self._duration(e) for e in events
                       if e.event_date == day.isoformat())
            remaining = min(
                weekday["available_minutes"] - used,
                self.guards["max_minutes_per_day"] - used,
            )
            if remaining < 10:
                continue

            is_flex = (day_index == self.guards["flex_weekday"])

            for _ in range(2):  # max 2 tasks per micro session
                if remaining < 10:
                    break

                today_ids = state.languages_today.get(
                    day.isoformat(), set())

                # Daily language cap reached: consolidate only.
                allowed_ids = (
                    set(today_ids)
                    if len(today_ids)
                    >= self.guards["max_languages_per_day"]
                    else None
                )

                picker = (self.pick_language_flex if is_flex
                          else self.pick_language)
                language = picker(languages, state, day, allowed_ids)
                if language is None:
                    break

                task = self.choose_micro_task(
                    micro_tasks, language, state, day, remaining)
                if task is None:
                    continue

                duration = task["duration_min"]
                start = self._next_start(events, day, weekday)

                events.append(self._make_event(
                    day, start, duration, language, task, "micro",
                    f"{language['name']} - {task['name']}"))
                state.record(language["id"], day, duration,
                             task["id"], task["kind"])
                remaining -= duration

        # 3. Sunday Anki block.
        anki_minutes = self.guards["anki_minutes"]
        if anki_minutes > 0:
            for day_index in enabled_days:
                if day_index != 6:
                    continue
                day = week_start + timedelta(days=day_index)
                weekday = weekdays[day_index]
                events.append(self._make_event(
                    day, weekday["start_time"], anki_minutes,
                    None, None, "anki", "Anki - reviews"))

        return events

    # -- Helpers -------------------------------------------------------------

    def _make_event(self, day, start, duration, language, task,
                    kind, summary):
        return PlannedEvent(
            uid=uid_for(day.isoformat(),
                        language["id"] if language else None,
                        task["id"] if task else None, kind),
            event_date=day.isoformat(),
            start_time=start,
            end_time=add_minutes(start, duration),
            language_id=language["id"] if language else None,
            task_id=task["id"] if task else None,
            kind=kind,
            summary=summary,
        )

    @staticmethod
    def _next_start(events, day, weekday):
        today = [e for e in events
                 if e.event_date == day.isoformat()]
        return today[-1].end_time if today else weekday["start_time"]

    @staticmethod
    def _duration(event):
        sh, sm = map(int, event.start_time.split(":"))
        eh, em = map(int, event.end_time.split(":"))
        return eh * 60 + em - sh * 60 - sm

    # -- Multi-week generation -------------------------------------------

    def generate(self, start_date: date, months=3):
        last_day = start_date + timedelta(days=months * 31)

        # Real history drives the adaptive rotation.
        self.prepare_history(start_date)

        all_events = []
        cum = defaultdict(int)  # cumulative main-session counter
        current = start_date - timedelta(days=start_date.weekday())

        while current <= last_day:
            all_events.extend(self.schedule_week(current, cum))
            current += timedelta(days=7)

        return all_events
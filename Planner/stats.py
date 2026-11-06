"""
Progress tracking: text reports + standalone HTML dashboard.

Data sources:
- planned_events: what was scheduled (per week, per language).
- session_logs: what really happened (real minutes from timer/log, quality scores, skipped sessions).

`build_stats()` returns plain dicts so both the CLI and the web GUI can render them;
`render_dashboard()` produces a single self-contained HTML file (Chart.js from CDN).
"""

from __future__ import annotations

import html
import json
from collections import defaultdict
from datetime import date, timedelta

from . import config


def _duration_of(row):
    sh, sm = map(int, row["start_time"].split(":"))
    eh, em = map(int, row["end_time"].split(":"))
    return eh * 60 + em - sh * 60 - sm


def build_stats(db, weeks=None):
    """Aggregate everything the dashboard and reports need."""
    languages = {row["id"]: dict(row)
                 for row in db.languages(active_only=True)}

    events = db.planned_events()
    logs = db.session_logs()

    # ---- weekly aggregation ---------------------------------------
    by_week = defaultdict(lambda: {
        "planned_min": defaultdict(int),
        "done_min": defaultdict(int),
        "contacts": defaultdict(int),
    })

    for event in events:
        lid = event["language_id"]
        if lid is None:
            continue
        day = date.fromisoformat(event["event_date"])
        year, week, _ = day.isocalendar()
        by_week[(year, week)]["planned_min"][lid] += (
            _duration_of(event))

    for log in logs:
        if log["skipped"] or log["language_id"] is None:
            continue
        day = date.fromisoformat(log["event_date"])
        year, week, _ = day.isocalendar()
        cell = by_week[(year, week)]
        cell["done_min"][log["language_id"]] += log["minutes"]
        cell["contacts"][log["language_id"]] += 1

    week_keys = sorted(by_week)
    if weeks:
        week_keys = week_keys[-weeks:]

    weekly = []
    for key in week_keys:
        year, week = key
        cell = by_week[key]
        weekly.append({
            "label": f"{year}-W{week:02d}",
            "planned": {
                languages[lid]["name"]: minutes
                for lid, minutes in cell["planned_min"].items()
                if lid in languages
            },
            "done": {
                languages[lid]["name"]: minutes
                for lid, minutes in cell["done_min"].items()
                if lid in languages
            },
        })

    # ---- daily real minutes (time series) --------------------------
    daily = defaultdict(int)
    for log in logs:
        if not log["skipped"]:
            daily[log["event_date"]] += log["minutes"]
    daily_series = [
        {"date": d, "minutes": daily[d]}
        for d in sorted(daily)
    ]

    # ---- quality per language ---------------------------------------
    quality = defaultdict(list)
    for log in logs:
        if log["quality"] is not None \
                and log["language_id"] is not None:
            quality[log["language_id"]].append(log["quality"])

    quality_by_language = {
        languages[lid]["name"]: {
            "average": round(sum(qs) / len(qs), 2),
            "count": len(qs),
        }
        for lid, qs in quality.items() if lid in languages
    }

    # ---- completion + totals -----------------------------------------
    planned_total = sum(1 for e in events)
    done_total = sum(1 for log in logs if not log["skipped"])
    skipped_total = sum(1 for log in logs if log["skipped"])

    minutes_by_language = defaultdict(int)
    for log in logs:
        if not log["skipped"] and log["language_id"]:
            minutes_by_language[log["language_id"]] += (
                log["minutes"])

    totals = {
        "planned_events": planned_total,
        "done_events": done_total,
        "skipped_events": skipped_total,
        "completion_rate": (
            round(100 * done_total / planned_total, 1)
            if planned_total else 0.0
        ),
        "minutes_by_language": {
            languages[lid]["name"]: minutes
            for lid, minutes in minutes_by_language.items()
            if lid in languages
        },
    }

    return {
        "weekly": weekly,
        "daily": daily_series,
        "quality": quality_by_language,
        "totals": totals,
        "targets": {
            languages[lid]["name"]:
                languages[lid]["target_minutes_week"]
            for lid in languages
        },
    }


def print_report(stats):
    """Console-friendly weekly report (successor of `suivi`)."""
    print()
    print("WEEKLY PROGRESS")
    print("-" * 60)

    targets = stats["targets"]

    for week in stats["weekly"]:
        print()
        print(week["label"])
        names = sorted(set(week["planned"]) | set(week["done"]))
        for name in names:
            done = week["done"].get(name, 0)
            planned = week["planned"].get(name, 0)
            target = targets.get(name, 60)
            if target > 0:
                ratio = int(100 * done / target)
                bar = "#" * min(10, ratio // 10)
                print(f"  {name:<12} {done:>4}/{target:<4} min"
                      f" {ratio:>3}% {bar:<10}")
            else:
                print(f"  {name:<12} {done:>4} min")

    totals = stats["totals"]
    print()
    print("TOTALS")
    print("-" * 60)
    print(f"  planned sessions : {totals['planned_events']}")
    print(f"  done sessions    : {totals['done_events']}"
          f" ({totals['completion_rate']}%)")
    print(f"  skipped sessions : {totals['skipped_events']}")
    print()

    print("QUALITY")
    print("-" * 60)
    for name, info in stats["quality"].items():
        trend = "consolidate" if info["average"] < 3 \
            else "on track"
        print(f"  {name:<12} avg {info['average']:.1f}/5"
              f" over {info['count']} sessions ({trend})")

    if not stats["quality"]:
        print("  (no quality rating logged yet)")


_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Language Planner - Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
 body {{ font-family: system-ui, sans-serif; margin: 2rem;
        background: #f6f7fb; color: #222; }}
 h1 {{ margin-top: 0; }}
 .cards {{ display: flex; gap: 1rem; flex-wrap: wrap; margin: 1rem 0 2rem; }}
 .card {{ background: #fff; border-radius: 10px; padding: 1rem 1.4rem;
         box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
 .card .value {{ font-size: 1.6rem; font-weight: 600; }}
 .chart {{ background: #fff; border-radius: 10px; padding: 1rem;
          box-shadow: 0 1px 4px rgba(0,0,0,.08);
          margin-bottom: 1.5rem; max-width: 900px; }}
</style>
</head>
<body>
<h1>Language Planner &mdash; Dashboard</h1>
<div class="cards">
  <div class="card"><div>Done sessions</div>
    <div class="value">{done_events}</div></div>
  <div class="card"><div>Completion</div>
    <div class="value">{completion_rate}%</div></div>
  <div class="card"><div>Skipped</div>
    <div class="value">{skipped_events}</div></div>
  <div class="card"><div>Total real minutes</div>
    <div class="value">{total_minutes}</div></div>
</div>
<div class="chart"><canvas id="daily"></canvas></div>
<div class="chart"><canvas id="weekly"></canvas></div>
<div class="chart"><canvas id="quality"></canvas></div>
<script>
const data = {payload};
new Chart(document.getElementById('daily'), {{
  type: 'line',
  data: {{
    labels: data.daily.map(d => d.date),
    datasets: [{{ label: 'Real minutes per day',
      data: data.daily.map(d => d.minutes),
      borderColor: '#4c6ef5', backgroundColor: '#4c6ef533',
      fill: true, tension: .3 }}]
  }}
}});
const langs = [...new Set(data.weekly.flatMap(w =>
  Object.keys(w.done)))];
new Chart(document.getElementById('weekly'), {{
  type: 'bar',
  data: {{
    labels: data.weekly.map(w => w.label),
    datasets: langs.map(name => ({{
      label: name,
      data: data.weekly.map(w => w.done[name] || 0)
    }}))
  }},
  options: {{ scales: {{ x: {{ stacked: true }},
                    y: {{ stacked: true }} }} }}
}});
new Chart(document.getElementById('quality'), {{
  type: 'bar',
  data: {{
    labels: Object.keys(data.quality),
    datasets: [{{ label: 'Average quality /5',
      data: Object.values(data.quality).map(q => q.average),
      backgroundColor: '#12b886' }}]
  }},
  options: {{ scales: {{ y: {{ min: 0, max: 5 }} }} }}
}});
</script>
</body>
</html>
"""


def render_dashboard(stats, output_path="dashboard.html"):
    """Write a standalone HTML dashboard with charts."""
    payload = json.dumps(stats)
    total_minutes = sum(stats["totals"]["minutes_by_language"]
                        .values())

    page = _TEMPLATE.format(
        payload=payload,
        done_events=stats["totals"]["done_events"],
        completion_rate=stats["totals"]["completion_rate"],
        skipped_events=stats["totals"]["skipped_events"],
        total_minutes=total_minutes,
    )

    with open(output_path, "w", encoding="utf-8") as file:
        file.write(page)

    return output_path
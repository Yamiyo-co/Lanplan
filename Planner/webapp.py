"""
Flask web GUI - version 2 of the planner.

Pages:
    /            dashboard (stats + charts)
    /events      calendar-style list of planned sessions
    /languages   view + quick edit of languages
    /timer       pick a session, start/stop the timer
    /actions     one-click plan / sync (dry-run or real)

Run with: python -m langplanner.cli web
"""

from __future__ import annotations

import time
from datetime import date

from flask import Flask, redirect, render_template_string, request

from . import config, stats
from .database import Database
from .scheduler import Scheduler
from .caldav_sync import from_environment

app = Flask(__name__)

# Simple in-memory timer state (single-user local app).
_timer_state = {"uid": None, "start": None, "event": None}


def _duration_of(row):
    sh, sm = map(int, row["start_time"].split(":"))
    eh, em = map(int, row["end_time"].split(":"))
    return eh * 60 + em - sh * 60 - sm


_BASE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Language Planner</title>
<style>
 body { font-family: system-ui, sans-serif; margin: 0;
        background: #f6f7fb; color: #222; }
 nav { background: #1d2a44; padding: .8rem 2rem; }
 nav a { color: #fff; margin-right: 1.4rem; text-decoration: none;
         font-weight: 500; }
 main { padding: 2rem; max-width: 1000px; margin: auto; }
 table { border-collapse: collapse; background: #fff; width: 100%;
         box-shadow: 0 1px 4px rgba(0,0,0,.08);
         border-radius: 8px; overflow: hidden; }
 th, td { padding: .55rem .9rem; text-align: left;
          border-bottom: 1px solid #eee; font-size: .92rem; }
 th { background: #eef1f8; }
 .btn { display: inline-block; padding: .45rem .9rem; margin: .2rem;
        background: #4c6ef5; color: #fff; border: none;
        border-radius: 6px; text-decoration: none; cursor: pointer; }
 .btn.warn { background: #e8590c; }
 .btn.ok { background: #12b886; }
 .card { background: #fff; border-radius: 10px; padding: 1rem 1.4rem;
         box-shadow: 0 1px 4px rgba(0,0,0,.08); display:
         inline-block; margin: .3rem; }
 .value { font-size: 1.5rem; font-weight: 600; }
 h1 { margin-top: 0; }
</style>
</head>
<body>
<nav>
  <a href="/">Dashboard</a>
  <a href="/events">Calendar</a>
  <a href="/languages">Languages</a>
  <a href="/timer">Timer</a>
  <a href="/actions">Actions</a>
</nav>
<main>{{ body|safe }}
</main>
</body>
</html>
"""


def _page(body):
    return render_template_string(_BASE, body=body)


@app.route("/")
def dashboard():
    db = Database()
    data = stats.build_stats(db, weeks=8)
    db.close()

    totals = data["totals"]
    cards = (
        f'<div class="card"><div>Done sessions</div>'
        f'<div class="value">{totals["done_events"]}</div></div>'
        f'<div class="card"><div>Completion</div>'
        f'<div class="value">{totals["completion_rate"]}%</div></div>'
        f'<div class="card"><div>Skipped</div>'
        f'<div class="value">{totals["skipped_events"]}</div></div>'
    )

    rows = ""
    for name, minutes in sorted(
            totals["minutes_by_language"].items(),
            key=lambda x: -x[1]):
        rows += (f"<tr><td>{name}</td>"
                 f"<td>{minutes} min</td></tr>")

    quality = ""
    for name, info in data["quality"].items():
        quality += (f"<tr><td>{name}</td>"
                    f"<td>{info['average']:.1f}/5</td>"
                    f"<td>{info['count']} sessions</td></tr>")

    weeks_html = ""
    for week in data["weekly"]:
        detail = ", ".join(
            f"{name} {done} min"
            for name, done in sorted(week["done"].items()))
        weeks_html += (f"<tr><td>{week['label']}</td>"
                       f"<td>{detail}</td></tr>")

    body = f"""
    <h1>Dashboard</h1>
    {cards}
    <h2>Real minutes by language</h2>
    <table><tr><th>Language</th><th>Minutes</th></tr>{rows}</table>
    <h2>Quality</h2>
    <table><tr><th>Language</th><th>Avg</th><th>Sessions</th></tr>
    {quality}</table>
    <h2>Last weeks</h2>
    <table><tr><th>Week</th><th>Done</th></tr>{weeks_html}</table>
    <p><a class="btn" href="/stats.html">Full charts dashboard</a>
    <a class="btn" href="/actions">Plan &amp; sync</a></p>
    """
    return _page(body)


@app.route("/stats.html")
def full_dashboard():
    db = Database()
    data = stats.build_stats(db)
    db.close()
    path = config.PKG_DIR.parent / "dashboard.html"
    stats.render_dashboard(data, str(path))
    return redirect("/dashboard-static")


@app.route("/dashboard-static")
def dashboard_static():
    path = config.PKG_DIR.parent / "dashboard.html"
    if not path.exists():
        return _page("<h1>No dashboard yet</h1>"
                     "<p>Generate it from the Dashboard page.</p>")
    return path.read_text(encoding="utf-8")


@app.route("/events")
def events():
    db = Database()
    names = {row["id"]: row["name"] for row in db.languages()}
    rows = ""
    for event in db.planned_events()[:400]:
        lang = names.get(event["language_id"], "-")
        rows += (f"<tr><td>{event['event_date']}</td>"
                 f"<td>{event['start_time']}-"
                 f"{event['end_time']}</td>"
                 f"<td>{lang}</td>"
                 f"<td>{event['summary']}</td></tr>")
    db.close()
    return _page(f"""
    <h1>Calendar</h1>
    <table>
      <tr><th>Date</th><th>Time</th><th>Language</th>
          <th>Session</th></tr>
      {rows}
    </table>
    """)


@app.route("/languages")
def languages():
    db = Database()
    rows = ""
    for lang in db.languages():
        rows += (f"<tr><td>{lang['id']}</td>"
                 f"<td>{lang['name']}</td>"
                 f"<td>{lang['level']} -> {lang['objective']}</td>"
                 f"<td>{lang['status']}</td>"
                 f"<td>{lang['target_minutes_week']} min/w</td>"
                 f"<td>{lang['weight']}</td></tr>")
    db.close()
    return _page(f"""
    <h1>Languages</h1>
    <table>
      <tr><th>ID</th><th>Name</th><th>Level</th><th>Status</th>
          <th>Target</th><th>Weight</th></tr>
      {rows}
    </table>
    <p>Use the CLI editor for full editing:
    <code>python -m langplanner.cli editor</code></p>
    """)


@app.route("/timer", methods=["GET"])
def timer_page():
    db = Database()
    today = date.today().isoformat()
    done = db.logged_uids(today)
    events = [e for e in db.planned_events(today)
              if e["uid"] not in done]
    db.close()

    rows = ""
    for index, event in enumerate(events):
        rows += (f"<tr><td>{event['start_time']}</td>"
                 f"<td>{event['summary']}</td>"
                 f"<td><a class='btn ok' "
                 f"href='/timer/start/{index}'>Start</a></td></tr>")

    running = ""
    if _timer_state["start"] is not None:
        running = (
            f"<p class='card'><b>Running:</b> "
            f"{_timer_state['event']['summary']} — "
            f"<a class='btn warn' href='/timer/stop'>Stop</a></p>")

    return _page(f"""
    <h1>Timer - {today}</h1>
    {running}
    <table>
      <tr><th>Time</th><th>Session</th><th></th></tr>
      {rows or "<tr><td colspan='3'>"
               "Nothing planned today.</td></tr>"}
    </table>
    """)


@app.route("/timer/start/<int:index>")
def timer_start(index):
    db = Database()
    today = date.today().isoformat()
    done = db.logged_uids(today)
    events = [e for e in db.planned_events(today)
              if e["uid"] not in done]
    db.close()

    if index < len(events):
        _timer_state["event"] = dict(events[index])
        _timer_state["start"] = time.monotonic()
    return redirect("/timer")


@app.route("/timer/stop")
def timer_stop():
    if _timer_state["start"] is None:
        return redirect("/timer")

    elapsed = time.monotonic() - _timer_state["start"]
    minutes = max(1, round(elapsed / 60))
    event = _timer_state["event"]
    quality = request.args.get("quality")

    db = Database()
    db.log_session(
        uid=event["uid"], event_date=event["event_date"],
        language_id=event["language_id"],
        task_id=event["task_id"], kind=event["kind"],
        minutes=minutes,
        quality=int(quality) if quality else None,
        skipped=0, note="timed from web GUI",
    )
    db.close()

    _timer_state.update({"uid": None, "start": None,
                         "event": None})
    return _page(f"<h1>Session logged</h1>"
                 f"<p>{minutes} minutes recorded.</p>"
                 f"<p><a class='btn' href='/'>Dashboard</a></p>")


@app.route("/actions")
def actions():
    return _page("""
    <h1>Actions</h1>
    <p>Always preview first, then apply:</p>
    <p>
      <a class="btn" href="/actions/plan">Re-plan locally</a>
      <a class="btn" href="/actions/sync?dry=1">
        Sync (dry-run)</a>
      <a class="btn warn" href="/actions/sync">Sync (real)</a>
    </p>
    <p>The web timer records real durations; the CLI
    <code>log</code> command adds quality scores.</p>
    """)


@app.route("/actions/plan")
def do_plan():
    db = Database()
    scheduler = Scheduler(db)
    events = scheduler.generate(start_date=date.today(), months=3)
    db.replace_planned_events(
        [(e.uid, e.event_date, e.start_time, e.end_time,
          e.language_id, e.task_id, e.kind, e.summary)
         for e in events])
    db.close()
    return _page(f"<h1>Planned</h1><p>{len(events)} events "
                 f"generated.</p><p><a class='btn' "
                 f"href='/events'>See calendar</a></p>")


@app.route("/actions/sync")
def do_sync():
    dry = request.args.get("dry") == "1"
    db = Database()
    scheduler = Scheduler(db)
    events = scheduler.generate(start_date=date.today(), months=3)

    try:
        settings = db.settings()
        client = from_environment(
            calendar_name=settings.get("calendar_name"),
            timezone=settings.get("timezone"),
        )
        result = client.sync(events, dry_run=dry)
        message = (f"Created: {result['created']}, "
                   f"existing: {result['existing']}, "
                   f"deleted: {result['deleted']}")
    except Exception as error:
        message = f"Sync failed: {error}"
    finally:
        db.close()

    return _page(f"<h1>Sync {'(dry-run)' if dry else ''}</h1>"
                 f"<p>{message}</p>"
                 f"<p><a class='btn' href='/actions'>Back</a></p>")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
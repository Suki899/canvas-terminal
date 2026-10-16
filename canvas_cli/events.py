"""Calendar events: classes, tests and other dated items courses put on Canvas."""

from datetime import datetime, timedelta
from urllib.parse import urlencode

from .api import CanvasError
from .util import colours, emit, html_to_text, parse_time

# Canvas accepts at most 10 context codes per calendar request.
CHUNK = 10


def fetch(client, courses, start, end, kind):
    me = client.one("/api/v1/users/self")
    codes = [f"course_{c['id']}" for c in courses] + [f"user_{me['id']}"]
    names = {f"course_{c['id']}": c.get("course_code") or c.get("name") for c in courses}
    found = {}
    for i in range(0, len(codes), CHUNK):
        query = [("type", kind), ("start_date", start.isoformat()), ("end_date", end.isoformat())]
        query += [("context_codes[]", code) for code in codes[i:i + CHUNK]]
        for event in client.listing(f"/api/v1/calendar_events?{urlencode(query)}"):
            found[(kind, event.get("id"))] = (event, names.get(event.get("context_code"), "personal"))
    return list(found.values())


def record(event, course):
    assignment = event.get("assignment") or {}
    return {"id": event.get("id"), "type": "assignment" if assignment else "event",
            "title": (event.get("title") or "").strip(), "course": course,
            "start_at": parse_time(event.get("start_at")), "end_at": parse_time(event.get("end_at")),
            "all_day": bool(event.get("all_day")),
            "location": event.get("location_name") or event.get("location_address"),
            "description": html_to_text(event.get("description")), "url": event.get("html_url")}


def day_range(text):
    try:
        return datetime.strptime(text, "%Y-%m-%d").astimezone()
    except ValueError as exc:
        raise CanvasError(f"--from expects YYYY-MM-DD, not {text!r}.") from exc


def run(client, args, courses, today):
    cols = colours()
    start = day_range(args.start) if args.start else today.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=args.span)
    rows = fetch(client, courses, start, end, "event")
    if args.due:
        rows += fetch(client, courses, start, end, "assignment")
    items = sorted((record(e, c) for e, c in rows), key=lambda r: (r["start_at"] or end, r["title"]))
    if args.json:
        emit(items)
        return
    if not items:
        print(f"No events from {start:%d %b} to {end:%d %b}." + ("" if args.due else " --due adds assignment deadlines."))
        return
    width = max(len(i["course"] or "") for i in items)
    day = None
    for item in items:
        when = item["start_at"]
        if when and when.date() != day:
            day = when.date()
            print(f"\n{cols['bold']}{when:%a %d %b}{cols['off']}")
        if item["all_day"] or not when:
            span = "all day"
        elif item["type"] == "assignment":
            span = f"due {when:%H:%M}"
        else:
            span = f"{when:%H:%M}" + (f"–{item['end_at']:%H:%M}" if item["end_at"] and item["end_at"] != when else "")
        place = f"  {cols['dim']}@ {item['location']}{cols['off']}" if item["location"] else ""
        colour = cols["yellow"] if item["type"] == "assignment" else ""
        print(f"  {cols['dim']}{span:<12}{cols['off']}{item['course'] or '':<{width}}  {colour}{item['title']}"
              f"{cols['off']}{place}")
    print(f"\n{cols['dim']}{len(items)} items, {start:%d %b} to {end:%d %b}"
          f"{'' if args.due else ' · --due to add assignment deadlines'}{cols['off']}")


def add_args(parser):
    parser.add_argument("--days", dest="span", type=int, default=14, metavar="N",
                        help="how many days to show (default: 14)")
    parser.add_argument("--from", dest="start", metavar="YYYY-MM-DD", help="start date (default: today)")
    parser.add_argument("--due", action="store_true", help="include assignment due dates")

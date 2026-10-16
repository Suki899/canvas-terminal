"""Course announcements."""

from datetime import datetime, timezone

from .courses import label
from .util import colours, html_to_text, parse_time, relative, wrap

OLDEST = datetime.min.replace(tzinfo=timezone.utc)


def fetch(client, courses):
    """Every announcement across the courses, newest first."""
    items = []
    for course in courses:
        path = f"/api/v1/courses/{course['id']}/discussion_topics?only_announcements=true"
        for item in client.optional_listing(path):
            items.append((course, item, parse_time(item.get("posted_at") or item.get("created_at"))))
    items.sort(key=lambda i: i[2] or OLDEST, reverse=True)
    return items


def unread(item):
    return item.get("read_state") == "unread"


def gist(body, width=96):
    """First substantial line, which skips "Hi everyone," style openers."""
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    pick = next((line for line in lines if len(line) > 30), lines[0] if lines else "")
    return pick[:width] + ("…" if len(pick) > width else "")


def run(client, args, courses, today):
    cols = colours()
    items = fetch(client, courses)
    shown = 0
    for course, item, posted in items:
        if args.unread and not unread(item):
            continue
        if not args.unread and posted and (today - posted).days > args.days:
            continue
        shown += 1
        mark = f"{cols['cyan']}●{cols['off']}" if unread(item) else " "
        when = posted.strftime("%a %d %b %H:%M") if posted else "undated"
        print(f"\n{mark} {cols['bold']}{label(course)}{cols['off']}  "
              f"{cols['dim']}{when} · {relative(posted, today)}{cols['off']}")
        print(f"  {(item.get('title') or '').strip()}")
        body = html_to_text(item.get("message"))
        if body and args.full:
            print()
            print(wrap(body))
        elif body:
            print(f"  {cols['dim']}{gist(body)}{cols['off']}")

    if not shown:
        print("Nothing unread." if args.unread else f"Nothing in the last {args.days} days.")
    count = sum(1 for _, item, _ in items if unread(item))
    print(f"\n{cols['dim']}{shown} shown, {count} unread, {len(items)} total"
          f"{'' if args.full else ' · --full for whole messages'}{cols['off']}")


def add_args(parser):
    parser.add_argument("--days", type=int, default=14, metavar="N",
                        help="how far back to look (default: 14)")
    parser.add_argument("--unread", action="store_true", help="only unread, any age")
    parser.add_argument("--full", action="store_true", help="print whole messages")

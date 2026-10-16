"""Course discussions (not announcements), read-only.

The topic list and the /view endpoint leave read state alone, so reading a
thread here does not clear its unread markers in Canvas.
"""

from .api import UnavailableError
from .courses import label, ref
from .util import colours, emit, html_to_text, parse_time, plural, relative, wrap


def fetch(client, course, match):
    topics = client.optional_listing(f"/api/v1/courses/{course['id']}/discussion_topics")
    if match:
        needle = match.casefold()
        topics = [t for t in topics if needle in (t.get("title") or "").casefold() or match == str(t.get("id"))]
    return topics


def thread(client, course, topic):
    """Entries as a nested list, or None when the course requires a post first."""
    try:
        view = client.one(f"/api/v1/courses/{course['id']}/discussion_topics/{topic['id']}/view")
    except UnavailableError:
        return None
    names = {p.get("id"): p.get("display_name") for p in view.get("participants") or []}
    unread = set(view.get("unread_entries") or [])

    def entry(e):
        return {"id": e.get("id"), "author": names.get(e.get("user_id")),
                "created_at": parse_time(e.get("created_at")), "unread": e.get("id") in unread,
                "deleted": bool(e.get("deleted")), "message": html_to_text(e.get("message")),
                "replies": [entry(r) for r in e.get("replies") or []]}

    return [entry(e) for e in view.get("view") or []]


def record(course, topic, entries=None):
    author = topic.get("author") or {}
    out = {"id": topic.get("id"), "title": (topic.get("title") or "").strip(), "course": ref(course),
           "author": author.get("display_name"), "posted_at": parse_time(topic.get("posted_at")),
           "last_reply_at": parse_time(topic.get("last_reply_at")),
           "replies": topic.get("discussion_subentry_count"), "unread_replies": topic.get("unread_count"),
           "unread": topic.get("read_state") == "unread", "locked": bool(topic.get("locked")),
           "must_post_first": bool(topic.get("require_initial_post")),
           "message": html_to_text(topic.get("message")), "url": topic.get("html_url")}
    if entries is not False:
        out["entries"] = entries
    return out


def show_entries(entries, cols, depth=1):
    for e in entries:
        indent = "  " * (depth + 1)
        mark = f"{cols['cyan']}●{cols['off']} " if e["unread"] else ""
        when = e["created_at"].strftime("%d %b %H:%M") if e["created_at"] else ""
        print(f"\n{indent}{mark}{cols['bold']}{e['author'] or '?'}{cols['off']} {cols['dim']}{when}{cols['off']}")
        print(wrap("(deleted)" if e["deleted"] else e["message"], indent=indent + "  "))
        show_entries(e["replies"], cols, depth + 1)


def run(client, args, courses, today):
    cols = colours()
    found = []
    for course in courses:
        for topic in fetch(client, course, args.match):
            if args.unread and not (topic.get("unread_count") or topic.get("read_state") == "unread"):
                continue
            found.append((course, topic))
    show_all = args.full or (args.match and len(found) == 1)
    records = [record(c, t, thread(client, c, t) if show_all else False) for c, t in found]
    if args.json:
        emit(records)
        return
    if not records:
        print("No discussions found." + (" Try a different match." if args.match else ""))
        return
    current = None
    for course, item in zip((c for c, _ in found), records):
        if course is not current:
            print(f"\n{cols['bold']}{label(course)}{cols['off']}")
            current = course
        latest = item["last_reply_at"] or item["posted_at"]
        unread = f"  {cols['cyan']}{item['unread_replies']} unread{cols['off']}" if item["unread_replies"] else ""
        print(f"  {item['title']}  {cols['dim']}{plural(item['replies'] or 0, 'reply', 'replies')} · "
              f"{relative(latest, today)}{cols['off']}{unread}")
        if show_all:
            if item["message"]:
                print(wrap(item["message"]))
            if item["entries"] is None:
                print(f"    {cols['yellow']}Post a reply in Canvas first to see the others.{cols['off']}")
            else:
                show_entries(item["entries"], cols)
    print(f"\n{cols['dim']}{plural(len(records), 'discussion')} · reading here never marks them read"
          f"{'' if show_all else ' · name one, or --full, to read'}{cols['off']}")


def add_args(parser):
    parser.add_argument("match", nargs="?", help="only discussions whose title contains this, or an id")
    parser.add_argument("--unread", action="store_true", help="only ones with unread posts")
    parser.add_argument("--full", action="store_true", help="print whole threads")

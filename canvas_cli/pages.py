"""Course Pages (wiki pages)."""

from urllib.parse import quote

from .api import UnavailableError
from .courses import label, ref
from .util import colours, emit, html_to_text, parse_time, relative, wrap


def body(client, course, page):
    try:
        full = client.one(f"/api/v1/courses/{course['id']}/pages/{quote(page['url'], safe='')}")
    except UnavailableError:
        return ""
    return html_to_text(full.get("body"))


def listed(client, course, match):
    pages = client.optional_listing(f"/api/v1/courses/{course['id']}/pages")
    if match:
        needle = match.casefold()
        pages = [p for p in pages if needle in (p.get("title") or "").casefold()]
    return pages


def run(client, args, courses, today):
    cols = colours()
    if args.json:
        out = []
        for course in courses:
            for page in listed(client, course, args.match):
                out.append({"title": (page.get("title") or "").strip(), "slug": page.get("url"),
                            "course": ref(course), "updated_at": parse_time(page.get("updated_at")),
                            "url": page.get("html_url"),
                            "body": body(client, course, page) if args.full and page.get("url") else None})
        emit(out)
        return
    shown = 0
    for course in courses:
        pages = listed(client, course, args.match)
        if not pages:
            continue
        print(f"\n{cols['bold']}{label(course)}{cols['off']}")
        for page in pages:
            shown += 1
            updated = parse_time(page.get("updated_at"))
            when = updated.strftime("%d %b %Y") if updated else "undated"
            print(f"  {cols['dim']}{when:<12}{relative(updated, today):<10}{cols['off']} "
                  f"{(page.get('title') or '').strip()}")
            if args.full and page.get("url"):
                text = body(client, course, page)
                if text:
                    print(f"\n{wrap(text)}\n")

    if not shown:
        print("No pages found." + (" Try a different match." if args.match else ""))
        return
    print(f"\n{cols['dim']}{shown} page{'s' if shown != 1 else ''}"
          f"{'' if args.full else ' · --full to read them'}{cols['off']}")


def add_args(parser):
    parser.add_argument("match", nargs="?", help="only pages whose title contains this")
    parser.add_argument("--full", action="store_true", help="print page contents")

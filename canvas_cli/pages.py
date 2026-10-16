"""Course Pages (wiki pages)."""

from urllib.parse import quote

from .api import UnavailableError
from .courses import label
from .util import colours, html_to_text, parse_time, relative, wrap


def run(client, args, courses, today):
    cols = colours()
    shown = 0
    for course in courses:
        pages = client.optional_listing(f"/api/v1/courses/{course['id']}/pages")
        if args.match:
            needle = args.match.casefold()
            pages = [p for p in pages if needle in (p.get("title") or "").casefold()]
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
                try:
                    full = client.one(f"/api/v1/courses/{course['id']}/pages/{quote(page['url'], safe='')}")
                except UnavailableError:
                    continue
                body = html_to_text(full.get("body"))
                if body:
                    print(f"\n{wrap(body)}\n")

    if not shown:
        print("No pages found." + (" Try a different match." if args.match else ""))
        return
    print(f"\n{cols['dim']}{shown} page{'s' if shown != 1 else ''}"
          f"{'' if args.full else ' · --full to read them'}{cols['off']}")


def add_args(parser):
    parser.add_argument("match", nargs="?", help="only pages whose title contains this")
    parser.add_argument("--full", action="store_true", help="print page contents")

"""canvas: your Canvas courses from the terminal.

Run `canvas` on its own for what needs attention now.
"""

import argparse
import os
from pathlib import Path
import signal
import sys
import threading

from . import __version__, announcements, assignments, config, courses, mirror, pages, quizzes, submit
from .api import AuthenticationError, CanvasError
from .storage import folder_lock
from .util import colours, now, relative


def overview(client, args, picked, today):
    cols = colours()
    buckets = assignments.bucket(assignments.fetch(client, picked), today)
    soon, later = assignments.split_soon(buckets["todo"], today, args.days)
    print(f"{cols['bold']}Canvas{cols['off']} {cols['dim']}· {len(picked)} "
          f"course{'s' if len(picked) != 1 else ''}{cols['off']}")
    assignments.render("OVERDUE", buckets["overdue"], today, cols, cols["red"])
    assignments.render(f"DUE IN THE NEXT {args.days} DAYS", soon, today, cols, cols["yellow"])

    news = announcements.fetch(client, picked)
    # Old unread posts in long-dead orientation courses are noise here.
    unread = [n for n in news if announcements.unread(n[1]) and n[2] and (today - n[2]).days <= 30]
    if unread:
        print(f"\n{cols['bold']}{cols['cyan']}UNREAD ANNOUNCEMENTS{cols['off']}")
        width = max(len(courses.label(c)) for c, _, _ in unread[:8])
        for course, item, posted in unread[:8]:
            when = posted.strftime("%d %b") if posted else "undated"
            print(f"  {courses.label(course):<{width}}  {cols['dim']}{when:<7}"
                  f"{relative(posted, today):<10}{cols['off']} {(item.get('title') or '').strip()}")
        if len(unread) > 8:
            print(f"  {cols['dim']}… and {len(unread) - 8} more (canvas news --unread){cols['off']}")

    print(f"\n{cols['dim']}{len(buckets['overdue'])} overdue, {len(soon)} due soon, {len(later)} later · "
          f"{len(unread)} unread announcements this month{cols['off']}")
    print(f"{cols['dim']}canvas todo · news · pages · quizzes · sync · submit · --help{cols['off']}")


def list_courses(client, args, picked, today):
    cols = colours()
    width = max(len(courses.label(c)) for c in picked)
    for course in picked:
        term = (course.get("term") or {}).get("name") or ""
        ended = courses.ended(course, today)
        print(f"{course['id']:>8}  {cols['bold']}{courses.label(course):<{width}}{cols['off']}  "
              f"{course.get('name', '')}" + (f"  {cols['dim']}[{term}]{cols['off']}" if term else "")
              + (f"  {cols['dim']}(ended){cols['off']}" if ended else ""))


def sync(client, args, picked, today):
    root = args.folder.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    user = config.whoami(client)
    identity = {"url": client.url, "user_id": str(user["id"])}
    stopped = threading.Event()
    previous = {}
    with folder_lock(root):
        engine = mirror.Mirror(root, identity, report=lambda line: print(line, flush=True))
        engine.save()
        print(f"Mirroring {len(picked)} course{'s' if len(picked) != 1 else ''} to {root}", flush=True)
        if not args.watch:
            counts = engine.run(client, picked)
            return 1 if counts["errors"] or counts["protected"] else 0
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, lambda *_: stopped.set())
        try:
            while not stopped.is_set():
                try:
                    engine.run(client, picked)
                except AuthenticationError:
                    raise
                except (CanvasError, OSError) as exc:
                    print(f"Sync failed: {exc}", file=sys.stderr, flush=True)
                print(f"Next sync in {args.watch}s. Ctrl+C to stop.", flush=True)
                stopped.wait(args.watch)
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
    return 0


def interval(value):
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a whole number of seconds") from exc
    if number < 60:
        raise argparse.ArgumentTypeError("must be at least 60 seconds")
    return number


def course_flags():
    """The course filters, as a fresh parent parser for each (sub)parser.

    argparse shares action objects between parsers built from one parent, and
    set_defaults on the top parser rewrites those shared defaults, so each
    parser needs its own copy. SUPPRESS keeps a subcommand from resetting a
    flag given before its name (`canvas --course X todo`).
    """
    flags = argparse.ArgumentParser(add_help=False)
    flags.add_argument("--course", action="append", metavar="CODE", default=argparse.SUPPRESS,
                       help="only this course: id, or part of its code or name (repeatable)")
    flags.add_argument("--term", metavar="NAME", default=argparse.SUPPRESS,
                       help="only courses whose term name contains this (default: $CANVAS_TERM)")
    flags.add_argument("--all-courses", action="store_true", default=argparse.SUPPRESS,
                       help="include courses that have ended")
    return flags


def build_parser():
    parser = argparse.ArgumentParser(prog="canvas", description=__doc__, parents=[course_flags()],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--days", type=int, default=argparse.SUPPRESS, metavar="N",
                        help="how far ahead counts as due soon (default: 7)")
    parser.set_defaults(handler=overview, course=None, term=os.environ.get("CANVAS_TERM") or None, all_courses=False, days=7)
    subs = parser.add_subparsers(dest="command", metavar="<command>")

    p = subs.add_parser("login", help="save your Canvas URL and access token")
    p.add_argument("url", nargs="?", help="Canvas site, e.g. canvas.example.edu")
    p.set_defaults(handler=None)
    subs.add_parser("logout", help="forget the saved token").set_defaults(handler=None)
    subs.add_parser("whoami", help="show who the token belongs to").set_defaults(handler=None)

    p = subs.add_parser("courses", parents=[course_flags()], help="list your courses")
    p.set_defaults(handler=list_courses)

    p = subs.add_parser("todo", parents=[course_flags()], help="assignments: overdue, due, done")
    assignments.add_args(p)
    p.set_defaults(handler=assignments.run)

    p = subs.add_parser("news", parents=[course_flags()], help="announcements")
    announcements.add_args(p)
    p.set_defaults(handler=announcements.run)

    p = subs.add_parser("pages", parents=[course_flags()], help="course Pages")
    pages.add_args(p)
    p.set_defaults(handler=pages.run)

    p = subs.add_parser("quizzes", aliases=["quiz"], parents=[course_flags()], help="quizzes and past attempts")
    quizzes.add_args(p)
    p.set_defaults(handler=quizzes.run)

    p = subs.add_parser("submit", parents=[course_flags()], help="hand files in to an assignment")
    submit.add_args(p)
    p.set_defaults(handler=submit.run, one_course=True)

    p = subs.add_parser("sync", parents=[course_flags()], help="mirror course Files into a folder")
    p.add_argument("folder", type=Path, help="destination folder (created if needed)")
    p.add_argument("--watch", type=interval, metavar="SECONDS",
                   help="keep running, syncing every SECONDS (minimum 60)")
    p.set_defaults(handler=sync)
    return parser


def account(command, args):
    if command == "login":
        user = config.login(args.url)
        print(f"Signed in as {user.get('name') or user['id']}. Saved to {config.config_path()}")
    elif command == "logout":
        print("Signed out." if config.logout() else "Was not signed in.")
    else:
        with config.client() as client:
            user = config.whoami(client)
        print(f"{user.get('name') or '?'} ({user.get('primary_email') or user.get('login_id') or user['id']}) "
              f"on {client.url}")
    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.handler is None:
            return account(args.command, args)
        today = now()
        with config.client() as client:
            if getattr(args, "one_course", False):
                picked = courses.one(client, args, today)
            else:
                picked = courses.fetch(client, args, today)
            status = args.handler(client, args, picked, today) or 0
        # Flush here so a closed pipe is caught below, not at interpreter exit.
        sys.stdout.flush()
        return status
    except AuthenticationError as exc:
        print(f"canvas: {exc}", file=sys.stderr)
        return 3
    except (CanvasError, OSError) as exc:
        print(f"canvas: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        # `canvas news | head` is normal; silence the flush at exit.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0

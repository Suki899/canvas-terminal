"""Assignments: overdue, due soon, later, done, missed."""

import argparse
from datetime import datetime, timezone

from .courses import label
from .util import colours, parse_time, relative, score, stamp

# Gradebook placeholders that cannot be handed in through Canvas.
UNSUBMITTABLE = {"none", "on_paper", "not_graded", "wiki_page", "external_tool"}
BUCKETS = ("overdue", "todo", "done", "missed", "undated", "untracked")
LAST = datetime.max.replace(tzinfo=timezone.utc)


def classify(assignment, today):
    """(bucket, due) for one assignment that carries its own submission."""
    submission = assignment.get("submission") or {}
    due = parse_time(assignment.get("due_at"))
    # Trust a hand-in or an excusal, not workflow_state: some courses pre-fill
    # a 0 before the due date, which makes "graded" mean "untouched".
    if submission.get("excused") or submission.get("submitted_at"):
        return "done", due
    # A real mark with no Canvas hand-in was handed in some other way.
    if submission.get("workflow_state") == "graded" and (submission.get("score") or 0) > 0:
        return "done", due
    types = set(assignment.get("submission_types") or [])
    # New Quizzes are external_tool assignments, but they are real work.
    if types <= UNSUBMITTABLE and not assignment.get("is_quiz_lti_assignment"):
        return "untracked", due
    if due is None:
        return "undated", None
    if due >= today:
        return "todo", due
    # Past the lock date nothing can be handed in; that is not a to-do.
    closed = parse_time(assignment.get("lock_at"))
    return ("missed" if closed and closed < today else "overdue"), due


def fetch(client, courses):
    rows = []
    for course in courses:
        path = f"/api/v1/courses/{course['id']}/assignments?include[]=submission"
        for assignment in client.optional_listing(path):
            rows.append((course, assignment))
    return rows


def bucket(rows, today):
    buckets = {name: [] for name in BUCKETS}
    for course, assignment in rows:
        name, due = classify(assignment, today)
        buckets[name].append((course, assignment, due))
    for items in buckets.values():
        items.sort(key=lambda r: (r[2] or LAST, label(r[0]), r[1].get("name") or ""))
    return buckets


def split_soon(todo, today, days):
    soon = [r for r in todo if (r[2].date() - today.date()).days <= days]
    return soon, todo[len(soon):]


def note(assignment, today, cols):
    notes = []
    submission = assignment.get("submission") or {}
    if submission.get("workflow_state") == "graded" and not submission.get("submitted_at"):
        shown = score(submission.get("score"), assignment.get("points_possible"))
        if shown:
            notes.append(f"gradebook shows {shown}")
    if assignment.get("locked_for_user"):
        opens = parse_time(assignment.get("unlock_at"))
        notes.append(f"opens {stamp(opens)}" if opens and opens > today else "locked")
    return f"  {cols['dim']}({'; '.join(notes)}){cols['off']}" if notes else ""


def render(title, rows, today, cols, colour=""):
    if not rows:
        return
    print(f"\n{cols['bold']}{colour}{title}{cols['off']}")
    width = max(len(label(c)) for c, _, _ in rows)
    for course, assignment, due in rows:
        print(f"  {label(course):<{width}}  {stamp(due):<18} "
              f"{cols['dim']}{relative(due, today):<10}{cols['off']} "
              f"{(assignment.get('name') or '').strip()}" + note(assignment, today, cols))


def run(client, args, courses, today):
    cols = colours()
    buckets = bucket(fetch(client, courses), today)
    soon, later = split_soon(buckets["todo"], today, args.days)

    render("OVERDUE", buckets["overdue"], today, cols, cols["red"])
    render(f"DUE IN THE NEXT {args.days} DAYS", soon, today, cols, cols["yellow"])
    render("LATER", later, today, cols)
    if args.done:
        render("DONE", buckets["done"], today, cols, cols["green"])
    if args.all:
        render("MISSED (CLOSED)", buckets["missed"], today, cols)
        render("NO DUE DATE", buckets["undated"], today, cols)
        render("NOT SUBMITTED THROUGH CANVAS", buckets["untracked"], today, cols)

    parts = [f"{len(buckets['overdue'])} overdue", f"{len(soon)} due soon",
             f"{len(later)} later", f"{len(buckets['done'])} done"]
    hidden = len(buckets["missed"]) + len(buckets["undated"]) + len(buckets["untracked"])
    if hidden and not args.all:
        parts.append(f"{hidden} hidden (--all)")
    print(f"\n{cols['dim']}{', '.join(parts)}{cols['off']}")


def add_args(parser):
    # SUPPRESS: the top-level parser owns the default, so `canvas --days 3 todo` holds.
    parser.add_argument("--days", type=int, default=argparse.SUPPRESS, metavar="N",
                        help="how far ahead counts as due soon (default: 7)")
    parser.add_argument("--done", action="store_true", help="also list handed-in work")
    parser.add_argument("--all", action="store_true",
                        help="also list missed, undated and gradebook-only entries")

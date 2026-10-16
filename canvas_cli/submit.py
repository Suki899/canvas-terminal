"""Hand files in to an assignment. The only command that writes to Canvas.

A Canvas file submission is three requests:
1. ask Canvas for an upload slot;
2. POST the bytes to the storage host it names (no token: it is not Canvas);
3. tell Canvas the uploaded file ids are the submission.
"""

from datetime import datetime
import mimetypes
import os
from urllib.parse import urljoin

from .api import CanvasError, REDIRECTS
from .courses import label, ref
from .util import colours, emit, parse_time, relative, stamp

UPLOAD = "online_upload"


def resolve(client, course, wanted):
    """One assignment by id or by an unambiguous name fragment."""
    assignments = client.optional_listing(
        f"/api/v1/courses/{course['id']}/assignments?include[]=submission")
    if wanted.isdigit():
        for assignment in assignments:
            if str(assignment.get("id")) == wanted:
                return assignment
        raise CanvasError(f"No assignment with id {wanted} in {label(course)}.")
    needle = wanted.casefold()
    hits = [a for a in assignments if needle in (a.get("name") or "").casefold()]
    exact = [a for a in hits if (a.get("name") or "").strip().casefold() == needle]
    hits = exact or hits
    if not hits:
        names = "\n  ".join(sorted(a.get("name") or "" for a in assignments)) or "(none visible)"
        raise CanvasError(f"Nothing in {label(course)} matches {wanted!r}. Assignments:\n  {names}")
    if len(hits) > 1:
        names = "\n  ".join(f"{a['id']}  {a.get('name') or ''}" for a in hits)
        raise CanvasError(f"{wanted!r} matches {len(hits)} assignments:\n  {names}\nPass the id instead.")
    return hits[0]


def problems(assignment, paths):
    """Every reason Canvas would refuse, found before anything is uploaded."""
    found = []
    types = set(assignment.get("submission_types") or [])
    if UPLOAD not in types:
        found.append(f"does not take file uploads (accepts: {', '.join(sorted(types)) or 'nothing'})")
    if assignment.get("locked_for_user"):
        found.append(f"is locked: {assignment.get('lock_explanation') or 'no reason given'}")
    allowed = [e.lower().lstrip(".") for e in assignment.get("allowed_extensions") or []]
    for path in paths:
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        if allowed and ext not in allowed:
            found.append(f"only accepts .{', .'.join(allowed)} ({os.path.basename(path)} is .{ext or '?'})")
        if os.path.getsize(path) == 0:
            found.append(f"{os.path.basename(path)} is empty")
    return found


def describe(assignment, course, paths, today, cols):
    """Show exactly what will be handed in, including each file's full path."""
    print(f"\n  {cols['bold']}{(assignment.get('name') or '').strip()}{cols['off']}")
    print(f"  {cols['dim']}course{cols['off']}  {label(course)}")
    for path in paths:
        st = os.stat(path)
        modified = datetime.fromtimestamp(st.st_mtime).strftime("%d %b %H:%M")
        print(f"  {cols['dim']}file{cols['off']}    {path}  "
              f"{cols['dim']}({st.st_size / 1024:.1f} KiB, modified {modified}){cols['off']}")
    due = parse_time(assignment.get("due_at"))
    late = due is not None and due < today
    print(f"  {cols['dim']}due{cols['off']}     {cols['red'] if late else ''}{stamp(due)}{cols['off']}"
          + (f" {cols['dim']}({relative(due, today)}){cols['off']}" if due else ""))
    if late:
        print(f"  {cols['red']}This will be recorded as late.{cols['off']}")
    submission = assignment.get("submission") or {}
    if submission.get("submitted_at"):
        when = parse_time(submission["submitted_at"])
        print(f"  {cols['yellow']}Already submitted {stamp(when)}; this becomes attempt "
              f"{(submission.get('attempt') or 0) + 1}.{cols['off']}")


def json_of(response):
    try:
        with response:
            return response.json()
    except ValueError as exc:
        raise CanvasError("Canvas returned an invalid upload response.") from exc


def upload(client, course, assignment, path):
    """Steps 1 and 2 for one file. Returns the Canvas file id."""
    base = f"/api/v1/courses/{course['id']}/assignments/{assignment['id']}/submissions/self/files"
    slot = json_of(client.post(base, data={
        "name": os.path.basename(path),
        "size": os.path.getsize(path),
        "content_type": mimetypes.guess_type(path)[0] or "application/octet-stream",
    }))
    if not isinstance(slot, dict) or not slot.get("upload_url"):
        raise CanvasError("Canvas did not offer an upload slot.")

    with open(path, "rb") as stream:
        response = client.post(slot["upload_url"], data=slot.get("upload_params") or {},
                               files={"file": (os.path.basename(path), stream)})
    location = response.headers.get("Location")
    if response.status_code in REDIRECTS:
        response.close()
        body = {}
    else:
        body = json_of(response)
    if not (isinstance(body, dict) and "id" in body) and location:
        # S3-style storage: confirm by following Location. That URL is on the
        # Canvas site, so client.get attaches the token there and only there.
        body = json_of(client.get(urljoin(slot["upload_url"], location), download=True))
    if not isinstance(body, dict) or "id" not in body:
        raise CanvasError(f"Upload of {os.path.basename(path)} did not return a file id.")
    return body["id"]


def confirm(question):
    try:
        return input(question).strip().lower() in ("y", "yes")
    except EOFError:
        raise CanvasError("No terminal to confirm on; pass --yes to submit non-interactively.")


def run(client, args, course, today):
    cols = colours()
    paths = [os.path.abspath(os.path.expanduser(p)) for p in args.files]
    for path in paths:
        if not os.path.isfile(path):
            raise CanvasError(f"No such file: {path}")
    assignment = resolve(client, course, args.assignment)
    found = problems(assignment, paths)
    if found:
        raise CanvasError("Cannot submit. This assignment:\n  - " + "\n  - ".join(found))

    due = parse_time(assignment.get("due_at"))
    plan = {"assignment": {"id": assignment.get("id"), "name": (assignment.get("name") or "").strip(),
                           "due_at": due, "url": assignment.get("html_url")},
            "course": ref(course), "files": [{"path": p, "size": os.path.getsize(p)} for p in paths],
            "late": due is not None and due < today,
            "resubmission": bool((assignment.get("submission") or {}).get("submitted_at"))}
    if args.json and not (args.dry_run or args.yes):
        raise CanvasError("--json cannot ask for confirmation; add --dry-run to check, or --yes to submit.")
    if not args.json:
        describe(assignment, course, paths, today, cols)
    if args.dry_run:
        if args.json:
            emit({**plan, "submitted": False})
        else:
            print(f"\n{cols['dim']}--dry-run: nothing uploaded.{cols['off']}")
        return
    if not args.yes and not confirm("\nSubmit this? [y/N] "):
        print("Not submitted.")
        return

    ids = [upload(client, course, assignment, path) for path in paths]
    result = json_of(client.post(
        f"/api/v1/courses/{course['id']}/assignments/{assignment['id']}/submissions",
        data=[("submission[submission_type]", UPLOAD)]
        + [("submission[file_ids][]", str(i)) for i in ids]))
    when = parse_time(result.get("submitted_at")) or today
    if args.json:
        emit({**plan, "submitted": True, "submitted_at": when, "attempt": result.get("attempt"),
              "marked_late": bool(result.get("late"))})
        return
    print(f"\n{cols['green']}Submitted{cols['off']} {stamp(when)} "
          f"{cols['dim']}(attempt {result.get('attempt') or 1}){cols['off']}")
    if result.get("late"):
        print(f"{cols['red']}Canvas marked it late.{cols['off']}")


def add_args(parser):
    parser.add_argument("assignment", help="assignment id, or part of its name")
    parser.add_argument("files", nargs="+", metavar="FILE", help="file(s) to hand in")
    parser.add_argument("--dry-run", action="store_true", help="check everything, upload nothing")
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")

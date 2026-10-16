"""Course syllabus pages."""

from .courses import label, ref
from .util import colours, emit, html_to_text, wrap


def fetch(client, course):
    full = client.one(f"/api/v1/courses/{course['id']}?include[]=syllabus_body")
    return {"course": ref(course), "text": html_to_text((full or {}).get("syllabus_body"))}


def run(client, args, courses, today):
    cols = colours()
    found = [fetch(client, c) for c in courses]
    if args.json:
        emit(found)
        return
    found = [s for s in found if s["text"]]
    if not found:
        print("No syllabus has been posted.")
        return
    if len(found) > 1 and not args.full:
        width = max(len(s["course"]["code"] or "") for s in found)
        for s in found:
            words = f"{len(s['text'].split())} words"
            print(f"  {s['course']['code'] or '':<{width}}  {cols['dim']}{words:<12}{cols['off']}{s['course']['name'] or ''}")
        print(f"\n{cols['dim']}--course CODE to read one, or --full for all{cols['off']}")
        return
    for s in found:
        print(f"\n{cols['bold']}{s['course']['code']}{cols['off']}  {cols['dim']}{s['course']['name']}{cols['off']}\n")
        print(wrap(s["text"]))


def add_args(parser):
    parser.add_argument("--full", action="store_true", help="print every course's syllabus")

"""Which courses a command looks at."""

from .api import CanvasError
from .util import parse_time


def label(course):
    return course.get("course_code") or course.get("name") or str(course.get("id"))


def ended(course, today):
    """Past courses stay "active" on many Canvas sites; use the dates instead."""
    if course.get("restrict_enrollments_to_course_dates") and course.get("end_at"):
        end = parse_time(course["end_at"])
    else:
        end = parse_time((course.get("term") or {}).get("end_at"))
    return end is not None and end < today


def matches(course, wanted):
    haystack = [str(course.get("id")), (course.get("course_code") or "").casefold(),
                (course.get("name") or "").casefold()]
    return any(w == haystack[0] or w.casefold() in haystack[1] or w.casefold() in haystack[2]
               for w in wanted)


def select(courses, today, *, wanted=None, term=None, include_past=False):
    picked = []
    for course in courses:
        if course.get("access_restricted_by_date") or "name" not in course:
            continue
        if term and term.casefold() not in ((course.get("term") or {}).get("name") or "").casefold():
            continue
        if wanted and not matches(course, wanted):
            continue
        # Naming a course, or a term, is explicit enough to reach past ones.
        if not include_past and not wanted and not term and ended(course, today):
            continue
        picked.append(course)
    return sorted(picked, key=label)


def fetch(client, args, today):
    courses = client.listing("/api/v1/courses?include[]=term&enrollment_state=active")
    picked = select(courses, today, wanted=args.course, term=args.term,
                    include_past=args.all_courses)
    if not picked:
        hint = " Check --course/--term, or try --all-courses." if (args.course or args.term) else \
            " Try --all-courses to include ones that have ended."
        raise CanvasError("No courses matched." + hint)
    return picked


def one(client, args, today):
    picked = fetch(client, args, today)
    if len(picked) > 1:
        names = ", ".join(label(c) for c in picked)
        raise CanvasError(f"{len(picked)} courses matched ({names}). Pick one with --course.")
    return picked[0]

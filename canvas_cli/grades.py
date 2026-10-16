"""Grades: course totals where the course shows them, and every scored item."""

from .api import UnavailableError
from .courses import label, ref
from .util import colours, emit, parse_time, score, stamp


def totals(client, course):
    """The student enrolment's grades; every field is None when the course hides them."""
    try:
        enrolments = client.listing(f"/api/v1/courses/{course['id']}/enrollments"
                                    "?user_id=self&type[]=StudentEnrollment")
    except UnavailableError:
        return {}
    grades = (enrolments[0].get("grades") if enrolments else None) or {}
    return {key: grades.get(key) for key in ("current_score", "current_grade", "final_score", "final_grade")}


def assignment_record(assignment):
    sub = assignment.get("submission") or {}
    return {"id": assignment.get("id"), "name": (assignment.get("name") or "").strip(),
            "points_possible": assignment.get("points_possible"), "due_at": parse_time(assignment.get("due_at")),
            "score": sub.get("score"), "grade": sub.get("grade"), "excused": bool(sub.get("excused")),
            "late": bool(sub.get("late")), "missing": bool(sub.get("missing")),
            "submitted_at": parse_time(sub.get("submitted_at")),
            "graded_at": parse_time(sub.get("graded_at")), "url": assignment.get("html_url")}


def fetch(client, course):
    groups = client.optional_listing(f"/api/v1/courses/{course['id']}/assignment_groups"
                                     "?include[]=assignments&include[]=submission")
    return {
        "course": ref(course),
        "weighted": bool(course.get("apply_assignment_group_weights")),
        **totals(client, course),
        "groups": [{"id": g.get("id"), "name": (g.get("name") or "").strip(), "weight": g.get("group_weight"),
                    "assignments": [assignment_record(a) for a in g.get("assignments") or []]}
                   for g in sorted(groups, key=lambda g: g.get("position") or 0)],
    }


def scored(report):
    return [a for g in report["groups"] for a in g["assignments"] if a["score"] is not None and not a["excused"]]


def total_text(report):
    if report.get("current_score") is None:
        return "total hidden"
    grade = f" ({report['current_grade']})" if report.get("current_grade") else ""
    return f"{report['current_score']:g}%{grade}"


def status(item, cols):
    if item["excused"]:
        return "excused"
    shown = score(item["score"], item["points_possible"])
    flags = [f for f, on in (("late", item["late"]), ("missing", item["missing"])) if on]
    text = shown or ("awaiting grade" if item["submitted_at"] else "—")
    return text + (f"  {cols['red']}{', '.join(flags)}{cols['off']}" if flags else "")


def run(client, args, courses, today):
    cols = colours()
    reports = [fetch(client, c) for c in courses]
    if args.json:
        emit(reports)
        return

    if not args.full and len(reports) > 1:
        width = max(len(label(c)) for c in courses)
        for course, report in zip(courses, reports):
            items = scored(report)
            earned = sum(a["score"] for a in items)
            possible = sum(a["points_possible"] or 0 for a in items)
            raw = f"{earned:g}/{possible:g} raw points" if possible else "no raw points"
            print(f"  {label(course):<{width}}  {total_text(report):<14} "
                  f"{cols['dim']}{len(items)} graded · {raw}{cols['off']}")
        print(f"\n{cols['dim']}Raw points ignore group weights. --course or --full for every item.{cols['off']}")
        return

    for course, report in zip(courses, reports):
        print(f"\n{cols['bold']}{label(course)}{cols['off']}  {total_text(report)}")
        for group in report["groups"]:
            if not group["assignments"]:
                continue
            weight = f"  {cols['dim']}{group['weight']:g}%{cols['off']}" if report["weighted"] and group["weight"] else ""
            print(f"  {cols['bold']}{group['name']}{cols['off']}{weight}")
            for item in group["assignments"]:
                due = stamp(item["due_at"], with_time=False) if item["due_at"] else ""
                print(f"    {item['name'][:52]:<52} {status(item, cols):<15} {cols['dim']}{due}{cols['off']}")


def add_args(parser):
    parser.add_argument("--full", action="store_true", help="every item, even across several courses")

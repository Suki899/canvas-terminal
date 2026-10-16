"""Quizzes: what exists, when it closes, how past attempts went. Read-only.

Canvas has two quiz engines. Classic Quizzes are fully readable through
/quizzes. New Quizzes run as an external tool and are invisible there, so
they are listed from the assignments they create; their settings and attempt
history are not readable with a student token.
"""

from .api import UnavailableError
from .courses import label, ref
from .util import colours, emit, html_to_text, parse_time, relative, score, stamp, wrap

KINDS = {"assignment": "graded", "practice_quiz": "practice",
         "survey": "survey", "graded_survey": "survey"}


def fetch(client, course, match):
    classic = client.optional_listing(f"/api/v1/courses/{course['id']}/quizzes")
    assignments = client.optional_listing(
        f"/api/v1/courses/{course['id']}/assignments?include[]=submission")
    new = [a for a in assignments if a.get("is_quiz_lti_assignment")]
    submissions = {a["id"]: a.get("submission") or {} for a in assignments if "id" in a}
    if match:
        needle = match.casefold()
        classic = [q for q in classic if needle in (q.get("title") or "").casefold()
                   or match == str(q.get("id"))]
        new = [a for a in new if needle in (a.get("name") or "").casefold()
               or match == str(a.get("id"))]
    return classic, new, submissions


def settings(quiz):
    parts = []
    if quiz.get("question_count") is not None:
        parts.append(f"{quiz['question_count']} questions")
    if quiz.get("points_possible") is not None:
        parts.append(f"{quiz['points_possible']:g} pts")
    limit = quiz.get("time_limit")
    parts.append(f"{limit} min" if limit else "no time limit")
    attempts = quiz.get("allowed_attempts")
    if attempts == -1:
        parts.append("unlimited attempts")
    elif attempts is not None:
        parts.append(f"{attempts} attempt{'s' if attempts != 1 else ''}")
    if attempts not in (None, 1):
        policy = {"keep_highest": "best score kept", "keep_latest": "last score kept",
                  "keep_average": "average kept"}.get(quiz.get("scoring_policy"))
        if policy:
            parts.append(policy)
    if quiz.get("one_question_at_a_time"):
        parts.append("one question at a time" + (", no going back" if quiz.get("cant_go_back") else ""))
    if quiz.get("require_lockdown_browser"):
        parts.append("requires LockDown Browser")
    if quiz.get("has_access_code"):
        parts.append("access code required")
    return " · ".join(parts)


def status(item, submission, points):
    notes = []
    if submission.get("submitted_at"):
        notes.append(score(submission.get("score"), points) or "submitted")
    if item.get("locked_for_user"):
        notes.append("locked")
    return notes


def dates(item, today, cols):
    for name, key in (("opens", "unlock_at"), ("due", "due_at"), ("closes", "lock_at")):
        when = parse_time(item.get(key))
        if when:
            print(f"  {cols['dim']}{name:<7}{cols['off']}{stamp(when)} "
                  f"{cols['dim']}({relative(when, today)}){cols['off']}")


def fetch_attempts(client, course, quiz):
    try:
        # This list endpoint returns {"quiz_submissions": [...]}, not a bare list.
        payload = client.one(f"/api/v1/courses/{course['id']}/quizzes/{quiz['id']}/submissions")
    except UnavailableError:
        payload = {}
    subs = (payload or {}).get("quiz_submissions") or []
    return sorted(subs, key=lambda s: s.get("attempt") or 0)


SETTINGS = ("question_count", "points_possible", "time_limit", "allowed_attempts", "scoring_policy",
            "one_question_at_a_time", "cant_go_back", "require_lockdown_browser", "has_access_code",
            "shuffle_answers", "show_correct_answers", "show_correct_answers_at", "hide_results")


def record(client, course, item, submission, engine, full):
    """One quiz as JSON; settings and attempts only for Classic, only with --full."""
    title = item.get("title") if engine == "classic" else item.get("name")
    out = {"id": item.get("id"), "title": (title or "").strip(), "engine": engine,
           "kind": KINDS.get(item.get("quiz_type"), "quiz") if engine == "classic" else "graded",
           "course": ref(course), "due_at": parse_time(item.get("due_at")),
           "unlock_at": parse_time(item.get("unlock_at")), "lock_at": parse_time(item.get("lock_at")),
           "points_possible": item.get("points_possible"), "locked": bool(item.get("locked_for_user")),
           "submitted_at": parse_time(submission.get("submitted_at")), "score": submission.get("score"),
           "url": item.get("html_url")}
    if full and engine == "classic":
        out["settings"] = {key: item.get(key) for key in SETTINGS}
        out["description"] = html_to_text(item.get("description"))
        out["attempts"] = [{"attempt": s.get("attempt"), "score": s.get("score"),
                            "points_possible": s.get("quiz_points_possible"),
                            "started_at": parse_time(s.get("started_at")),
                            "finished_at": parse_time(s.get("finished_at")),
                            "time_spent": s.get("time_spent"), "state": s.get("workflow_state"),
                            "attempts_left": s.get("attempts_left")}
                           for s in fetch_attempts(client, course, item)]
    return out


def attempts(client, course, quiz, cols):
    subs = fetch_attempts(client, course, quiz)
    if not subs:
        print(f"  {cols['dim']}no attempts{cols['off']}")
        return
    for sub in subs:
        finished = parse_time(sub.get("finished_at"))
        when = finished.strftime("%d %b %H:%M") if finished else "unfinished"
        shown = score(sub.get("score"), sub.get("quiz_points_possible")) or "not yet scored"
        spent = sub.get("time_spent")
        taken = f"  {cols['dim']}({spent // 60}m {spent % 60}s){cols['off']}" if spent else ""
        print(f"  attempt {sub.get('attempt', '?')}  {cols['dim']}{when:<14}{cols['off']}{shown}{taken}")
    left = subs[-1].get("attempts_left")
    if isinstance(left, int) and left >= 0:
        print(f"  {cols['dim']}{left} attempt{'s' if left != 1 else ''} left{cols['off']}")


def detail(client, course, quiz, today, cols, full):
    print(f"\n  {cols['bold']}{(quiz.get('title') or '').strip()}{cols['off']} "
          f"{cols['dim']}#{quiz['id']} · {KINDS.get(quiz.get('quiz_type'), 'quiz')}{cols['off']}")
    print(f"  {cols['dim']}{settings(quiz)}{cols['off']}")
    dates(quiz, today, cols)
    if quiz.get("locked_for_user") and quiz.get("lock_explanation"):
        print(f"  {cols['yellow']}{html_to_text(quiz['lock_explanation'])}{cols['off']}")
    attempts(client, course, quiz, cols)
    body = html_to_text(quiz.get("description")) if full else ""
    if body:
        print(f"\n{wrap(body)}")
    if quiz.get("html_url"):
        print(f"  {cols['dim']}{quiz['html_url']}{cols['off']}")


def new_detail(assignment, today, cols):
    print(f"\n  {cols['bold']}{(assignment.get('name') or '').strip()}{cols['off']} "
          f"{cols['dim']}#{assignment['id']} · New Quizzes{cols['off']}")
    print(f"  {cols['dim']}settings and attempts are not readable with a student token{cols['off']}")
    dates(assignment, today, cols)
    notes = status(assignment, assignment.get("submission") or {}, assignment.get("points_possible"))
    print(f"  {'; '.join(notes) if notes else 'not attempted'}")
    if assignment.get("html_url"):
        print(f"  {cols['dim']}{assignment['html_url']}{cols['off']}")


def run(client, args, courses, today):
    cols = colours()
    found = []
    for course in courses:
        classic, new, submissions = fetch(client, course, args.match)
        if classic or new:
            found.append((course, classic, new, submissions))
    if args.json:
        emit([record(client, course, q, submissions.get(q.get("assignment_id"), {}), "classic", args.full)
              for course, classic, _, submissions in found for q in classic]
             + [record(client, course, a, a.get("submission") or {}, "new", args.full)
                for course, _, new, _ in found for a in new])
        return
    if not found:
        print("No quizzes found." + (" Try a different match." if args.match else ""))
        return

    total = sum(len(c) + len(n) for _, c, n, _ in found)
    if args.full or total == 1:
        for course, classic, new, _ in found:
            print(f"\n{cols['bold']}{label(course)}{cols['off']}")
            for quiz in classic:
                detail(client, course, quiz, today, cols, args.full)
            for assignment in new:
                new_detail(assignment, today, cols)
        return

    for course, classic, new, submissions in found:
        print(f"\n{cols['bold']}{label(course)}{cols['off']}")
        rows = [(KINDS.get(q.get("quiz_type"), "quiz"), q.get("title"), q,
                 submissions.get(q.get("assignment_id"), {}), q.get("points_possible")) for q in classic]
        rows += [("new", a.get("name"), a, a.get("submission") or {}, a.get("points_possible")) for a in new]
        rows.sort(key=lambda r: (r[2].get("due_at") or "9999", r[1] or ""))
        for kind, title, item, submission, points in rows:
            due = parse_time(item.get("due_at"))
            notes = status(item, submission, points)
            print(f"  {cols['dim']}{kind:<9}{cols['off']}{stamp(due):<18} "
                  f"{cols['dim']}{relative(due, today):<10}{cols['off']} {(title or '').strip()}"
                  + (f"  {cols['dim']}({'; '.join(notes)}){cols['off']}" if notes else ""))
    print(f"\n{cols['dim']}{total} quizzes · name one, or --full, for settings and attempts{cols['off']}")


def add_args(parser):
    parser.add_argument("match", nargs="?", help="only quizzes whose title contains this, or an id")
    parser.add_argument("--full", action="store_true", help="settings, dates, description, attempts")

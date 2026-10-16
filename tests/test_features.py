from datetime import datetime, timezone
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from canvas_cli import cli, discussions, events, grades, inbox, modules
from canvas_cli.api import CanvasError, UnavailableError
from canvas_cli.util import emit

TODAY = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
COURSE = {"id": 1, "course_code": "CS101", "name": "Intro"}


class Fake:
    """Answers by path prefix and records every request."""

    def __init__(self, routes):
        self.routes = routes
        self.paths = []
        self.url = "https://canvas.example"

    def answer(self, path):
        self.paths.append(path)
        for prefix, value in self.routes.items():
            if path.startswith(prefix):
                if isinstance(value, Exception):
                    raise value
                return value
        raise AssertionError(f"unexpected request {path}")

    listing = one = answer

    def optional_listing(self, path):
        try:
            return self.answer(path)
        except UnavailableError:
            return []


def args(**kw):
    base = dict(json=False, full=False, match=None, course=None, term=None, unread=False, scope="inbox")
    base.update(kw)
    return SimpleNamespace(**base)


def capture(fn, *a):
    with patch("sys.stdout", new_callable=io.StringIO) as out:
        fn(*a)
    return out.getvalue()


class ModuleTests(unittest.TestCase):
    def test_large_module_items_are_fetched_separately(self):
        client = Fake({"/api/v1/courses/1/modules?": [{"id": 5, "name": "Week 1"}],
                       "/api/v1/courses/1/modules/5/items": [{"id": 9, "type": "File", "title": "notes.pdf"}]})
        found = modules.fetch(client, COURSE)
        self.assertEqual(found[0]["items"][0]["title"], "notes.pdf")

    def test_untracked_module_does_not_claim_completed(self):
        client = Fake({"/api/v1/courses/1/modules?": [
            {"id": 5, "name": "Week 10", "state": "completed", "items": [{"type": "File", "title": "a"}]},
            {"id": 6, "name": "Week 1", "state": "completed",
             "items": [{"type": "Page", "title": "b", "completion_requirement": {"type": "must_view", "completed": True}}]}]})
        text = capture(modules.run, client, args(), [COURSE], TODAY)
        self.assertIn("Week 10  (1 item)", text)
        self.assertIn("Week 1  (1 item, completed)", text)


class GradeTests(unittest.TestCase):
    def test_hidden_totals_and_scored_items(self):
        client = Fake({
            "/api/v1/courses/1/assignment_groups": [{"name": "Quizzes", "group_weight": 40, "assignments": [
                {"id": 1, "name": "Q1", "points_possible": 10, "submission": {"score": 8}},
                {"id": 2, "name": "Q2", "points_possible": 10, "submission": {"score": 10, "excused": True}},
                {"id": 3, "name": "Q3", "points_possible": 10, "submission": {}}]}],
            "/api/v1/courses/1/enrollments": [{"grades": {"current_score": None}}]})
        report = grades.fetch(client, COURSE)
        self.assertEqual(grades.total_text(report), "total hidden")
        self.assertEqual([a["name"] for a in grades.scored(report)], ["Q1"])

    def test_visible_total(self):
        self.assertEqual(grades.total_text({"current_score": 91.5, "current_grade": "A"}), "91.5% (A)")


class InboxTests(unittest.TestCase):
    def test_opening_a_thread_never_marks_it_read(self):
        client = Fake({"/api/v1/conversations?": [{"id": 7, "subject": "Hi", "workflow_state": "unread"}],
                       "/api/v1/conversations/7": {"participants": [{"id": 1, "name": "Ada"}],
                                                   "messages": [{"author_id": 1, "body": "hello"}]}})
        out = capture(inbox.run, client, args(full=True, json=True), [], TODAY)
        thread = [p for p in client.paths if p.startswith("/api/v1/conversations/7")]
        self.assertEqual(thread, ["/api/v1/conversations/7?auto_mark_as_read=false"])
        self.assertEqual(json.loads(out)[0]["messages"][0]["author"], "Ada")

    def test_course_filter_only_when_asked(self):
        client = Fake({"/api/v1/conversations?": []})
        capture(inbox.run, client, args(), [COURSE], TODAY)
        self.assertNotIn("filter", client.paths[0])
        capture(inbox.run, client, args(course=["CS101"]), [COURSE], TODAY)
        self.assertIn("filter%5B%5D=course_1", client.paths[1])


class DiscussionTests(unittest.TestCase):
    def test_nested_replies_and_unread(self):
        client = Fake({"/api/v1/courses/1/discussion_topics/3/view": {
            "participants": [{"id": 1, "display_name": "Ada"}, {"id": 2, "display_name": "Bo"}],
            "unread_entries": [11],
            "view": [{"id": 10, "user_id": 1, "message": "<p>Q?</p>", "replies": [{"id": 11, "user_id": 2, "message": "A"}]}]}})
        entries = discussions.thread(client, COURSE, {"id": 3})
        self.assertEqual(entries[0]["message"], "Q?")
        self.assertEqual(entries[0]["replies"][0]["author"], "Bo")
        self.assertTrue(entries[0]["replies"][0]["unread"])

    def test_post_first_topics_are_reported_not_fatal(self):
        client = Fake({"/api/v1/courses/1/discussion_topics/3/view": UnavailableError("must post")})
        self.assertIsNone(discussions.thread(client, COURSE, {"id": 3}))


class EventTests(unittest.TestCase):
    def test_context_codes_are_chunked_and_include_the_user(self):
        many = [{"id": i, "course_code": f"C{i}"} for i in range(15)]
        client = Fake({"/api/v1/users/self": {"id": 99}, "/api/v1/calendar_events": []})
        events.fetch(client, many, TODAY, TODAY, "event")
        calls = [p for p in client.paths if p.startswith("/api/v1/calendar_events")]
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(p.count("context_codes") <= 10 for p in calls))
        self.assertIn("user_99", calls[-1])

    def test_bad_start_date(self):
        with self.assertRaises(CanvasError):
            events.day_range("16/10/2026")


class JsonTests(unittest.TestCase):
    def test_emit_serialises_datetimes(self):
        out = capture(emit, {"when": TODAY})
        self.assertEqual(json.loads(out)["when"], "2026-10-16T12:00:00+00:00")

    def test_json_flag_either_side(self):
        parse = cli.build_parser().parse_args
        self.assertTrue(parse(["--json", "todo"]).json)
        self.assertTrue(parse(["todo", "--json"]).json)
        self.assertFalse(parse(["todo"]).json)

    def test_submit_json_refuses_to_prompt(self):
        from canvas_cli import submit
        import os, tempfile
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"x")
        self.addCleanup(os.unlink, f.name)
        client = Fake({"/api/v1/courses/1/assignments": [{"id": 2, "name": "Essay", "submission_types": ["online_upload"]}]})
        a = SimpleNamespace(files=[f.name], assignment="Essay", json=True, dry_run=False, yes=False)
        with self.assertRaisesRegex(CanvasError, "--dry-run"):
            submit.run(client, a, COURSE, TODAY)
        a.dry_run = True
        plan = json.loads(capture(submit.run, client, a, COURSE, TODAY))
        self.assertFalse(plan["submitted"])
        self.assertEqual(plan["assignment"]["id"], 2)


if __name__ == "__main__":
    unittest.main()

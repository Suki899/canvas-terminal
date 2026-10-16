from datetime import datetime, timedelta, timezone
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from canvas_cli import assignments, config, courses, submit
from canvas_cli.api import AuthenticationError, CanvasError, Client
from canvas_cli.cli import build_parser, main
from canvas_cli.util import html_to_text, parse_time

from test_mirror import Response

TODAY = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


def iso(delta_days):
    return (TODAY + timedelta(days=delta_days)).strftime("%Y-%m-%dT%H:%M:%SZ")


class ThrottleTests(unittest.TestCase):
    def setUp(self):
        self.sleeps = []
        self.client = Client("https://canvas.example", "t", sleep=self.sleeps.append)
        self.addCleanup(self.client.close)
        self.client.session.get = Mock()

    def throttled(self):
        response = Response(status=403)
        response.text = "403 Forbidden (Rate Limit Exceeded)"
        return response

    def test_rate_limit_is_retried_not_treated_as_empty(self):
        self.client.session.get.side_effect = [self.throttled(), self.throttled(), Response([{"id": 1}])]
        self.assertEqual(self.client.optional_listing("/api/v1/x"), [{"id": 1}])
        self.assertEqual(self.sleeps, [2, 4])

    def test_persistent_rate_limit_is_an_error(self):
        self.client.session.get.side_effect = [self.throttled() for _ in range(5)]
        with self.assertRaisesRegex(CanvasError, "rate-limiting"):
            self.client.optional_listing("/api/v1/x")

    def test_disabled_tab_is_empty(self):
        self.client.session.get.return_value = Response(status=404)
        self.assertEqual(self.client.optional_listing("/api/v1/x"), [])


class CourseTests(unittest.TestCase):
    def course(self, id, code, term_end=None, term="Fall"):
        return {"id": id, "course_code": code, "name": f"{code} name",
                "term": {"name": term, "end_at": term_end}}

    def test_ended_courses_hidden_unless_asked(self):
        data = [self.course(1, "NOW", iso(30)), self.course(2, "OLD", iso(-30)), self.course(3, "OPEN")]
        pick = lambda **kw: [c["course_code"] for c in courses.select(data, TODAY, **kw)]
        self.assertEqual(pick(), ["NOW", "OPEN"])
        self.assertEqual(pick(include_past=True), ["NOW", "OLD", "OPEN"])
        self.assertEqual(pick(wanted=["old"]), ["OLD"])
        self.assertEqual(pick(wanted=["2"]), ["OLD"])

    def test_term_filter_and_restricted(self):
        data = [self.course(1, "A", term="2026 Spring"), self.course(2, "B", term="2025 Fall"),
                {"id": 3, "access_restricted_by_date": True}]
        self.assertEqual([c["id"] for c in courses.select(data, TODAY, term="spring")], [1])


class AssignmentTests(unittest.TestCase):
    def classify(self, **fields):
        base = {"submission_types": ["online_upload"], "due_at": iso(2), "submission": {}}
        base.update(fields)
        return assignments.classify(base, TODAY)[0]

    def test_buckets(self):
        self.assertEqual(self.classify(), "todo")
        self.assertEqual(self.classify(due_at=iso(-1)), "overdue")
        self.assertEqual(self.classify(due_at=iso(-3), lock_at=iso(-1)), "missed")
        self.assertEqual(self.classify(due_at=None), "undated")
        self.assertEqual(self.classify(submission_types=["on_paper"]), "untracked")
        self.assertEqual(self.classify(submission={"submitted_at": iso(-1)}), "done")
        self.assertEqual(self.classify(submission={"excused": True}), "done")

    def test_prefilled_zero_is_not_done_but_real_mark_is(self):
        self.assertEqual(self.classify(submission={"workflow_state": "graded", "score": 0}), "todo")
        self.assertEqual(self.classify(submission={"workflow_state": "graded", "score": 7}), "done")

    def test_new_quizzes_are_tracked(self):
        self.assertEqual(self.classify(submission_types=["external_tool"]), "untracked")
        self.assertEqual(self.classify(submission_types=["external_tool"], is_quiz_lti_assignment=True), "todo")

    def test_unlock_date_shown_for_not_yet_open(self):
        cols = dict.fromkeys(("dim", "off"), "")
        note = assignments.note({"locked_for_user": True, "unlock_at": iso(1)}, TODAY, cols)
        self.assertIn("opens", note)


class SubmitTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = os.path.join(temp.name, "essay.pdf")
        Path(self.path).write_bytes(b"%PDF")
        self.course = {"id": 1}
        self.assignment = {"id": 2, "submission_types": ["online_upload"]}
        self.client = Client("https://canvas.example", "secret")
        self.addCleanup(self.client.close)
        self.client.session.post = Mock()
        self.client.session.get = Mock()

    def slot(self):
        return Response({"upload_url": "https://storage.example/up", "upload_params": {"key": "k"}})

    def test_inst_fs_upload_does_not_send_token(self):
        self.client.session.post.side_effect = [self.slot(), Response({"id": 55}, status=201)]
        self.assertEqual(submit.upload(self.client, self.course, self.assignment, self.path), 55)
        canvas_call, storage_call = self.client.session.post.call_args_list
        self.assertIn("Authorization", canvas_call.kwargs["headers"])
        self.assertEqual(storage_call.kwargs["headers"], {})
        self.assertEqual(storage_call.kwargs["data"], {"key": "k"})

    def test_s3_redirect_confirms_on_canvas_with_token(self):
        location = "https://canvas.example/api/v1/files/55/create_success?uuid=x"
        self.client.session.post.side_effect = [self.slot(), Response(status=303, headers={"Location": location})]
        self.client.session.get.return_value = Response({"id": 55})
        self.assertEqual(submit.upload(self.client, self.course, self.assignment, self.path), 55)
        confirm = self.client.session.get.call_args
        self.assertEqual(confirm.args[0], location)
        self.assertIn("Authorization", confirm.kwargs["headers"])

    def test_preflight(self):
        found = submit.problems({"submission_types": ["online_text_entry"], "locked_for_user": True,
                                 "allowed_extensions": ["zip"]}, [self.path])
        self.assertEqual(len(found), 3)
        self.assertEqual(submit.problems(self.assignment, [self.path]), [])

    def test_name_match_prefers_exact_and_rejects_ambiguous(self):
        client = Mock()
        client.optional_listing.return_value = [{"id": 1, "name": "Essay"}, {"id": 2, "name": "Essay draft"}]
        self.assertEqual(submit.resolve(client, self.course, "essay")["id"], 1)
        client.optional_listing.return_value = [{"id": 1, "name": "Essay 1"}, {"id": 2, "name": "Essay 2"}]
        with self.assertRaisesRegex(CanvasError, "matches 2"):
            submit.resolve(client, self.course, "essay")

    def test_no_terminal_refuses_without_yes(self):
        with patch("builtins.input", side_effect=EOFError), self.assertRaisesRegex(CanvasError, "--yes"):
            submit.confirm("? ")


class ParserTests(unittest.TestCase):
    def test_flags_work_before_or_after_the_subcommand(self):
        parse = build_parser().parse_args
        self.assertEqual(parse(["--term", "X", "courses"]).term, "X")
        self.assertEqual(parse(["courses", "--term", "X"]).term, "X")
        self.assertEqual(parse(["--course", "A", "todo"]).course, ["A"])
        self.assertEqual(parse(["--days", "3", "todo"]).days, 3)
        self.assertEqual(parse(["todo"]).days, 7)

    def test_term_from_environment(self):
        with patch.dict(os.environ, {"CANVAS_TERM": "2610"}):
            self.assertEqual(build_parser().parse_args(["todo"]).term, "2610")


class ConfigTests(unittest.TestCase):
    def test_login_saves_private_file_and_bad_token_saves_nothing(self):
        with tempfile.TemporaryDirectory() as temp, \
                patch.dict(os.environ, {"XDG_CONFIG_HOME": temp}, clear=True), \
                patch("sys.stdin.isatty", return_value=True), \
                patch("builtins.input", return_value="canvas.example"), \
                patch("getpass.getpass", return_value="tok"), \
                patch("sys.stdout", new_callable=io.StringIO):
            with patch.object(Client, "one", side_effect=AuthenticationError("no")):
                with self.assertRaises(AuthenticationError):
                    config.login()
            self.assertFalse(config.config_path().exists())
            with patch.object(Client, "one", return_value={"id": 1, "name": "Ada"}):
                config.login()
            self.assertEqual(config.config_path().stat().st_mode & 0o777, 0o600)
            self.assertEqual(config.config_path().parent.stat().st_mode & 0o777, 0o700)
            client = config.client()
            self.assertEqual((client.url, client.token), ("https://canvas.example", "tok"))
            client.close()

    def test_not_signed_in_is_a_clear_error(self):
        with tempfile.TemporaryDirectory() as temp, \
                patch.dict(os.environ, {"XDG_CONFIG_HOME": temp}, clear=True), \
                patch("sys.stderr", new_callable=io.StringIO) as err:
            self.assertEqual(main(["todo"]), 1)
            self.assertIn("canvas login", err.getvalue())


class UtilTests(unittest.TestCase):
    def test_parse_time_accepts_z_on_all_versions(self):
        self.assertEqual(parse_time("2026-10-16T04:00:00Z").utcoffset() is not None, True)
        self.assertIsNone(parse_time("garbage"))

    def test_html_to_text(self):
        text = html_to_text('<p>Hi <a href="https://x.example">here</a></p><ul><li>one</li></ul>'
                            '<script>bad()</script><img alt="chart" src="https://x.example/c.png">')
        self.assertIn("here <https://x.example>", text)
        self.assertIn("- one", text)
        self.assertNotIn("bad()", text)
        self.assertIn("[chart]", text)


if __name__ == "__main__":
    unittest.main()


class TerminalSafetyTests(unittest.TestCase):
    """Text from other people must not reach the terminal as control sequences."""

    def test_listing_strips_escape_sequences_and_bidi_overrides(self):
        client = Client("https://canvas.example", "t")
        self.addCleanup(client.close)
        client.session.get = Mock(return_value=Response([{"title": "Hi\x1b[2J\x1b]0;pwned\x07 ‮evil\r", "n": 1}]))
        self.assertEqual(client.listing("/api/v1/x"), [{"title": "Hi[2J]0;pwned evil", "n": 1}])

    def test_html_entities_cannot_smuggle_escape(self):
        # &#x9b; decodes to "›" under HTML rules; &#27; would be a raw ESC.
        text = html_to_text("<p>a&#27;[31mb&#x9b;c&#x202e;d</p>")
        self.assertEqual(text, "a[31mb›cd")
        self.assertFalse(any(ord(ch) < 32 or 0x7f <= ord(ch) <= 0x9f for ch in text))

    def test_post_rejects_plain_http(self):
        client = Client("https://canvas.example", "t")
        self.addCleanup(client.close)
        client.session.post = Mock()
        with self.assertRaises(CanvasError):
            client.post("http://storage.example/up")
        client.session.post.assert_not_called()

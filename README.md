# canvas-terminal

Your Canvas LMS courses from the terminal: what is due, grades, announcements,
modules, pages, the syllabus, discussions, your inbox, calendar events,
quizzes, a local copy of course files, and file submissions. Every command can
also print JSON for scripts.

Works with any Canvas site that lets students create access tokens. Requires
Python 3.10+ on Linux or macOS.

```console
$ canvas
Canvas · 7 courses

OVERDUE
  BIO101   Mon 12 Oct 23:59   4d ago     Lab report 3

DUE IN THE NEXT 7 DAYS
  HIST210  Tue 20 Oct 23:59   in 4d      Essay outline
  CS101    Fri 23 Oct 16:00   in 7d      Week 10 Quiz  (opens Fri 16 Oct 16:00)

UNREAD ANNOUNCEMENTS
  CS101    16 Oct today      Tutorial moved to Thursday
```

## Install

```sh
pipx install git+https://github.com/Suki899/canvas-cli   # or, from a clone:
python3 -m pip install --user .
```

## Sign in

```sh
canvas login
```

It asks for your Canvas address (for example `canvas.example.edu`) and an
access token. Make the token in Canvas under **Account → Settings → Approved
Integrations → New Access Token**. The token is checked against Canvas before
it is saved.

The token is stored in plain text in `~/.config/canvas-cli/config.json`
(respecting `$XDG_CONFIG_HOME`), readable only by you. `canvas logout` deletes
it. For scripts and CI, set `CANVAS_URL` and `CANVAS_TOKEN` instead; they take
precedence over the saved login.

## Commands

| Command | What it shows or does |
| --- | --- |
| `canvas` | Overdue work, the next 7 days, and this month's unread announcements |
| `canvas todo` | Assignments: overdue, due soon, later. `--done`, `--all`, `--days N` |
| `canvas grades` | Course totals (where the course shows them) and points per course. With `--course` or `--full`: every item by assignment group |
| `canvas calendar` | Classes, tests and other events for the next 14 days. `--due` adds deadlines, `--days N`, `--from YYYY-MM-DD` |
| `canvas news` | Announcements from the last 14 days. `--unread`, `--full`, `--days N` |
| `canvas modules [MATCH]` | Each course's modules. With `--course`, a name, or `--full`: their files, pages, quizzes and links, with what's done |
| `canvas syllabus` | Which courses have a syllabus. `--course` or `--full` prints it |
| `canvas pages [MATCH]` | Course Pages by title. `--full` prints them |
| `canvas discussions [MATCH]` | Discussion topics with unread counts. Name one, or `--full`, for the whole thread. `--unread` |
| `canvas inbox [MATCH]` | Canvas Inbox conversations. `--unread`, `--scope sent\|starred\|archived`, `--full` for whole threads |
| `canvas quizzes [MATCH]` | Quizzes with due dates and scores. Name one, or `--full`, for settings and attempts |
| `canvas sync FOLDER` | Copy every course's Files into `FOLDER`. `--watch SECONDS` keeps it running |
| `canvas submit ASSIGNMENT FILE...` | Hand in files, after a confirmation. `--dry-run`, `--yes` |
| `canvas courses` | Your courses and their ids |
| `canvas whoami` | Which account the token belongs to |

Every course command accepts:

- `--course CODE`: one course, by id or part of its code or name. Repeatable.
- `--term NAME`: courses whose term name contains `NAME`. Set `CANVAS_TERM`
  to make it the default.
- `--all-courses`: include courses whose term has ended. These are hidden by
  default because many Canvas sites leave old enrolments active.
- `--json`: print one JSON document instead of text (see below).

`inbox` covers your whole account unless you pass `--course` or `--term`.

### Reading never marks anything read

The `inbox` and `discussions` commands leave Canvas's unread markers exactly as
they were, including with `--full`. Read a thread in the terminal, and it is
still unread on the website.

### JSON output

Add `--json`, before or after the command, and the command prints a single
JSON document on stdout instead of text. Use it for scripts, `jq`, or other
tools:

```sh
canvas todo --json | jq '.assignments[] | select(.status == "overdue") | .name'
canvas grades --course CS101 --json
```

- Times are ISO 8601 with your local offset, for example
  `"2026-10-20T23:59:00+08:00"`.
- Every record names its course as `{"id", "code", "name"}`.
- Filters such as `--course`, `--unread` and `--days` still apply. The text
  view's display limits do not: `todo --json` lists every assignment, each with
  a `status` of `overdue`, `todo`, `done`, `missed`, `undated` or `untracked`.
- `--full` adds bodies, threads, quiz settings and attempts where the text view
  would show them.
- Errors still go to stderr with a non-zero exit code. `sync --json` sends its
  progress to stderr and prints the counts as JSON.
- `submit --json` never prompts. It needs `--dry-run`, which prints the plan,
  or `--yes`, which submits and prints the result.

### How `todo` sorts assignments

- **Done:** submitted, excused, or given a mark above zero (handed in on
  paper, for example). A pre-filled zero does not count, because some courses
  enter zeros before the due date.
- **Overdue:** past due and still open for submission.
- **Missed:** past the lock date, so it can no longer be handed in. Shown with
  `--all`.
- **Hidden by default:** undated work, and gradebook rows you cannot submit
  through Canvas (paper, attendance, ungraded). Shown with `--all`.

### Submitting

```sh
canvas submit --course HIST210 "essay outline" outline.pdf
```

Before anything is uploaded, `submit` checks that the assignment takes file
uploads, is open, and accepts the file types. It then shows the full path,
size and modification time of each file, the due date, and whether this is a
late or repeat submission, and asks for confirmation. With no terminal it
refuses unless you pass `--yes`. The token is never sent to the file-storage
host.

### File sync

`canvas sync ~/Canvas` mirrors each course's Files area into
`~/Canvas/<code> [<id>]/`, keeping Canvas's folder structure. It is one-way
and never uploads.

- New and changed files are downloaded atomically, and size and content are
  checked.
- Remote renames are followed. Remote deletions are removed locally only if
  your copy is unchanged.
- Files you edited, or that were already there, are never overwritten. They
  are reported as *protected*.
- Losing access to a course or its Files tab leaves the local copies alone.
- Tracking data lives in `FOLDER/.canvas-sync/`. A folder is tied to one
  Canvas account, and two syncs of the same folder cannot run at once.

A single pass exits `0` on success and `1` on errors or protected-file
conflicts.

## Exit codes

`0` success, `1` error, `2` bad arguments, `3` token rejected (run
`canvas login`), `130` interrupted.

## Not supported

- **New Quizzes:** settings and attempts cannot be read with a student
  token, so only the due date and whether it was submitted are shown.
- **Text-entry and URL submissions:** only file uploads.
- **Writing anything other than submissions:** replying to discussions, sending
  messages, and marking items read or unread.
- **Hidden totals:** courses that hide totals from students, as many do, show
  "total hidden". Per-item scores still appear.
- **Group pages and group files.**
- **Windows:** `sync` needs `fcntl`. The other commands should work but are
  untested.

## Development

```sh
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/python -m unittest discover -s tests -v
```

The tests use simulated Canvas responses and need no credentials. CI runs them
on Linux and macOS with Python 3.10 and 3.14.

## Licence

MIT. See [LICENSE](LICENSE).

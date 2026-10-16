# Changelog

## 0.2.0 — 2026-10-16

### New commands

- **`grades`:** course totals (where shown) and every scored item by group.
- **`modules`:** modules and their items, with completion.
- **`syllabus`:** course syllabi.
- **`discussions`:** discussion topics and whole threads.
- **`inbox`:** conversations and whole threads.
- **`calendar`:** calendar events; `--due` adds assignment deadlines.

### Other changes

- **`--json`** on every command: one JSON document on stdout.
- **Reading leaves unread markers alone.** `inbox` and `discussions` never mark
  anything read, including whole threads.
- **Terminal safety:** control characters and text-direction overrides are
  stripped from everything Canvas returns.
- **Package renamed to `canvas-terminal`** (`canvas-cli` is taken on PyPI). The
  command is still `canvas`.
- **Fix:** piping output into `head` no longer prints "Broken pipe" errors.

## 0.1.0 — 2026-10-16

First release:

- **Commands:** overview, `todo`, `news`, `pages`, `quizzes`, `sync`,
  `submit`, `courses`, `login`, `logout` and `whoami`.

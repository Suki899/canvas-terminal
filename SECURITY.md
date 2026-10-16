# Security

## Reporting a vulnerability

Please report security problems privately through
[GitHub's private vulnerability reporting](https://github.com/Suki899/canvas-terminal/security/advisories/new)
rather than in a public issue. Include the version (`canvas --version`), what
you ran, and what happened. You should get a reply within a week.

Never include your Canvas access token in a report. If you think a token has
been exposed, delete it at once in Canvas under **Account → Settings →
Approved Integrations**, then run `canvas login` with a new one.

## What canvas-terminal promises

- **Your token only goes to your Canvas site.** It is never sent to file
  storage hosts or redirect targets. Requests use HTTPS only.
- **The saved token is private but not encrypted.** It is stored in plain text
  in `~/.config/canvas-cli/config.json`, which only your user can read (`0600`).
- **Only `canvas submit` writes to Canvas,** and only after a confirmation or an
  explicit `--yes`. Everything else is read-only and leaves unread markers
  alone.
- **`canvas sync` stays inside the folder you give it.** It never follows
  symlinks out, and never overwrites files you have changed.
- **Text from Canvas is cleaned before it reaches your terminal.** Control
  characters and text-direction overrides are removed, so a post or message
  cannot fake or rewrite terminal output.

A problem with any of these is a vulnerability. Please report it.

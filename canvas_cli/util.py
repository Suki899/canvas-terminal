"""Presentation helpers: colours, times, HTML to plain text."""

from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import os
import re
import sys
import textwrap

# Control characters (except newline and tab) and bidi overrides. Canvas text is
# written by other people; printed raw, these can move the cursor, rewrite
# earlier lines, or disguise what a line says.
UNSAFE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")


def clean(text):
    return UNSAFE.sub("", text)


def scrub(value):
    """clean() every string inside a decoded JSON value."""
    if isinstance(value, str):
        return clean(value)
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items()}
    return value


NAMES = ("red", "yellow", "green", "cyan", "dim", "bold", "off")
CODES = ("\033[31m", "\033[33m", "\033[32m", "\033[36m", "\033[2m", "\033[1m", "\033[0m")


def colours(stream=None):
    stream = stream or sys.stdout
    if not stream.isatty() or os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        return dict.fromkeys(NAMES, "")
    return dict(zip(NAMES, CODES))


def emit(data):
    """Print one JSON document. Datetimes become ISO 8601 with their offset."""
    def default(value):
        if isinstance(value, datetime):
            return value.isoformat()
        raise TypeError(f"{type(value).__name__} is not JSON serialisable")
    json.dump(data, sys.stdout, indent=2, ensure_ascii=False, default=default)
    sys.stdout.write("\n")


def now():
    return datetime.now(timezone.utc).astimezone()


def parse_time(value):
    """Canvas timestamps are UTC ISO 8601; return local time, or None."""
    if not value:
        return None
    try:
        # Python 3.10's fromisoformat does not accept a trailing Z.
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
    except (TypeError, ValueError):
        return None


def relative(when, today):
    if when is None:
        return ""
    days = (when.date() - today.date()).days
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    if days == -1:
        return "yesterday"
    return f"in {days}d" if days > 0 else f"{-days}d ago"


def stamp(when, with_time=True):
    if when is None:
        return "no due date"
    return when.strftime("%a %d %b %H:%M" if with_time else "%a %d %b")


def plural(count, word, many=None):
    return f"{count} {word if count == 1 else many or word + 's'}"


def score(value, points):
    if value is None:
        return ""
    return f"{value:g}/{points:g}" if points else f"{value:g}"


class _TextExtractor(HTMLParser):
    BLOCK = {"p", "div", "br", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
             "blockquote", "section", "article", "table", "pre"}
    SKIP = {"script", "style", "head"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skipping = 0
        self.list_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in self.SKIP:
            self.skipping += 1
        elif tag in ("ul", "ol"):
            self.list_depth += 1
            self.parts.append("\n")
        elif tag == "li":
            self.parts.append("\n" + "  " * max(self.list_depth - 1, 0) + "- ")
        elif tag in self.BLOCK:
            self.parts.append("\n")
        elif tag == "a" and attrs.get("href"):
            self.parts.append("\0LINK:" + attrs["href"] + "\0")
        elif tag == "img":
            # Some announcements are only a screenshot; keep a trace of it.
            label = (attrs.get("alt") or "").strip() or "image"
            src = attrs.get("src") or ""
            self.parts.append(f"\n[{label}]" + (f" {src}" if src else "") + "\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skipping = max(0, self.skipping - 1)
        elif tag in ("ul", "ol"):
            self.list_depth = max(0, self.list_depth - 1)
            self.parts.append("\n")
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skipping:
            self.parts.append(data)

    def text(self):
        def link(match):
            href, label = match.group(1), match.group(2).strip()
            if not label:
                return href
            bare = href[7:] if href.startswith("mailto:") else href
            return label if bare in label else f"{label} <{href}>"

        out = re.sub(r"\0LINK:(.*?)\0([^\0\n]*)", link, "".join(self.parts))
        out = clean(out.replace("\0", "").replace("\xa0", " "))
        out = re.sub(r"[ \t]+", " ", out)
        out = re.sub(r" *\n *", "\n", out)
        out = re.sub(r"\n{3,}", "\n\n", out)
        return out.strip()


def html_to_text(markup):
    if not markup:
        return ""
    parser = _TextExtractor()
    parser.feed(markup)
    parser.close()
    return parser.text()


def wrap(text, width=76, indent="    "):
    out = []
    for line in text.splitlines():
        if not line.strip():
            out.append("")
            continue
        hang = indent + ("  " if line.startswith("- ") else "")
        out.extend(textwrap.wrap(line, width=width, initial_indent=indent,
                                 subsequent_indent=hang) or [indent])
    return "\n".join(out)

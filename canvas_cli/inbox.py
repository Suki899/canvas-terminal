"""Canvas Inbox, read-only.

Opening a conversation through the API marks it read by default. Every fetch
here passes auto_mark_as_read=false, so reading from the terminal leaves the
unread markers exactly as they were.
"""

from urllib.parse import urlencode

from .util import colours, emit, html_to_text, parse_time, plural, relative, wrap

SCOPES = ("inbox", "unread", "starred", "sent", "archived")


def listing(client, scope, courses=None):
    query = [("scope", scope)] + [("filter[]", f"course_{c['id']}") for c in courses or []]
    return client.listing(f"/api/v1/conversations?{urlencode(query)}")


def thread(client, conversation_id):
    return client.one(f"/api/v1/conversations/{conversation_id}?auto_mark_as_read=false")


def record(conversation, full=None):
    out = {"id": conversation.get("id"), "subject": (conversation.get("subject") or "").strip(),
           "state": conversation.get("workflow_state"), "unread": conversation.get("workflow_state") == "unread",
           "starred": bool(conversation.get("starred")), "context": conversation.get("context_name"),
           "last_message_at": parse_time(conversation.get("last_message_at")),
           "message_count": conversation.get("message_count"),
           "participants": [p.get("name") for p in conversation.get("participants") or []],
           "last_message": (conversation.get("last_message") or "").strip()}
    if full is not None:
        names = {p.get("id"): p.get("name") for p in full.get("participants") or []}
        out["messages"] = [{"id": m.get("id"), "author": names.get(m.get("author_id")),
                            "created_at": parse_time(m.get("created_at")),
                            "body": (m.get("body") or "").strip(),
                            "attachments": [a.get("display_name") for a in m.get("attachments") or []]}
                           for m in sorted(full.get("messages") or [], key=lambda m: m.get("created_at") or "")]
    return out


def run(client, args, courses, today):
    cols = colours()
    scope = "unread" if args.unread else args.scope
    # Only narrow by course when one was asked for; the inbox is account-wide.
    narrowed = courses if (args.course or args.term) else None
    conversations = listing(client, scope, narrowed)
    if args.match:
        needle = args.match.casefold()
        conversations = [c for c in conversations if needle in (c.get("subject") or "").casefold()
                         or needle in (c.get("last_message") or "").casefold()]
    show_all = args.full or (args.match and len(conversations) == 1)
    records = [record(c, thread(client, c["id"]) if show_all else None) for c in conversations]
    if args.json:
        emit(records)
        return
    if not records:
        print(f"Nothing in {scope}." if not args.match else "No conversations matched.")
        return
    for item in records:
        mark = f"{cols['cyan']}●{cols['off']}" if item["unread"] else " "
        when = item["last_message_at"]
        people = ", ".join(item["participants"][:3]) + (" …" if len(item["participants"]) > 3 else "")
        print(f"\n{mark} {cols['bold']}{item['subject'] or '(no subject)'}{cols['off']}  "
              f"{cols['dim']}{when.strftime('%d %b %H:%M') if when else ''} · {relative(when, today)} · "
              f"{plural(item['message_count'] or 0, 'message')} · {item['context'] or ''}{cols['off']}")
        print(f"  {cols['dim']}{people}{cols['off']}")
        if "messages" in item:
            for message in item["messages"]:
                stamp_ = message["created_at"].strftime("%d %b %H:%M") if message["created_at"] else ""
                print(f"\n  {cols['bold']}{message['author'] or '?'}{cols['off']} {cols['dim']}{stamp_}{cols['off']}")
                print(wrap(html_to_text(message["body"]) if "<" in message["body"] else message["body"]))
                for name in message["attachments"]:
                    print(f"    {cols['dim']}[attachment] {name}{cols['off']}")
        else:
            first = " ".join(item["last_message"].split())
            print(f"  {first[:96]}{'…' if len(first) > 96 else ''}")
    unread = sum(1 for r in records if r["unread"])
    print(f"\n{cols['dim']}{plural(len(records), 'conversation')}, {unread} unread · reading here never marks them read"
          f"{'' if show_all else ' · --full for whole threads'}{cols['off']}")


def add_args(parser):
    parser.add_argument("match", nargs="?", help="only conversations whose subject or text contains this")
    parser.add_argument("--unread", action="store_true", help="only unread conversations")
    parser.add_argument("--scope", choices=SCOPES, default="inbox", help="which folder (default: inbox)")
    parser.add_argument("--full", action="store_true", help="print whole threads")

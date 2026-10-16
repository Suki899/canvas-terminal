"""Course Modules: the week-by-week structure most courses are built around."""

from .api import UnavailableError
from .courses import label, ref
from .util import colours, emit, parse_time, plural, stamp

KINDS = {"File": "file", "Page": "page", "Discussion": "discuss", "Assignment": "assign",
         "Quiz": "quiz", "ExternalUrl": "link", "ExternalTool": "tool", "SubHeader": ""}


def fetch(client, course):
    path = f"/api/v1/courses/{course['id']}/modules?include[]=items&include[]=content_details"
    modules = client.optional_listing(path)
    for module in modules:
        # Canvas leaves "items" out when a module is large; fetch those separately.
        if "items" not in module and module.get("id") is not None:
            try:
                module["items"] = client.listing(f"/api/v1/courses/{course['id']}/modules/{module['id']}"
                                                 "/items?include[]=content_details")
            except UnavailableError:
                module["items"] = []
    return modules


def item_record(item):
    details = item.get("content_details") or {}
    need = item.get("completion_requirement") or {}
    return {"id": item.get("id"), "type": item.get("type"), "title": (item.get("title") or "").strip(),
            "indent": item.get("indent") or 0, "url": item.get("html_url"),
            "external_url": item.get("external_url"),
            "due_at": parse_time(details.get("due_at")), "points_possible": details.get("points_possible"),
            "locked": bool(details.get("locked_for_user")),
            "requirement": need.get("type"), "completed": need.get("completed") if need else None}


def record(course, module):
    return {"id": module.get("id"), "name": (module.get("name") or "").strip(), "course": ref(course),
            "state": module.get("state"), "unlock_at": parse_time(module.get("unlock_at")),
            "completed_at": parse_time(module.get("completed_at")),
            "items": [item_record(i) for i in module.get("items") or []]}


def show_items(module, cols):
    for item in module["items"]:
        indent = "  " * (item["indent"] + 2)
        if item["type"] == "SubHeader":
            print(f"{indent}{cols['bold']}{item['title']}{cols['off']}")
            continue
        notes = []
        if item["due_at"]:
            notes.append(f"due {stamp(item['due_at'])}")
        if item["completed"] is True:
            notes.append(f"{cols['green']}done{cols['dim']}")
        elif item["requirement"]:
            notes.append(f"to do: {item['requirement'].replace('_', ' ')}")
        if item["locked"]:
            notes.append("locked")
        title = item["title"] or item["external_url"] or ""
        print(f"{indent}{cols['dim']}{KINDS.get(item['type'], item['type'] or '?'):<8}{cols['off']}{title}"
              + (f"  {cols['dim']}({'; '.join(notes)}){cols['off']}" if notes else ""))


def run(client, args, courses, today):
    cols = colours()
    found = []
    for course in courses:
        modules = [record(course, m) for m in fetch(client, course)]
        if args.match:
            needle = args.match.casefold()
            modules = [m for m in modules if needle in m["name"].casefold()]
        if modules:
            found.append((course, modules))
    if args.json:
        emit([m for _, modules in found for m in modules])
        return
    if not found:
        print("No modules found." + (" Try a different match." if args.match else ""))
        return

    # Items for one course, a named module, or on request; otherwise an outline.
    detail = args.full or args.match or len(found) == 1
    for course, modules in found:
        print(f"\n{cols['bold']}{label(course)}{cols['off']}")
        for module in modules:
            # Canvas calls a module with no requirements "completed" from day one.
            tracked = any(i["requirement"] for i in module["items"])
            state = module["state"] if tracked or module["state"] == "locked" else None
            if state == "locked" and module["unlock_at"]:
                state = f"opens {stamp(module['unlock_at'])}"
            tail = plural(len(module["items"]), "item") + (f", {state}" if state else "")
            print(f"  {module['name']}  {cols['dim']}({tail}){cols['off']}")
            if detail:
                show_items(module, cols)
    total = sum(len(m) for _, m in found)
    print(f"\n{cols['dim']}{plural(total, 'module')}"
          f"{'' if detail else ' · --course, a name, or --full to list items'}{cols['off']}")


def add_args(parser):
    parser.add_argument("match", nargs="?", help="only modules whose name contains this")
    parser.add_argument("--full", action="store_true", help="list every module's items")

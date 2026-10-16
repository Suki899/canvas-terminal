"""Where the Canvas URL and token live, and how a session gets them."""

import getpass
import os
from pathlib import Path
import sys

from .api import CanvasError, Client, normalize_url
from .storage import atomic_json, read_json


def config_path():
    home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return home / "canvas-cli" / "config.json"


def prompt(message, secret=False, default=None):
    if not sys.stdin.isatty():
        raise CanvasError("`canvas login` needs a terminal. For scripts, set CANVAS_URL and CANVAS_TOKEN.")
    if default:
        message = f"{message} [{default}]"
    value = (getpass.getpass(message + ": ") if secret else input(message + ": ")).strip() or default
    if not value:
        raise CanvasError("A value is required.")
    return value


def valid_token(token):
    return isinstance(token, str) and token.strip() and not any(c.isspace() for c in token)


def whoami(client):
    user = client.one("/api/v1/users/self/profile")
    if not isinstance(user, dict) or "id" not in user:
        raise CanvasError("Canvas did not return a user identity.")
    return user


def login(url=None):
    """Ask for URL and token, check them against Canvas, then save."""
    saved = read_json(config_path(), {})
    url = normalize_url(url or prompt("Canvas URL", default=saved.get("url")))
    print(f"Create a token at {url}/profile/settings (Approved Integrations → New Access Token).")
    token = prompt("Access token (hidden)", secret=True)
    if not valid_token(token):
        raise CanvasError("That does not look like an access token.")
    with Client(url, token) as client:
        user = whoami(client)
    atomic_json(config_path(), {"url": url, "token": token})
    return user


def logout():
    path = config_path()
    if path.exists():
        path.unlink()
        return True
    return False


def client():
    """A client from CANVAS_URL/CANVAS_TOKEN, falling back to the saved login."""
    saved = read_json(config_path(), {})
    url = os.environ.get("CANVAS_URL") or saved.get("url")
    token = os.environ.get("CANVAS_TOKEN") or saved.get("token")
    if not url or not token:
        raise CanvasError("Not signed in. Run `canvas login` first.")
    if not valid_token(token):
        raise CanvasError("The saved access token is malformed. Run `canvas login` again.")
    return Client(url, token)

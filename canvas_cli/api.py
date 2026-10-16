"""Canvas REST client: bounded requests, retries, and credential isolation."""

import time
from urllib.parse import urljoin, urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

TIMEOUT = (10, 60)
REDIRECTS = (301, 302, 303, 307, 308)


class CanvasError(Exception):
    pass


class AuthenticationError(CanvasError):
    pass


class UnavailableError(CanvasError):
    """403/404 that is not throttling: a disabled tab, a hidden item."""


class BoundedRetry(Retry):
    def get_retry_after(self, response):
        delay = super().get_retry_after(response)
        return min(delay, 60) if delay is not None else None


def origin(url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise CanvasError("Canvas and download URLs must use HTTPS without embedded credentials.")
    try:
        return parsed.hostname.lower(), parsed.port or 443
    except ValueError as exc:
        raise CanvasError("Invalid URL port.") from exc


def normalize_url(value):
    value = value.strip().rstrip("/")
    if "://" not in value:
        value = "https://" + value
    origin(value)
    parsed = urlsplit(value)
    if parsed.path or parsed.query or parsed.fragment:
        raise CanvasError("Enter only your Canvas site's URL, for example https://canvas.example.edu.")
    return value


def throttled(response):
    # Canvas signals throttling with 403 and this body, not with 429.
    return response.status_code == 403 and "Rate Limit Exceeded" in (response.text or "")


class Client:
    def __init__(self, url, token, *, sleep=time.sleep):
        self.url = normalize_url(url)
        self.token = token
        self.sleep = sleep
        self.session = requests.Session()
        # Do not let .netrc supply credentials to third-party storage hosts.
        self.session.trust_env = False
        retries = BoundedRetry(total=4, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504],
                               allowed_methods={"GET"}, respect_retry_after_header=True)
        self.session.mount("https://", HTTPAdapter(max_retries=retries))

    def close(self):
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _headers(self, url):
        # The token only ever goes to the Canvas site itself, never to S3,
        # inst-fs, or wherever a download redirects.
        return {"Authorization": f"Bearer {self.token}"} if origin(url) == origin(self.url) else {}

    def _check(self, response):
        if response.status_code == 401:
            response.close()
            raise AuthenticationError("Canvas rejected your token. Run `canvas login` again.")
        if response.status_code in (403, 404):
            response.close()
            raise UnavailableError("Canvas denied access or the resource is unavailable.")
        if not response.ok:
            status = response.status_code
            response.close()
            raise CanvasError(f"Canvas request failed (HTTP {status}).")
        return response

    def get(self, url, *, download=False):
        """GET following redirects by hand, so the token never crosses hosts."""
        throttles = 0
        for _ in range(6):
            if not download and origin(url) != origin(self.url):
                raise CanvasError("Canvas returned an API link to another site.")
            try:
                response = self.session.get(url, headers=self._headers(url), timeout=TIMEOUT,
                                            stream=download, allow_redirects=False)
            except requests.RequestException as exc:
                raise CanvasError("Network request failed; check your connection and try again.") from exc
            if response.status_code in REDIRECTS:
                location = response.headers.get("Location")
                response.close()
                if not location:
                    raise CanvasError("Canvas returned a redirect without a destination.")
                url = urljoin(url, location)
                continue
            if throttled(response) and throttles < 4:
                response.close()
                throttles += 1
                self.sleep(2 ** throttles)
                continue
            if throttled(response):
                response.close()
                raise CanvasError("Canvas is rate-limiting this token; try again in a minute.")
            return self._check(response)
        raise CanvasError("Too many redirects from Canvas.")

    def post(self, url, *, data=None, files=None):
        """POST once (never retried: a repeat could submit twice)."""
        if not url.startswith("https://"):
            url = self.url + url
        try:
            response = self.session.post(url, headers=self._headers(url), data=data, files=files,
                                         timeout=(10, 300), allow_redirects=False)
        except requests.RequestException as exc:
            raise CanvasError("Network request failed; check your connection and try again.") from exc
        if response.status_code in REDIRECTS:
            return response
        return self._check(response)

    def one(self, path):
        with self.get(self.url + path) as response:
            try:
                return response.json()
            except ValueError as exc:
                raise CanvasError("Canvas returned an invalid API response.") from exc

    def listing(self, path):
        url = self.url + path + ("&" if "?" in path else "?") + "per_page=100"
        seen = set()
        result = []
        while url:
            if url in seen:
                raise CanvasError("Canvas returned a pagination loop.")
            seen.add(url)
            with self.get(url) as response:
                try:
                    page = response.json()
                except ValueError as exc:
                    raise CanvasError("Canvas returned an invalid API response.") from exc
                if not isinstance(page, list) or not all(isinstance(item, dict) for item in page):
                    raise CanvasError("Canvas returned an invalid list response.")
                result.extend(page)
                next_url = response.links.get("next", {}).get("url")
                url = urljoin(url, next_url) if next_url else None
        return result

    def optional_listing(self, path):
        """A listing where a disabled tab (403/404) just means nothing to show."""
        try:
            return self.listing(path)
        except UnavailableError:
            return []

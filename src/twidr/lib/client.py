"""Machinery for session-bound, threaded, and rate-limited HTTP GET requests."""

import threading
import time
from threading import Event, Lock
from typing import Any, Final

from requests import RequestException, Response, Session

from . import meta

USER_AGENT: Final = f"{meta.APP_NAME}/{meta.VERSION} ({meta.ORG_DOMAIN})"


class RateLimiter:
    """A self-contained construct for rate-limiting an HTTP client atomically across threads."""

    def __init__(self, per_second: float, stop: Event) -> None:
        """Create a new RateLimiter with a per-second maximum rate and an Event to trigger pauses."""

        self._lock = Lock()
        self._interval = 1 / per_second
        self._next = 0.0
        self._stop = stop

    def wait(self) -> None:
        """Atomically trigger a pause."""

        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next)
            self._next = slot + self._interval

        delay = slot - now

        if delay > 0:
            self._stop.wait(delay)  # returns early on Ctrl-C

    def penalize(self, seconds: float) -> None:
        """Atomically add to the current pause delay."""

        with self._lock:
            self._next = max(self._next, time.monotonic() + seconds)


class Client:
    """A generic, rate-limited HTTP client implementing GET."""

    def __init__(self, rate: float, max_attempts: int) -> None:
        """Create a new Client with a rate limit and maximum number of attempts per request."""

        self.stop = Event()
        self._limiter = RateLimiter(rate, self.stop)
        self._max_attempts = max_attempts
        self._local = threading.local()

    def _session(self) -> Session:
        session: Session | None = getattr(self._local, "session", None)

        if session is None:
            session = Session()
            session.headers["User-Agent"] = USER_AGENT

            self._local.session = session

        return session

    def get(self, url: str, **kw: Any) -> Response | None:
        """Send an HTTP GET request with arbitrary parameters."""

        for attempt in range(self._max_attempts):
            self._limiter.wait()

            if self.stop.is_set():
                return None

            try:
                response = self._session().get(url, timeout=30, **kw)
            except RequestException:
                self._limiter.penalize(2**attempt)

                continue

            if response.status_code == 429 or response.status_code >= 500:
                self._limiter.penalize(5 * (attempt + 1))

                continue

            return response

        return None

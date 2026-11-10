"""A specialized, HTTP-based client for Twitter media stored in the Wayback Machine."""

from threading import Event
from typing import Final, Literal, NamedTuple

from requests import Response

from .client import Client


class Capture(NamedTuple):
    """An archived copy of a URL on the Wayback Machine."""

    timestamp: str
    original: str


def resolution_rank(capture: Capture) -> tuple[int, str]:
    """Rank captures of an image by resolution, then by timestamp."""

    url = capture.original

    ordinal = (
        0 if "orig" in url else 1 if "large" in url else 2 if "medium" in url else 3
    )

    return (ordinal, capture.timestamp)


class Wayback:
    """A specialized, rate-limited client for retrieving Twitter media from the Wayback Machine."""

    CDX_URL: Final = "https://web.archive.org/cdx/search/cdx"
    WEB_URL: Final = "https://web.archive.org/web"

    def __init__(self, client: Client) -> None:
        """Create a new Wayback client, wrapping a Client providing generic, rate-limited HTTP."""

        self._client = client

    @property
    def stop(self) -> Event:
        return self._client.stop

    def _cdx(self, **params: str) -> list[list[str]] | None:
        """Get raw CDX rows (header skipped) or return None on request failure."""

        response = self._client.get(self.CDX_URL, params={"output": "json", **params})

        # failure at request time
        if response is None or not response.ok:
            return None

        # empty
        if not response.text.strip():
            return []

        # success
        try:
            rows: list[list[str]] = response.json()

        # failure at parse time
        except ValueError:
            return None

        return rows[1:]

    def _replay(
        self, capture: Capture, modifier: Literal["id", "im"]
    ) -> Response | None:
        """Fetch a capture; "id" gets a raw capture and "im" gets an image."""

        return self._client.get(
            f"{self.WEB_URL}/{capture.timestamp}{modifier}_/{capture.original}"
        )

    def captures(self, user: str, domain: str) -> list[Capture] | None:
        """Get every capture of a user's tweet pages on a domain."""

        rows = self._cdx(
            url=f"{domain}/{user}/status/*",
            fl="timestamp,original",
            filter="!statuscode:404",
        )

        return None if rows is None else [Capture(row[0], row[1]) for row in rows]

    def variants(self, media_id: str) -> list[Capture]:
        """Get captures of a piece of media, best resolution first."""

        rows = self._cdx(
            url=f"pbs.twimg.com/media/{media_id}*",
            fl="timestamp,original,mimetype",
            filter="statuscode:200",
        )

        if rows is None:
            return []

        return sorted(
            (Capture(row[0], row[1]) for row in rows if not row[2].startswith("text/")),
            key=resolution_rank,
        )

    def page(self, capture: Capture) -> str | None:
        """Get a captured document as HTML."""

        response = self._replay(capture, "id")

        if response is None or response.status_code != 200:
            return None

        return response.text

    def image(self, capture: Capture) -> Response | None:
        """Get a captured image as a Response."""

        response = self._replay(capture, "im")

        if response is None or not response.ok:
            return None

        return response

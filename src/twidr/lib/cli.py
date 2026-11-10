"""Constructs for command-line argument parsing."""

import re
from argparse import ArgumentParser, ArgumentTypeError
from pathlib import Path
from typing import Final

from . import defaults, meta

HANDLE_RE: Final = re.compile(r"[A-Za-z0-9_]{1,15}")
DOMAIN_RE: Final = re.compile(r"[a-z0-9\-]+(?:\.[a-z0-9\-]+)+")


def handle(value: str) -> str:
    h = value.lstrip("@")

    if not HANDLE_RE.fullmatch(h):
        raise ArgumentTypeError(
            f"{value!r} is not a valid handle; must be 1–15 letters, digits, or underscores"
        )

    return h


def domain(value: str) -> str:
    d = value.lower()

    if not DOMAIN_RE.fullmatch(d):
        raise ArgumentTypeError(
            f"{value!r} is not a valid domain (expected something like twitter.com)"
        )

    return d


def positive_float(value: str) -> float:
    f = float(value)

    if f <= 0:
        raise ArgumentTypeError("Must be > 0")

    return f


def positive_int(value: str) -> int:
    i = int(value)

    if i < 1:
        raise ArgumentTypeError("Must be >= 1")

    return i


def parser() -> ArgumentParser:
    """Get an ArgumentParser instance preconfigured for this program."""

    p = ArgumentParser(description=meta.APP_DESCRIPTION)

    p.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"🐦️ {meta.APP_NAME}, {meta.PROJECT_DESCRIPTION} ({meta.ORG_DOMAIN}) {meta.VERSION}",
    )

    p.add_argument("username", type=handle, help="account handle, with or without @")

    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="directory for media and state files (default: a directory named after the handle)",
    )

    p.add_argument(
        "--domain",
        type=domain,
        action="append",
        default=None,
        help=(
            "archived domain to search (repeat the argument for multiple; "
            f"domains tried in order; default {", ".join(defaults.DOMAINS)})"
        ),
    )

    p.add_argument(
        "--max-attempts",
        type=positive_int,
        default=defaults.MAX_ATTEMPTS,
        help=f"attempts per request before giving up (default {defaults.MAX_ATTEMPTS})",
    )

    p.add_argument(
        "--refresh-index",
        action="store_true",
        help="requery the Wayback Machine's CDX index for the account",
    )

    p.add_argument(
        "--retry-failed",
        action="store_true",
        help="retry tweets or images that failed or yielded no media in previous runs",
    )

    p.add_argument(
        "-t",
        "--threads",
        type=positive_int,
        default=defaults.NUM_WORKERS,
        help=f"number of parallel worker threads (default {defaults.NUM_WORKERS})",
    )

    p.add_argument(
        "--rate",
        type=positive_float,
        default=defaults.RATE,
        help=f"max total requests per second across all workers (default {defaults.RATE})",
    )

    return p

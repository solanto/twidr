"""Configurable and pyproject.toml-derived information about this program."""

from importlib.metadata import metadata
from typing import Final

APP_NAME: Final = "twidr"
APP_DESCRIPTION: Final = (
    "download images from the Wayback Machine's snapshots of a Twitter (X) account"
)
ORG_DOMAIN: Final = "dandelion.computer"

_meta = metadata(APP_NAME)

VERSION: Final = _meta["Version"]
PROJECT_DESCRIPTION: Final = _meta["Summary"]

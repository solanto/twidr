# PYTHON_ARGCOMPLETE_OK

"""Load and cache CDX indices from the Wayback Machine, rank image results, and parallel-process tweets to download their media."""

import json
import re
import time
from collections import OrderedDict, defaultdict
from collections.abc import Mapping
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from types import MappingProxyType
from typing import Any, Final, Literal, NamedTuple, Self

from argcomplete import autocomplete
from tqdm import tqdm

from .lib import cli, defaults
from .lib.client import Client
from .lib.wayback import Capture, Wayback

MEDIA_RE: Final = re.compile(
    r"https?:(?:\\?/){2}pbs\.twimg\.com(?:\\?/)media(?:\\?/)[\w\-]+"
)

TWEET_ID_RE: Final = re.compile(r"/status/(\d+)")

FILETYPES: Final = MappingProxyType(
    {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/gif": "gif",
        "image/webp": "webp",
    }
)


@dataclass(frozen=True)
class Config:
    """Program preferences and paths."""

    user: str
    directory: Path
    domains: tuple[str, ...]

    @property
    def index_file(self) -> Path:
        return self.directory / ".index.json"

    @property
    def progress_file(self) -> Path:
        return self.directory / ".progress.jsonl"


class TweetEntry(NamedTuple):
    """A tweet and its captures in the order they should be tried."""

    tweet_id: str
    captures: list[Capture]


type CaptureIndex = Mapping[str, list[Capture]]

type ResultStatus = Literal["done", "no_media"]


def result_status(status: str) -> ResultStatus:
    """Create a ResultStatus from the given string."""

    if status in ("done", "no_media"):
        return status
    else:
        raise ValueError(f"Invalid result status {str(status)!r}")


@dataclass
class Stats:
    """Statistics to be aggregated from download workers."""

    images: int = 0
    no_media: int = 0
    failed: int = 0
    fetch_errors: int = 0
    pages_fetched: int = 0
    twimg_but_no_match: int = 0

    def merge(self, other: Self) -> None:
        """Absorb a worker's statistics into this Stats object."""

        self.images += other.images
        self.no_media += other.no_media
        self.failed += other.failed
        self.fetch_errors += other.fetch_errors
        self.pages_fetched += other.pages_fetched
        self.twimg_but_no_match += other.twimg_but_no_match


@dataclass(frozen=True)
class TweetResult:
    """The final record of a tweet's media: what was found and what was saved."""

    status: ResultStatus
    media: Mapping[str, bool]

    @property
    def saved(self) -> int:
        return sum(self.media.values())

    @property
    def failed_ids(self) -> list[str]:
        return [media_id for media_id, ok in self.media.items() if not ok]

    @property
    def complete(self) -> bool:
        return self.status == "done" and all(self.media.values())

    def needs_work(self, retry_failed: bool) -> bool:
        """Return whether the tweet still needs to be processed or reprocessed."""

        return retry_failed and not self.complete

    def merged(self, other: Self) -> Self:
        """Combine with a newer result; the newer status wins and media accumulates."""

        return type(self)(other.status, {**self.media, **other.media})

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Self:
        """Create a TweetResult from data providing "status" and "media" keys."""

        status, media = data["status"], data["media"]

        if not isinstance(status, str):
            raise ValueError(f"Invalid result status {status!r}")

        if not isinstance(media, Mapping) or not all(
            isinstance(k, str) and isinstance(v, bool) for k, v in media.items()
        ):
            raise ValueError("Invalid media mapping")

        return cls(result_status(status), dict(media))

    def to_mapping(self, tweet_id: str) -> dict[str, Any]:
        """Return the result as data with "tweet", "status", and "media" keys."""

        return {"tweet": tweet_id, "status": self.status, "media": dict(self.media)}


@dataclass
class TweetOutcome:
    """The data a worker hands back to the main thread for each tweet.

    result covers only what this run attempted and is None if the worker was
    interrupted, in which case the tweet must be reprocessed.
    """

    tweet_id: str
    stats: Stats = field(default_factory=Stats)
    result: TweetResult | None = None


class Claims:
    """An atomic journal of the media items that have been processed."""

    def __init__(self, initial: set[str]) -> None:
        """Create a new Claims object from an initial set of seen items."""

        self._lock = Lock()
        self._seen = set(initial)

    def claim(self, media_id: str) -> bool:
        """Return True for an unclaimed item and False otherwise."""

        with self._lock:
            if media_id in self._seen:
                return False

            self._seen.add(media_id)

            return True


def build_index(wayback: Wayback, config: Config) -> tuple[CaptureIndex, bool]:
    """Use a Wayback client to query and create a local index of archived tweets."""

    index: defaultdict[str, list[Capture]] = defaultdict(list)
    complete = True

    for domain in config.domains:
        print(f"🏛️ querying CDX index for {domain}/{config.user}…", flush=True)

        captures = wayback.captures(config.user, domain)

        if captures is None:
            print(f"└─⛔️ CDX lookup failed for {domain}", flush=True)

            complete = False

            continue

        print(f"└─📸 {len(captures)} captures found", flush=True)

        for capture in sorted(captures):
            match: re.Match[str] | None = TWEET_ID_RE.search(capture.original)

            if match:
                index[match.group(1)].append(capture)

    return dict(index), complete


def save_index(config: Config, index: CaptureIndex) -> None:
    """Cache an index of archived tweets to disk."""

    data: dict[str, Any] = {
        "user": config.user,
        "domains": list(config.domains),
        "fetched_at": time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime()),
        "tweets": {
            tweet_id: [list(capture) for capture in captures]
            for tweet_id, captures in index.items()
        },
    }

    tmp = config.index_file.with_name(config.index_file.name + ".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(config.index_file)


def load_index(config: Config) -> CaptureIndex | None:
    """Load a cached index of archived tweets from disk."""

    if not config.index_file.exists():
        return None

    try:
        data: dict[str, Any] = json.loads(config.index_file.read_text(encoding="utf-8"))

        # priorities depend on domain order; a different list invalidates the cache
        if data["user"] != config.user or data["domains"] != list(config.domains):
            return None

        index: CaptureIndex = {
            tweet_id: [Capture(str(t), str(o)) for t, o in captures]
            for tweet_id, captures in data["tweets"].items()
        }

        print(f"🗄️ using cached index from {data['fetched_at']} ({len(index)} tweets)")

        return index
    except (ValueError, KeyError, TypeError):
        return None


def load_progress(config: Config) -> dict[str, TweetResult]:
    """Load previous runs' progress from disk."""

    progress: dict[str, TweetResult] = {}

    if not config.progress_file.exists():
        return progress

    with config.progress_file.open(encoding="utf-8") as file:
        for line in file:
            try:
                record = json.loads(line)

                progress[str(record["tweet"])] = TweetResult.from_mapping(record)

            # ignore invalid (i.e., truncated) lines
            except (ValueError, KeyError, TypeError):
                continue

    return progress


def log_result(config: Config, tweet_id: str, result: TweetResult) -> None:
    """Log a TweetResult."""

    with config.progress_file.open("a", encoding="utf-8") as file:
        file.write(json.dumps(result.to_mapping(tweet_id)) + "\n")


def count_saved(progress: Mapping[str, TweetResult]) -> int:
    """Get the number of images saved across all runs."""

    return sum(result.saved for result in progress.values())


def already_saved(config: Config, media_id: str) -> bool:
    """Return whether a media item is already present on disk."""

    return any(
        not p.name.endswith(".part") for p in config.directory.glob(f"*_{media_id}.*")
    )


def download_image(
    config: Config, wayback: Wayback, media_id: str, tweet_id: str
) -> bool:
    """Use a Wayback client to download a media item from a tweet."""

    if already_saved(config, media_id):
        return True

    for capture in wayback.variants(media_id)[:3]:
        response = wayback.image(capture)

        if response is None:
            continue

        content_type = response.headers.get("content-type", "").split(";")[0]

        if content_type in FILETYPES:
            final = (
                config.directory / f"{tweet_id}_{media_id}.{FILETYPES[content_type]}"
            )

            part = final.with_name(final.name + ".part")
            part.write_bytes(response.content)
            part.replace(final)

            return True

    return False


def process_tweet(
    config: Config,
    wayback: Wayback,
    entry: TweetEntry,
    claims: Claims,
) -> TweetOutcome:
    """Download a tweet's media from its first media-containing capture.

    Captures are tried in order of domain priority, then oldest to newest.
    """

    tweet_id = entry.tweet_id
    stats = Stats()
    media: dict[str, bool] = {}
    found = False

    for capture in entry.captures:
        if wayback.stop.is_set():
            return TweetOutcome(tweet_id, stats)

        html = wayback.page(capture)

        if html is None:
            stats.fetch_errors += 1
        else:
            stats.pages_fetched += 1

        urls: set[str] = (
            {u.replace("\\", "") for u in MEDIA_RE.findall(html)} if html else set()
        )

        stats.twimg_but_no_match += bool(html and not urls and "twimg" in html)

        if not urls:
            continue

        for media_id in sorted({u.rsplit("/", 1)[-1] for u in urls}):
            if not claims.claim(media_id):
                continue

            if wayback.stop.is_set():
                return TweetOutcome(tweet_id, stats)

            ok = download_image(config, wayback, media_id, tweet_id)

            media[media_id] = ok

            if ok:
                stats.images += 1
            else:
                stats.failed += 1

        found = True

        break

    # in the case that the worker is interrupted, don't assume no media
    if wayback.stop.is_set() and not found:
        return TweetOutcome(tweet_id, stats)

    return TweetOutcome(
        tweet_id, stats, TweetResult("done" if found else "no_media", media)
    )


def main() -> None:
    parser = cli.parser()
    autocomplete(parser)
    args = parser.parse_args()

    wayback = Wayback(Client(rate=args.rate, max_attempts=args.max_attempts))

    config = Config(
        user=args.username,
        directory=args.output or Path(args.username),
        domains=tuple(dict.fromkeys(args.domain or defaults.DOMAINS)),
    )

    config.directory.mkdir(parents=True, exist_ok=True)

    for stale in config.directory.glob("*.part"):
        stale.unlink(missing_ok=True)

    print(f"💾 saving to {config.directory}")

    index = None if args.refresh_index else load_index(config)

    if index is None:
        index, complete = build_index(wayback, config)

        if complete:
            save_index(config, index)
        else:
            print(
                "⚠️ index incomplete (a CDX lookup likely failed); not caching; rerun to retry"
            )

    progress = load_progress(config)

    retry_failed: bool = args.retry_failed

    pending = sorted(
        (
            TweetEntry(tweet_id, captures)
            for tweet_id, captures in index.items()
            if (r := progress.get(tweet_id)) is None or r.needs_work(retry_failed)
        ),
        key=lambda entry: int(entry.tweet_id),
    )

    print(
        "🧠 "
        f"{len(index)} tweets in index, {len(index) - len(pending)} already handled, "
        f"{len(pending)} to process "
        f"({args.threads} threads @ ≤{args.rate:g} req/s)\n",
        flush=True,
    )

    initial: set[str] = set()

    for result in progress.values():
        for mid, ok in result.media.items():
            if ok or not retry_failed:
                initial.add(mid)

    claims = Claims(initial)
    stats = Stats()

    progress_bar: tqdm = tqdm(total=len(pending), unit="twt", desc=config.user)

    postfix = OrderedDict(
        {
            "images": stats.images,
            "no media": stats.no_media,
            "failed": stats.failed,
            "errors": stats.fetch_errors,
        }
    )

    executor = ThreadPoolExecutor(max_workers=args.threads)

    futures: list[Future[TweetOutcome]] = [
        executor.submit(process_tweet, config, wayback, entry, claims)
        for entry in pending
    ]

    try:
        for future in as_completed(futures):
            outcome = future.result()

            run_result = outcome.result

            # interrupted; the tweet gets redone on resume
            if run_result is None:
                continue

            stats.merge(outcome.stats)

            stats.no_media += run_result.status == "no_media"

            for mid in run_result.failed_ids:
                tqdm.write(f"no archived copy of {mid} (tweet {outcome.tweet_id})")

            previous_result = progress.get(outcome.tweet_id)

            tweet_result = (
                previous_result.merged(run_result) if previous_result else run_result
            )

            progress[outcome.tweet_id] = tweet_result

            log_result(config, outcome.tweet_id, tweet_result)

            postfix["images"] = stats.images
            postfix["no media"] = stats.no_media
            postfix["failed"] = stats.failed
            postfix["errors"] = stats.fetch_errors

            progress_bar.update(1)
            progress_bar.set_postfix(postfix)

    except KeyboardInterrupt:
        print("\n⚠️ interrupted; finishing requests in flight and saving progress")
    finally:
        wayback.stop.set()

        executor.shutdown(wait=True, cancel_futures=True)

        progress_bar.close()

    print(
        f"\n🐦️\n"
        f"this run: {stats.images} images saved, {stats.no_media} tweets with no media, "
        f"{stats.failed} failed downloads\n"
        f"pages fetched: {stats.pages_fetched}, fetch errors: {stats.fetch_errors}, "
        f"pages mentioning twimg without a match: {stats.twimg_but_no_match}\n"
        f"{count_saved(progress)} images saved in total in {config.directory}"
    )


if __name__ == "__main__":
    main()

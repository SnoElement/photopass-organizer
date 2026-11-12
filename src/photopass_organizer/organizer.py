"""Discover PhotoPass downloads, plan where each item belongs, and carry the plan out."""

from __future__ import annotations

import logging
import os
import re
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from enum import Enum
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import LEDGER_NAME, LOG_NAME, Config, ShareMethod
from .ledger import ALREADY_HANDLED, Ledger
from .media import (
    RESORT_BY_TIMEZONE,
    event_name,
    has_embedded_color_profile,
    hash_file,
    is_folder_name,
    is_uuid_folder_name,
    park_timezone_name,
    parse_loose_video_name,
    parse_photopass_name,
    read_photo_capture_time,
    read_video_creation_time_utc,
    resort_name,
    unknown_parks,
)
from .shared import SharedFolderIndex

log = logging.getLogger(__name__)

PENDING_IMPORT_NAME = "pending-import"
TRIP_RANGE_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:\.\.(\d{4}-\d{2}-\d{2}))?$")
IGNORED_NAMES = {".DS_Store"}
VIDEO_PAIRING_MAX_MINUTES = 180
EXIF_FILENAME_MAX_GAP_DAYS = 2
NO_EXIF_TIME_OF_DAY = time(
    12, 0
)  # noon keeps the day stable when Photos shows it in another timezone


class PlaceMode(Enum):
    MOVE = "move"
    COPY = "copy"


class ActionKind(Enum):
    SHARE = "share"
    PLACE = "place"
    DELETE = "delete"
    DUPLICATE = "duplicate"
    STOCK = "stock"
    SKIP = "skip"


class StockPolicy(Enum):
    DELETE = "delete"
    KEEP = "keep"


STOCK_FOLDER_NAME = "_Stock art"


@dataclass(frozen=True)
class TripRange:
    start: date
    end: date

    @classmethod
    def parse(cls, text: str) -> TripRange:
        matched = TRIP_RANGE_PATTERN.match(text.strip())
        if matched is None:
            raise ValueError(
                f"expected YYYY-MM-DD or YYYY-MM-DD..YYYY-MM-DD, got {text!r}"
            )
        start = date.fromisoformat(matched.group(1))
        end = date.fromisoformat(matched.group(2) or matched.group(1))
        if end < start:
            raise ValueError(f"trip range ends before it starts: {text!r}")
        return cls(start, end)

    def contains(self, local_date: date) -> bool:
        return self.start <= local_date <= self.end


@dataclass
class MediaItem:
    source: Path
    park: str | None
    captured_at: datetime | None
    is_video: bool
    content_hash: str
    size_bytes: int
    date_source: str
    is_stock: bool = False
    paired_still: Path | None = None
    event: str | None = None

    @property
    def local_date(self) -> str | None:
        return self.captured_at.date().isoformat() if self.captured_at else None


@dataclass
class Discovery:
    batch_folders: list[Path] = field(default_factory=list)
    media_files: list[Path] = field(default_factory=list)
    loose_videos: list[Path] = field(default_factory=list)
    foreign_folders: list[Path] = field(default_factory=list)
    empty_uuid_folders: list[Path] = field(default_factory=list)


@dataclass
class Action:
    kind: ActionKind
    source: Path
    target: Path | None = None
    reason: str = ""
    captured_at: datetime | None = None
    content_hash: str = ""
    friend: str | None = None


@dataclass
class Plan:
    actions: list[Action]
    discovery: Discovery
    items: list[MediaItem]
    unknown_parks: list[str] = field(default_factory=list)


@dataclass
class Summary:
    placed: int = 0
    shared: int = 0
    deleted: int = 0
    duplicates: int = 0
    stock: int = 0
    skipped: int = 0
    undecided: int = 0
    ignored: int = 0
    folders_removed: int = 0
    import_files: dict[Path, set[Path]] = field(default_factory=dict)
    album_shares: dict[str, list[tuple[Path, str]]] = field(default_factory=dict)
    pending_import_folders: dict[str, Path] = field(default_factory=dict)
    staged_shares: dict[str, list[tuple[Path, str]]] = field(default_factory=dict)
    unknown_parks: list[str] = field(default_factory=list)


def _visible_children(folder: Path) -> list[Path]:
    return [
        child
        for child in folder.iterdir()
        if child.name not in IGNORED_NAMES and not child.name.startswith(".")
    ]


class Organizer:
    def __init__(
        self,
        config: Config,
        state_dir: Path,
        mode: PlaceMode = PlaceMode.MOVE,
        dry_run: bool = False,
        shared_index: SharedFolderIndex | None = None,
        trip: TripRange | None = None,
    ) -> None:
        self.config = config
        self.source = config.settings.source
        self.destination = config.settings.destination
        self.default_timezone = config.settings.default_timezone
        self.stock_policy = StockPolicy(config.settings.stock_art)
        self.state_dir = state_dir
        self.mode = mode
        self.dry_run = dry_run
        self.trip = trip
        self.ledger = Ledger.load(state_dir / LEDGER_NAME)
        self.shared_index = (
            shared_index
            if shared_index is not None
            else SharedFolderIndex.load(config.folder_friends())
        )
        self._destination_files: dict[str, Path] | None = None

    def _timezone_name(self, park: str | None) -> str:
        return park_timezone_name(
            park, self.default_timezone, self.config.settings.parks
        )

    def _scan_destination(self) -> dict[str, Path]:
        if self._destination_files is None:
            found: dict[str, Path] = {}
            if self.destination.is_dir():
                for existing in sorted(self.destination.rglob("*")):
                    if existing.is_file() and not existing.name.startswith("."):
                        found.setdefault(hash_file(existing), existing)
            self._destination_files = found
        return self._destination_files

    def destination_hashes(self) -> set[str]:
        return set(self._scan_destination())

    def discover(self) -> Discovery:
        discovery = Discovery()
        for entry in sorted(self.source.iterdir()):
            if entry.is_dir() and is_uuid_folder_name(entry.name):
                children = _visible_children(entry)
                if not children:
                    discovery.empty_uuid_folders.append(entry)
                elif all(parse_photopass_name(child.name) for child in children):
                    discovery.batch_folders.append(entry)
                    discovery.media_files.extend(sorted(children))
                else:
                    discovery.foreign_folders.append(entry)
                    log.info("Leaving folder with non-PhotoPass files alone: %s", entry)
            elif entry.is_file() and parse_loose_video_name(entry.name):
                discovery.loose_videos.append(entry)
            elif entry.is_file() and parse_photopass_name(entry.name):
                discovery.media_files.append(entry)
        return discovery

    def _trusted_capture_time(self, path: Path, parsed) -> tuple[datetime | None, str]:
        """Capture time from metadata, or None when it is missing or contradicts the filename date.

        Stock art keeps the EXIF of the template it was made from, often years off; on-ride
        photos have no EXIF at all. The filename date is UTC, so a genuine capture time is
        within a day of it; EXIF_FILENAME_MAX_GAP_DAYS allows one more day of slack.
        """
        timezone_name = self._timezone_name(parsed.park)
        if parsed.extension == "mp4":
            created_utc = read_video_creation_time_utc(path)
            captured = (
                created_utc.astimezone(ZoneInfo(timezone_name)) if created_utc else None
            )
            source = "container"
        else:
            captured = read_photo_capture_time(path)
            if captured is not None and captured.tzinfo is None:
                captured = captured.replace(tzinfo=ZoneInfo(timezone_name))
            source = "exif"
        if captured is None:
            return None, source
        filename_date = datetime.fromisoformat(parsed.filename_date).date()
        if abs((captured.date() - filename_date).days) > EXIF_FILENAME_MAX_GAP_DAYS:
            return None, "implausible"
        return captured, source

    def _date_media_files(self, paths: list[Path]) -> list[MediaItem]:
        parsed_by_path = {path: parse_photopass_name(path.name) for path in paths}
        hashes = {path: hash_file(path) for path in paths}
        kept = {
            path
            for path, digest in hashes.items()
            if (override := self.config.photos.get(digest)) is not None
            and override.action == "keep"
        }
        trusted: dict[Path, tuple[datetime, str]] = {}
        local_dates_by_group: dict[tuple[str, str], Counter] = defaultdict(Counter)
        stock_paths: set[Path] = set()
        for path, parsed in parsed_by_path.items():
            captured, source = self._trusted_capture_time(path, parsed)
            if (
                parsed.extension != "mp4"
                and path not in kept
                and (source == "implausible" or has_embedded_color_profile(path))
            ):
                stock_paths.add(path)
                continue
            if captured is not None:
                trusted[path] = (captured, source)
                local_dates_by_group[(parsed.filename_date, parsed.park)][
                    captured.date()
                ] += 1
        items = []
        for path, parsed in parsed_by_path.items():
            timezone_name = self._timezone_name(parsed.park)
            if path in stock_paths:
                captured = datetime.fromisoformat(parsed.filename_date).replace(
                    tzinfo=ZoneInfo(timezone_name)
                )
                items.append(
                    MediaItem(
                        path,
                        parsed.park,
                        captured,
                        False,
                        hashes[path],
                        path.stat().st_size,
                        "stock",
                        is_stock=True,
                    )
                )
                continue
            if path in trusted:
                captured, source = trusted[path]
            else:
                neighbours = local_dates_by_group.get(
                    (parsed.filename_date, parsed.park)
                )
                if neighbours:
                    local_date = neighbours.most_common(1)[0][0]
                    source = "neighbours"
                else:
                    local_date = datetime.fromisoformat(parsed.filename_date).date()
                    source = "filename"
                captured = datetime.combine(
                    local_date, NO_EXIF_TIME_OF_DAY, tzinfo=ZoneInfo(timezone_name)
                )
                log.log(
                    logging.INFO if neighbours else logging.WARNING,
                    "No usable capture time in %s; dated by %s as %s",
                    path.name,
                    source,
                    local_date,
                )
            items.append(
                MediaItem(
                    path,
                    parsed.park,
                    captured,
                    parsed.extension == "mp4",
                    hashes[path],
                    path.stat().st_size,
                    source,
                    event=event_name(parsed.park, parsed.location),
                )
            )
        return items

    def _date_loose_video(
        self, path: Path, dated_items: list[MediaItem]
    ) -> MediaItem | None:
        """Ride videos pair with a still shot minutes apart; the nearest timed photo gives park and timezone."""
        created_utc = read_video_creation_time_utc(path)
        if created_utc is None:
            return None
        timed_photos = [
            item
            for item in dated_items
            if not item.is_video
            and not item.is_stock
            and item.date_source in ("exif", "container")
        ]
        nearest = min(
            timed_photos,
            key=lambda item: abs(item.captured_at - created_utc),
            default=None,
        )
        if (
            nearest is not None
            and abs(nearest.captured_at - created_utc).total_seconds()
            <= VIDEO_PAIRING_MAX_MINUTES * 60
        ):
            captured = created_utc.astimezone(nearest.captured_at.tzinfo)
            return MediaItem(
                path,
                nearest.park,
                captured,
                True,
                hash_file(path),
                path.stat().st_size,
                "paired",
                paired_still=nearest.source,
                event=nearest.event,
            )
        timezone_name = (
            self._timezone_name(nearest.park)
            if nearest is not None
            else self.default_timezone
        )
        captured = created_utc.astimezone(ZoneInfo(timezone_name))
        same_day_parks = {
            item.park
            for item in dated_items
            if item.local_date == captured.date().isoformat()
            and item.park
            and not item.is_stock
        }
        park = (
            next(iter(same_day_parks))
            if len(same_day_parks) == 1
            else resort_name(timezone_name)
        )
        return MediaItem(
            path,
            park,
            captured,
            True,
            hash_file(path),
            path.stat().st_size,
            "container",
        )

    def _folder(self, item: MediaItem) -> Path:
        """Where an item is filed under the destination; a special event is filed under its own name."""
        place = item.event or item.park
        if not is_folder_name(place):
            raise ValueError(f"{place!r} cannot be used as a folder name")
        layout = self.config.settings.layout
        if layout == "date/park":
            return Path(item.local_date) / place
        if layout == "park/date":
            return Path(place) / item.local_date
        return Path(f"{item.local_date} - {place}")

    def _unique_target(self, folder: Path, name: str, reserved: set[Path]) -> Path:
        candidate = folder / name
        stem, suffix = os.path.splitext(name)
        counter = 2
        while candidate in reserved or candidate.exists():
            candidate = folder / f"{stem} ({counter}){suffix}"
            counter += 1
        return candidate

    def _share_actions(
        self,
        item: MediaItem,
        friends: tuple[str, ...],
        reserved_targets: set[Path],
        planned_shares: dict[str, set[str]],
    ) -> list[Action]:
        if self.ledger.is_complete(item.content_hash):
            return []
        actions = []
        already = (
            self.shared_index.friends_holding(item.source.name, item.size_bytes)
            | self.ledger.shared_with(item.content_hash)
            | planned_shares[item.content_hash]
        )
        for name in friends:
            if name in already:
                continue
            planned_shares[item.content_hash].add(name)
            if self.config.friend(name).share is ShareMethod.PHOTOS_ALBUM:
                actions.append(
                    Action(
                        ActionKind.SHARE,
                        item.source,
                        None,
                        "",
                        item.captured_at,
                        item.content_hash,
                        friend=name,
                    )
                )
                continue
            target = self._unique_target(
                self.shared_index.folder_for(name), item.source.name, reserved_targets
            )
            reserved_targets.add(target)
            actions.append(
                Action(
                    ActionKind.SHARE,
                    item.source,
                    target,
                    "",
                    item.captured_at,
                    item.content_hash,
                    friend=name,
                )
            )
        return actions

    def _handled(
        self, item: MediaItem, planned: dict[str, Path | None]
    ) -> tuple[bool, Path | None]:
        if item.content_hash in planned:
            return True, planned[item.content_hash]
        if item.content_hash in self.ledger:
            recorded = self.ledger.path_for(item.content_hash)
            return True, None if recorded == ALREADY_HANDLED else Path(recorded)
        destination_files = self._scan_destination()
        if item.content_hash in destination_files:
            return True, destination_files[item.content_hash]
        return bool(
            self.shared_index.friends_holding(item.source.name, item.size_bytes)
        ), None

    def plan(self) -> Plan:
        discovery = self.discover()
        items = self._date_media_files(discovery.media_files)
        actions: list[Action] = []
        for video_path in discovery.loose_videos:
            video_item = self._date_loose_video(video_path, items)
            if video_item is None:
                actions.append(
                    Action(
                        ActionKind.SKIP,
                        video_path,
                        reason="no creation time in the MP4 header",
                    )
                )
                log.info(
                    "Skipping %s: no creation time in the MP4 header", video_path.name
                )
            else:
                items.append(video_item)
        resort_names = set(RESORT_BY_TIMEZONE.values())
        missing_timezones = unknown_parks(
            (
                item.park
                for item in items
                if item.park and item.park not in resort_names
            ),
            self.config.settings.parks,
        )
        if missing_timezones:
            log.warning(
                "parks without a timezone, dated with %s: %s",
                self.default_timezone,
                ", ".join(missing_timezones),
            )
        planned: dict[str, Path | None] = {}
        planned_shares: dict[str, set[str]] = defaultdict(set)
        reserved_targets: set[Path] = set()
        for item in sorted(
            items, key=lambda media: (media.captured_at, media.source.name)
        ):
            if item.is_stock:
                stock_target = None
                if self.stock_policy is StockPolicy.KEEP:
                    stock_target = self._unique_target(
                        self.destination / STOCK_FOLDER_NAME,
                        item.source.name,
                        reserved_targets,
                    )
                    reserved_targets.add(stock_target)
                actions.append(
                    Action(
                        ActionKind.STOCK,
                        item.source,
                        stock_target,
                        "Disney stock art",
                        item.captured_at,
                        item.content_hash,
                    )
                )
                continue
            local_date = item.captured_at.date()
            override = self.config.photos.get(item.content_hash)
            if override is not None and override.action == "ignore":
                planned[item.content_hash] = None
                actions.append(
                    Action(
                        ActionKind.DELETE,
                        item.source,
                        None,
                        "ignored photo",
                        item.captured_at,
                        item.content_hash,
                    )
                )
                continue
            rule = self.config.rule_for(local_date, item.park)
            in_scope = self.trip is None or self.trip.contains(local_date)
            handled, known_target = self._handled(item, planned)
            if handled:
                if rule is not None and in_scope:
                    actions.extend(
                        self._share_actions(
                            item, rule.friends, reserved_targets, planned_shares
                        )
                    )
                actions.append(
                    Action(
                        ActionKind.DUPLICATE,
                        item.source,
                        known_target,
                        "same content previously processed",
                        item.captured_at,
                        item.content_hash,
                    )
                )
                continue
            if rule is None:
                actions.append(
                    Action(
                        ActionKind.SKIP,
                        item.source,
                        None,
                        "undecided",
                        item.captured_at,
                        item.content_hash,
                    )
                )
                continue
            if not in_scope:
                actions.append(
                    Action(
                        ActionKind.SKIP,
                        item.source,
                        None,
                        "outside --trip",
                        item.captured_at,
                        item.content_hash,
                    )
                )
                continue
            if rule.ignore:
                planned[item.content_hash] = None
                actions.append(
                    Action(
                        ActionKind.DELETE,
                        item.source,
                        None,
                        "ignored day",
                        item.captured_at,
                        item.content_hash,
                    )
                )
                continue
            actions.extend(
                self._share_actions(
                    item, rule.friends, reserved_targets, planned_shares
                )
            )
            if not rule.i_was_there:
                planned[item.content_hash] = None
                actions.append(
                    Action(
                        ActionKind.DELETE,
                        item.source,
                        None,
                        "friend's trip, not mine",
                        item.captured_at,
                        item.content_hash,
                    )
                )
                continue
            target = self._unique_target(
                self.destination / self._folder(item),
                item.source.name,
                reserved_targets,
            )
            reserved_targets.add(target)
            planned[item.content_hash] = target
            actions.append(
                Action(
                    ActionKind.PLACE,
                    item.source,
                    target,
                    item.date_source,
                    item.captured_at,
                    item.content_hash,
                )
            )
        return Plan(
            actions=actions,
            discovery=discovery,
            items=items,
            unknown_parks=missing_timezones,
        )

    def _record(self, log_handle, message: str) -> None:
        log.info(message)
        if log_handle is not None:
            log_handle.write(
                f"{datetime.now(UTC).isoformat(timespec='seconds')} {message}\n"
            )

    def _hand_off_to_albums(
        self,
        action: Action,
        friends: list[str],
        summary: Summary,
        log_handle,
        created: list[Path],
    ) -> None:
        """Make a file that is about to leave the source folder reachable for each album friend."""
        if not friends:
            return
        if action.target is not None and action.target.is_file():
            summary.import_files.setdefault(action.target.parent, set()).add(
                action.target
            )
            for friend in friends:
                summary.album_shares.setdefault(friend, []).append(
                    (action.target, action.content_hash)
                )
            return
        for position, friend in enumerate(friends):
            folder = self.state_dir / PENDING_IMPORT_NAME / friend
            if self.dry_run:
                self._record(
                    log_handle,
                    f"Would stage {action.source} for Photos album {friend} in {folder}",
                )
                continue
            staged = self._unique_target(folder, action.source.name, set())
            staged.parent.mkdir(parents=True, exist_ok=True)
            if self.mode is PlaceMode.MOVE and position == len(friends) - 1:
                shutil.move(str(action.source), str(staged))
            else:
                shutil.copy2(action.source, staged)
                created.append(staged)
            summary.pending_import_folders[friend] = folder
            summary.staged_shares.setdefault(friend, []).append(
                (staged, action.content_hash)
            )
            self._record(log_handle, f"staged {staged} for Photos album {friend}")

    def _copy_share(self, share: Action, log_handle, created: list[Path]) -> None:
        prefix = "Would " if self.dry_run else ""
        if share.target is None:
            verb = "import" if self.dry_run else "queue"
            self._record(
                log_handle,
                f"{prefix}{verb} {share.source} into Photos album {share.friend}",
            )
            return
        self._record(log_handle, f"{prefix}share {share.source} -> {share.target}")
        if not self.dry_run:
            share.target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(share.source, share.target)
            created.append(share.target)

    def _finish_item(
        self,
        action: Action,
        album_friends: list[str],
        summary: Summary,
        log_handle,
        created: list[Path],
    ) -> None:
        prefix = "Would " if self.dry_run else ""
        if action.kind is ActionKind.DELETE:
            verb = "delete" if self.mode is PlaceMode.MOVE else "leave"
            self._record(log_handle, f"{prefix}{verb} {action.source}: {action.reason}")
            self._hand_off_to_albums(
                action, album_friends, summary, log_handle, created
            )
            if not self.dry_run:
                self.ledger.record_deleted(action.content_hash, action.reason)
                if self.mode is PlaceMode.MOVE:
                    action.source.unlink(missing_ok=True)
            if action.reason.startswith("ignored"):
                summary.ignored += 1
            else:
                summary.deleted += 1
        elif action.kind is ActionKind.PLACE:
            self._record(
                log_handle,
                f"{prefix}{self.mode.value} {action.source} -> {action.target}",
            )
            if not self.dry_run:
                action.target.parent.mkdir(parents=True, exist_ok=True)
                if self.mode is PlaceMode.MOVE:
                    shutil.move(str(action.source), str(action.target))
                else:
                    shutil.copy2(action.source, action.target)
                if action.captured_at is not None:
                    stamp = action.captured_at.timestamp()
                    os.utime(action.target, (stamp, stamp))
                self.ledger.record_placed(action.content_hash, action.target)
            for friend in album_friends:
                summary.album_shares.setdefault(friend, []).append(
                    (action.target, action.content_hash)
                )
            summary.import_files.setdefault(action.target.parent, set()).add(
                action.target
            )
            summary.placed += 1
        else:
            verb = (
                "delete duplicate" if self.mode is PlaceMode.MOVE else "skip duplicate"
            )
            same_as = f" (same as {action.target})" if action.target is not None else ""
            self._record(log_handle, f"{prefix}{verb} {action.source}{same_as}")
            self._hand_off_to_albums(
                action, album_friends, summary, log_handle, created
            )
            if not self.dry_run and self.mode is PlaceMode.MOVE:
                action.source.unlink(missing_ok=True)
            summary.duplicates += 1

    def _run_item(
        self, action: Action, shares: list[Action], summary: Summary, log_handle
    ) -> None:
        """Shares and the final action of one photo succeed together; the ledger learns of them only afterwards."""
        created: list[Path] = []
        completed = False
        try:
            for share in shares:
                self._copy_share(share, log_handle, created)
            self._finish_item(
                action,
                [share.friend for share in shares if share.target is None],
                summary,
                log_handle,
                created,
            )
            completed = True
        finally:
            if not completed:
                for leftover in created:
                    leftover.unlink(missing_ok=True)
                message = f"could not finish {action.source}; removed {len(created)} copies made for it"
                log.error(message)
                if log_handle is not None:
                    log_handle.write(
                        f"{datetime.now(UTC).isoformat(timespec='seconds')} ERROR: {message}\n"
                    )
        if not self.dry_run:
            for share in shares:
                if share.target is not None:
                    self.ledger.record_shared(share.content_hash, share.friend)
        summary.shared += len(shares)

    def confirm_album_shares(self, added_by_friend: dict[str, list[str]]) -> None:
        """Record the album shares Photos confirmed; unconfirmed ones are planned again next run."""
        for friend, content_hashes in added_by_friend.items():
            for content_hash in content_hashes:
                self.ledger.record_shared(content_hash, friend)
        self.ledger.save()

    def execute(self, plan: Plan) -> Summary:
        summary = Summary(unknown_parks=list(plan.unknown_parks))
        prefix = "Would " if self.dry_run else ""
        shares_by_source: dict[Path, list[Action]] = defaultdict(list)
        for action in plan.actions:
            if action.kind is ActionKind.SHARE:
                shares_by_source[action.source].append(action)
        log_handle = None
        if not self.dry_run:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            log_handle = (self.state_dir / LOG_NAME).open("a", encoding="utf-8")
        try:
            for action in plan.actions:
                if action.kind is ActionKind.SHARE:
                    continue
                if action.kind in (
                    ActionKind.DELETE,
                    ActionKind.PLACE,
                    ActionKind.DUPLICATE,
                ):
                    self._run_item(
                        action,
                        shares_by_source.get(action.source, []),
                        summary,
                        log_handle,
                    )
                elif action.kind is ActionKind.STOCK:
                    if action.target is not None:
                        self._record(
                            log_handle,
                            f"{prefix}{self.mode.value} stock art {action.source} -> {action.target}",
                        )
                        if not self.dry_run:
                            action.target.parent.mkdir(parents=True, exist_ok=True)
                            if self.mode is PlaceMode.MOVE:
                                shutil.move(str(action.source), str(action.target))
                            else:
                                shutil.copy2(action.source, action.target)
                    else:
                        verb = (
                            "delete stock art"
                            if self.mode is PlaceMode.MOVE
                            else "skip stock art"
                        )
                        self._record(log_handle, f"{prefix}{verb} {action.source}")
                        if not self.dry_run and self.mode is PlaceMode.MOVE:
                            action.source.unlink()
                    summary.stock += 1
                else:
                    self._record(
                        log_handle, f"{prefix}skip {action.source}: {action.reason}"
                    )
                    if action.reason == "undecided":
                        summary.undecided += 1
                    else:
                        summary.skipped += 1
            if self.mode is PlaceMode.MOVE:
                for folder in (
                    plan.discovery.batch_folders + plan.discovery.empty_uuid_folders
                ):
                    if self.dry_run:
                        summary.folders_removed += 1
                        self._record(log_handle, f"Would remove folder {folder}")
                    elif folder.is_dir() and not _visible_children(folder):
                        shutil.rmtree(folder)
                        summary.folders_removed += 1
                        self._record(log_handle, f"removed folder {folder}")
        finally:
            if log_handle is not None:
                log_handle.close()
            if not self.dry_run:
                self.ledger.save()
        return summary

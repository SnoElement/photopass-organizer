"""Configuration from photopass.toml: settings, friends, trip rules and per-photo overrides."""

from __future__ import annotations

import os
import shutil
import sys
import tomllib
from dataclasses import dataclass, field, replace
from datetime import date
from enum import Enum
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import tomli_w

CONFIG_NAME = "photopass.toml"
LEDGER_NAME = "ledger.json"
LOG_NAME = "organizer.log"
STATE_DIR_ENV = "PHOTOPASS_ORGANIZER_HOME"
HEADER_COMMENT = (
    "# Written by photopass-organizer; see docs/reference.md for every key.\n"
)

STOCK_ART_CHOICES = ("delete", "keep")
LAYOUT_CHOICES = ("flat", "date/park", "park/date")
PHOTO_ACTIONS = ("ignore", "keep")


class ConfigError(ValueError):
    pass


def is_macos() -> bool:
    return sys.platform == "darwin"


class ShareMethod(Enum):
    FOLDER = "folder"
    PHOTOS_ALBUM = "photos-album"


@dataclass(frozen=True)
class Friend:
    name: str
    share: ShareMethod
    path: Path | None = None
    album: str | None = None


@dataclass(frozen=True)
class Settings:
    source: Path
    destination: Path
    default_timezone: str
    stock_art: str
    shared_root: Path | None
    import_to_photos: bool
    photos_folder: str
    purge_after_import: bool
    parks: dict[str, str]
    layout: str = "flat"

    @classmethod
    def platform_defaults(cls) -> Settings:
        from .media import DEFAULT_TIMEZONE

        mac = is_macos()
        return cls(
            source=Path.home() / "Downloads",
            destination=Path.home() / "Pictures" / "PhotoPass",
            default_timezone=DEFAULT_TIMEZONE,
            stock_art="delete",
            shared_root=Path.home()
            / "Library"
            / "Mobile Documents"
            / "com~apple~CloudDocs"
            / "Shared Photos"
            if mac
            else None,
            import_to_photos=mac,
            photos_folder="PhotoPass",
            purge_after_import=True,
            parks={},
        )


@dataclass(frozen=True)
class TripRule:
    start: date
    end: date
    friends: tuple[str, ...]
    i_was_there: bool
    parks: frozenset[str] | None = None
    ignore: bool = False

    def matches(self, local_date: date, park: str | None) -> bool:
        if not (self.start <= local_date <= self.end):
            return False
        return self.parks is None or park in self.parks


@dataclass(frozen=True)
class PhotoOverride:
    hash: str
    action: str
    name: str = ""


@dataclass
class Config:
    settings: Settings = field(default_factory=Settings.platform_defaults)
    friends: dict[str, Friend] = field(default_factory=dict)
    trips: list[TripRule] = field(default_factory=list)
    photos: dict[str, PhotoOverride] = field(default_factory=dict)

    def rule_for(self, local_date: date, park: str | None) -> TripRule | None:
        matches = [rule for rule in self.trips if rule.matches(local_date, park)]
        if len(matches) > 1:
            raise ConfigError(
                f"{len(matches)} trip rules overlap on {local_date} {park or ''}".strip()
            )
        return matches[0] if matches else None

    def friend(self, name: str) -> Friend:
        entry = self.friends.get(name)
        if entry is not None and (
            entry.share is ShareMethod.PHOTOS_ALBUM or entry.path is not None
        ):
            return entry
        shared_root = self.settings.shared_root
        if shared_root is None:
            raise ConfigError(
                f"friend {name} has no sharing method and shared_root is not set"
            )
        return Friend(name=name, share=ShareMethod.FOLDER, path=shared_root / name)

    def folder_friends(self) -> dict[str, Path]:
        names = set(self.friends) | {
            name for rule in self.trips for name in rule.friends
        }
        resolved = (self.friend(name) for name in sorted(names))
        return {
            friend.name: friend.path
            for friend in resolved
            if friend.share is ShareMethod.FOLDER and friend.path
        }

    def known_friends(self) -> list[str]:
        names = set(self.friends) | {
            name for rule in self.trips for name in rule.friends
        }
        shared_root = self.settings.shared_root
        if shared_root is not None and shared_root.is_dir():
            names.update(
                child.name
                for child in shared_root.iterdir()
                if child.is_dir() and not child.name.startswith(".")
            )
        return sorted(names)


def state_dir(override: Path | None = None) -> Path:
    if override is not None:
        return override.expanduser()
    from_env = os.environ.get(STATE_DIR_ENV)
    if from_env:
        return Path(from_env).expanduser()
    return Path.home() / ".config" / "photopass-organizer"


def _parse_date(value, field_name: str) -> date:
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ConfigError(f"{field_name} must be YYYY-MM-DD, got {value!r}")
    try:
        return date.fromisoformat(str(value))
    except ValueError as error:
        raise ConfigError(f"{field_name} must be YYYY-MM-DD, got {value!r}") from error


def _check_keys(entry: dict, allowed: set[str], table: str) -> None:
    unknown = set(entry) - allowed
    if unknown:
        raise ConfigError(f"{table}: unknown keys {sorted(unknown)}")


def _expect(value, kind: type, table: str, key: str):
    if not isinstance(value, kind) or (kind is str and not value):
        raise ConfigError(
            f"{table}: {key} must be a {'non-empty string' if kind is str else 'true or false'}, got {value!r}"
        )
    return value


def _expect_names(value, table: str, key: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(name, str) and name for name in value
    ):
        raise ConfigError(f"{table}: {key} must be a list of names, got {value!r}")
    return tuple(value)


def _resolve_path(value, table: str, key: str, base_dir: Path) -> Path:
    return base_dir / Path(_expect(value, str, table, key)).expanduser()


def _parse_settings(entry: dict, base_dir: Path) -> Settings:
    if "downloads" in entry:
        raise ConfigError("settings.downloads is now called settings.source")
    _check_keys(
        entry,
        {
            "source",
            "destination",
            "default_timezone",
            "stock_art",
            "shared_root",
            "import_to_photos",
            "photos_folder",
            "purge_after_import",
            "layout",
        },
        "settings",
    )
    settings = Settings.platform_defaults()
    changes: dict = {}
    for key in ("source", "destination"):
        if key in entry:
            changes[key] = _resolve_path(entry[key], "settings", key, base_dir)
    if "shared_root" in entry:
        empty = entry["shared_root"] == ""
        changes["shared_root"] = (
            None
            if empty
            else _resolve_path(
                entry["shared_root"], "settings", "shared_root", base_dir
            )
        )
    if "default_timezone" in entry:
        changes["default_timezone"] = _expect_timezone(
            entry["default_timezone"], "settings", "default_timezone"
        )
    if "photos_folder" in entry:
        changes["photos_folder"] = _expect(
            entry["photos_folder"], str, "settings", "photos_folder"
        )
    for key in ("import_to_photos", "purge_after_import"):
        if key in entry:
            changes[key] = _expect(entry[key], bool, "settings", key)
    if "stock_art" in entry:
        if entry["stock_art"] not in STOCK_ART_CHOICES:
            raise ConfigError(
                f"settings: stock_art must be one of {list(STOCK_ART_CHOICES)}, got {entry['stock_art']!r}"
            )
        changes["stock_art"] = entry["stock_art"]
    if "layout" in entry:
        if entry["layout"] not in LAYOUT_CHOICES:
            raise ConfigError(
                f"settings: layout must be one of {list(LAYOUT_CHOICES)}, got {entry['layout']!r}"
            )
        changes["layout"] = entry["layout"]
    return replace(settings, **changes)


def _expect_timezone(value, table: str, key: str) -> str:
    name = _expect(value, str, table, key)
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError) as error:
        raise ConfigError(
            f"{table}: {key} must be an IANA timezone such as America/New_York, got {name!r}"
        ) from error
    return name


def _parse_parks(entry: dict) -> dict[str, str]:
    return {name: _expect_timezone(zone, "parks", name) for name, zone in entry.items()}


def _parse_friend(name: str, entry: dict, base_dir: Path) -> Friend:
    table = f"friends.{name}"
    _check_keys(entry, {"share", "path", "album"}, table)
    share_value = entry.get("share", ShareMethod.FOLDER.value)
    try:
        share = ShareMethod(share_value)
    except ValueError as error:
        choices = [method.value for method in ShareMethod]
        raise ConfigError(
            f"{table}: share must be one of {choices}, got {share_value!r}"
        ) from error
    if share is ShareMethod.PHOTOS_ALBUM:
        if "path" in entry:
            raise ConfigError(f'{table}: path applies to share = "folder" only')
        if not is_macos():
            raise ConfigError(
                f'{table}: share = "photos-album" needs macOS; use share = "folder" here'
            )
        return Friend(
            name=name,
            share=share,
            album=_expect(entry.get("album", name), str, table, "album"),
        )
    if "album" in entry:
        raise ConfigError(f'{table}: album applies to share = "photos-album" only')
    path = (
        _resolve_path(entry["path"], table, "path", base_dir)
        if "path" in entry
        else None
    )
    return Friend(name=name, share=share, path=path)


def _parse_trip(index: int, entry: dict) -> TripRule:
    table = f"trip {index}"
    _check_keys(
        entry, {"start", "end", "friends", "i_was_there", "parks", "ignore"}, table
    )
    start = _parse_date(entry.get("start"), f"{table} start")
    end = _parse_date(entry.get("end", entry.get("start")), f"{table} end")
    if end < start:
        raise ConfigError(f"{table}: end {end} is before start {start}")
    parks = _expect_names(entry.get("parks", []), table, "parks")
    parks_set = frozenset(parks) if parks else None
    if _expect(entry.get("ignore", False), bool, table, "ignore"):
        if "friends" in entry or "i_was_there" in entry:
            raise ConfigError(
                f"{table}: an ignore rule may not set friends or i_was_there"
            )
        return TripRule(
            start=start,
            end=end,
            friends=(),
            i_was_there=False,
            parks=parks_set,
            ignore=True,
        )
    friends = _expect_names(entry.get("friends", []), table, "friends")
    i_was_there = _expect(entry.get("i_was_there", True), bool, table, "i_was_there")
    if not i_was_there and not friends:
        raise ConfigError(
            f"{table}: i_was_there = false with no friends would delete photos and share them with nobody"
        )
    return TripRule(
        start=start,
        end=end,
        friends=friends,
        i_was_there=i_was_there,
        parks=parks_set,
    )


def _parse_photo(index: int, entry: dict) -> PhotoOverride:
    table = f"photo {index}"
    _check_keys(entry, {"hash", "action", "name"}, table)
    if "hash" not in entry or "action" not in entry:
        raise ConfigError(f"{table}: hash and action are required")
    if entry["action"] not in PHOTO_ACTIONS:
        raise ConfigError(
            f"{table}: action must be one of {list(PHOTO_ACTIONS)}, got {entry['action']!r}"
        )
    return PhotoOverride(
        hash=_expect(entry["hash"], str, table, "hash"),
        action=entry["action"],
        name=str(entry.get("name", "")),
    )


def parse_config(text: str, base_dir: Path | None = None) -> Config:
    base_dir = Path.home() if base_dir is None else base_dir
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"photopass.toml is not valid TOML: {error}") from error
    _check_keys(
        document, {"settings", "parks", "friends", "trip", "photo"}, "top level"
    )
    settings = _parse_settings(document.get("settings", {}), base_dir)
    settings = replace(settings, parks=_parse_parks(document.get("parks", {})))
    config = Config(
        settings=settings,
        friends={
            name: _parse_friend(name, entry, base_dir)
            for name, entry in document.get("friends", {}).items()
        },
        trips=[
            _parse_trip(index, entry)
            for index, entry in enumerate(document.get("trip", []), start=1)
        ],
        photos={},
    )
    for index, entry in enumerate(document.get("photo", []), start=1):
        override = _parse_photo(index, entry)
        if override.hash in config.photos:
            raise ConfigError(f"photo {index}: hash {override.hash} already listed")
        config.photos[override.hash] = override
    _check_overlaps(config)
    return config


def _check_overlaps(config: Config) -> None:
    rules = config.trips
    for first_index, first in enumerate(rules):
        for second in rules[first_index + 1 :]:
            if first.end < second.start or second.end < first.start:
                continue
            if (
                first.parks is not None
                and second.parks is not None
                and not (first.parks & second.parks)
            ):
                continue
            raise ConfigError(
                f"trip rules overlap: {first.start}..{first.end} and {second.start}..{second.end}"
            )


def load_config(path: Path) -> Config:
    if not path.is_file():
        return Config()
    return parse_config(path.read_text(encoding="utf-8"), path.parent)


def _toml_path(path: Path) -> str:
    try:
        return "~/" + path.relative_to(Path.home()).as_posix()
    except ValueError:
        return str(path)


def _settings_table(settings: Settings) -> dict:
    table: dict = {
        "source": _toml_path(settings.source),
        "destination": _toml_path(settings.destination),
        "default_timezone": settings.default_timezone,
        "stock_art": settings.stock_art,
    }
    table["shared_root"] = (
        "" if settings.shared_root is None else _toml_path(settings.shared_root)
    )
    table["import_to_photos"] = settings.import_to_photos
    table["photos_folder"] = settings.photos_folder
    table["purge_after_import"] = settings.purge_after_import
    table["layout"] = settings.layout
    return table


def _friend_table(friend: Friend) -> dict:
    table: dict = {"share": friend.share.value}
    if friend.path is not None:
        table["path"] = _toml_path(friend.path)
    if friend.album is not None:
        table["album"] = friend.album
    return table


def _trip_table(rule: TripRule) -> dict:
    table: dict = {"start": rule.start.isoformat(), "end": rule.end.isoformat()}
    if rule.ignore:
        table["ignore"] = True
    else:
        table["friends"] = list(rule.friends)
        table["i_was_there"] = rule.i_was_there
    if rule.parks is not None:
        table["parks"] = sorted(rule.parks)
    return table


def _photo_table(override: PhotoOverride) -> dict:
    table = {"hash": override.hash, "action": override.action}
    if override.name:
        table["name"] = override.name
    return table


def _table_array(name: str, tables: list[dict]) -> str:
    return "".join(f"\n[[{name}]]\n{tomli_w.dumps(table)}" for table in tables)


def display_path(path: Path) -> str:
    """A path as the user would write it, with the home folder shown as ~."""
    return _toml_path(path)


def settings_table(settings: Settings) -> dict:
    """The [settings] table as it is written to photopass.toml."""
    return _settings_table(settings)


def with_settings(config: Config, entry: dict, base_dir: Path) -> Config:
    """The config with its [settings] replaced by a table in photopass.toml form; parks are kept."""
    if not isinstance(entry, dict):
        raise ConfigError("settings must be a table")
    settings = _parse_settings(entry, base_dir)
    return replace(config, settings=replace(settings, parks=config.settings.parks))


def render_config(config: Config) -> str:
    document: dict = {"settings": _settings_table(config.settings)}
    if config.settings.parks:
        document["parks"] = dict(config.settings.parks)
    if config.friends:
        document["friends"] = {
            name: _friend_table(friend) for name, friend in config.friends.items()
        }
    text = HEADER_COMMENT + tomli_w.dumps(document)
    text += _table_array("trip", [_trip_table(rule) for rule in config.trips])
    text += _table_array(
        "photo", [_photo_table(override) for override in config.photos.values()]
    )
    return text


def write_config(config: Config, path: Path) -> None:
    text = render_config(config)
    parse_config(text, path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        shutil.copy2(path, path.with_suffix(".toml.bak"))
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)

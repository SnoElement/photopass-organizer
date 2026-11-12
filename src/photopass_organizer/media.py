"""Parsing and metadata extraction for PhotoPass photos and videos."""

from __future__ import annotations

import hashlib
import re
import struct
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, UnidentifiedImageError

PHOTOPASS_NAME = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2}) - (?P<park>.+?) - (?P<location>.+?)"
    r"(?:_(?P<sequence>\d+))?(?: \d+| \(\d+\))?\.(?P<extension>jpe?g|mp4)$",
    re.IGNORECASE,
)
LOOSE_VIDEO_NAME = re.compile(r"^(?P<media_id>\d+)(?: \d+| \(\d+\))?\.mp4$")
UUID_FOLDER_NAME = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)

SPECIAL_EVENTS_NAME = re.compile(r"^Special Events at (?P<host>.+)$", re.IGNORECASE)
EVENT_SUBTITLE_GAP = re.compile(r"\s{2,}")
EVENT_HOST_ALIASES = {"DCA": "Disney California Adventure Park"}
EVENT_ACRONYMS = frozenset({"DCA", "DVC", "WDW", "USA", "UK", "II", "III", "IV"})

QUICKTIME_EPOCH = datetime(1904, 1, 1, tzinfo=UTC)
EXIF_IFD_POINTER = 0x8769
DATE_TIME_ORIGINAL = 0x9003
OFFSET_TIME_ORIGINAL = 0x9011
MOOV_SCAN_BYTES = 4 * 1024 * 1024

DEFAULT_TIMEZONE = "America/New_York"
PARK_TIMEZONES = {
    "Disneyland Park": "America/Los_Angeles",
    "Disney California Adventure Park": "America/Los_Angeles",
    "Special Events at Disneyland": "America/Los_Angeles",
    "runDisney Disneyland": "America/Los_Angeles",
    "Magic Kingdom Park": "America/New_York",
    "Epcot": "America/New_York",
    "Disneys Hollywood Studios": "America/New_York",
    "Disneys Animal Kingdom Park": "America/New_York",
}
RESORT_BY_TIMEZONE = {
    "America/Los_Angeles": "Disneyland Resort",
    "America/New_York": "Walt Disney World",
}


@dataclass(frozen=True)
class ParsedName:
    filename_date: str
    park: str
    location: str
    sequence: int | None
    extension: str


def is_folder_name(name: str) -> bool:
    """True when a park or event name is safe to use as one folder under the destination."""
    return name.strip() not in ("", ".", "..") and "/" not in name and "\\" not in name


def parse_photopass_name(name: str) -> ParsedName | None:
    match = PHOTOPASS_NAME.match(name)
    if match is None or not is_folder_name(match.group("park")):
        return None
    sequence = match.group("sequence")
    return ParsedName(
        filename_date=match.group("date"),
        park=match.group("park"),
        location=match.group("location").strip(),
        sequence=int(sequence) if sequence is not None else None,
        extension=match.group("extension").lower(),
    )


def parse_loose_video_name(name: str) -> str | None:
    match = LOOSE_VIDEO_NAME.match(name)
    return match.group("media_id") if match else None


def is_uuid_folder_name(name: str) -> bool:
    return UUID_FOLDER_NAME.match(name) is not None


def event_host(park: str | None) -> str | None:
    """The place a "Special Events at <place>" label names, or None for an ordinary park."""
    match = SPECIAL_EVENTS_NAME.match(park) if park else None
    return match.group("host").strip() if match else None


def _title_word(word: str) -> str:
    """Capitalise a word of an event name; Disney lower-cases acronyms, so known ones are restored."""
    if word.upper() in EVENT_ACRONYMS:
        return word.upper()
    if word != word.lower():
        return word[0].upper() + word[1:]
    return word.capitalize()


def event_name(park: str | None, location: str) -> str | None:
    """The event a special-events photo belongs to; Disney puts it in the location part of the name.

    "Oogie boogie bash  a disney halloween party" is the event followed by its subtitle, with the
    punctuation between them reduced to a double space.
    """
    if event_host(park) is None:
        return None
    title = EVENT_SUBTITLE_GAP.split(location.strip())[0]
    name = " ".join(_title_word(word) for word in title.split())
    return name if is_folder_name(name) else None


def _known_timezone(park: str, parks: Mapping[str, str]) -> str | None:
    known = {**PARK_TIMEZONES, **parks}
    if park in known:
        return known[park]
    host = event_host(park)
    if host is None:
        return None
    host = EVENT_HOST_ALIASES.get(host, host)
    if host in known:
        return known[host]
    matches = {
        timezone_name
        for name, timezone_name in known.items()
        if event_host(name) is None and host.lower() in name.lower()
    }
    return matches.pop() if len(matches) == 1 else None


def park_timezone_name(
    park: str | None,
    default_timezone: str = DEFAULT_TIMEZONE,
    parks: Mapping[str, str] | None = None,
) -> str:
    if park is None:
        return default_timezone
    return _known_timezone(park, parks or {}) or default_timezone


def unknown_parks(parks_seen: Iterable[str], parks: Mapping[str, str]) -> list[str]:
    return sorted({park for park in parks_seen if _known_timezone(park, parks) is None})


def resort_name(timezone_name: str) -> str:
    return RESORT_BY_TIMEZONE.get(timezone_name, "Disney")


def fingerprint(name: str, size_bytes: int) -> tuple | None:
    """A dedupe key that needs no file contents, so it works on evicted iCloud files.

    PhotoPass renumbers the _N suffix per download batch, so the suffix is dropped;
    the byte size disambiguates different photos of the same location.
    """
    parsed = parse_photopass_name(name)
    if parsed is not None:
        return ("photo", parsed.filename_date, parsed.park, parsed.location, size_bytes)
    media_id = parse_loose_video_name(name)
    if media_id is not None:
        return ("video", media_id, size_bytes)
    return None


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_exif_offset(offset_text: str) -> timezone | None:
    match = re.fullmatch(r"([+-])(\d{2}):(\d{2})", offset_text.strip())
    if match is None:
        return None
    sign = 1 if match.group(1) == "+" else -1
    delta = timedelta(hours=int(match.group(2)), minutes=int(match.group(3)))
    return timezone(sign * delta)


def read_photo_capture_time(path: Path) -> datetime | None:
    """EXIF DateTimeOriginal, timezone-aware when OffsetTimeOriginal is present."""
    try:
        with Image.open(path) as image:
            exif_ifd = image.getexif().get_ifd(EXIF_IFD_POINTER)
    except (UnidentifiedImageError, OSError, SyntaxError):
        return None
    original = exif_ifd.get(DATE_TIME_ORIGINAL)
    if not original:
        return None
    try:
        captured = datetime.strptime(str(original).strip(), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
    offset_text = exif_ifd.get(OFFSET_TIME_ORIGINAL)
    if offset_text:
        offset = _parse_exif_offset(str(offset_text))
        if offset is not None:
            return captured.replace(tzinfo=offset)
    return captured


def has_embedded_color_profile(path: Path) -> bool:
    """PhotoPass stock art is exported from Lightroom/Photoshop with an ICC profile; camera JPEGs have none."""
    try:
        with Image.open(path) as image:
            return bool(image.info.get("icc_profile"))
    except (UnidentifiedImageError, OSError):
        return False


def read_video_creation_time_utc(path: Path) -> datetime | None:
    """Creation time from the MP4 movie header; None when absent or zero."""
    with path.open("rb") as handle:
        head = handle.read(MOOV_SCAN_BYTES)
    position = head.find(b"mvhd")
    if position < 0:
        return None
    version = head[position + 4]
    try:
        if version == 1:
            (creation_seconds,) = struct.unpack(
                ">Q", head[position + 8 : position + 16]
            )
        else:
            (creation_seconds,) = struct.unpack(
                ">I", head[position + 8 : position + 12]
            )
    except struct.error:
        return None
    if creation_seconds == 0:
        return None
    created = QUICKTIME_EPOCH + timedelta(seconds=creation_seconds)
    if created.year < 1990:
        return None
    return created


def local_date_for_video(created_utc: datetime, timezone_name: str) -> datetime:
    return created_utc.astimezone(ZoneInfo(timezone_name))

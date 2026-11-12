"""Local HTTP server behind the review page: state, thumbnails, media, save, run."""

from __future__ import annotations

import dataclasses
import io
import json
import logging
import mimetypes
import re
import secrets
import threading
import webbrowser
from dataclasses import replace
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from PIL import Image

from .config import (
    CONFIG_NAME,
    LAYOUT_CHOICES,
    LEDGER_NAME,
    PHOTO_ACTIONS,
    STOCK_ART_CHOICES,
    Config,
    ConfigError,
    Friend,
    PhotoOverride,
    ShareMethod,
    _check_overlaps,
    display_path,
    is_macos,
    load_config,
    settings_table,
    with_settings,
    write_config,
)
from .ledger import Ledger
from .organizer import MediaItem, Organizer, PlaceMode, TripRange
from .photos import PhotosSummary, sync_photos
from .review import (
    DECISION_STATES,
    DayDecision,
    apply_decisions,
    build_state,
    decision_for,
    dry_run_counts,
)
from .review_page import render_page
from .shared import SharedFolderIndex

log = logging.getLogger(__name__)

MAX_BODY_BYTES = 4 * 1024 * 1024
THUMBNAIL_EDGE = 320
STREAM_CHUNK_BYTES = 64 * 1024
SAVE_KEYS = frozenset({"days", "photos", "friends"})
RANGE_PATTERN = re.compile(r"^bytes=(\d+)-(\d*)$")


class HttpError(Exception):
    def __init__(self, status: int, message: str | None = None) -> None:
        super().__init__(message or "")
        self.status = status
        self.message = message


def to_json_value(value):
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: to_json_value(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (set, frozenset)):
        return sorted(to_json_value(entry) for entry in value)
    if isinstance(value, dict):
        return {str(key): to_json_value(entry) for key, entry in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_value(entry) for entry in value]
    return value


def make_thumbnail(path: Path) -> bytes | None:
    try:
        with Image.open(path) as image:
            image.draft("RGB", (THUMBNAIL_EDGE * 2, THUMBNAIL_EDGE * 2))
            image = image.convert("RGB")
            image.thumbnail((THUMBNAIL_EDGE, THUMBNAIL_EDGE))
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=70)
    except (OSError, Image.DecompressionBombError):
        return None
    return buffer.getvalue()


def _require_text(entry: dict, key: str, where: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{where}: {key} must be a non-empty string")
    return value


def parse_friend(entry: object) -> Friend:
    if not isinstance(entry, dict):
        raise ConfigError("friends: each entry must be an object")
    name = _require_text(entry, "name", "friends")
    try:
        share = ShareMethod(entry.get("share"))
    except ValueError as error:
        raise ConfigError(
            f"friend {name}: share must be one of {[method.value for method in ShareMethod]}"
        ) from error
    if share is ShareMethod.FOLDER:
        raw_path = _require_text(entry, "path", f"friend {name}")
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            raise ConfigError(
                f"friend {name}: path must be absolute or start with ~, got {raw_path!r}"
            )
        return Friend(name, share, path=path)
    if not is_macos():
        raise ConfigError(
            f'friend {name}: share = "photos-album" needs macOS; use share = "folder" here'
        )
    return Friend(name, share, album=_require_text(entry, "album", f"friend {name}"))


def parse_photos(entries: object) -> dict[str, PhotoOverride]:
    if not isinstance(entries, list):
        raise ConfigError("photos must be a list")
    overrides = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ConfigError("photos: each entry must be an object")
        content_hash = _require_text(entry, "hash", "photos")
        if (
            not isinstance(entry.get("action"), str)
            or entry["action"] not in PHOTO_ACTIONS
        ):
            raise ConfigError(
                f"photo {content_hash}: action must be one of {list(PHOTO_ACTIONS)}"
            )
        overrides[content_hash] = PhotoOverride(
            content_hash, entry["action"], str(entry.get("name", ""))
        )
    return overrides


def parse_decisions(entries: object, known: set[str]) -> list[DayDecision]:
    if not isinstance(entries, list):
        raise ConfigError("days must be a list")
    decisions = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ConfigError("days: each entry must be an object")
        try:
            day = date.fromisoformat(str(entry.get("date")))
        except ValueError as error:
            raise ConfigError(f"days: bad date {entry.get('date')!r}") from error
        if (
            not isinstance(entry.get("state"), str)
            or entry["state"] not in DECISION_STATES
        ):
            raise ConfigError(f"days: state must be one of {list(DECISION_STATES)}")
        friends = entry.get("friends", [])
        if not isinstance(friends, list) or not all(
            isinstance(name, str) for name in friends
        ):
            raise ConfigError("days: friends must be a list of names")
        unknown = sorted(set(friends) - known)
        if unknown:
            raise ConfigError(
                f"days: unknown friend {unknown[0]}; add them under friends first"
            )
        if entry["state"] == "friends" and not friends:
            raise ConfigError(
                f"days: {entry.get('date')} is friends-only but names no friends"
            )
        decisions.append(
            DayDecision(
                day,
                _require_text(entry, "park", "days"),
                entry["state"],
                tuple(friends),
            )
        )
    return decisions


def parse_trip(body: dict) -> TripRange | None:
    trip = body.get("trip")
    if trip is None:
        return None
    if not isinstance(trip, dict):
        raise ConfigError("trip must be an object or null")
    try:
        return TripRange.parse(f"{trip.get('start')}..{trip.get('end')}")
    except ValueError as error:
        raise ConfigError(f"trip: {error}") from error


class ReviewServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self, state_dir: Path, config: Config, host: str = "127.0.0.1", port: int = 0
    ) -> None:
        super().__init__((host, port), ReviewHandler)
        self.state_dir = state_dir
        self.config = config
        self.token = secrets.token_urlsafe(16)
        self.lock = threading.Lock()
        self.run_lock = threading.Lock()
        self.thumbnails: dict[str, bytes] = {}
        self._shared_index: SharedFolderIndex | None = None
        self._state: dict | None = None
        self._items: dict[str, MediaItem] = {}
        self._still_for_video: dict[str, str] = {}
        self._thread: threading.Thread | None = None
        self._serving = threading.Event()

    @property
    def url(self) -> str:
        return f"http://{self.server_address[0]}:{self.server_address[1]}/{self.token}/"

    def serve_forever(self, poll_interval: float = 0.5) -> None:
        self._serving.set()
        super().serve_forever(poll_interval)

    def start_in_thread(self) -> None:
        self._thread = threading.Thread(
            target=self.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )
        self._thread.start()
        self._serving.wait()

    def shutdown(self) -> None:
        if self._serving.is_set():
            super().shutdown()
        self.server_close()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join()

    def shared_index(self) -> SharedFolderIndex:
        if self._shared_index is None:
            self._shared_index = SharedFolderIndex.load(self.config.folder_friends())
        return self._shared_index

    def drop_plan_cache(self) -> None:
        self._state = None
        self._items = {}
        self._still_for_video = {}

    def set_config(self, config: Config) -> None:
        self.config = config
        self._shared_index = None
        self.drop_plan_cache()

    def refresh_state(self) -> dict:
        organizer = Organizer(
            self.config, self.state_dir, dry_run=True, shared_index=self.shared_index()
        )
        plan = organizer.plan()
        state = build_state(
            plan,
            self.config,
            self.shared_index(),
            organizer.ledger,
            organizer.destination_hashes(),
        )
        self._items = {item.content_hash: item for item in plan.items}
        self._still_for_video = {
            entry["hash"]: entry["paired_still"]
            for trip in state["trips"]
            for day in trip["days"]
            for entry in day["new"] + day["handled"]
            if entry["paired_still"]
        }
        self._state = state
        return state

    def ensure_items(self) -> None:
        if self._state is None:
            self.refresh_state()

    def thumbnail_source(self, content_hash: str) -> Path | None:
        self.ensure_items()
        item = self._items.get(content_hash)
        if item is not None and item.is_video:
            item = self._items.get(self._still_for_video.get(content_hash, ""))
        return item.source if item is not None and not item.is_video else None

    def media_path(self, content_hash: str) -> Path | None:
        self.ensure_items()
        item = self._items.get(content_hash)
        return item.source if item is not None else None

    def _counts_for(self, config: Config) -> dict:
        index = SharedFolderIndex.load(config.folder_friends())
        return dry_run_counts(
            Organizer(config, self.state_dir, dry_run=True, shared_index=index)
        )

    def save(self, body: dict) -> dict:
        with self.lock:
            path = self.state_dir / CONFIG_NAME
            saved_friends = load_config(path).friends
            if not SAVE_KEYS & body.keys():
                return {
                    "saved": False,
                    "counts": self._counts_for(self.config),
                    "unsaved_friends": sorted(
                        set(self.config.friends) - set(saved_friends)
                    ),
                }
            friend_entries = body.get("friends", [])
            if not isinstance(friend_entries, list):
                raise ConfigError("friends must be a list")
            friends = dict(self.config.friends)
            for entry in friend_entries:
                friend = parse_friend(entry)
                friends[friend.name] = friend
            photos = (
                parse_photos(body["photos"]) if "photos" in body else self.config.photos
            )
            candidate = replace(self.config, friends=friends, photos=photos)
            decisions = parse_decisions(
                body.get("days", []), set(candidate.known_friends())
            )
            try:
                candidate = apply_decisions(candidate, decisions)
            except ValueError as error:
                raise ConfigError(str(error)) from error
            _check_overlaps(candidate)
            self._reopen_days_with_new_friends(decisions)
            counts = self._counts_for(candidate)
            selected = {name for rule in candidate.trips for name in rule.friends}
            unsaved = {
                name: friend
                for name, friend in candidate.friends.items()
                if name not in saved_friends and name not in selected
            }
            to_write = replace(
                candidate,
                friends={
                    name: friend
                    for name, friend in candidate.friends.items()
                    if name not in unsaved
                },
            )
            if to_write != load_config(path):
                write_config(to_write, path)
                written = load_config(path)
                self.set_config(
                    replace(written, friends={**written.friends, **unsaved})
                )
            return {
                "saved": True,
                "counts": counts,
                "unsaved_friends": sorted(unsaved),
            }

    def _reopen_days_with_new_friends(self, decisions: list[DayDecision]) -> None:
        """Make photos processed before share tracking shareable with a friend newly added to their date."""
        added_to: dict[tuple[str, str], tuple[str, ...]] = {}
        for decision in decisions:
            before = decision_for(self.config, decision.date, decision.park).friends
            if set(decision.friends) - set(before):
                added_to[(decision.date.isoformat(), decision.park)] = before
        if not added_to or self.run_lock.locked():
            return
        self.ensure_items()
        ledger = Ledger.load(self.state_dir / LEDGER_NAME)
        reopened = [
            ledger.reopen_for_sharing(item.content_hash, added_to[key])
            for item in self._items.values()
            if (key := (item.local_date, item.park)) in added_to
        ]
        if any(reopened):
            ledger.save()
            self.drop_plan_cache()

    def settings_view(self) -> dict:
        with self.lock:
            return {
                "path": display_path(self.state_dir / CONFIG_NAME),
                "settings": settings_table(self.config.settings),
                "choices": {
                    "layout": list(LAYOUT_CHOICES),
                    "stock_art": list(STOCK_ART_CHOICES),
                },
                "photos_available": is_macos(),
            }

    def save_settings(self, body: dict) -> dict:
        if self.run_lock.locked():
            raise HttpError(409, "organizing is in progress")
        with self.lock:
            path = self.state_dir / CONFIG_NAME
            saved = load_config(path)
            unsaved = {
                name: friend
                for name, friend in self.config.friends.items()
                if name not in saved.friends
            }
            candidate = with_settings(saved, body.get("settings"), self.state_dir)
            if candidate != saved:
                write_config(candidate, path)
            written = load_config(path)
            self.set_config(replace(written, friends={**written.friends, **unsaved}))
        return self.settings_view()

    def add_friends(self, body: dict) -> dict:
        entries = body.get("friends")
        if not isinstance(entries, list):
            raise ConfigError("friends must be a list")
        added = [parse_friend(entry) for entry in entries]
        with self.lock:
            merged = {
                **self.config.friends,
                **{friend.name: friend for friend in added},
            }
            self.set_config(replace(self.config, friends=merged))
        return {"ok": True}

    def run(self, body: dict) -> dict:
        trip = parse_trip(body)
        if not self.run_lock.acquire(blocking=False):
            raise HttpError(409, "organizing is already in progress")
        try:
            with self.lock:
                config, index = self.config, self.shared_index()
            organizer = Organizer(
                config,
                self.state_dir,
                mode=PlaceMode.MOVE,
                shared_index=index,
                trip=trip,
            )
            try:
                summary = organizer.execute(organizer.plan())
                photos = sync_photos(summary, config) if is_macos() else PhotosSummary()
                organizer.confirm_album_shares(photos.added_by_friend)
            finally:
                with self.lock:
                    self.drop_plan_cache()
        finally:
            self.run_lock.release()
        return {"summary": to_json_value(summary), "photos": to_json_value(photos)}


class ReviewHandler(BaseHTTPRequestHandler):
    server: ReviewServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args) -> None:
        log.debug("%s %s", self.address_string(), format % args)

    def _send(
        self,
        status: int,
        body: bytes = b"",
        content_type: str = "application/json",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        if body:
            self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        self._send(status, json.dumps(payload).encode("utf-8"))

    def _route(self) -> str:
        prefix = f"/{self.server.token}/"
        path = unquote(urlsplit(self.path).path)
        if not path.startswith(prefix):
            raise HttpError(404)
        return path[len(prefix) :]

    def _read_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise HttpError(400, "bad Content-Length") from error
        if length > MAX_BODY_BYTES:
            self.close_connection = True
            raise HttpError(413, "request body too large")
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            body = json.loads(raw)
        except json.JSONDecodeError as error:
            raise HttpError(400, f"invalid JSON: {error}") from error
        if not isinstance(body, dict):
            raise HttpError(400, "body must be a JSON object")
        return body

    def _handle(self, method: str) -> None:
        try:
            route = self._route()
            if method == "GET":
                self._get(route)
            else:
                self._post(route)
        except HttpError as error:
            if error.message is None:
                self._send(error.status)
            else:
                self._send_json({"error": error.message}, error.status)
        except ConfigError as error:
            self._send_json({"error": str(error)}, 400)
        except OSError as error:
            log.error("%s", error)
            self._send_json({"error": str(error)}, 500)

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def _get(self, route: str) -> None:
        if route == "":
            self._send(
                200,
                render_page(self.server.token).encode("utf-8"),
                "text/html; charset=utf-8",
            )
        elif route == "api/state":
            with self.server.lock:
                state = self.server.refresh_state()
            self._send_json(state)
        elif route == "api/settings":
            self._send_json(self.server.settings_view())
        elif route.startswith("thumb/"):
            self._send_thumbnail(route[len("thumb/") :])
        elif route.startswith("media/"):
            self._send_media(route[len("media/") :])
        else:
            raise HttpError(404)

    def _post(self, route: str) -> None:
        if route not in (
            "api/save",
            "api/run",
            "api/friends",
            "api/done",
            "api/settings",
        ):
            raise HttpError(404)
        body = self._read_body()
        if route == "api/settings":
            self._send_json(self.server.save_settings(body))
        elif route == "api/save":
            self._send_json(self.server.save(body))
        elif route == "api/friends":
            self._send_json(self.server.add_friends(body))
        elif route == "api/run":
            self._send_json(self.server.run(body))
        else:
            if self.server.run_lock.locked():
                raise HttpError(409, "organizing is in progress")
            self._send_json({"ok": True})
            threading.Thread(target=self.server.shutdown).start()

    def _send_thumbnail(self, content_hash: str) -> None:
        with self.server.lock:
            data = self.server.thumbnails.get(content_hash)
            source = (
                None if data is not None else self.server.thumbnail_source(content_hash)
            )
        if data is None:
            data = make_thumbnail(source) if source is not None else None
            if data is None:
                raise HttpError(404)
            with self.server.lock:
                self.server.thumbnails[content_hash] = data
        self._send(200, data, "image/jpeg", {"Cache-Control": "max-age=3600"})

    def _byte_range(self, size: int) -> tuple[int, int] | None:
        header = self.headers.get("Range")
        if header is None:
            return None
        matched = RANGE_PATTERN.match(header.strip())
        if matched is None:
            raise HttpError(416)
        first = int(matched.group(1))
        last = min(int(matched.group(2)), size - 1) if matched.group(2) else size - 1
        if first >= size or last < first:
            raise HttpError(416)
        return first, last

    def _send_media(self, content_hash: str) -> None:
        with self.server.lock:
            path = self.server.media_path(content_hash)
        if path is None:
            raise HttpError(404)
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        try:
            size = path.stat().st_size
        except FileNotFoundError as error:
            raise HttpError(404) from error
        try:
            byte_range = self._byte_range(size)
        except HttpError:
            self._send(416, headers={"Content-Range": f"bytes */{size}"})
            return
        first, last = byte_range if byte_range is not None else (0, size - 1)
        self.send_response(206 if byte_range is not None else 200)
        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(last - first + 1 if size else 0))
        if byte_range is not None:
            self.send_header("Content-Range", f"bytes {first}-{last}/{size}")
        self.end_headers()
        remaining = last - first + 1 if size else 0
        try:
            with path.open("rb") as handle:
                handle.seek(first)
                while remaining > 0:
                    chunk = handle.read(min(STREAM_CHUNK_BYTES, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True


def open_review(state_dir: Path, config: Config, open_browser: bool, port: int) -> int:
    server = ReviewServer(state_dir, config, port=port)
    log.info("review page at %s", server.url)
    if open_browser:
        webbrowser.open(server.url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("review stopped")
    finally:
        server.server_close()
        with server.run_lock:
            pass
    return 0

"""Import organized folders into Photos.app as albums and add shared photos to friends' albums."""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config, is_macos
from .organizer import Summary

log = logging.getLogger(__name__)

SHARED_FOLDER_NAME = "Shared"
DEFAULT_PARENT_FOLDER = "PhotoPass"

IMPORT_SCRIPT = """
on run argv
    set parentName to item 1 of argv
    set albumName to item 2 of argv
    set mediaFiles to {}
    repeat with argumentIndex from 3 to count of argv
        set end of mediaFiles to POSIX file (item argumentIndex of argv)
    end repeat
    tell application "Photos"
        if not (exists folder parentName) then make new folder named parentName
        set parentFolder to folder parentName
        if not (exists album albumName of parentFolder) then make new album named albumName at parentFolder
        set importedItems to import mediaFiles into album albumName of parentFolder skip check duplicates true
        set outputText to ""
        repeat with theItem in importedItems
            set outputText to outputText & (id of theItem) & tab & (filename of theItem) & tab & linefeed
        end repeat
        return outputText
    end tell
end run
"""

ADD_SCRIPT = """
on run argv
    set parentName to item 1 of argv
    set albumName to item 2 of argv
    tell application "Photos"
        if not (exists folder parentName) then make new folder named parentName
        set parentFolder to folder parentName
        if not (exists album albumName of parentFolder) then make new album named albumName at parentFolder
        set mediaItems to {}
        repeat with argumentIndex from 3 to count of argv
            set end of mediaItems to media item id (item argumentIndex of argv)
        end repeat
        add mediaItems to album albumName of parentFolder
        return count of mediaItems
    end tell
end run
"""

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class ImportResult:
    count: int
    ids_by_filename: dict[str, str]


@dataclass
class PhotosSummary:
    imported: int = 0
    purged: int = 0
    added_to_friend_albums: int = 0
    friend_imports: int = 0
    added_by_friend: dict[str, list[str]] = field(default_factory=dict)
    failed_by_friend: dict[str, int] = field(default_factory=dict)


def _run_osascript(script: str, arguments: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["osascript", "-", *arguments],
        input=script,
        text=True,
        capture_output=True,
        check=False,
    )


def media_files_in(folder: Path) -> list[Path]:
    return sorted(
        path
        for path in folder.iterdir()
        if path.is_file() and not path.name.startswith(".")
    )


def _parse_imported_items(stdout: str) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    for record in stdout.split("\t\n"):
        item_id, separator, filename = record.partition("\t")
        if item_id and separator:
            records.append((item_id, filename))
    return records


def _ids_by_filename(records: list[tuple[str, str]]) -> dict[str, str]:
    ids_by_filename: dict[str, str] = {}
    for item_id, filename in records:
        if filename in ids_by_filename:
            log.warning(
                "Photos imported more than one item named %s; keeping the first id",
                filename,
            )
        else:
            ids_by_filename[filename] = item_id
    return ids_by_filename


def _import_paths(
    paths: list[Path], album_name: str, parent_folder: str
) -> ImportResult:
    if not paths:
        return ImportResult(count=0, ids_by_filename={})
    completed = _run_osascript(
        IMPORT_SCRIPT, [parent_folder, album_name, *(str(path) for path in paths)]
    )
    if completed.returncode != 0:
        log.error(
            "Photos import into %s/%s failed: %s",
            parent_folder,
            album_name,
            completed.stderr.strip(),
        )
        return ImportResult(count=0, ids_by_filename={})
    records = _parse_imported_items(completed.stdout)
    count = len(records)
    ids_by_filename = _ids_by_filename(records)
    if count != len(paths):
        log.warning(
            "Photos imported %d of %d items into %s/%s",
            count,
            len(paths),
            parent_folder,
            album_name,
        )
    else:
        log.info(
            "Imported %d items into Photos album %s/%s",
            count,
            parent_folder,
            album_name,
        )
    return ImportResult(count=count, ids_by_filename=ids_by_filename)


def import_files(
    files: list[Path], album_name: str, parent_folder: str
) -> ImportResult:
    return _import_paths(files, album_name, parent_folder)


def import_folder(
    folder: Path,
    album_name: str | None = None,
    parent_folder: str = DEFAULT_PARENT_FOLDER,
) -> ImportResult:
    """Import a folder into a Photos album; the result maps each imported filename to its Photos item id."""
    return _import_paths(
        media_files_in(folder), album_name or album_name_for(folder), parent_folder
    )


def add_to_album(item_ids: list[str], album_name: str, parent_folder: str) -> int:
    """Add already imported Photos items to an album; returns how many Photos reports it added."""
    if not item_ids:
        return 0
    completed = _run_osascript(ADD_SCRIPT, [parent_folder, album_name, *item_ids])
    if completed.returncode != 0:
        log.error(
            "Adding %d items to Photos album %s/%s failed: %s",
            len(item_ids),
            parent_folder,
            album_name,
            completed.stderr.strip(),
        )
        return 0
    try:
        added = int(completed.stdout.strip())
    except ValueError:
        log.error(
            "Adding to Photos album %s/%s returned no count: %r",
            parent_folder,
            album_name,
            completed.stdout.strip(),
        )
        return 0
    log.info("Added %d items to Photos album %s/%s", added, parent_folder, album_name)
    return added


def _nested_day(folder: Path) -> tuple[str, str] | None:
    """(date, place) for a folder of the date/park or park/date layout, else None."""
    if ISO_DATE.match(folder.name):
        return folder.name, folder.parent.name
    if ISO_DATE.match(folder.parent.name):
        return folder.parent.name, folder.name
    return None


def album_name_for(folder: Path) -> str:
    """One album per day and place, named the same whatever the folder layout."""
    nested = _nested_day(folder)
    return f"{nested[0]} - {nested[1]}" if nested else folder.name


def _purge_folder(folder: Path) -> None:
    for path in folder.iterdir():
        path.unlink()
    folder.rmdir()
    if _nested_day(folder) and not any(folder.parent.iterdir()):
        folder.parent.rmdir()


def import_and_purge(
    folder: Path,
    album_name: str | None = None,
    parent_folder: str = DEFAULT_PARENT_FOLDER,
) -> tuple[ImportResult, bool]:
    """Import, then delete the local folder only when Photos took every file."""
    expected = len(media_files_in(folder))
    result = import_folder(folder, album_name, parent_folder)
    if expected == 0 or result.count != expected:
        return result, False
    _purge_folder(folder)
    return result, True


def _album_name(config: Config, friend_name: str) -> str:
    friend = config.friends.get(friend_name)
    return friend.album if friend is not None and friend.album else friend_name


def _import_placed_files(
    summary: Summary, config: Config, result: PhotosSummary
) -> dict[Path, dict[str, str]]:
    settings = config.settings
    ids_by_folder: dict[Path, dict[str, str]] = {}
    for folder, files in sorted(summary.import_files.items()):
        present = sorted(path for path in files if path.is_file())
        if not present:
            log.warning("Nothing left to import from %s", folder)
            continue
        imported = import_files(present, album_name_for(folder), settings.photos_folder)
        ids_by_folder[folder] = imported.ids_by_filename
        result.imported += imported.count
        if (
            settings.purge_after_import
            and imported.count == len(present)
            and media_files_in(folder) == present
        ):
            _purge_folder(folder)
            result.purged += 1
    return ids_by_folder


def _record_confirmed(
    result: PhotosSummary, friend_name: str, confirmed: list[str], failed: int
) -> None:
    if confirmed:
        known = result.added_by_friend.setdefault(friend_name, [])
        known.extend(
            content_hash for content_hash in confirmed if content_hash not in known
        )
    if failed:
        result.failed_by_friend[friend_name] = (
            result.failed_by_friend.get(friend_name, 0) + failed
        )
        log.warning(
            "Photos could not add %d photos for %s; they are retried the next time that photo is downloaded",
            failed,
            friend_name,
        )


def _add_shares_to_albums(
    summary: Summary,
    config: Config,
    ids_by_folder: dict[Path, dict[str, str]],
    result: PhotosSummary,
) -> None:
    for friend_name, shares in sorted(summary.album_shares.items()):
        item_ids: list[str] = []
        hashes: list[str] = []
        for path, content_hash in shares:
            item_id = ids_by_folder.get(path.parent, {}).get(path.name)
            if item_id is None:
                log.warning(
                    "No Photos id for %s; not added to %s's album", path, friend_name
                )
                continue
            item_ids.append(item_id)
            hashes.append(content_hash)
        added = add_to_album(
            item_ids, _album_name(config, friend_name), SHARED_FOLDER_NAME
        )
        result.added_to_friend_albums += added
        confirmed = hashes if item_ids and added == len(item_ids) else []
        _record_confirmed(result, friend_name, confirmed, len(shares) - len(confirmed))


def _import_shares_directly(
    summary: Summary, config: Config, result: PhotosSummary
) -> None:
    for friend_name, shares in sorted(summary.album_shares.items()):
        imported = import_files(
            [path for path, _ in shares],
            _album_name(config, friend_name),
            SHARED_FOLDER_NAME,
        )
        result.friend_imports += imported.count
        confirmed = [
            content_hash
            for path, content_hash in shares
            if path.name in imported.ids_by_filename
        ]
        _record_confirmed(result, friend_name, confirmed, len(shares) - len(confirmed))


def _import_pending_folders(
    summary: Summary, config: Config, result: PhotosSummary
) -> None:
    for friend_name, folder in sorted(summary.pending_import_folders.items()):
        expected = len(media_files_in(folder))
        imported, purged = import_and_purge(
            folder, _album_name(config, friend_name), SHARED_FOLDER_NAME
        )
        result.friend_imports += imported.count
        if not purged and expected:
            log.warning(
                "%d of %d files from %s stayed in %s; import them by hand",
                expected - imported.count,
                expected,
                folder.name,
                folder,
            )
        shares = summary.staged_shares.get(friend_name, [])
        confirmed = [
            content_hash
            for path, content_hash in shares
            if path.name in imported.ids_by_filename
        ]
        _record_confirmed(result, friend_name, confirmed, len(shares) - len(confirmed))


def sync_photos(summary: Summary, config: Config) -> PhotosSummary:
    result = PhotosSummary()
    if not is_macos():
        log.error("Photos.app import needs macOS")
        return result
    if config.settings.import_to_photos:
        ids_by_folder = _import_placed_files(summary, config, result)
        _add_shares_to_albums(summary, config, ids_by_folder, result)
    else:
        _import_shares_directly(summary, config, result)
    _import_pending_folders(summary, config, result)
    return result

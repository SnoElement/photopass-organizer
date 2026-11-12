"""Unpack PhotoPass downloads that the browser left zipped."""

from __future__ import annotations

import logging
import shutil
import zipfile
from pathlib import Path, PurePosixPath

from .media import is_uuid_folder_name, parse_photopass_name

log = logging.getLogger(__name__)

ZIP_SUFFIX = ".zip"
MAC_RESOURCE_FOLDER = "__MACOSX"
PARTIAL_SUFFIX = ".partial"


def _media_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    """Members that are real files, without the extras macOS adds to a zip."""
    members = []
    for member in archive.infolist():
        path = PurePosixPath(member.filename)
        if member.is_dir() or MAC_RESOURCE_FOLDER in path.parts:
            continue
        if path.name.startswith("."):
            continue
        members.append(member)
    return members


def _photopass_members(path: Path) -> list[zipfile.ZipInfo] | None:
    """The members to unpack, or None when the zip is not a PhotoPass batch."""
    with zipfile.ZipFile(path) as archive:
        members = _media_members(archive)
    names = [PurePosixPath(member.filename).name for member in members]
    if not names or not all(parse_photopass_name(name) for name in names):
        return None
    if len(set(names)) != len(names):
        log.warning(
            "Leaving %s alone: it holds the same file name more than once", path
        )
        return None
    return members


def _unpack(path: Path, members: list[zipfile.ZipInfo], folder: Path) -> None:
    partial = folder.with_name("." + folder.name + PARTIAL_SUFFIX)
    if partial.exists():
        shutil.rmtree(partial)
    partial.mkdir()
    try:
        with zipfile.ZipFile(path) as archive:
            for member in members:
                target = partial / PurePosixPath(member.filename).name
                with archive.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
        partial.rename(folder)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise


def expand_zip_batches(source: Path, dry_run: bool = False) -> list[Path]:
    """Unpack every UUID-named zip of PhotoPass files into a folder of the same name.

    The zip is deleted once every file is out. A dry run only reports. Returns the folders made.
    """
    if not source.is_dir():
        return []
    expanded = []
    for path in sorted(source.iterdir()):
        if path.suffix.lower() != ZIP_SUFFIX or not is_uuid_folder_name(path.stem):
            continue
        if not path.is_file():
            continue
        try:
            members = _photopass_members(path)
        except (zipfile.BadZipFile, OSError) as error:
            log.warning("Could not read %s: %s", path, error)
            continue
        if members is None:
            continue
        folder = path.with_suffix("")
        if folder.exists():
            log.warning("Leaving %s alone: %s already exists", path, folder)
            continue
        if dry_run:
            log.info("Would expand %s (%d files)", path, len(members))
            continue
        try:
            _unpack(path, members, folder)
        except (zipfile.BadZipFile, OSError) as error:
            log.warning("Could not expand %s: %s", path, error)
            continue
        path.unlink()
        log.info("Expanded %s (%d files)", path, len(members))
        expanded.append(folder)
    return expanded

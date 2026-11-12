"""Command-line entry point."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .archives import expand_zip_batches
from .config import (
    CONFIG_NAME,
    Config,
    ConfigError,
    Settings,
    load_config,
    state_dir,
    write_config,
)
from .organizer import Organizer, PlaceMode, TripRange
from .photos import (
    album_name_for,
    import_and_purge,
    import_folder,
    media_files_in,
    sync_photos,
)
from .review_server import open_review

log = logging.getLogger(__name__)


class OncePerMessage(logging.Filter):
    """Drop a message already shown; the review server plans again after every change."""

    def __init__(self) -> None:
        super().__init__()
        self._seen: set[tuple[int, str]] = set()

    def filter(self, record: logging.LogRecord) -> bool:
        key = (record.levelno, record.getMessage())
        if key in self._seen:
            return False
        self._seen.add(key)
        return True


def _common_options() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help="folder holding photopass.toml, the ledger and the log",
    )
    common.add_argument("--verbose", action="store_true")
    return common


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="photopass-organizer", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    common = _common_options()

    subparsers.add_parser(
        "init",
        parents=[common],
        help="write a starter photopass.toml in the state directory",
    )

    review_parser = subparsers.add_parser(
        "review", parents=[common], help="decide which days to keep, share or ignore"
    )
    review_parser.add_argument(
        "--no-open",
        action="store_true",
        help="do not open the review page in the browser",
    )
    review_parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="port for the review page; default any free port",
    )

    organize_parser = subparsers.add_parser(
        "organize",
        parents=[common],
        help="file the photos in the source folder by local date and park",
    )
    organize_parser.add_argument(
        "--dry-run", action="store_true", help="print the plan and change nothing"
    )
    organize_parser.add_argument(
        "--copy",
        action="store_true",
        help="copy instead of move; leaves the source folder untouched",
    )
    organize_parser.add_argument(
        "--trip",
        metavar="RANGE",
        help="only handle days in YYYY-MM-DD or YYYY-MM-DD..YYYY-MM-DD",
    )

    import_parser = subparsers.add_parser(
        "import-photos",
        parents=[common],
        help="import already organized folders into Photos albums",
    )
    import_parser.add_argument(
        "folders",
        nargs="*",
        type=Path,
        help="folders to import; default every day folder under the destination",
    )
    import_parser.add_argument(
        "--purge",
        action="store_true",
        help="delete a local folder once Photos confirms it imported every file",
    )
    return parser


def _load(state: Path) -> Config:
    return load_config(state / CONFIG_NAME)


def _run_init(state: Path) -> int:
    config_path = state / CONFIG_NAME
    if config_path.exists():
        log.warning("%s already exists, nothing written", config_path)
        return 0
    state.mkdir(parents=True, exist_ok=True)
    write_config(Config(settings=Settings.platform_defaults()), config_path)
    print(
        f"SUCCESS: wrote {config_path}; edit [settings] then run photopass-organizer review"
    )
    return 0


def _run_review(state: Path, args: argparse.Namespace) -> int:
    config = _load(state)
    expand_zip_batches(config.settings.source)
    plan = Organizer(config, state, mode=PlaceMode.COPY, dry_run=True).plan()
    if not plan.items:
        log.info("no PhotoPass files found in %s", config.settings.source)
    return open_review(state, config, open_browser=not args.no_open, port=args.port)


def _run_organize(state: Path, args: argparse.Namespace) -> int:
    try:
        trip = TripRange.parse(args.trip) if args.trip else None
    except ValueError as error:
        log.error("--trip: %s", error)
        return 2
    config = _load(state)
    mode = PlaceMode.COPY if args.copy else PlaceMode.MOVE
    expand_zip_batches(config.settings.source, dry_run=args.dry_run or args.copy)
    organizer = Organizer(config, state, mode=mode, dry_run=args.dry_run, trip=trip)
    summary = organizer.execute(organizer.plan())
    verb = "Would place" if args.dry_run else "Placed"
    print(
        f"SUCCESS: {verb} {summary.placed} for me, shared {summary.shared}, deleted {summary.deleted} friend-only, "
        f"ignored {summary.ignored}, duplicates {summary.duplicates}, stock art {summary.stock}, "
        f"undecided {summary.undecided} left in the source folder, folders removed {summary.folders_removed}"
    )
    wants_photos = (
        config.settings.import_to_photos
        or summary.album_shares
        or summary.pending_import_folders
    )
    if not args.dry_run and wants_photos:
        photos = sync_photos(summary, config)
        organizer.confirm_album_shares(photos.added_by_friend)
        print(
            f"SUCCESS: imported {photos.imported} into Photos, purged {photos.purged} folders, "
            f"added {photos.added_to_friend_albums} to friend albums, imported {photos.friend_imports} for friends"
        )
    return 0


def _day_folders(destination: Path) -> list[Path]:
    if not destination.is_dir():
        return []
    return sorted(
        (
            folder
            for folder in destination.rglob("*")
            if folder.is_dir()
            and not any(
                part.startswith(("_", "."))
                for part in folder.relative_to(destination).parts
            )
            and media_files_in(folder)
        ),
        key=album_name_for,
    )


def _run_import_photos(state: Path, args: argparse.Namespace) -> int:
    settings = _load(state).settings
    folders = args.folders or _day_folders(settings.destination)
    imported_total = 0
    purged = 0
    for folder in folders:
        if args.purge:
            imported, was_purged = import_and_purge(
                folder,
                album_name=album_name_for(folder),
                parent_folder=settings.photos_folder,
            )
            purged += was_purged
        else:
            imported = import_folder(
                folder,
                album_name=album_name_for(folder),
                parent_folder=settings.photos_folder,
            )
        imported_total += imported.count
    print(
        f"SUCCESS: imported {imported_total} items from {len(folders)} folders into Photos, purged {purged}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
        force=True,
    )
    if args.command == "review":
        for handler in logging.getLogger().handlers:
            handler.addFilter(OncePerMessage())
    state = state_dir(args.state_dir)
    try:
        if args.command == "init":
            return _run_init(state)
        if args.command == "review":
            return _run_review(state, args)
        if args.command == "organize":
            return _run_organize(state, args)
        return _run_import_photos(state, args)
    except ConfigError as error:
        log.error("%s", error)
        return 2
    except OSError as error:
        log.error("%s", error)
        return 1


if __name__ == "__main__":
    sys.exit(main())

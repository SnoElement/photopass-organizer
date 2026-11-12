import logging
import os
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from conftest import decided_config, write_jpeg, write_mp4

from photopass_organizer.media import hash_file
from photopass_organizer.organizer import (
    STOCK_FOLDER_NAME,
    ActionKind,
    Organizer,
    PlaceMode,
)

BATCH_A = "ecd5e910-484f-4b99-ac12-9fad86cefc89"
BATCH_B = "ece7d414-cd5e-4995-adf1-ccea11580c47"


@pytest.fixture
def downloads(tmp_path):
    folder = tmp_path / "Downloads"
    folder.mkdir()
    return folder


@pytest.fixture
def destination(tmp_path):
    return tmp_path / "PhotoPass"


def make_organizer(
    downloads, destination, mode=PlaceMode.MOVE, dry_run=False, stock_art="delete"
):
    config = decided_config(downloads, destination, stock_art)
    return Organizer(config, destination.parent / "state", mode=mode, dry_run=dry_run)


def plan_for(downloads, destination, mode=PlaceMode.MOVE):
    organizer = make_organizer(downloads, destination, mode)
    return organizer, organizer.plan()


def test_evening_photo_lands_on_local_date_not_filename_date(downloads, destination):
    write_jpeg(
        downloads / BATCH_A / "2026-03-07 - Disneyland Park - Castle.jpeg",
        "2026:03:06 22:11:49",
        "-08:00",
    )
    _, plan = plan_for(downloads, destination)
    placements = [a for a in plan.actions if a.kind is ActionKind.PLACE]
    assert len(placements) == 1
    assert (
        placements[0].target
        == destination
        / "2026-03-06 - Disneyland Park"
        / "2026-03-07 - Disneyland Park - Castle.jpeg"
    )


def test_photo_without_exif_falls_back_to_filename_date(downloads, destination):
    write_jpeg(
        downloads / BATCH_A / "2026-03-07 - Disneyland Park - Castle.jpeg", None, None
    )
    _, plan = plan_for(downloads, destination)
    placements = [a for a in plan.actions if a.kind is ActionKind.PLACE]
    assert placements[0].target.parent == destination / "2026-03-07 - Disneyland Park"


def test_duplicate_content_across_batches_is_placed_once(downloads, destination):
    write_jpeg(
        downloads
        / BATCH_A
        / "2026-03-06 - Disneyland Park - New orleans square_6.jpeg",
        "2026:03:06 14:00:00",
        "-08:00",
        seed=1,
    )
    write_jpeg(
        downloads / BATCH_B / "2026-03-06 - Disneyland Park - New orleans square.jpeg",
        "2026:03:06 14:00:00",
        "-08:00",
        seed=1,
    )
    _, plan = plan_for(downloads, destination)
    kinds = sorted(
        (
            a.kind
            for a in plan.actions
            if a.kind in (ActionKind.PLACE, ActionKind.DUPLICATE)
        ),
        key=lambda kind: kind.value,
    )
    assert kinds == [ActionKind.DUPLICATE, ActionKind.PLACE]


def test_same_name_different_content_gets_suffix(downloads, destination):
    write_jpeg(
        downloads / BATCH_A / "2026-03-06 - Disneyland Park - New orleans square.jpeg",
        "2026:03:06 14:00:00",
        "-08:00",
        seed=1,
    )
    write_jpeg(
        downloads / BATCH_B / "2026-03-06 - Disneyland Park - New orleans square.jpeg",
        "2026:03:06 15:00:00",
        "-08:00",
        seed=2,
    )
    _, plan = plan_for(downloads, destination)
    targets = sorted(a.target.name for a in plan.actions if a.kind is ActionKind.PLACE)
    assert targets == [
        "2026-03-06 - Disneyland Park - New orleans square (2).jpeg",
        "2026-03-06 - Disneyland Park - New orleans square.jpeg",
    ]


def test_existing_destination_content_counts_as_duplicate(downloads, destination):
    existing = (
        destination
        / "2026-03-06 - Disneyland Park"
        / "2026-03-06 - Disneyland Park - Castle.jpeg"
    )
    write_jpeg(existing, "2026:03:06 14:00:00", "-08:00", seed=9)
    write_jpeg(
        downloads / BATCH_A / "2026-03-06 - Disneyland Park - Castle_3.jpeg",
        "2026:03:06 14:00:00",
        "-08:00",
        seed=9,
    )
    _, plan = plan_for(downloads, destination)
    assert [
        a.kind
        for a in plan.actions
        if a.kind in (ActionKind.PLACE, ActionKind.DUPLICATE)
    ] == [ActionKind.DUPLICATE]


def test_dated_video_uses_park_timezone(downloads, destination):
    created = datetime(2026, 6, 7, 0, 47, 25, tzinfo=UTC)
    write_mp4(
        downloads
        / BATCH_A
        / "2026-06-07 - Magic Kingdom Park - Main street usa_16.mp4",
        created,
    )
    _, plan = plan_for(downloads, destination)
    placements = [a for a in plan.actions if a.kind is ActionKind.PLACE]
    assert (
        placements[0].target.parent == destination / "2026-06-06 - Magic Kingdom Park"
    )


def test_loose_video_infers_park_from_nearby_photo(downloads, destination):
    write_jpeg(
        downloads / BATCH_A / "2026-06-06 - Magic Kingdom Park - Castle.jpeg",
        "2026:06:06 18:00:00",
        "-04:00",
    )
    write_mp4(
        downloads / "2145506679.mp4",
        datetime(2026, 6, 7, 0, 47, 25, tzinfo=UTC),
    )
    _, plan = plan_for(downloads, destination)
    video_actions = [a for a in plan.actions if a.source.name == "2145506679.mp4"]
    assert video_actions[0].kind is ActionKind.PLACE
    assert (
        video_actions[0].target
        == destination / "2026-06-06 - Magic Kingdom Park" / "2145506679.mp4"
    )


def test_loose_video_pairs_with_nearest_timed_photo_within_three_hours(
    downloads, destination
):
    write_jpeg(
        downloads / BATCH_A / "2026-06-06 - Magic Kingdom Park - Castle.jpeg",
        "2026:06:06 10:00:00",
        "-04:00",
        seed=1,
    )
    still = write_jpeg(
        downloads / BATCH_A / "2026-06-06 - Epcot - Spaceship earth.jpeg",
        "2026:06:06 20:45:00",
        "-04:00",
        seed=2,
    )
    write_mp4(
        downloads / "2145506679.mp4",
        datetime(2026, 6, 7, 0, 47, 25, tzinfo=UTC),
    )
    _, plan = plan_for(downloads, destination)
    video_actions = [a for a in plan.actions if a.source.name == "2145506679.mp4"]
    assert video_actions[0].target.parent == destination / "2026-06-06 - Epcot"
    video_item = next(item for item in plan.items if item.is_video)
    assert video_item.paired_still == still


def test_loose_video_with_two_parks_and_no_close_photo_uses_resort_folder(
    downloads, destination
):
    write_jpeg(
        downloads / BATCH_A / "2026-06-06 - Magic Kingdom Park - Castle.jpeg",
        "2026:06:06 09:00:00",
        "-04:00",
        seed=1,
    )
    write_jpeg(
        downloads / BATCH_A / "2026-06-06 - Epcot - Spaceship earth.jpeg",
        "2026:06:06 12:00:00",
        "-04:00",
        seed=2,
    )
    write_mp4(
        downloads / "2145506679.mp4",
        datetime(2026, 6, 7, 2, 47, 25, tzinfo=UTC),
    )
    _, plan = plan_for(downloads, destination)
    video_actions = [a for a in plan.actions if a.source.name == "2145506679.mp4"]
    assert (
        video_actions[0].target.parent == destination / "2026-06-06 - Walt Disney World"
    )


def test_loose_video_without_creation_time_is_skipped(downloads, destination):
    write_mp4(downloads / "13190208.mp4", None)
    _, plan = plan_for(downloads, destination)
    assert [a.kind for a in plan.actions] == [ActionKind.SKIP]


def test_folder_with_foreign_files_is_left_alone(downloads, destination):
    foreign = downloads / "32cfbee1-0000-4000-8000-000000000000"
    write_mp4(foreign / "18-video-108971099.mp4", datetime(2025, 8, 5, tzinfo=UTC))
    write_jpeg(
        downloads / BATCH_A / "2026-03-06 - Disneyland Park - Castle.jpeg",
        "2026:03:06 14:00:00",
        "-08:00",
    )
    organizer, plan = plan_for(downloads, destination)
    assert all(a.source.parent != foreign for a in plan.actions)
    organizer.execute(plan)
    assert (foreign / "18-video-108971099.mp4").exists()


def test_execute_move_sets_mtime_deletes_duplicates_and_empty_folders(
    downloads, destination
):
    write_jpeg(
        downloads / BATCH_A / "2026-03-06 - Disneyland Park - Castle.jpeg",
        "2026:03:06 14:00:00",
        "-08:00",
        seed=1,
    )
    write_jpeg(
        downloads / BATCH_B / "2026-03-06 - Disneyland Park - Castle_2.jpeg",
        "2026:03:06 14:00:00",
        "-08:00",
        seed=1,
    )
    (downloads / BATCH_B / ".DS_Store").write_bytes(b"junk")
    stale_empty = downloads / "1566530b-0000-4000-8000-000000000000"
    stale_empty.mkdir()
    organizer, plan = plan_for(downloads, destination)
    summary = organizer.execute(plan)
    placed = (
        destination
        / "2026-03-06 - Disneyland Park"
        / "2026-03-06 - Disneyland Park - Castle.jpeg"
    )
    assert placed.exists()
    assert datetime.fromtimestamp(os.stat(placed).st_mtime, tz=UTC) == datetime(
        2026, 3, 6, 22, 0, 0, tzinfo=UTC
    )
    assert not (downloads / BATCH_A).exists()
    assert not (downloads / BATCH_B).exists()
    assert not stale_empty.exists()
    assert (
        summary.placed == 1 and summary.duplicates == 1 and summary.folders_removed == 3
    )


def test_execute_copy_leaves_sources(downloads, destination):
    source = write_jpeg(
        downloads / BATCH_A / "2026-03-06 - Disneyland Park - Castle.jpeg",
        "2026:03:06 14:00:00",
        "-08:00",
    )
    organizer, plan = plan_for(downloads, destination, mode=PlaceMode.COPY)
    organizer.execute(plan)
    assert source.exists()
    assert (destination / "2026-03-06 - Disneyland Park" / source.name).exists()
    assert (downloads / BATCH_A).exists()


def test_dry_run_changes_nothing(downloads, destination):
    source = write_jpeg(
        downloads / BATCH_A / "2026-03-06 - Disneyland Park - Castle.jpeg",
        "2026:03:06 14:00:00",
        "-08:00",
    )
    organizer = make_organizer(downloads, destination, dry_run=True)
    organizer.execute(organizer.plan())
    assert source.exists()
    assert not destination.exists()
    assert not (destination.parent / "state").exists()


def test_on_ride_photo_without_exif_is_dated_by_same_day_neighbours(
    downloads, destination
):
    write_jpeg(
        downloads / BATCH_A / "2026-10-15 - Magic Kingdom Park - Castle.jpeg",
        "2026:10:14 21:00:00",
        "-04:00",
        seed=1,
    )
    write_jpeg(
        downloads / BATCH_A / "2026-10-15 - Magic Kingdom Park - Castle_2.jpeg",
        "2026:10:14 21:30:00",
        "-04:00",
        seed=2,
    )
    write_jpeg(
        downloads / BATCH_A / "2026-10-15 - Magic Kingdom Park - Buzz lightyear.jpeg",
        None,
        None,
        seed=4,
    )
    _, plan = plan_for(downloads, destination)
    folders = {a.target.parent.name for a in plan.actions if a.kind is ActionKind.PLACE}
    assert folders == {"2026-10-14 - Magic Kingdom Park"}


def test_template_exif_date_marks_stock_art(downloads, destination):
    write_jpeg(
        downloads
        / BATCH_A
        / "2026-10-15 - Magic Kingdom Park - Haunted mansion_3.jpeg",
        "2010:10:05 21:23:15",
        None,
    )
    _, plan = plan_for(downloads, destination)
    assert [a.kind for a in plan.actions] == [ActionKind.STOCK]
    assert plan.actions[0].target is None


def test_embedded_color_profile_marks_stock_art(downloads, destination):
    write_jpeg(
        downloads / BATCH_A / "2026-10-15 - Magic Kingdom Park - Castle.jpeg",
        "2026:10:15 12:00:00",
        "-04:00",
        icc=True,
    )
    _, plan = plan_for(downloads, destination)
    assert [a.kind for a in plan.actions] == [ActionKind.STOCK]


def test_stock_art_deleted_in_move_mode_or_kept_when_asked(downloads, destination):
    source = write_jpeg(
        downloads / BATCH_A / "2026-10-15 - Magic Kingdom Park - Castle.jpeg",
        "2026:10:15 12:00:00",
        "-04:00",
        icc=True,
    )
    organizer, plan = plan_for(downloads, destination)
    summary = organizer.execute(plan)
    assert (
        summary.stock == 1
        and not source.exists()
        and not (destination / STOCK_FOLDER_NAME).exists()
    )
    source = write_jpeg(
        downloads / BATCH_A / "2026-10-15 - Magic Kingdom Park - Castle.jpeg",
        "2026:10:15 12:00:00",
        "-04:00",
        icc=True,
    )
    organizer = make_organizer(downloads, destination, stock_art="keep")
    organizer.execute(organizer.plan())
    assert (destination / STOCK_FOLDER_NAME / source.name).exists()


def test_loose_photopass_photo_at_top_level_is_organized(downloads, destination):
    source = write_jpeg(
        downloads / "2026-03-06 - Disneyland Park - Tianas bayou adventure.jpeg",
        "2026:03:06 14:00:00",
        "-08:00",
    )
    _, plan = plan_for(downloads, destination)
    placements = [a for a in plan.actions if a.kind is ActionKind.PLACE]
    assert placements[0].source == source
    assert placements[0].target.parent == destination / "2026-03-06 - Disneyland Park"


def test_photo_without_exif_is_stamped_at_local_noon(downloads, destination):
    write_jpeg(
        downloads
        / BATCH_A
        / "2025-01-01 - Epcot - Guardians of the galaxy cosmic rewind.jpeg",
        None,
        None,
    )
    _, plan = plan_for(downloads, destination)
    placement = next(a for a in plan.actions if a.kind is ActionKind.PLACE)
    assert placement.captured_at == datetime(2025, 1, 1, 12, 0, tzinfo=UTC).astimezone(
        placement.captured_at.tzinfo
    ).replace(hour=12)
    assert (
        placement.captured_at.hour == 12
        and placement.captured_at.utcoffset().total_seconds() == -5 * 3600
    )


def test_destination_hashes_are_cached_and_skip_dot_files(downloads, destination):
    placed = write_jpeg(
        destination / "2026-03-06 - Disneyland Park" / "Castle.jpeg",
        "2026:03:06 14:00:00",
        "-08:00",
        seed=3,
    )
    (destination / ".hidden").write_bytes(b"secret")
    organizer = make_organizer(downloads, destination)
    first = organizer.destination_hashes()
    assert first == {hash_file(placed)}
    write_jpeg(destination / "later.jpeg", "2026:03:06 14:00:00", "-08:00", seed=4)
    assert organizer.destination_hashes() == {hash_file(placed)}


def layout_organizer(downloads, destination, layout):
    config = decided_config(downloads, destination)
    config = replace(config, settings=replace(config.settings, layout=layout))
    return Organizer(config, destination.parent / "state")


@pytest.mark.parametrize(
    ("layout", "folder"),
    [
        ("flat", "2026-03-06 - Disneyland Park"),
        ("date/park", "2026-03-06/Disneyland Park"),
        ("park/date", "Disneyland Park/2026-03-06"),
    ],
)
def test_layout_setting_chooses_the_folder_structure(
    layout, folder, downloads, destination
):
    name = "2026-03-07 - Disneyland Park - Castle.jpeg"
    write_jpeg(downloads / BATCH_A / name, "2026:03:06 22:11:49", "-08:00")
    organizer = layout_organizer(downloads, destination, layout)
    organizer.execute(organizer.plan())
    assert (destination / folder / name).is_file()


@pytest.mark.parametrize(
    ("layout", "folder"),
    [
        ("flat", "2026-09-20 - Oogie Boogie Bash"),
        ("date/park", "2026-09-20/Oogie Boogie Bash"),
        ("park/date", "Oogie Boogie Bash/2026-09-20"),
    ],
)
def test_special_event_photos_go_to_a_folder_named_for_the_event(
    layout, folder, downloads, destination
):
    name = "2026-09-21 - Special Events at DCA - Oogie boogie bash  a disney halloween party_3.jpeg"
    write_jpeg(downloads / BATCH_A / name, "2026:09:20 22:54:03", None)
    ride = "2026-09-21 - Disney California Adventure Park - Incredicoaster.jpeg"
    write_jpeg(downloads / BATCH_A / ride, "2026:09:20 18:45:01", None, seed=2)
    organizer = layout_organizer(downloads, destination, layout)
    plan = organizer.plan()
    assert plan.unknown_parks == []
    organizer.execute(plan)
    assert (destination / folder / name).is_file()
    assert not (destination / folder / ride).exists()


def test_routine_skips_are_info_and_only_a_filename_date_is_a_warning(
    downloads, destination, caplog
):
    write_jpeg(downloads / BATCH_A / "notes.jpeg", None, None)
    write_mp4(downloads / "13190208.mp4", None)
    write_jpeg(
        downloads / "2026-03-07 - Disneyland Park - Castle.jpeg",
        "2026:03:06 22:11:49",
        "-08:00",
    )
    write_jpeg(
        downloads / "2026-03-07 - Disneyland Park - Ride.jpeg", None, None, seed=2
    )
    write_jpeg(downloads / "2026-05-01 - Epcot - Ride.jpeg", None, None, seed=3)
    with caplog.at_level(logging.INFO):
        plan_for(downloads, destination)
    levels = {record.getMessage(): record.levelname for record in caplog.records}
    by_start = {
        text.split(":")[0].split(";")[0]: level for text, level in levels.items()
    }
    assert by_start["Leaving folder with non-PhotoPass files alone"] == "INFO"
    assert by_start["Skipping 13190208.mp4"] == "INFO"
    assert (
        levels[
            "No usable capture time in 2026-03-07 - Disneyland Park - Ride.jpeg; dated by neighbours as 2026-03-06"
        ]
        == "INFO"
    )
    assert (
        levels[
            "No usable capture time in 2026-05-01 - Epcot - Ride.jpeg; dated by filename as 2026-05-01"
        ]
        == "WARNING"
    )


@pytest.mark.parametrize("layout", ["flat", "date/park", "park/date"])
def test_a_dot_dot_park_cannot_file_outside_the_destination(
    layout, downloads, destination
):
    name = "2026-03-07 - .. - Castle.jpeg"
    write_jpeg(downloads / name, "2026:03:06 22:11:49", "-08:00")
    organizer = layout_organizer(downloads, destination, layout)
    plan = organizer.plan()
    assert plan.items == []
    organizer.execute(plan)
    assert (downloads / name).is_file()
    strays = [
        path
        for path in destination.parent.rglob("*.jpeg")
        if downloads not in path.parents
    ]
    assert strays == []

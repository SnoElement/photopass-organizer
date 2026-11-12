import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import write_jpeg, write_mp4

from photopass_organizer.config import ConfigError, parse_config
from photopass_organizer.media import hash_file
from photopass_organizer.organizer import ActionKind, Organizer, PlaceMode, TripRange
from photopass_organizer.shared import SharedFolderIndex

BATCH = "ecd5e910-484f-4b99-ac12-9fad86cefc89"


@pytest.fixture
def world(tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    shared_root = tmp_path / "Shared Photos"
    (shared_root / "Alex").mkdir(parents=True)
    (shared_root / "Sam").mkdir()
    return downloads, tmp_path / "PhotoPass", shared_root


def config_for(world, toml_text):
    downloads, destination, shared_root = world
    header = f'[settings]\nsource = "{downloads}"\ndestination = "{destination}"\nshared_root = "{shared_root}"\n\n'
    return parse_config(header + toml_text)


def state_dir_for(world):
    return world[1].parent / "state"


def organizer_for(world, toml_text, mode=PlaceMode.MOVE, trip=None):
    _, _, shared_root = world
    return Organizer(
        config_for(world, toml_text),
        state_dir_for(world),
        mode=mode,
        shared_index=SharedFolderIndex.load(
            {"Alex": shared_root / "Alex", "Sam": shared_root / "Sam"}
        ),
        trip=trip,
    )


def ledger_json(world):
    return json.loads(
        (state_dir_for(world) / "ledger.json").read_text(encoding="utf-8")
    )


def trip_toml(
    friends="", i_was_there=True, start="2026-10-09", end="2026-10-14", extra=""
):
    return f'[[trip]]\nstart = "{start}"\nend = "{end}"\nfriends = [{friends}]\ni_was_there = {str(i_was_there).lower()}\n{extra}'


def kinds_for(plan, name):
    return [(a.kind, a.target) for a in plan.actions if a.source.name == name]


def test_parse_config_rules_and_defaults():
    config = parse_config("""
[[trip]]
start = "2026-10-09"
end = "2026-10-14"
friends = ["Alex"]
i_was_there = false

[[trip]]
start = "2025-06-18"
end = "2025-06-21"
friends = ["Sam", "Brandon"]
""")
    assert len(config.trips) == 2
    assert config.trips[0].i_was_there is False and config.trips[0].parks is None
    assert config.trips[1].i_was_there is True and config.trips[1].friends == (
        "Sam",
        "Brandon",
    )
    assert config.rule_for(datetime(2026, 10, 10).date(), "Epcot") is config.trips[0]
    assert config.rule_for(datetime(2026, 10, 20).date(), "Epcot") is None


def test_parse_config_rejects_overlap_and_unknown_keys():
    with pytest.raises(ConfigError):
        parse_config(
            '[[trip]]\nstart = "2026-10-09"\nend = "2026-10-14"\n[[trip]]\nstart = "2026-10-14"\nend = "2026-10-18"\n'
        )
    with pytest.raises(ConfigError):
        parse_config('[[trip]]\nstart = "2026-10-09"\nowner = "x"\n')


def test_park_split_rules_do_not_overlap():
    config = parse_config("""
[[trip]]
start = "2026-10-14"
end = "2026-10-14"
parks = ["Epcot"]
friends = ["Alex"]
i_was_there = false

[[trip]]
start = "2026-10-14"
end = "2026-10-14"
parks = ["Magic Kingdom Park"]
friends = []
""")
    assert config.rule_for(datetime(2026, 10, 14).date(), "Epcot").friends == ("Alex",)
    assert (
        config.rule_for(datetime(2026, 10, 14).date(), "Magic Kingdom Park").friends
        == ()
    )


def test_friend_only_trip_is_shared_then_deleted(world):
    downloads, destination, shared_root = world
    source = write_jpeg(
        downloads / BATCH / "2026-10-10 - Epcot - Italy at epcot_8.jpeg",
        "2026:10:10 14:00:00",
        "-04:00",
        seed=1,
    )
    organizer = organizer_for(
        world,
        '[[trip]]\nstart = "2026-10-09"\nend = "2026-10-14"\nfriends = ["Alex"]\ni_was_there = false\n',
    )
    plan = organizer.plan()
    assert [kind for kind, _ in kinds_for(plan, source.name)] == [
        ActionKind.SHARE,
        ActionKind.DELETE,
    ]
    summary = organizer.execute(plan)
    assert (shared_root / "Alex" / source.name).exists()
    assert not source.exists()
    assert not destination.joinpath("2026-10-10 - Epcot").exists()
    assert summary.shared == 1 and summary.deleted == 1 and summary.placed == 0


def test_my_trip_with_two_friends_is_shared_twice_and_kept(world):
    downloads, destination, shared_root = world
    source = write_jpeg(
        downloads / BATCH / "2025-06-21 - Disneyland Park - Mickey.jpeg",
        "2025:06:21 13:47:00",
        "-07:00",
        seed=1,
    )
    organizer = organizer_for(
        world,
        '[[trip]]\nstart = "2025-06-18"\nend = "2025-06-21"\nfriends = ["Sam", "Alex"]\n',
    )
    plan = organizer.plan()
    assert [kind for kind, _ in kinds_for(plan, source.name)] == [
        ActionKind.SHARE,
        ActionKind.SHARE,
        ActionKind.PLACE,
    ]
    organizer.execute(plan)
    assert (shared_root / "Sam" / source.name).exists()
    assert (shared_root / "Alex" / source.name).exists()
    assert (destination / "2025-06-21 - Disneyland Park" / source.name).exists()


def test_already_shared_photo_is_not_copied_again(world):
    downloads, _destination, shared_root = world
    source = write_jpeg(
        downloads / BATCH / "2026-10-10 - Epcot - Italy at epcot_8.jpeg",
        "2026:10:10 14:00:00",
        "-04:00",
        seed=1,
    )
    write_jpeg(
        shared_root / "Alex" / "2026-10-10 - Epcot - Italy at epcot_3.jpeg",
        "2026:10:10 14:00:00",
        "-04:00",
        seed=1,
    )
    organizer = organizer_for(
        world,
        '[[trip]]\nstart = "2026-10-09"\nend = "2026-10-14"\nfriends = ["Alex"]\ni_was_there = false\n',
    )
    plan = organizer.plan()
    assert [kind for kind, _ in kinds_for(plan, source.name)] == [ActionKind.DUPLICATE]


def test_friend_only_delete_is_remembered_on_the_next_run(world):
    downloads, _destination, _shared_root = world
    toml_text = '[[trip]]\nstart = "2026-10-09"\nend = "2026-10-14"\nfriends = ["Alex"]\ni_was_there = false\n'
    write_jpeg(
        downloads / BATCH / "2026-10-10 - Epcot - Italy at epcot_8.jpeg",
        "2026:10:10 14:00:00",
        "-04:00",
        seed=1,
    )
    organizer_for(world, toml_text).execute(organizer_for(world, toml_text).plan())
    redownload = write_jpeg(
        downloads / BATCH / "2026-10-10 - Epcot - Italy at epcot_2.jpeg",
        "2026:10:10 14:00:00",
        "-04:00",
        seed=1,
    )
    plan = organizer_for(world, "").plan()
    assert plan.actions[0].reason == "same content previously processed"
    assert [kind for kind, _ in kinds_for(plan, redownload.name)] == [
        ActionKind.DUPLICATE
    ]


def test_legacy_ledger_entry_is_complete_so_nothing_is_reshared(world):
    downloads, _destination, shared_root = world
    source = write_jpeg(
        downloads / BATCH / "2026-10-10 - Epcot - Italy at epcot_8.jpeg",
        "2026:10:10 14:00:00",
        "-04:00",
        seed=1,
    )
    state = state_dir_for(world)
    state.mkdir(parents=True)
    (state / "ledger.json").write_text(
        json.dumps({hash_file(source): {"path": "", "handled_at": "2026-01-01"}}),
        encoding="utf-8",
    )
    organizer = organizer_for(
        world,
        '[[trip]]\nstart = "2026-10-09"\nend = "2026-10-14"\nfriends = ["Alex"]\ni_was_there = false\n',
    )
    plan = organizer.plan()
    assert [kind for kind, _ in kinds_for(plan, source.name)] == [ActionKind.DUPLICATE]
    organizer.execute(plan)
    assert list((shared_root / "Alex").iterdir()) == []


def test_paired_video_follows_the_trip_rule_of_its_still(world):
    downloads, _destination, shared_root = world
    write_jpeg(
        downloads / BATCH / "2026-10-12 - Magic Kingdom Park - Buzz.jpeg",
        "2026:10:12 09:17:00",
        "-04:00",
        seed=1,
    )
    video = write_mp4(
        downloads / "2266277915.mp4",
        datetime(2026, 10, 12, 13, 19, 35, tzinfo=UTC),
    )
    organizer = organizer_for(
        world,
        '[[trip]]\nstart = "2026-10-09"\nend = "2026-10-14"\nfriends = ["Alex"]\ni_was_there = false\n',
    )
    plan = organizer.plan()
    assert [kind for kind, _ in kinds_for(plan, video.name)] == [
        ActionKind.SHARE,
        ActionKind.DELETE,
    ]
    assert kinds_for(plan, video.name)[0][1] == shared_root / "Alex" / video.name


def test_copy_mode_shares_but_never_deletes(world):
    downloads, _destination, shared_root = world
    source = write_jpeg(
        downloads / BATCH / "2026-10-10 - Epcot - Italy at epcot_8.jpeg",
        "2026:10:10 14:00:00",
        "-04:00",
        seed=1,
    )
    organizer = organizer_for(
        world,
        '[[trip]]\nstart = "2026-10-09"\nend = "2026-10-14"\nfriends = ["Alex"]\ni_was_there = false\n',
        mode=PlaceMode.COPY,
    )
    organizer.execute(organizer.plan())
    assert source.exists() and (shared_root / "Alex" / source.name).exists()


def test_zero_size_shared_file_warns_and_is_not_matched(world, caplog):
    _, _, shared_root = world
    name = "2026-10-10 - Epcot - Italy_1.jpeg"
    (shared_root / "Alex" / name).touch()
    (shared_root / "Sam" / name).write_bytes(b"x" * 1234)
    with caplog.at_level("WARNING"):
        index = SharedFolderIndex.load(
            {"Alex": shared_root / "Alex", "Sam": shared_root / "Sam"}
        )
    assert index.zero_size_files == {"Alex": 1}
    assert "report size 0" in caplog.text
    assert index.friends_holding(name, 0) == set()
    assert index.friends_holding(name, 1234) == {"Sam"}


def test_index_uses_each_configured_folder_and_tolerates_missing_ones(tmp_path):
    other_drive = tmp_path / "OtherDrive" / "Jordan"
    other_drive.mkdir(parents=True)
    (other_drive / "2026-10-10 - Epcot - Italy_1.jpeg").write_bytes(b"x" * 1234)
    (other_drive / ".hidden").write_bytes(b"x")
    missing = tmp_path / "NotThere"
    index = SharedFolderIndex.load({"Jordan": other_drive, "Alex": missing})
    assert index.friends == ["Jordan", "Alex"]
    assert index.file_count == 1
    assert index.zero_size_files == {}
    assert index.folder_for("Jordan") == other_drive
    assert index.friends_holding("2026-10-10 - Epcot - Italy_1.jpeg", 1234) == {
        "Jordan"
    }
    assert not missing.exists()
    with pytest.raises(KeyError):
        index.folder_for("Sam")


PHOTO = "2026-10-10 - Epcot - Italy at epcot_8.jpeg"
OTHER_DAY_PHOTO = "2026-10-12 - Epcot - Italy at epcot_8.jpeg"


def test_day_without_rule_is_left_undecided(world):
    downloads, destination, _ = world
    source = write_jpeg(
        downloads / BATCH / PHOTO, "2026:10:10 14:00:00", "-04:00", seed=1
    )
    organizer = organizer_for(world, "")
    plan = organizer.plan()
    assert [(a.kind, a.reason) for a in plan.actions] == [
        (ActionKind.SKIP, "undecided")
    ]
    summary = organizer.execute(plan)
    assert source.exists()
    assert not destination.exists()
    assert summary.undecided == 1 and summary.skipped == 0 and summary.placed == 0


def test_ignored_day_is_deleted(world):
    downloads, _, _ = world
    source = write_jpeg(
        downloads / BATCH / PHOTO, "2026:10:10 14:00:00", "-04:00", seed=1
    )
    organizer = organizer_for(world, '[[trip]]\nstart = "2026-10-10"\nignore = true\n')
    plan = organizer.plan()
    assert [(a.kind, a.reason) for a in plan.actions] == [
        (ActionKind.DELETE, "ignored day")
    ]
    summary = organizer.execute(plan)
    assert not source.exists()
    assert summary.ignored == 1 and summary.placed == 0
    assert ledger_json(world)[plan.actions[0].content_hash]["reason"] == "ignored day"


def test_ignored_photo_override_is_deleted_whatever_the_day_says(world):
    downloads, destination, _ = world
    source = write_jpeg(
        downloads / BATCH / PHOTO, "2026:10:10 14:00:00", "-04:00", seed=1
    )
    digest = hash_file(source)
    toml_text = trip_toml() + f'\n[[photo]]\nhash = "{digest}"\naction = "ignore"\n'
    organizer = organizer_for(world, toml_text)
    plan = organizer.plan()
    assert [(a.kind, a.reason) for a in plan.actions] == [
        (ActionKind.DELETE, "ignored photo")
    ]
    organizer.execute(plan)
    assert not source.exists()
    assert not destination.exists()
    assert ledger_json(world)[digest]["reason"] == "ignored photo"


def test_keep_override_exempts_stock_detection(world):
    downloads, destination, _ = world
    source = write_jpeg(
        downloads / BATCH / PHOTO, "2026:10:10 14:00:00", "-04:00", seed=1, icc=True
    )
    digest = hash_file(source)
    stock_plan = organizer_for(world, trip_toml()).plan()
    assert [a.kind for a in stock_plan.actions] == [ActionKind.STOCK]
    toml_text = trip_toml() + f'\n[[photo]]\nhash = "{digest}"\naction = "keep"\n'
    organizer = organizer_for(world, toml_text)
    plan = organizer.plan()
    assert [a.kind for a in plan.actions] == [ActionKind.PLACE]
    organizer.execute(plan)
    assert (destination / "2026-10-10 - Epcot" / PHOTO).exists()


def test_handled_photo_gets_shared_to_newly_added_friend_then_deleted_as_duplicate(
    world,
):
    downloads, destination, shared_root = world
    write_jpeg(downloads / BATCH / PHOTO, "2026:10:10 14:00:00", "-04:00", seed=1)
    first = organizer_for(world, trip_toml('"Alex"'))
    first.execute(first.plan())
    assert (destination / "2026-10-10 - Epcot" / PHOTO).exists()
    assert (shared_root / "Alex" / PHOTO).exists()
    redownload = write_jpeg(
        downloads / BATCH / PHOTO, "2026:10:10 14:00:00", "-04:00", seed=1
    )
    second = organizer_for(world, trip_toml('"Alex", "Sam"'))
    plan = second.plan()
    assert kinds_for(plan, PHOTO) == [
        (ActionKind.SHARE, shared_root / "Sam" / PHOTO),
        (ActionKind.DUPLICATE, destination / "2026-10-10 - Epcot" / PHOTO),
    ]
    summary = second.execute(plan)
    assert (shared_root / "Sam" / PHOTO).exists()
    assert not redownload.exists()
    assert summary.shared == 1 and summary.duplicates == 1 and summary.placed == 0
    assert [p.name for p in (destination / "2026-10-10 - Epcot").iterdir()] == [PHOTO]
    assert second.ledger.shared_with(hash_file(shared_root / "Sam" / PHOTO)) == {
        "Alex",
        "Sam",
    }
    assert Organizer(config_for(world, ""), state_dir_for(world)).ledger.shared_with(
        hash_file(shared_root / "Sam" / PHOTO)
    ) == {"Alex", "Sam"}


def test_photo_in_friend_folder_counts_as_handled(world):
    downloads, _destination, shared_root = world
    write_jpeg(downloads / BATCH / PHOTO, "2026:10:10 14:00:00", "-04:00", seed=1)
    write_jpeg(shared_root / "Alex" / PHOTO, "2026:10:10 14:00:00", "-04:00", seed=1)
    plan = organizer_for(world, trip_toml('"Alex"')).plan()
    assert [kind for kind, _ in kinds_for(plan, PHOTO)] == [ActionKind.DUPLICATE]


def test_trip_scope_leaves_other_decided_days_alone_but_removes_duplicates_everywhere(
    world,
):
    downloads, destination, _ = world
    write_jpeg(downloads / BATCH / PHOTO, "2026:10:10 14:00:00", "-04:00", seed=1)
    other = write_jpeg(
        downloads / BATCH / OTHER_DAY_PHOTO, "2026:10:12 14:00:00", "-04:00", seed=2
    )
    repeat = write_jpeg(
        downloads / BATCH / "2026-10-12 - Epcot - Italy at epcot_9.jpeg",
        "2026:10:12 14:00:00",
        "-04:00",
        seed=3,
    )
    write_jpeg(
        destination / "2026-10-12 - Epcot" / "earlier.jpeg",
        "2026:10:12 14:00:00",
        "-04:00",
        seed=3,
    )
    organizer = organizer_for(world, trip_toml(), trip=TripRange.parse("2026-10-10"))
    plan = organizer.plan()
    assert [kind for kind, _ in kinds_for(plan, PHOTO)] == [ActionKind.PLACE]
    outside = [a for a in plan.actions if a.source == other]
    assert [(a.kind, a.reason) for a in outside] == [
        (ActionKind.SKIP, "outside --trip")
    ]
    assert [(a.kind, a.reason) for a in plan.actions if a.source == repeat] == [
        (ActionKind.DUPLICATE, "same content previously processed")
    ]
    summary = organizer.execute(plan)
    assert other.exists() and not repeat.exists()
    assert summary.skipped == 1 and summary.duplicates == 1 and summary.placed == 1


def test_album_friend_share_of_my_photo_lands_in_album_shares(world, monkeypatch):
    monkeypatch.setattr("photopass_organizer.config.is_macos", lambda: True)
    downloads, destination, shared_root = world
    source = write_jpeg(
        downloads / BATCH / PHOTO, "2026:10:10 14:00:00", "-04:00", seed=1
    )
    organizer = organizer_for(
        world, '[friends.Sam]\nshare = "photos-album"\n\n' + trip_toml('"Sam"')
    )
    plan = organizer.plan()
    assert [(a.kind, a.target, a.friend) for a in plan.actions] == [
        (ActionKind.SHARE, None, "Sam"),
        (ActionKind.PLACE, destination / "2026-10-10 - Epcot" / PHOTO, None),
    ]
    summary = organizer.execute(plan)
    placed = destination / "2026-10-10 - Epcot" / PHOTO
    assert placed.exists() and not source.exists()
    digest = hash_file(placed)
    assert summary.album_shares == {"Sam": [(placed, digest)]}
    assert summary.import_files == {placed.parent: {placed}}
    assert summary.shared == 1 and summary.pending_import_folders == {}
    assert list((shared_root / "Sam").iterdir()) == []
    assert organizer.ledger.shared_with(digest) == set()


def test_duplicate_with_an_existing_target_is_imported_and_shared_to_an_album_friend(
    world, monkeypatch
):
    monkeypatch.setattr("photopass_organizer.config.is_macos", lambda: True)
    downloads, destination, _ = world
    earlier = write_jpeg(
        destination / "2026-10-10 - Epcot" / "earlier.jpeg",
        "2026:10:10 14:00:00",
        "-04:00",
        seed=1,
    )
    repeat = write_jpeg(
        downloads / BATCH / PHOTO, "2026:10:10 14:00:00", "-04:00", seed=1
    )
    organizer = organizer_for(
        world, '[friends.Sam]\nshare = "photos-album"\n\n' + trip_toml('"Sam"')
    )
    plan = organizer.plan()
    assert [(a.kind, a.friend) for a in plan.actions] == [
        (ActionKind.SHARE, "Sam"),
        (ActionKind.DUPLICATE, None),
    ]
    summary = organizer.execute(plan)
    digest = hash_file(earlier)
    assert not repeat.exists()
    assert summary.import_files == {earlier.parent: {earlier}}
    assert summary.album_shares == {"Sam": [(earlier, digest)]}
    assert organizer.ledger.shared_with(digest) == set()
    assert ledger_json(world).get(digest, {}).get("shared_with", []) == []


def test_confirm_album_shares_records_and_saves_the_ledger(world, monkeypatch):
    monkeypatch.setattr("photopass_organizer.config.is_macos", lambda: True)
    downloads, _, _ = world
    write_jpeg(downloads / BATCH / PHOTO, "2026:10:10 14:00:00", "-04:00", seed=1)
    organizer = organizer_for(
        world, '[friends.Sam]\nshare = "photos-album"\n\n' + trip_toml('"Sam"')
    )
    organizer.execute(organizer.plan())
    digest = next(iter(ledger_json(world)))
    assert ledger_json(world)[digest]["shared_with"] == []
    organizer.confirm_album_shares({"Sam": [digest]})
    assert ledger_json(world)[digest]["shared_with"] == ["Sam"]
    assert Organizer(config_for(world, ""), state_dir_for(world)).ledger.shared_with(
        digest
    ) == {"Sam"}


def test_album_friend_share_of_friend_only_photo_is_staged_for_import(
    world, monkeypatch
):
    monkeypatch.setattr("photopass_organizer.config.is_macos", lambda: True)
    downloads, destination, _ = world
    source = write_jpeg(
        downloads / BATCH / PHOTO, "2026:10:10 14:00:00", "-04:00", seed=1
    )
    organizer = organizer_for(
        world,
        '[friends.Sam]\nshare = "photos-album"\n\n'
        + trip_toml('"Sam"', i_was_there=False),
    )
    summary = organizer.execute(organizer.plan())
    staged = state_dir_for(world) / "pending-import" / "Sam"
    assert (staged / PHOTO).exists() and not source.exists()
    assert summary.pending_import_folders == {"Sam": staged}
    assert summary.staged_shares == {
        "Sam": [(staged / PHOTO, hash_file(staged / PHOTO))]
    }
    assert summary.album_shares == {} and summary.deleted == 1 and summary.shared == 1
    assert not destination.exists()


def test_two_album_friends_each_get_a_staged_copy(world, monkeypatch):
    monkeypatch.setattr("photopass_organizer.config.is_macos", lambda: True)
    downloads, _, _ = world
    source = write_jpeg(
        downloads / BATCH / PHOTO, "2026:10:10 14:00:00", "-04:00", seed=1
    )
    friends = '[friends.Sam]\nshare = "photos-album"\n\n[friends.Jordan]\nshare = "photos-album"\n\n'
    organizer = organizer_for(
        world, friends + trip_toml('"Sam", "Jordan"', i_was_there=False)
    )
    summary = organizer.execute(organizer.plan())
    staged = state_dir_for(world) / "pending-import"
    assert (staged / "Sam" / PHOTO).exists() and (staged / "Jordan" / PHOTO).exists()
    assert not source.exists()
    assert set(summary.pending_import_folders) == {"Sam", "Jordan"}


def test_album_dry_run_logs_the_import_and_stages_nothing(world, monkeypatch, caplog):
    monkeypatch.setattr("photopass_organizer.config.is_macos", lambda: True)
    downloads, _, _ = world
    source = write_jpeg(
        downloads / BATCH / PHOTO, "2026:10:10 14:00:00", "-04:00", seed=1
    )
    organizer = organizer_for(
        world,
        '[friends.Sam]\nshare = "photos-album"\n\n'
        + trip_toml('"Sam"', i_was_there=False),
    )
    organizer.dry_run = True
    with caplog.at_level("INFO"):
        organizer.execute(organizer.plan())
    assert f"Would import {source} into Photos album Sam" in caplog.text
    assert source.exists() and not state_dir_for(world).exists()


def test_trip_range_parse():
    single = TripRange.parse("2026-10-10")
    assert single.start == single.end == datetime(2026, 10, 10).date()
    span = TripRange.parse("2026-10-09..2026-10-14")
    assert span.contains(datetime(2026, 10, 12).date()) and not span.contains(
        datetime(2026, 10, 15).date()
    )
    for bad in (
        "2026-10",
        "2026-10-14..2026-10-09",
        "soon",
        "2026-10-09..2026-10-10..2026-10-11",
    ):
        with pytest.raises(ValueError):
            TripRange.parse(bad)


def test_unknown_park_is_reported_once(world, caplog):
    downloads, _, _ = world
    write_jpeg(
        downloads / BATCH / "2026-10-10 - Tokyo Disneyland - Castle.jpeg",
        "2026:10:10 14:00:00",
        "+09:00",
        seed=1,
    )
    write_jpeg(
        downloads / BATCH / "2026-10-10 - Tokyo Disneyland - Gate.jpeg",
        "2026:10:10 15:00:00",
        "+09:00",
        seed=2,
    )
    organizer = organizer_for(world, trip_toml())
    with caplog.at_level("WARNING"):
        summary = organizer.execute(organizer.plan())
    assert summary.unknown_parks == ["Tokyo Disneyland"]
    warnings = [
        record.getMessage()
        for record in caplog.records
        if "without a timezone" in record.getMessage()
    ]
    assert warnings == [
        "parks without a timezone, dated with America/New_York: Tokyo Disneyland"
    ]


def failing_move(blocked_name):
    real_move = shutil.move

    def move(source, target, *args, **kwargs):
        if Path(source).name == blocked_name:
            raise OSError("disk full")
        return real_move(source, target, *args, **kwargs)

    return move


def test_failed_placement_leaves_no_share_copy_and_no_ledger_entry(
    world, monkeypatch, caplog
):
    downloads, destination, shared_root = world
    first = write_jpeg(
        downloads / BATCH / PHOTO, "2026:10:10 14:00:00", "-04:00", seed=1
    )
    second = write_jpeg(
        downloads / BATCH / OTHER_DAY_PHOTO, "2026:10:12 14:00:00", "-04:00", seed=2
    )
    organizer = organizer_for(world, trip_toml('"Alex"'))
    plan = organizer.plan()
    monkeypatch.setattr(
        "photopass_organizer.organizer.shutil.move", failing_move(OTHER_DAY_PHOTO)
    )
    with caplog.at_level("ERROR"), pytest.raises(OSError):
        organizer.execute(plan)
    assert second.exists() and not first.exists()
    assert (shared_root / "Alex" / PHOTO).exists()
    assert not (shared_root / "Alex" / OTHER_DAY_PHOTO).exists()
    ledger = ledger_json(world)
    assert hash_file(destination / "2026-10-10 - Epcot" / PHOTO) in ledger
    assert hash_file(second) not in ledger
    assert [
        record.getMessage() for record in caplog.records if record.levelname == "ERROR"
    ] == [f"could not finish {second}; removed 1 copies made for it"]


def test_failed_album_staging_records_no_share_and_removes_partial_copies(
    world, monkeypatch
):
    monkeypatch.setattr("photopass_organizer.config.is_macos", lambda: True)
    downloads, _, _ = world
    source = write_jpeg(
        downloads / BATCH / PHOTO, "2026:10:10 14:00:00", "-04:00", seed=1
    )
    friends = '[friends.Sam]\nshare = "photos-album"\n\n[friends.Jordan]\nshare = "photos-album"\n\n'
    organizer = organizer_for(
        world, friends + trip_toml('"Sam", "Jordan"', i_was_there=False)
    )
    plan = organizer.plan()
    monkeypatch.setattr(
        "photopass_organizer.organizer.shutil.move", failing_move(PHOTO)
    )
    with pytest.raises(OSError):
        organizer.execute(plan)
    assert source.exists()
    assert list((state_dir_for(world) / "pending-import").rglob(PHOTO)) == []
    assert hash_file(source) not in ledger_json(world)

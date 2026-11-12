from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from conftest import write_jpeg, write_mp4

from photopass_organizer.media import (
    event_name,
    park_timezone_name,
    parse_photopass_name,
    read_photo_capture_time,
    read_video_creation_time_utc,
    unknown_parks,
)


def test_parse_dated_name_with_sequence():
    parsed = parse_photopass_name(
        "2026-03-07 - Disneyland Park - Sleeping beauty castle_10.jpeg"
    )
    assert parsed is not None
    assert parsed.filename_date == "2026-03-07"
    assert parsed.park == "Disneyland Park"
    assert parsed.location == "Sleeping beauty castle"
    assert parsed.sequence == 10
    assert parsed.extension == "jpeg"


def test_parse_dated_name_without_sequence_and_video():
    parsed = parse_photopass_name(
        "2026-10-13 - Disneys Hollywood Studios - Millennium falcon.mp4"
    )
    assert parsed is not None
    assert parsed.sequence is None
    assert parsed.extension == "mp4"
    assert parsed.park == "Disneys Hollywood Studios"


def test_parse_rejects_non_photopass_names():
    assert parse_photopass_name("18-video-108971099.mp4") is None
    assert parse_photopass_name("2145373472.mp4") is None
    assert parse_photopass_name("IMG_0001.jpeg") is None


def test_read_photo_capture_time_uses_exif_offset(tmp_path):
    photo = write_jpeg(tmp_path / "p.jpeg", "2026:03:06 22:11:49", "-08:00")
    captured = read_photo_capture_time(photo)
    assert captured == datetime(
        2026, 3, 6, 22, 11, 49, tzinfo=ZoneInfo("America/Los_Angeles")
    )
    assert captured.utcoffset().total_seconds() == -8 * 3600


def test_read_photo_capture_time_without_offset_is_naive(tmp_path):
    photo = write_jpeg(tmp_path / "p.jpeg", "2026:03:06 22:11:49", None)
    captured = read_photo_capture_time(photo)
    assert captured == datetime(2026, 3, 6, 22, 11, 49)
    assert captured.tzinfo is None


def test_read_photo_capture_time_missing_exif(tmp_path):
    photo = write_jpeg(tmp_path / "p.jpeg", None, None)
    assert read_photo_capture_time(photo) is None


def test_read_video_creation_time(tmp_path):
    created = datetime(2026, 6, 7, 0, 47, 25, tzinfo=UTC)
    video = write_mp4(tmp_path / "v.mp4", created)
    assert read_video_creation_time_utc(video) == created


def test_read_video_creation_time_zero_is_none(tmp_path):
    video = write_mp4(tmp_path / "v.mp4", None)
    assert read_video_creation_time_utc(video) is None


def test_park_timezone_override_and_unknown_parks():
    assert (
        park_timezone_name(
            "Disneyland Paris", parks={"Disneyland Paris": "Europe/Paris"}
        )
        == "Europe/Paris"
    )
    assert (
        park_timezone_name("Epcot", parks={"Epcot": "Europe/Paris"}) == "Europe/Paris"
    )
    assert unknown_parks(["Epcot", "Tokyo Disneyland"], {}) == ["Tokyo Disneyland"]


def test_event_name_comes_from_the_location_of_a_special_events_photo():
    bash = "Oogie boogie bash  a disney halloween party"
    assert event_name("Special Events at DCA", bash) == "Oogie Boogie Bash"
    assert (
        event_name(
            "Special Events at Magic Kingdom", "Mickeys very merry christmas party"
        )
        == "Mickeys Very Merry Christmas Party"
    )
    assert (
        event_name("Special Events at DCA", "Dca after dark  usa night")
        == "DCA After Dark"
    )
    assert (
        event_name("Special Events at Disneyland", "dvc moonlight magic")
        == "DVC Moonlight Magic"
    )
    assert (
        event_name("Special Events at Disneyland", "runDisney expo") == "RunDisney Expo"
    )
    assert event_name("Disney California Adventure Park", bash) is None
    assert event_name(None, bash) is None


def test_special_events_take_the_timezone_of_their_host_park():
    pacific, eastern = "America/Los_Angeles", "America/New_York"
    assert park_timezone_name("Special Events at DCA", eastern) == pacific
    assert park_timezone_name("Special Events at Disneyland", eastern) == pacific
    assert park_timezone_name("Special Events at Magic Kingdom", pacific) == eastern
    assert park_timezone_name("Special Events at Hollywood Studios", pacific) == eastern
    paris = {"Disneyland Paris": "Europe/Paris"}
    assert (
        park_timezone_name("Special Events at Disneyland Paris", eastern, paris)
        == "Europe/Paris"
    )
    assert park_timezone_name("Special Events at Atlantis", eastern) == eastern
    assert unknown_parks(
        ["Special Events at DCA", "Special Events at Atlantis"], {}
    ) == ["Special Events at Atlantis"]


def test_a_park_that_is_not_a_plain_folder_name_is_not_a_photopass_file():
    assert parse_photopass_name("2026-03-07 - .. - Castle.jpeg") is None
    assert parse_photopass_name("2026-03-07 - . - Castle.jpeg") is None
    assert parse_photopass_name("2026-03-07 - a\\b - Castle.jpeg") is None
    assert parse_photopass_name("2026-03-07 - Epcot - Castle.jpeg") is not None
    assert event_name("Special Events at DCA", "..") is None
    assert event_name("Special Events at DCA", ".") is None

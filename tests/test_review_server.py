import http.client
import io
import json
import threading
import time
import tomllib
from dataclasses import replace
from datetime import UTC, date, datetime
from urllib.parse import urlsplit

import pytest
from conftest import write_jpeg, write_mp4
from PIL import Image

from photopass_organizer import review_server
from photopass_organizer.config import (
    CONFIG_NAME,
    Config,
    Friend,
    Settings,
    ShareMethod,
    TripRule,
    write_config,
)
from photopass_organizer.photos import PhotosSummary
from photopass_organizer.review_server import ReviewServer

BATCH = "ecd5e910-484f-4b99-ac12-9fad86cefc89"
DAY = "2026-03-07"
PARK = "Disneyland Park"


def make_config(tmp_path, trips=()):
    downloads = tmp_path / "Downloads"
    write_jpeg(
        downloads / BATCH / "2026-03-07 - Disneyland Park - Castle.jpeg",
        "2026:03:07 10:00:00",
        "-08:00",
        seed=1,
    )
    write_jpeg(
        downloads / BATCH / "2026-03-07 - Disneyland Park - Train.jpeg",
        "2026:03:07 11:00:00",
        "-08:00",
        seed=2,
    )
    settings = replace(
        Settings.platform_defaults(),
        source=downloads,
        destination=tmp_path / "PhotoPass",
        shared_root=None,
        import_to_photos=False,
    )
    return Config(settings=settings, trips=list(trips))


@pytest.fixture
def start_server(tmp_path):
    started = []

    def start(config):
        state_dir = tmp_path / "state"
        write_config(config, state_dir / CONFIG_NAME)
        server = ReviewServer(state_dir, config, port=0)
        server.start_in_thread()
        started.append(server)
        return server

    yield start
    for server in started:
        server.shutdown()


@pytest.fixture
def server(tmp_path, start_server):
    return start_server(make_config(tmp_path))


def request(server, method, route, body=None, headers=None, prefix=None):
    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_address[1], timeout=10
    )
    try:
        payload = (
            body
            if isinstance(body, bytes) or body is None
            else json.dumps(body).encode("utf-8")
        )
        path = f"/{server.token if prefix is None else prefix}/{route}"
        connection.request(method, path, body=payload, headers=headers or {})
        response = connection.getresponse()
        return response.status, response, response.read()
    finally:
        connection.close()


def get_json(server, route):
    status, _, data = request(server, "GET", route)
    return status, json.loads(data)


def post_json(server, route, body):
    status, _, data = request(server, "POST", route, body)
    return status, json.loads(data)


def new_hashes(server):
    _, state = get_json(server, "api/state")
    return [entry["hash"] for day in state["trips"][0]["days"] for entry in day["new"]]


def alex_save(**overrides):
    body = {
        "days": [{"date": DAY, "park": PARK, "state": "friends", "friends": ["Alex"]}],
        "photos": [],
        "friends": [{"name": "Alex", "share": "folder", "path": "/tmp/shared/Alex"}],
    }
    body.update(overrides)
    return body


def test_requests_without_token_are_404(server):
    for method, route in (("GET", "api/state"), ("POST", "api/done"), ("GET", "")):
        status, _, data = request(server, method, route, prefix="wrong")
        assert (status, data) == (404, b"")
    status, _, data = request(server, "GET", "no-such-route")
    assert (status, data) == (404, b"")
    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_address[1], timeout=10
    )
    connection.request("GET", "/")
    response = connection.getresponse()
    assert (response.status, response.read()) == (404, b"")
    connection.close()


def test_root_serves_the_page(server):
    status, response, data = request(server, "GET", "")
    assert status == 200
    assert response.getheader("Content-Type").startswith("text/html")
    assert data.decode("utf-8") == review_server.render_page(server.token)
    assert data.startswith(b"<!doctype html>")


def test_state_lists_new_items(server):
    status, state = get_json(server, "api/state")
    assert status == 200
    day = state["trips"][0]["days"][0]
    assert (day["date"], day["park"]) == (DAY, PARK)
    assert [entry["name"] for entry in day["new"]] == [
        "2026-03-07 - Disneyland Park - Castle.jpeg",
        "2026-03-07 - Disneyland Park - Train.jpeg",
    ]
    assert state["undecided_count"] == 1


def test_each_state_request_sees_files_added_since_the_last(server, tmp_path):
    before = new_hashes(server)
    write_jpeg(
        tmp_path / "Downloads" / BATCH / "2026-03-07 - Disneyland Park - Parade.jpeg",
        "2026:03:07 12:00:00",
        "-08:00",
        seed=9,
    )
    after = new_hashes(server)
    assert len(after) == len(before) + 1
    assert set(before) < set(after)
    assert request(server, "GET", f"thumb/{(set(after) - set(before)).pop()}")[0] == 200


def test_thumb_and_media_are_served(server):
    first = new_hashes(server)[0]
    status, response, data = request(server, "GET", f"thumb/{first}")
    assert (status, response.getheader("Content-Type")) == (200, "image/jpeg")
    assert Image.open(io.BytesIO(data)).format == "JPEG"

    status, response, whole = request(server, "GET", f"media/{first}")
    assert (
        status,
        response.getheader("Content-Type"),
        response.getheader("Accept-Ranges"),
    ) == (200, "image/jpeg", "bytes")
    assert int(response.getheader("Content-Length")) == len(whole)

    status, response, part = request(
        server, "GET", f"media/{first}", headers={"Range": "bytes=0-9"}
    )
    assert status == 206
    assert part == whole[:10]
    assert response.getheader("Content-Range") == f"bytes 0-9/{len(whole)}"
    assert response.getheader("Content-Length") == "10"

    status, response, tail = request(
        server, "GET", f"media/{first}", headers={"Range": "bytes=10-"}
    )
    assert (status, tail) == (206, whole[10:])
    assert (
        response.getheader("Content-Range") == f"bytes 10-{len(whole) - 1}/{len(whole)}"
    )


@pytest.mark.parametrize(
    "range_header",
    [
        "bytes=-5",
        "bytes=0-1,4-5",
        "items=0-1",
        "bytes=999999-",
        "bytes=9-3",
        "bytes=a-b",
    ],
)
def test_unsatisfiable_or_malformed_range_is_416(server, range_header):
    first = new_hashes(server)[0]
    status, response, _ = request(
        server, "GET", f"media/{first}", headers={"Range": range_header}
    )
    assert status == 416
    assert response.getheader("Content-Range").startswith("bytes */")


def test_unknown_hash_is_404(server):
    assert request(server, "GET", "thumb/deadbeef")[0] == 404
    assert request(server, "GET", "media/deadbeef")[0] == 404


def test_video_thumbnail_is_its_paired_still(tmp_path, start_server):
    config = make_config(tmp_path)
    write_mp4(
        config.settings.source / "2145506679.mp4",
        datetime(2026, 3, 7, 18, 30, tzinfo=UTC),
        seed=3,
    )
    server = start_server(config)
    _, state = get_json(server, "api/state")
    videos = [
        entry for entry in state["trips"][0]["days"][0]["new"] if entry["is_video"]
    ]
    assert len(videos) == 1 and videos[0]["paired_still"]
    status, response, data = request(server, "GET", f"thumb/{videos[0]['hash']}")
    assert (status, response.getheader("Content-Type")) == (200, "image/jpeg")
    assert Image.open(io.BytesIO(data)).format == "JPEG"
    status, response, _ = request(server, "GET", f"media/{videos[0]['hash']}")
    assert (status, response.getheader("Content-Type")) == (200, "video/mp4")


def test_save_writes_config_and_returns_counts(server, tmp_path):
    status, payload = post_json(server, "api/save", alex_save())
    assert status == 200
    assert payload["saved"] is True
    assert payload["counts"]["share"] == {"Alex": 2}
    document = tomllib.loads(
        (tmp_path / "state" / CONFIG_NAME).read_text(encoding="utf-8")
    )
    assert document["trip"][0]["friends"] == ["Alex"]
    assert document["trip"][0]["start"] == DAY
    assert document["friends"]["Alex"]["share"] == "folder"
    _, state = get_json(server, "api/state")
    assert state["trips"][0]["days"][0]["decision"] == {
        "state": "friends",
        "friends": ["Alex"],
    }


def test_empty_save_is_a_dry_run_that_leaves_the_config_byte_identical(
    tmp_path, start_server
):
    rules = [
        TripRule(date(2026, 3, 1), date(2026, 3, 3), (), False, ignore=True),
        TripRule(date(2026, 3, 5), date(2026, 3, 6), (), False, ignore=True),
    ]
    server = start_server(make_config(tmp_path, trips=rules))
    path = tmp_path / "state" / CONFIG_NAME
    before = path.read_bytes()
    status, payload = post_json(server, "api/save", {})
    assert status == 200
    assert payload["saved"] is False
    assert "share" in payload["counts"]
    assert path.read_bytes() == before
    assert not path.with_suffix(".toml.bak").exists()
    assert server.config.trips == rules


def test_save_that_changes_nothing_does_not_write(server, tmp_path):
    path = tmp_path / "state" / CONFIG_NAME
    assert post_json(server, "api/save", alex_save())[1]["saved"] is True
    backup = path.with_suffix(".toml.bak")
    backup.unlink()
    before = path.read_bytes()
    status, payload = post_json(server, "api/save", alex_save())
    assert (status, payload["saved"]) == (200, True)
    assert path.read_bytes() == before
    assert not backup.exists()


JORDAN = {"name": "Jordan", "share": "photos-album", "album": "Jordan Shared"}


def test_save_does_not_write_a_new_friend_no_day_selects(server, tmp_path, monkeypatch):
    monkeypatch.setattr("photopass_organizer.config.is_macos", lambda: True)
    monkeypatch.setattr(review_server, "is_macos", lambda: True)
    assert post_json(server, "api/friends", {"friends": [JORDAN]})[0] == 200
    body = alex_save()
    body["friends"] = [*body["friends"], JORDAN]
    status, payload = post_json(server, "api/save", body)
    assert (status, payload["saved"]) == (200, True)
    assert payload["unsaved_friends"] == ["Jordan"]
    text = (tmp_path / "state" / CONFIG_NAME).read_text(encoding="utf-8")
    assert "Jordan" not in text
    _, state = get_json(server, "api/state")
    assert "Jordan" in [friend["name"] for friend in state["friends"]]


def test_save_writes_a_new_friend_once_a_day_selects_them(
    server, tmp_path, monkeypatch
):
    monkeypatch.setattr("photopass_organizer.config.is_macos", lambda: True)
    monkeypatch.setattr(review_server, "is_macos", lambda: True)
    assert post_json(server, "api/friends", {"friends": [JORDAN]})[0] == 200
    body = {
        "days": [
            {"date": DAY, "park": PARK, "state": "friends", "friends": ["Jordan"]}
        ],
        "friends": [JORDAN],
    }
    status, payload = post_json(server, "api/save", body)
    assert (status, payload["saved"]) == (200, True)
    assert payload["unsaved_friends"] == []
    assert 'album = "Jordan Shared"' in (tmp_path / "state" / CONFIG_NAME).read_text(
        encoding="utf-8"
    )


def test_empty_save_reports_new_friends_that_are_not_saved(
    server, tmp_path, monkeypatch
):
    monkeypatch.setattr("photopass_organizer.config.is_macos", lambda: True)
    monkeypatch.setattr(review_server, "is_macos", lambda: True)
    status, payload = post_json(server, "api/save", {})
    assert (status, payload["unsaved_friends"]) == (200, [])
    assert post_json(server, "api/friends", {"friends": [JORDAN]})[0] == 200
    status, payload = post_json(server, "api/save", {})
    assert (status, payload["saved"]) == (200, False)
    assert payload["unsaved_friends"] == ["Jordan"]


def test_save_replaces_photo_overrides(server, tmp_path):
    first = new_hashes(server)[0]
    body = alex_save(photos=[{"hash": first, "action": "ignore", "name": "Castle"}])
    assert post_json(server, "api/save", body)[0] == 200
    document = tomllib.loads(
        (tmp_path / "state" / CONFIG_NAME).read_text(encoding="utf-8")
    )
    assert [(entry["hash"], entry["action"]) for entry in document["photo"]] == [
        (first, "ignore")
    ]
    assert post_json(server, "api/save", alex_save(photos=[]))[0] == 200
    assert "photo" not in tomllib.loads(
        (tmp_path / "state" / CONFIG_NAME).read_text(encoding="utf-8")
    )


@pytest.mark.parametrize(
    "overrides, fragment",
    [
        (
            {"days": [{"date": "March", "park": PARK, "state": "mine", "friends": []}]},
            "bad date",
        ),
        (
            {"days": [{"date": DAY, "park": PARK, "state": "maybe", "friends": []}]},
            "state",
        ),
        (
            {
                "days": [
                    {
                        "date": DAY,
                        "park": PARK,
                        "state": "friends",
                        "friends": ["Nobody"],
                    }
                ]
            },
            "Nobody",
        ),
        ({"photos": [{"hash": "abc", "action": "burn", "name": ""}]}, "action"),
        (
            {"friends": [{"name": "Sam", "share": "carrier-pigeon", "path": "/x"}]},
            "share",
        ),
        ({"friends": [{"name": "Sam", "share": "folder"}]}, "path"),
        ({"friends": [{"name": "Sam", "share": "photos-album"}]}, "album"),
    ],
)
def test_save_rejects_invalid_bodies_and_leaves_disk_alone(
    server, tmp_path, overrides, fragment
):
    before = (tmp_path / "state" / CONFIG_NAME).read_text(encoding="utf-8")
    status, payload = post_json(server, "api/save", alex_save(**overrides))
    assert status == 400
    assert fragment in payload["error"]
    assert (tmp_path / "state" / CONFIG_NAME).read_text(encoding="utf-8") == before


def test_friend_only_decision_without_friends_is_400(server, tmp_path):
    path = tmp_path / "state" / CONFIG_NAME
    before = path.read_bytes()
    day = [{"date": DAY, "park": PARK, "state": "friends", "friends": []}]
    status, payload = post_json(server, "api/save", {"days": day})
    assert status == 400
    assert "friends" in payload["error"]
    assert path.read_bytes() == before


def test_wrong_token_thumb_and_media_are_404(server):
    digest = new_hashes(server)[0]
    for route in (f"thumb/{digest}", f"media/{digest}"):
        assert request(server, "GET", route, prefix="wrong")[0] == 404
        assert request(server, "GET", route)[0] == 200


def test_photos_album_friend_is_rejected_off_macos_and_disk_is_unchanged(
    server, tmp_path, monkeypatch
):
    monkeypatch.setattr(review_server, "is_macos", lambda: False)
    path = tmp_path / "state" / CONFIG_NAME
    before = path.read_bytes()
    entry = {"name": "Sam", "share": "photos-album", "album": "Sam"}
    status, payload = post_json(server, "api/save", alex_save(friends=[entry]))
    assert status == 400
    assert "macOS" in payload["error"]
    assert path.read_bytes() == before
    assert post_json(server, "api/friends", {"friends": [entry]})[0] == 400


@pytest.mark.parametrize("friend_path", ["shared/Alex", "./Alex"])
def test_relative_friend_path_is_400(server, tmp_path, friend_path):
    path = tmp_path / "state" / CONFIG_NAME
    before = path.read_bytes()
    entry = {"name": "Alex", "share": "folder", "path": friend_path}
    status, payload = post_json(server, "api/save", alex_save(friends=[entry]))
    assert status == 400
    assert "path" in payload["error"]
    assert path.read_bytes() == before


def test_home_relative_friend_path_is_accepted(server):
    entry = {"name": "Alex", "share": "folder", "path": "~/Alex"}
    assert post_json(server, "api/save", alex_save(friends=[entry]))[0] == 200


def test_save_with_overlapping_rules_is_400(tmp_path):
    config = make_config(
        tmp_path,
        trips=[
            TripRule(date(2026, 3, 1), date(2026, 3, 31), (), True),
            TripRule(
                date(2026, 3, 7),
                date(2026, 3, 7),
                (),
                False,
                parks=frozenset({PARK}),
                ignore=True,
            ),
        ],
    )
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / CONFIG_NAME).write_text("# original\n", encoding="utf-8")
    server = ReviewServer(state_dir, config, port=0)
    server.start_in_thread()
    try:
        body = {
            "days": [
                {"date": "2026-04-02", "park": PARK, "state": "mine", "friends": []}
            ],
            "photos": [],
            "friends": [],
        }
        status, payload = post_json(server, "api/save", body)
    finally:
        server.shutdown()
    assert status == 400
    assert "overlap" in payload["error"]
    assert (state_dir / CONFIG_NAME).read_text(encoding="utf-8") == "# original\n"


def test_friends_endpoint_updates_memory_until_next_save(server, tmp_path, monkeypatch):
    monkeypatch.setattr("photopass_organizer.config.is_macos", lambda: True)
    monkeypatch.setattr(review_server, "is_macos", lambda: True)
    friend = {"name": "Jordan", "share": "photos-album", "album": "Jordan Shared"}
    assert post_json(server, "api/friends", {"friends": [friend]}) == (
        200,
        {"ok": True},
    )
    _, state = get_json(server, "api/state")
    assert {
        "name": "Jordan",
        "share": "photos-album",
        "location": "Jordan Shared",
    } in state["friends"]
    assert "Jordan" not in (tmp_path / "state" / CONFIG_NAME).read_text(
        encoding="utf-8"
    )
    day = [{"date": DAY, "park": PARK, "state": "friends", "friends": ["Jordan"]}]
    assert post_json(server, "api/save", {"days": day})[0] == 200
    assert 'album = "Jordan Shared"' in (tmp_path / "state" / CONFIG_NAME).read_text(
        encoding="utf-8"
    )
    assert (
        post_json(
            server, "api/friends", {"friends": [{"name": "Sam", "share": "nope"}]}
        )[0]
        == 400
    )


def test_run_moves_files_and_state_shows_them_handled(server, tmp_path, monkeypatch):
    monkeypatch.setattr(review_server, "is_macos", lambda: True)
    calls = []

    def fake_sync(summary, config):
        calls.append(summary)
        return PhotosSummary(
            imported=2, purged=0, added_to_friend_albums=0, friend_imports=0
        )

    monkeypatch.setattr(review_server, "sync_photos", fake_sync)
    day = [{"date": DAY, "park": PARK, "state": "mine", "friends": []}]
    assert post_json(server, "api/save", {"days": day})[0] == 200
    status, payload = post_json(server, "api/run", {"trip": None})
    assert status == 200
    assert payload["summary"]["placed"] == 2
    assert payload["photos"] == {
        "imported": 2,
        "purged": 0,
        "added_to_friend_albums": 0,
        "friend_imports": 0,
        "added_by_friend": {},
        "failed_by_friend": {},
    }
    assert all(
        isinstance(folder, str) and isinstance(files, list)
        for folder, files in payload["summary"]["import_files"].items()
    )
    assert len(calls) == 1
    downloads = tmp_path / "Downloads"
    assert [path for path in downloads.rglob("*") if path.is_file()] == []
    assert len([path for path in (tmp_path / "PhotoPass").rglob("*.jpeg")]) == 2
    _, state = get_json(server, "api/state")
    assert [day["new"] for trip in state["trips"] for day in trip["days"]] == []


def test_run_does_not_call_photos_off_macos(server, monkeypatch):
    def forbidden(summary, config):
        raise AssertionError("sync_photos must not run off macOS")

    monkeypatch.setattr(review_server, "is_macos", lambda: False)
    monkeypatch.setattr(review_server, "sync_photos", forbidden)
    day = [{"date": DAY, "park": PARK, "state": "mine", "friends": []}]
    assert post_json(server, "api/save", {"days": day})[0] == 200
    status, payload = post_json(server, "api/run", {"trip": None})
    assert status == 200
    assert payload["photos"]["imported"] == 0


def test_run_records_album_shares_only_for_what_photos_confirmed(
    tmp_path, start_server, monkeypatch
):
    monkeypatch.setattr("photopass_organizer.config.is_macos", lambda: True)
    monkeypatch.setattr(review_server, "is_macos", lambda: True)
    config = make_config(tmp_path)
    friend = Friend("Sam", ShareMethod.PHOTOS_ALBUM, album="Sam")
    config = replace(
        config,
        friends={"Sam": friend},
        trips=[TripRule(date(2026, 3, 7), date(2026, 3, 7), ("Sam",), True)],
    )
    server = start_server(config)
    ledger_path = tmp_path / "state" / "ledger.json"
    seen = []

    def fake_sync(summary, config):
        hashes = [digest for _, digest in summary.album_shares["Sam"]]
        entries = json.loads(ledger_path.read_text(encoding="utf-8"))
        seen.append([entries[digest]["shared_with"] for digest in hashes])
        return PhotosSummary(
            imported=2, added_by_friend={"Sam": hashes[:1]}, failed_by_friend={"Sam": 1}
        )

    monkeypatch.setattr(review_server, "sync_photos", fake_sync)
    assert post_json(server, "api/run", {"trip": None})[0] == 200
    assert seen == [[[], []]]
    entries = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert sorted(entry["shared_with"] for entry in entries.values()) == [
        [],
        ["Sam"],
    ]


def test_run_with_a_trip_range_only_touches_those_days(server, tmp_path, monkeypatch):
    monkeypatch.setattr(review_server, "is_macos", lambda: True)
    monkeypatch.setattr(
        review_server, "sync_photos", lambda summary, config: PhotosSummary()
    )
    day = [{"date": DAY, "park": PARK, "state": "mine", "friends": []}]
    post_json(server, "api/save", {"days": day})
    _, payload = post_json(
        server, "api/run", {"trip": {"start": "2026-04-01", "end": "2026-04-02"}}
    )
    assert payload["summary"]["placed"] == 0
    assert (
        post_json(server, "api/run", {"trip": {"start": "April", "end": "May"}})[0]
        == 400
    )


def test_run_reports_os_errors_and_keeps_serving(server, monkeypatch):
    monkeypatch.setattr(review_server, "is_macos", lambda: True)

    def broken_sync(summary, config):
        raise OSError("disk full")

    monkeypatch.setattr(review_server, "sync_photos", broken_sync)
    status, payload = post_json(server, "api/run", {"trip": None})
    assert (status, payload) == (500, {"error": "disk full"})
    assert get_json(server, "api/state")[0] == 200


def test_oversized_body_is_413_and_bad_json_is_400(server):
    status, _, _ = request(
        server,
        "POST",
        "api/save",
        b"{}",
        headers={"Content-Length": str(4 * 1024 * 1024 + 1)},
    )
    assert status == 413
    status, _, data = request(server, "POST", "api/save", b"{not json")
    assert status == 400
    assert "error" in json.loads(data)
    status, _, _ = request(server, "POST", "api/save", b"[1, 2]")
    assert status == 400


def test_done_stops_server(server):
    assert post_json(server, "api/done", {}) == (200, {"ok": True})
    server._thread.join(timeout=10)
    assert not server._thread.is_alive()
    with pytest.raises(OSError):
        request(server, "GET", "api/state")


def test_done_during_a_run_is_409_and_works_after_release(server):
    assert server.run_lock.acquire(blocking=False)
    try:
        assert post_json(server, "api/done", {}) == (
            409,
            {"error": "organizing is in progress"},
        )
        assert get_json(server, "api/state")[0] == 200
    finally:
        server.run_lock.release()
    assert post_json(server, "api/done", {}) == (200, {"ok": True})


def test_open_review_waits_for_a_running_run_before_returning(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    created = []
    original = review_server.ReviewServer

    class Recording(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created.append(self)

    monkeypatch.setattr(review_server, "ReviewServer", Recording)
    returned = threading.Event()
    result = []

    def serve():
        result.append(
            review_server.open_review(
                tmp_path / "state", config, open_browser=False, port=0
            )
        )
        returned.set()

    worker = threading.Thread(target=serve)
    worker.start()
    deadline = time.monotonic() + 10
    while not (created and created[0]._serving.is_set()):
        assert time.monotonic() < deadline
        time.sleep(0.01)
    server = created[0]
    assert server.run_lock.acquire(blocking=False)
    threading.Thread(target=lambda: original.shutdown(server)).start()
    assert not returned.wait(timeout=0.5)
    server.run_lock.release()
    assert returned.wait(timeout=10)
    worker.join(timeout=10)
    assert result == [0]


def test_open_review_logs_the_url_opens_the_browser_and_returns_when_done(
    tmp_path, monkeypatch, caplog
):
    config = make_config(tmp_path)
    opened = []

    def post_done(url):
        parts = urlsplit(url)
        connection = http.client.HTTPConnection(parts.hostname, parts.port, timeout=10)
        connection.request("POST", parts.path + "api/done", body=b"{}")
        connection.getresponse().read()
        connection.close()

    def fake_open(url):
        opened.append(url)
        threading.Thread(target=post_done, args=(url,)).start()

    monkeypatch.setattr(review_server.webbrowser, "open", fake_open)
    with caplog.at_level("INFO", logger="photopass_organizer.review_server"):
        assert (
            review_server.open_review(
                tmp_path / "state", config, open_browser=True, port=0
            )
            == 0
        )
    assert len(opened) == 1
    assert f"review page at {opened[0]}" in caplog.text


def test_save_without_photos_key_keeps_existing_overrides(server, tmp_path):
    first = new_hashes(server)[0]
    assert (
        post_json(
            server,
            "api/save",
            alex_save(photos=[{"hash": first, "action": "ignore", "name": "Castle"}]),
        )[0]
        == 200
    )
    day = [{"date": DAY, "park": PARK, "state": "mine", "friends": []}]
    assert post_json(server, "api/save", {"days": day})[0] == 200
    document = tomllib.loads(
        (tmp_path / "state" / CONFIG_NAME).read_text(encoding="utf-8")
    )
    assert [(entry["hash"], entry["action"]) for entry in document["photo"]] == [
        (first, "ignore")
    ]
    assert "Alex" in document["friends"]
    assert post_json(server, "api/save", {})[0] == 200


@pytest.mark.parametrize(
    "overrides",
    [
        {"photos": [{"hash": "abc", "action": ["ignore"], "name": ""}]},
        {"days": [{"date": DAY, "park": PARK, "state": {"x": 1}, "friends": []}]},
        {"friends": 7},
    ],
)
def test_save_with_unhashable_values_is_400_not_a_dropped_connection(server, overrides):
    assert post_json(server, "api/save", alex_save(**overrides))[0] == 400


def test_decompression_bomb_thumbnail_is_none(tmp_path, monkeypatch):
    def bomb(path):
        raise review_server.Image.DecompressionBombError("too big")

    monkeypatch.setattr(review_server.Image, "open", bomb)
    assert review_server.make_thumbnail(tmp_path / "x.jpeg") is None


def test_second_run_during_a_run_is_409_and_the_first_completes(server, monkeypatch):
    monkeypatch.setattr(review_server, "is_macos", lambda: True)
    entered = threading.Event()
    release = threading.Event()

    def blocking_sync(summary, config):
        entered.set()
        assert release.wait(timeout=10)
        return PhotosSummary()

    monkeypatch.setattr(review_server, "sync_photos", blocking_sync)
    first = {}
    worker = threading.Thread(
        target=lambda: first.update(result=post_json(server, "api/run", {"trip": None}))
    )
    worker.start()
    assert entered.wait(timeout=10)
    assert post_json(server, "api/run", {"trip": None}) == (
        409,
        {"error": "organizing is already in progress"},
    )
    release.set()
    worker.join(timeout=10)
    assert first["result"][0] == 200
    assert post_json(server, "api/run", {"trip": None})[0] == 200


def test_adding_a_friend_to_a_previously_processed_date_shares_it_again(
    tmp_path, start_server
):
    alex = Friend("Alex", ShareMethod.FOLDER, path=tmp_path / "shared" / "Alex")
    config = make_config(
        tmp_path, [TripRule(date(2026, 3, 7), date(2026, 3, 7), ("Alex",), True)]
    )
    config = replace(config, friends={"Alex": alex})
    server = start_server(config)
    _, state = get_json(server, "api/state")
    hashes = [entry["hash"] for entry in state["trips"][0]["days"][0]["new"]]
    ledger_path = tmp_path / "state" / "ledger.json"
    legacy = {
        digest: {"path": "", "handled_at": "2026-03-08T00:00:00+00:00"}
        for digest in hashes
    }
    ledger_path.write_text(json.dumps(legacy), encoding="utf-8")
    server.drop_plan_cache()
    sam = {"name": "Sam", "share": "folder", "path": str(tmp_path / "shared" / "Sam")}
    body = {
        "days": [
            {"date": DAY, "park": PARK, "state": "mine", "friends": ["Alex", "Sam"]}
        ],
        "friends": [sam],
    }
    status, payload = post_json(server, "api/save", body)
    assert status == 200
    assert payload["counts"]["share"] == {"Sam": 2}
    entries = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert [entries[digest]["shared_with"] for digest in hashes] == [["Alex"], ["Alex"]]
    assert post_json(server, "api/run", {"trip": None})[0] == 200
    assert len(list((tmp_path / "shared" / "Sam").iterdir())) == 2
    assert not (tmp_path / "shared" / "Alex").exists()


def test_saving_the_same_friends_leaves_legacy_ledger_entries_alone(
    tmp_path, start_server
):
    alex = Friend("Alex", ShareMethod.FOLDER, path=tmp_path / "shared" / "Alex")
    config = make_config(
        tmp_path, [TripRule(date(2026, 3, 7), date(2026, 3, 7), ("Alex",), True)]
    )
    server = start_server(replace(config, friends={"Alex": alex}))
    hashes = new_hashes(server)
    ledger_path = tmp_path / "state" / "ledger.json"
    legacy = {
        digest: {"path": "", "handled_at": "2026-03-08T00:00:00+00:00"}
        for digest in hashes
    }
    ledger_path.write_text(json.dumps(legacy), encoding="utf-8")
    server.drop_plan_cache()
    body = {"days": [{"date": DAY, "park": PARK, "state": "mine", "friends": ["Alex"]}]}
    status, payload = post_json(server, "api/save", body)
    assert (status, payload["counts"]["share"]) == (200, {})
    assert json.loads(ledger_path.read_text(encoding="utf-8")) == legacy


def test_settings_can_be_read_and_changed_from_the_page(server, tmp_path):
    assert post_json(server, "api/save", alex_save())[0] == 200
    status, view = get_json(server, "api/settings")
    assert status == 200
    assert view["path"] == str(tmp_path / "state" / CONFIG_NAME)
    assert view["settings"]["layout"] == "flat"
    assert view["choices"]["layout"] == ["flat", "date/park", "park/date"]
    changed = {**view["settings"], "layout": "park/date", "stock_art": "keep"}
    changed["destination"] = str(tmp_path / "Sorted")
    status, saved = post_json(server, "api/settings", {"settings": changed})
    assert status == 200
    assert saved["settings"]["layout"] == "park/date"
    document = tomllib.loads(
        (tmp_path / "state" / CONFIG_NAME).read_text(encoding="utf-8")
    )
    assert document["settings"]["layout"] == "park/date"
    assert document["settings"]["stock_art"] == "keep"
    assert document["settings"]["destination"] == str(tmp_path / "Sorted")
    assert document["trip"][0]["friends"] == ["Alex"]
    assert "Alex" in document["friends"]
    assert get_json(server, "api/state")[0] == 200


def test_bad_settings_are_rejected_and_nothing_is_written(server, tmp_path):
    path = tmp_path / "state" / CONFIG_NAME
    before = path.read_bytes()
    _, view = get_json(server, "api/settings")
    for bad in (
        {**view["settings"], "layout": "by-moon"},
        {**view["settings"], "surprise": 1},
        {**view["settings"], "import_to_photos": "yes"},
        "not a table",
    ):
        status, payload = post_json(server, "api/settings", {"settings": bad})
        assert status == 400, bad
        assert payload["error"]
    assert path.read_bytes() == before

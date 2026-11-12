import json
import logging
import tomllib
import zipfile
from dataclasses import replace
from datetime import date

import pytest
from conftest import write_jpeg

from photopass_organizer import cli
from photopass_organizer.cli import main
from photopass_organizer.config import (
    CONFIG_NAME,
    Config,
    Friend,
    Settings,
    ShareMethod,
    TripRule,
    load_config,
    write_config,
)
from photopass_organizer.photos import ImportResult, PhotosSummary

BATCH = "ecd5e910-484f-4b99-ac12-9fad86cefc89"


@pytest.fixture
def state(tmp_path):
    return tmp_path / "state"


@pytest.fixture
def downloads(tmp_path):
    folder = tmp_path / "Downloads"
    folder.mkdir()
    return folder


@pytest.fixture
def sync_calls(monkeypatch):
    calls = []

    def fake_sync(summary, config):
        calls.append((summary, config))
        return PhotosSummary(
            imported=3, purged=1, added_to_friend_albums=2, friend_imports=4
        )

    monkeypatch.setattr(cli, "sync_photos", fake_sync)
    return calls


def write_state_config(state, downloads, destination, import_to_photos=False):
    settings = replace(
        Settings.platform_defaults(),
        source=downloads,
        destination=destination,
        shared_root=None,
        import_to_photos=import_to_photos,
    )
    write_config(Config(settings=settings), state / CONFIG_NAME)


def add_photo(downloads):
    write_jpeg(
        downloads / BATCH / "2026-03-07 - Disneyland Park - Castle.jpeg",
        "2026:03:07 10:00:00",
        "-08:00",
    )


def test_init_writes_default_config_and_refuses_to_overwrite(state, capsys):
    assert main(["init", "--state-dir", str(state)]) == 0
    written = state / CONFIG_NAME
    captured = capsys.readouterr()
    assert (
        captured.out.strip()
        == f"SUCCESS: wrote {written}; edit [settings] then run photopass-organizer review"
    )
    assert "settings" in tomllib.loads(written.read_text(encoding="utf-8"))
    written.write_text(
        written.read_text(encoding="utf-8") + "\n# keep me\n", encoding="utf-8"
    )

    assert main(["init", "--state-dir", str(state)]) == 0
    captured = capsys.readouterr()
    assert f"WARNING: {written} already exists, nothing written" in captured.err
    assert "# keep me" in written.read_text(encoding="utf-8")


def test_organize_reports_undecided_days(
    state, downloads, tmp_path, capsys, sync_calls
):
    add_photo(downloads)
    write_state_config(state, downloads, tmp_path / "PhotoPass")
    assert main(["organize", "--state-dir", str(state)]) == 0
    captured = capsys.readouterr()
    assert (
        "SUCCESS: Placed 0 for me, shared 0, deleted 0 friend-only, ignored 0, duplicates 0, stock art 0, undecided 1 left in the source folder, "
        "folders removed 0" in captured.out
    )
    assert sync_calls == []
    assert (downloads / BATCH / "2026-03-07 - Disneyland Park - Castle.jpeg").is_file()


def test_organize_dry_run_never_syncs_photos(
    state, downloads, tmp_path, capsys, sync_calls
):
    add_photo(downloads)
    write_state_config(state, downloads, tmp_path / "PhotoPass", import_to_photos=True)
    assert main(["organize", "--dry-run", "--state-dir", str(state)]) == 0
    assert "SUCCESS: Would place 0 for me" in capsys.readouterr().out
    assert sync_calls == []


def test_organize_syncs_photos_when_enabled(
    state, downloads, tmp_path, capsys, sync_calls
):
    write_state_config(state, downloads, tmp_path / "PhotoPass", import_to_photos=True)
    assert main(["organize", "--state-dir", str(state)]) == 0
    assert len(sync_calls) == 1
    assert (
        "SUCCESS: imported 3 into Photos, purged 1 folders, added 2 to friend albums, imported 4 for friends"
        in capsys.readouterr().out
    )


def test_organize_records_album_shares_only_after_photos_confirms(
    state, downloads, tmp_path, monkeypatch
):
    monkeypatch.setattr("photopass_organizer.config.is_macos", lambda: True)
    add_photo(downloads)
    settings = replace(
        Settings.platform_defaults(),
        source=downloads,
        destination=tmp_path / "PhotoPass",
        shared_root=None,
        import_to_photos=True,
    )
    day = date(2026, 3, 7)
    config = Config(
        settings=settings,
        friends={"Sam": Friend("Sam", ShareMethod.PHOTOS_ALBUM, album="Sam")},
        trips=[TripRule(day, day, ("Sam",), True)],
    )
    write_config(config, state / CONFIG_NAME)
    confirm = []

    def fake_sync(summary, config):
        ((_, digest),) = summary.album_shares["Sam"]
        shared = json.loads((state / "ledger.json").read_text(encoding="utf-8"))
        confirm.append(shared[digest]["shared_with"])
        return PhotosSummary(imported=1, added_by_friend={"Sam": [digest]})

    monkeypatch.setattr(cli, "sync_photos", fake_sync)
    assert main(["organize", "--state-dir", str(state)]) == 0
    assert confirm == [[]]
    ledger = json.loads((state / "ledger.json").read_text(encoding="utf-8"))
    assert [entry["shared_with"] for entry in ledger.values()] == [["Sam"]]


def test_organize_bad_trip_range_exits_2(
    state, downloads, tmp_path, capsys, sync_calls
):
    write_state_config(state, downloads, tmp_path / "PhotoPass")
    assert main(["organize", "--trip", "March", "--state-dir", str(state)]) == 2
    captured = capsys.readouterr()
    assert captured.err.startswith("ERROR: ")
    assert "YYYY-MM-DD" in captured.err
    assert captured.out == ""


def test_review_with_no_photopass_files_still_opens_the_page(
    state, downloads, tmp_path, capsys, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        cli, "open_review", lambda *args, **kwargs: calls.append(args) or 0
    )
    write_state_config(state, downloads, tmp_path / "PhotoPass")
    assert main(["review", "--no-open", "--state-dir", str(state)]) == 0
    assert len(calls) == 1
    assert f"INFO: no PhotoPass files found in {downloads}" in capsys.readouterr().err


def test_review_with_files_opens_the_review_server(
    state, downloads, tmp_path, monkeypatch
):
    calls = []

    def fake_open_review(state_dir, config, open_browser, port):
        calls.append((state_dir, config.settings.source, open_browser, port))
        return 0

    monkeypatch.setattr(cli, "open_review", fake_open_review)
    add_photo(downloads)
    write_state_config(state, downloads, tmp_path / "PhotoPass")
    assert (
        main(["review", "--no-open", "--port", "8123", "--state-dir", str(state)]) == 0
    )
    assert calls == [(state, downloads, False, 8123)]
    assert main(["review", "--state-dir", str(state)]) == 0
    assert calls[1][2:] == (True, 0)


def test_config_error_exits_2(state, capsys):
    state.mkdir()
    (state / CONFIG_NAME).write_text("[settings\nbroken", encoding="utf-8")
    assert main(["organize", "--state-dir", str(state)]) == 2
    captured = capsys.readouterr()
    assert captured.err.startswith("ERROR: ")
    assert captured.out == ""


def test_import_photos_defaults_to_day_folders_under_destination(
    state, downloads, tmp_path, capsys, monkeypatch
):
    destination = tmp_path / "PhotoPass"
    write_jpeg(destination / "2026-03-07 - Disneyland Park" / "a.jpeg", None, None)
    write_jpeg(destination / "_Stock art" / "b.jpeg", None, None)
    write_state_config(state, downloads, destination)
    imported = []

    def fake_import(folder, album_name=None, parent_folder="PhotoPass"):
        imported.append((folder.name, parent_folder))
        return ImportResult(count=1, ids_by_filename={})

    monkeypatch.setattr(cli, "import_folder", fake_import)
    assert main(["import-photos", "--state-dir", str(state)]) == 0
    assert imported == [("2026-03-07 - Disneyland Park", "PhotoPass")]
    assert (
        "SUCCESS: imported 1 items from 1 folders into Photos, purged 0"
        in capsys.readouterr().out
    )
    assert load_config(state / CONFIG_NAME).settings.destination == destination


def zip_photo(downloads, tmp_path):
    source = write_jpeg(
        tmp_path / "source" / "castle.jpeg", "2026:03:07 10:00:00", "-08:00"
    )
    archive = downloads / f"{BATCH}.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.write(source, "2026-03-07 - Disneyland Park - Castle.jpeg")
    return archive


def test_review_expands_a_zipped_batch_before_planning(
    state, downloads, tmp_path, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        cli, "open_review", lambda *args, **kwargs: calls.append(args) or 0
    )
    archive = zip_photo(downloads, tmp_path)
    write_state_config(state, downloads, tmp_path / "PhotoPass")
    assert main(["review", "--no-open", "--state-dir", str(state)]) == 0
    assert len(calls) == 1
    assert not archive.exists()
    assert (downloads / BATCH / "2026-03-07 - Disneyland Park - Castle.jpeg").is_file()


def test_organize_expands_a_zipped_batch(state, downloads, tmp_path, capsys):
    archive = zip_photo(downloads, tmp_path)
    write_state_config(state, downloads, tmp_path / "PhotoPass")
    assert main(["organize", "--state-dir", str(state)]) == 0
    assert not archive.exists()
    assert "undecided 1 left in the source folder" in capsys.readouterr().out


@pytest.mark.parametrize("flag", ["--dry-run", "--copy"])
def test_organize_leaves_a_zip_alone_when_downloads_must_not_change(
    flag, state, downloads, tmp_path, capsys
):
    archive = zip_photo(downloads, tmp_path)
    write_state_config(state, downloads, tmp_path / "PhotoPass")
    assert main(["organize", flag, "--state-dir", str(state)]) == 0
    assert archive.exists()
    assert not (downloads / BATCH).exists()
    assert f"Would expand {archive} (1 files)" in capsys.readouterr().err


def test_import_photos_finds_nested_day_folders_and_names_albums_by_day(
    state, downloads, tmp_path, monkeypatch
):
    destination = tmp_path / "PhotoPass"
    write_jpeg(destination / "2026-03-07" / "Disneyland Park" / "a.jpeg", None, None)
    write_jpeg(destination / "Epcot" / "2026-06-05" / "b.jpeg", None, None, seed=2)
    write_jpeg(destination / "_Stock art" / "c.jpeg", None, None, seed=3)
    write_state_config(state, downloads, destination)
    imported = []

    def fake_import(folder, album_name=None, parent_folder="PhotoPass"):
        imported.append(album_name)
        return ImportResult(count=1, ids_by_filename={})

    monkeypatch.setattr(cli, "import_folder", fake_import)
    assert main(["import-photos", "--state-dir", str(state)]) == 0
    assert imported == ["2026-03-07 - Disneyland Park", "2026-06-05 - Epcot"]


def test_once_per_message_filter_drops_repeats():
    once = cli.OncePerMessage()

    def record(level, text):
        return logging.LogRecord("name", level, "path", 1, text, None, None)

    assert once.filter(record(logging.INFO, "Skipping 1.mp4")) is True
    assert once.filter(record(logging.INFO, "Skipping 1.mp4")) is False
    assert once.filter(record(logging.WARNING, "Skipping 1.mp4")) is True
    assert once.filter(record(logging.INFO, "Skipping 2.mp4")) is True

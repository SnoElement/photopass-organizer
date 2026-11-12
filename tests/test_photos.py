import logging
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from photopass_organizer import photos
from photopass_organizer.config import Config, Friend, Settings, ShareMethod
from photopass_organizer.organizer import Summary


class FakeOsascript:
    def __init__(self, *replies: subprocess.CompletedProcess):
        self.replies = list(replies)
        self.calls: list[tuple[str, list[str]]] = []

    def __call__(
        self, script: str, arguments: list[str]
    ) -> subprocess.CompletedProcess:
        self.calls.append((script, arguments))
        return self.replies.pop(0)


def reply(
    stdout: str = "", returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def make_folder(parent: Path, name: str, *filenames: str) -> Path:
    folder = parent / name
    folder.mkdir()
    for filename in filenames:
        (folder / filename).write_bytes(b"x")
    return folder


def install(monkeypatch, *replies: subprocess.CompletedProcess) -> FakeOsascript:
    fake = FakeOsascript(*replies)
    monkeypatch.setattr(photos, "_run_osascript", fake)
    monkeypatch.setattr(photos, "is_macos", lambda: True)
    return fake


def photos_config(
    tmp_path: Path,
    import_to_photos: bool = True,
    purge: bool = False,
    **friends: Friend,
) -> Config:
    settings = replace(
        Settings.platform_defaults(),
        destination=tmp_path / "dest",
        shared_root=None,
        import_to_photos=import_to_photos,
        purge_after_import=purge,
        photos_folder="Trips",
    )
    return Config(settings=settings, friends=dict(friends))


def album_friend(name: str, album: str | None) -> Friend:
    return Friend(name=name, share=ShareMethod.PHOTOS_ALBUM, album=album)


def test_import_folder_returns_ids_by_filename(tmp_path, monkeypatch):
    folder = make_folder(
        tmp_path, "2026-10-10 - Epcot", "b.jpeg", "a.jpeg", ".DS_Store"
    )
    fake = install(monkeypatch, reply("A1\ta.jpeg\t\nB2\tb.jpeg\t\n\n"))
    result = photos.import_folder(folder)
    assert result == photos.ImportResult(
        count=2, ids_by_filename={"a.jpeg": "A1", "b.jpeg": "B2"}
    )
    script, arguments = fake.calls[0]
    assert arguments == [
        "PhotoPass",
        "2026-10-10 - Epcot",
        str(folder / "a.jpeg"),
        str(folder / "b.jpeg"),
    ]
    assert "argv" in script
    assert "PhotoPass" not in script
    assert "Epcot" not in script


def test_import_folder_uses_given_album_and_parent_folder(tmp_path, monkeypatch):
    folder = make_folder(tmp_path, "2026-10-10 - Epcot", "a.jpeg")
    fake = install(monkeypatch, reply("A1\ta.jpeg\t\n"))
    photos.import_folder(folder, album_name="Alex Trip", parent_folder="Shared")
    assert fake.calls[0][1][:2] == ["Shared", "Alex Trip"]


def test_import_folder_reports_failure(tmp_path, monkeypatch, caplog):
    folder = make_folder(tmp_path, "2026-10-10 - Epcot", "a.jpeg")
    install(monkeypatch, reply("", returncode=1, stderr="boom"))
    with caplog.at_level(logging.ERROR):
        result = photos.import_folder(folder)
    assert result == photos.ImportResult(count=0, ids_by_filename={})
    assert "boom" in caplog.text


def test_import_folder_of_nothing_does_not_call_photos(tmp_path, monkeypatch):
    folder = make_folder(tmp_path, "empty", ".DS_Store")
    fake = install(monkeypatch)
    assert photos.import_folder(folder) == photos.ImportResult(
        count=0, ids_by_filename={}
    )
    assert fake.calls == []


def test_import_files_passes_album_parent_and_paths(tmp_path, monkeypatch):
    folder = make_folder(tmp_path, "day", "a.jpeg", "b.jpeg")
    fake = install(monkeypatch, reply("A1\ta.jpeg\t\nB2\tb.jpeg\t\n"))
    result = photos.import_files(
        [folder / "a.jpeg", folder / "b.jpeg"], "Sam", "Shared"
    )
    assert result.ids_by_filename == {"a.jpeg": "A1", "b.jpeg": "B2"}
    assert fake.calls[0][1] == [
        "Shared",
        "Sam",
        str(folder / "a.jpeg"),
        str(folder / "b.jpeg"),
    ]


def test_import_files_counts_every_line_and_warns_once_about_repeated_filenames(
    tmp_path, monkeypatch, caplog
):
    first = make_folder(tmp_path, "day one", "IMG.jpeg")
    second = make_folder(tmp_path, "day two", "IMG.jpeg")
    install(monkeypatch, reply("A1\tIMG.jpeg\t\nB2\tIMG.jpeg\t\n\n"))
    with caplog.at_level(logging.WARNING):
        result = photos.import_files(
            [first / "IMG.jpeg", second / "IMG.jpeg"], "Sam", "Shared"
        )
    assert result == photos.ImportResult(count=2, ids_by_filename={"IMG.jpeg": "A1"})
    warnings = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    assert "IMG.jpeg" in warnings[0]


def test_import_folder_keeps_filenames_with_newlines_and_tabs(tmp_path, monkeypatch):
    folder = make_folder(tmp_path, "day", "a.jpeg", "b.jpeg")
    install(monkeypatch, reply("A1\ta\nname.jpeg\t\nB2\tb\tname.jpeg\t\n\n"))
    result = photos.import_folder(folder)
    assert result.count == 2
    assert result.ids_by_filename == {"a\nname.jpeg": "A1", "b\tname.jpeg": "B2"}


def test_add_to_album_passes_ids_and_album(monkeypatch):
    fake = install(monkeypatch, reply("2\n"))
    assert photos.add_to_album(["A1", "B2"], "Sam", "Shared") == 2
    script, arguments = fake.calls[0]
    assert arguments == ["Shared", "Sam", "A1", "B2"]
    assert "media item id" in script
    assert "Sam" not in script


def test_add_to_album_failure_adds_nothing(monkeypatch, caplog):
    install(monkeypatch, reply("", returncode=1, stderr="no such item"))
    with caplog.at_level(logging.ERROR):
        assert photos.add_to_album(["A1"], "Sam", "Shared") == 0
    assert "no such item" in caplog.text


def test_add_to_album_with_no_ids_does_not_call_photos(monkeypatch):
    fake = install(monkeypatch)
    assert photos.add_to_album([], "Sam", "Shared") == 0
    assert fake.calls == []


def test_import_and_purge_removes_folder_only_on_full_import(tmp_path, monkeypatch):
    folder = make_folder(tmp_path, "2026-10-10 - Epcot", "a.jpeg", "b.jpeg")
    install(monkeypatch, reply("A1\ta.jpeg\t\n"))
    result, purged = photos.import_and_purge(folder)
    assert (result.count, purged) == (1, False)
    assert folder.exists()
    install(monkeypatch, reply("A1\ta.jpeg\t\nB2\tb.jpeg\t\n"))
    result, purged = photos.import_and_purge(folder)
    assert (result.count, purged) == (2, True)
    assert not folder.exists()


def test_sync_photos_imports_placed_files_then_adds_to_friend_album(
    tmp_path, monkeypatch
):
    placed = make_folder(tmp_path, "2026-10-10 - Epcot", "a.jpeg", "b.jpeg")
    fake = install(monkeypatch, reply("A1\ta.jpeg\t\nB2\tb.jpeg\t\n"), reply("1\n"))
    summary = Summary(
        import_files={placed: {placed / "a.jpeg", placed / "b.jpeg"}},
        album_shares={"Sam": [(placed / "b.jpeg", "hash-b")]},
    )
    config = photos_config(tmp_path, Sam=album_friend("Sam", "Sam at Epcot"))
    result = photos.sync_photos(summary, config)
    assert fake.calls[0][1][:2] == ["Trips", "2026-10-10 - Epcot"]
    assert fake.calls[1][1] == ["Shared", "Sam at Epcot", "B2"]
    assert result == photos.PhotosSummary(
        imported=2,
        purged=0,
        added_to_friend_albums=1,
        friend_imports=0,
        added_by_friend={"Sam": ["hash-b"]},
    )
    assert placed.exists()


def test_sync_photos_imports_only_the_files_placed_this_run(tmp_path, monkeypatch):
    folder = make_folder(tmp_path, "day", "old.jpeg", "new.jpeg")
    fake = install(monkeypatch, reply("N1\tnew.jpeg\t\n"))
    summary = Summary(import_files={folder: {folder / "new.jpeg"}})
    result = photos.sync_photos(summary, photos_config(tmp_path, purge=True))
    assert fake.calls[0][1] == ["Trips", "day", str(folder / "new.jpeg")]
    assert (result.imported, result.purged) == (1, 0)
    assert (folder / "old.jpeg").exists() and (folder / "new.jpeg").exists()


def test_sync_photos_purges_a_folder_whose_every_file_was_imported(
    tmp_path, monkeypatch
):
    placed = make_folder(tmp_path, "2026-10-10 - Epcot", "a.jpeg")
    install(monkeypatch, reply("A1\ta.jpeg\t\n"), reply("1\n"))
    summary = Summary(
        import_files={placed: {placed / "a.jpeg"}},
        album_shares={"Sam": [(placed / "a.jpeg", "hash-a")]},
    )
    config = photos_config(tmp_path, purge=True, Sam=album_friend("Sam", "Sam"))
    result = photos.sync_photos(summary, config)
    assert not placed.exists()
    assert result == photos.PhotosSummary(
        imported=1,
        purged=1,
        added_to_friend_albums=1,
        friend_imports=0,
        added_by_friend={"Sam": ["hash-a"]},
    )


def test_sync_photos_does_not_purge_after_a_short_import(tmp_path, monkeypatch):
    folder = make_folder(tmp_path, "day", "a.jpeg", "b.jpeg")
    install(monkeypatch, reply("A1\ta.jpeg\t\n"))
    summary = Summary(import_files={folder: {folder / "a.jpeg", folder / "b.jpeg"}})
    result = photos.sync_photos(summary, photos_config(tmp_path, purge=True))
    assert folder.exists()
    assert (result.imported, result.purged) == (1, 0)


def test_sync_photos_album_name_falls_back_to_friend_name(tmp_path, monkeypatch):
    placed = make_folder(tmp_path, "day", "a.jpeg")
    fake = install(monkeypatch, reply("A1\ta.jpeg\t\n"), reply("1\n"))
    summary = Summary(
        import_files={placed: {placed / "a.jpeg"}},
        album_shares={"Jordan": [(placed / "a.jpeg", "hash-a")]},
    )
    photos.sync_photos(
        summary, photos_config(tmp_path, Jordan=album_friend("Jordan", None))
    )
    assert fake.calls[1][1][:2] == ["Shared", "Jordan"]


def test_sync_photos_leaves_unconfirmed_shares_for_the_next_run(
    tmp_path, monkeypatch, caplog
):
    placed = make_folder(tmp_path, "day", "a.jpeg", "b.jpeg")
    fake = install(monkeypatch, reply("A1\ta.jpeg\t\n"), reply("1\n"))
    summary = Summary(
        import_files={placed: {placed / "a.jpeg", placed / "b.jpeg"}},
        album_shares={
            "Sam": [(placed / "a.jpeg", "hash-a"), (placed / "b.jpeg", "hash-b")]
        },
    )
    with caplog.at_level(logging.WARNING):
        result = photos.sync_photos(
            summary, photos_config(tmp_path, Sam=album_friend("Sam", "Sam"))
        )
    assert fake.calls[1][1] == ["Shared", "Sam", "A1"]
    assert result.added_by_friend == {"Sam": ["hash-a"]}
    assert result.failed_by_friend == {"Sam": 1}
    messages = [record.getMessage() for record in caplog.records]
    assert any("b.jpeg" in message for message in messages)
    assert any(
        "Photos could not add 1 photos for Sam; they are retried the next time that photo is downloaded"
        in message
        for message in messages
    )


def test_sync_photos_confirms_nothing_when_the_album_add_fails(tmp_path, monkeypatch):
    placed = make_folder(tmp_path, "day", "a.jpeg")
    install(
        monkeypatch,
        reply("A1\ta.jpeg\t\n"),
        reply("", returncode=1, stderr="no such album"),
    )
    summary = Summary(
        import_files={placed: {placed / "a.jpeg"}},
        album_shares={"Sam": [(placed / "a.jpeg", "hash-a")]},
    )
    result = photos.sync_photos(
        summary, photos_config(tmp_path, Sam=album_friend("Sam", "Sam"))
    )
    assert result.added_by_friend == {}
    assert result.failed_by_friend == {"Sam": 1}


def test_sync_photos_imports_pending_folder_into_friend_album_and_purges(
    tmp_path, monkeypatch
):
    pending = make_folder(tmp_path, "Sam", "a.jpeg", "b.jpeg")
    fake = install(monkeypatch, reply("A1\ta.jpeg\t\nB2\tb.jpeg\t\n"))
    summary = Summary(
        pending_import_folders={"Sam": pending},
        staged_shares={
            "Sam": [(pending / "a.jpeg", "hash-a"), (pending / "b.jpeg", "hash-b")]
        },
    )
    config = photos_config(tmp_path, Sam=album_friend("Sam", "Sam at Epcot"))
    result = photos.sync_photos(summary, config)
    assert fake.calls[0][1][:2] == ["Shared", "Sam at Epcot"]
    assert not pending.exists()
    assert result == photos.PhotosSummary(
        imported=0,
        purged=0,
        added_to_friend_albums=0,
        friend_imports=2,
        added_by_friend={"Sam": ["hash-a", "hash-b"]},
    )


def test_sync_photos_warns_when_pending_folder_stays(tmp_path, monkeypatch, caplog):
    pending = make_folder(tmp_path, "Sam", "a.jpeg", "b.jpeg", "c.jpeg")
    install(monkeypatch, reply("A1\ta.jpeg\t\n"))
    summary = Summary(
        pending_import_folders={"Sam": pending},
        staged_shares={
            "Sam": [
                (pending / name, f"hash-{name}")
                for name in ("a.jpeg", "b.jpeg", "c.jpeg")
            ]
        },
    )
    with caplog.at_level(logging.WARNING):
        result = photos.sync_photos(
            summary, photos_config(tmp_path, Sam=album_friend("Sam", "Sam"))
        )
    assert pending.exists()
    assert result.friend_imports == 1
    assert result.added_by_friend == {"Sam": ["hash-a.jpeg"]}
    assert result.failed_by_friend == {"Sam": 2}
    warnings = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING
    ]
    assert any(str(pending) in message and "2 of 3" in message for message in warnings)


def test_sync_photos_without_library_import_imports_files_into_friend_album(
    tmp_path, monkeypatch
):
    placed = make_folder(tmp_path, "day", "a.jpeg", "b.jpeg")
    fake = install(monkeypatch, reply("A1\ta.jpeg\t\nB2\tb.jpeg\t\n"))
    summary = Summary(
        import_files={placed: {placed / "a.jpeg", placed / "b.jpeg"}},
        album_shares={
            "Sam": [(placed / "a.jpeg", "hash-a"), (placed / "b.jpeg", "hash-b")]
        },
    )
    config = photos_config(
        tmp_path, import_to_photos=False, Sam=album_friend("Sam", "Sam at Epcot")
    )
    result = photos.sync_photos(summary, config)
    assert len(fake.calls) == 1
    assert fake.calls[0][1] == [
        "Shared",
        "Sam at Epcot",
        str(placed / "a.jpeg"),
        str(placed / "b.jpeg"),
    ]
    assert result == photos.PhotosSummary(
        imported=0,
        purged=0,
        added_to_friend_albums=0,
        friend_imports=2,
        added_by_friend={"Sam": ["hash-a", "hash-b"]},
    )
    assert placed.exists()


def test_sync_photos_off_macos_is_an_error_without_osascript(
    tmp_path, monkeypatch, caplog
):
    fake = FakeOsascript()
    monkeypatch.setattr(photos, "_run_osascript", fake)
    monkeypatch.setattr(photos, "is_macos", lambda: False)
    placed = make_folder(tmp_path, "day", "a.jpeg")
    summary = Summary(
        import_files={placed: {placed / "a.jpeg"}},
        album_shares={"Sam": [(placed / "a.jpeg", "hash-a")]},
        pending_import_folders={"Sam": placed},
    )
    with caplog.at_level(logging.INFO):
        result = photos.sync_photos(
            summary, photos_config(tmp_path, Sam=album_friend("Sam", "Sam"))
        )
    assert fake.calls == []
    assert result == photos.PhotosSummary()
    errors = [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert [record.getMessage() for record in errors] == [
        "Photos.app import needs macOS"
    ]


def test_sync_photos_with_nothing_to_do_does_not_call_photos(tmp_path, monkeypatch):
    fake = install(monkeypatch)
    assert photos.sync_photos(Summary(), photos_config(tmp_path)) == (
        photos.PhotosSummary()
    )
    assert fake.calls == []


@pytest.mark.parametrize("script_name", ["IMPORT_SCRIPT", "ADD_SCRIPT"])
def test_scripts_are_ascii(script_name):
    getattr(photos, script_name).encode("ascii")


def test_album_name_is_date_then_place_for_every_layout(tmp_path):
    assert (
        photos.album_name_for(tmp_path / "2026-03-07 - Epcot") == "2026-03-07 - Epcot"
    )
    assert (
        photos.album_name_for(tmp_path / "2026-03-07" / "Epcot") == "2026-03-07 - Epcot"
    )
    assert (
        photos.album_name_for(tmp_path / "Epcot" / "2026-03-07") == "2026-03-07 - Epcot"
    )

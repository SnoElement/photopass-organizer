import logging
import zipfile

from conftest import write_jpeg

from photopass_organizer.archives import expand_zip_batches

BATCH = "ecd5e910-484f-4b99-ac12-9fad86cefc89"
CASTLE = "2026-03-07 - Disneyland Park - Castle.jpeg"
TRAIN = "2026-03-07 - Disneyland Park - Train_2.jpeg"


def make_zip(downloads, members, name=f"{BATCH}.zip"):
    downloads.mkdir(parents=True, exist_ok=True)
    path = downloads / name
    with zipfile.ZipFile(path, "w") as archive:
        for member, data in members.items():
            archive.writestr(member, data)
    return path


def jpeg_bytes(tmp_path, seed):
    path = write_jpeg(
        tmp_path / "source" / f"{seed}.jpeg", "2026:03:07 10:00:00", "-08:00", seed=seed
    )
    return path.read_bytes()


def test_expands_a_uuid_zip_of_photopass_files_and_deletes_it(tmp_path):
    downloads = tmp_path / "Downloads"
    castle, train = jpeg_bytes(tmp_path, 1), jpeg_bytes(tmp_path, 2)
    archive = make_zip(downloads, {CASTLE: castle, TRAIN: train})
    assert expand_zip_batches(downloads) == [downloads / BATCH]
    assert (downloads / BATCH / CASTLE).read_bytes() == castle
    assert (downloads / BATCH / TRAIN).read_bytes() == train
    assert not archive.exists()
    assert sorted(path.name for path in downloads.iterdir()) == [BATCH]


def test_members_inside_a_top_folder_are_flattened_and_mac_extras_ignored(tmp_path):
    downloads = tmp_path / "Downloads"
    castle = jpeg_bytes(tmp_path, 1)
    make_zip(
        downloads,
        {
            f"{BATCH}/{CASTLE}": castle,
            f"__MACOSX/{BATCH}/._{CASTLE}": b"resource fork",
            f"{BATCH}/.DS_Store": b"store",
        },
    )
    assert expand_zip_batches(downloads) == [downloads / BATCH]
    assert [path.name for path in (downloads / BATCH).iterdir()] == [CASTLE]


def test_dry_run_reports_and_changes_nothing(tmp_path, caplog):
    downloads = tmp_path / "Downloads"
    archive = make_zip(downloads, {CASTLE: jpeg_bytes(tmp_path, 1)})
    with caplog.at_level(logging.INFO):
        assert expand_zip_batches(downloads, dry_run=True) == []
    assert archive.exists()
    assert not (downloads / BATCH).exists()
    assert f"Would expand {archive} (1 files)" in caplog.text


def test_leaves_zips_that_are_not_photopass_batches(tmp_path, caplog):
    downloads = tmp_path / "Downloads"
    other = "28fb2cc8-f4c3-4d2f-afb6-e634a549ddef"
    foreign = make_zip(downloads, {"1-video-3372160481.mp4": b"x"})
    mixed = make_zip(
        downloads,
        {CASTLE: jpeg_bytes(tmp_path, 1), "notes.txt": b"x"},
        name=f"{other}.zip",
    )
    plain = make_zip(downloads, {CASTLE: jpeg_bytes(tmp_path, 1)}, name="holiday.zip")
    empty = make_zip(downloads, {}, name="71c48028-31f9-4a4c-91e4-25a302cfdeb9.zip")
    with caplog.at_level(logging.INFO):
        assert expand_zip_batches(downloads) == []
    assert all(path.exists() for path in (foreign, mixed, plain, empty))
    assert sorted(path.name for path in downloads.iterdir() if path.is_dir()) == []
    assert caplog.text == ""


def test_same_file_name_twice_in_a_zip_is_left_alone(tmp_path, caplog):
    downloads = tmp_path / "Downloads"
    archive = make_zip(
        downloads,
        {
            f"a/{CASTLE}": jpeg_bytes(tmp_path, 1),
            f"b/{CASTLE}": jpeg_bytes(tmp_path, 2),
        },
    )
    assert expand_zip_batches(downloads) == []
    assert archive.exists()
    assert "more than once" in caplog.text


def test_existing_folder_is_not_overwritten(tmp_path, caplog):
    downloads = tmp_path / "Downloads"
    archive = make_zip(downloads, {CASTLE: jpeg_bytes(tmp_path, 1)})
    (downloads / BATCH).mkdir()
    (downloads / BATCH / "keep.txt").write_text("mine", encoding="utf-8")
    assert expand_zip_batches(downloads) == []
    assert archive.exists()
    assert [path.name for path in (downloads / BATCH).iterdir()] == ["keep.txt"]
    assert "already exists" in caplog.text


def test_a_damaged_zip_is_left_alone_with_a_warning(tmp_path, caplog):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    broken = downloads / f"{BATCH}.zip"
    broken.write_bytes(b"PK\x03\x04 not really a zip")
    assert expand_zip_batches(downloads) == []
    assert broken.exists()
    assert "Could not read" in caplog.text
    assert sorted(path.name for path in downloads.iterdir()) == [broken.name]


def test_a_member_that_fails_its_checksum_leaves_no_folder(tmp_path, caplog):
    downloads = tmp_path / "Downloads"
    data = jpeg_bytes(tmp_path, 1)
    archive = make_zip(downloads, {CASTLE: data})
    raw = bytearray(archive.read_bytes())
    position = raw.index(data[:16]) + 20
    raw[position] ^= 0xFF
    archive.write_bytes(bytes(raw))
    assert expand_zip_batches(downloads) == []
    assert archive.exists()
    assert sorted(path.name for path in downloads.iterdir()) == [archive.name]
    assert "Could not expand" in caplog.text


def test_missing_downloads_folder_is_nothing_to_do(tmp_path):
    assert expand_zip_batches(tmp_path / "nowhere") == []

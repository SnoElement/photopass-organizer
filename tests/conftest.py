import struct
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

from PIL import Image, ImageCms

from photopass_organizer.config import Config, Settings, TripRule

QUICKTIME_EPOCH = datetime(1904, 1, 1, tzinfo=UTC)


def write_jpeg(
    path: Path,
    capture_local: str | None,
    offset: str | None,
    seed: int = 0,
    icc: bool = False,
) -> Path:
    """Write a tiny JPEG whose pixel content depends on seed, with optional EXIF capture time and ICC profile."""
    image = Image.new("RGB", (8, 8), (seed % 256, (seed * 7) % 256, (seed * 13) % 256))
    if icc:
        image.info["icc_profile"] = ImageCms.ImageCmsProfile(
            ImageCms.createProfile("sRGB")
        ).tobytes()
    exif = Image.Exif()
    if capture_local is not None:
        exif_ifd = exif.get_ifd(0x8769)
        exif_ifd[0x9003] = capture_local
        if offset is not None:
            exif_ifd[0x9011] = offset
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(
        path,
        format="JPEG",
        exif=exif.tobytes(),
        icc_profile=image.info.get("icc_profile"),
    )
    return path


def write_mp4(path: Path, created_utc: datetime | None, seed: int = 0) -> Path:
    """Write a minimal MP4 container: ftyp + moov(mvhd v0) + mdat with seed-dependent payload."""
    if created_utc is None:
        creation_seconds = 0
    else:
        creation_seconds = int((created_utc - QUICKTIME_EPOCH).total_seconds())
    ftyp = b"ftyp" + b"isom" + struct.pack(">I", 512) + b"isomiso2mp41"
    ftyp = struct.pack(">I", 8 + len(ftyp)) + ftyp
    mvhd_body = bytes([0, 0, 0, 0]) + struct.pack(
        ">IIII", creation_seconds, creation_seconds, 1000, 30000
    )
    mvhd_body += bytes(80)
    mvhd = struct.pack(">I", 8 + len(mvhd_body)) + b"mvhd" + mvhd_body
    moov = struct.pack(">I", 8 + len(mvhd)) + b"moov" + mvhd
    payload = (b"%08d" % seed) * 4
    mdat = struct.pack(">I", 8 + len(payload)) + b"mdat" + payload
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(ftyp + moov + mdat)
    return path


def decided_config(
    downloads: Path, destination: Path, stock_art: str = "delete"
) -> Config:
    """A config whose single rule covers every date under test, with no friends."""
    settings = replace(
        Settings.platform_defaults(),
        source=downloads,
        destination=destination,
        shared_root=None,
        stock_art=stock_art,
        import_to_photos=False,
    )
    return Config(
        settings=settings,
        trips=[TripRule(date(2025, 1, 1), date(2026, 12, 31), (), True)],
    )

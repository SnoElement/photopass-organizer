# Changelog

## 1.0.0 - 2026-11-11

First public release.

- `photopass-organizer review` opens a local review page that shows every new photo, with per-day decisions (I was there, friends, ignore this day) that save automatically.
- Per-friend sharing: each friend receives photos in a synced folder anywhere on disk or in a Photos.app album.
- Trip rules in `photopass.toml` with `ignore` days and `parks` scoping; overlapping rules are rejected unless their parks are disjoint.
- Per-photo overrides: ignore a single photo, or keep a photo that stock-art detection would drop.
- Duplicate handling by content hash and by fingerprint against evicted cloud folders, and stock-art detection (delete or keep under `_Stock art`).
- A ledger records every hash already placed, shared or deleted, so adding a friend to an old trip shares the photos on the next run without duplicating them.
- `organize --trip DATE` and `--trip START..END` handle one trip at a time; `--dry-run` and `--copy` make runs safe.
- Dates come from EXIF and MP4 metadata rather than the UTC filename date; videos without metadata are dated from their paired photo; parks outside the built-in table are added with `[parks]`.
- `photopass-organizer init` writes a starter config into the state directory (`~/.config/photopass-organizer`, or `--state-dir`, or `PHOTOPASS_ORGANIZER_HOME`), which also holds the ledger and the action log.
- `photopass-organizer import-photos` and the `import_to_photos` setting import day folders into Photos.app albums, with an optional purge of the local folder once Photos confirms the count.
- A UUID-named zip of PhotoPass files left unexpanded in the source folder is unpacked by `review` and `organize` (not by `--dry-run` or `--copy`), and the zip is deleted once every file is out.
- `layout` setting: file under `<date> - <park>` (default), `<date>/<park>` or `<park>/<date>`.
- Special-event photos (`Special Events at ...`) are filed in a folder named for the event and take the host park's timezone.
- The review page has a Settings form for the `[settings]` table, filters by park, type, decision and friend, and unknown timezones are rejected when the config is read.
- Linux support for everything except the Photos.app features.

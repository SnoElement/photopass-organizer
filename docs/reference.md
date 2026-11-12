# Reference

Every setting, rule and command of photopass-organizer. For step-by-step instructions, read
[How to use photopass-organizer](how-to.md). For the reasons behind the behaviour, read
[How photopass-organizer works](how-it-works.md).

## Configuration reference

The file is TOML. Unknown keys and unknown tables are an error, so a typo is caught on the next run. The
old key `downloads` is rejected with a message naming `source`. Relative paths resolve against the folder
holding `photopass.toml`; a leading `~` is the home folder.

### `[settings]`

| Key | Default | Meaning |
| --- | --- | --- |
| `source` | `~/Downloads` | The folder PhotoPass batches are read from |
| `destination` | `~/Pictures/PhotoPass` | Where your own day folders are filed |
| `default_timezone` | `America/New_York` | IANA timezone for parks not in the built-in table or `[parks]`; an unknown name is an error |
| `stock_art` | `delete` | `delete` or `keep` |
| `shared_root` | macOS: iCloud Drive `Shared Photos` folder; Linux: none | Parent of folder friends' default folders. `""` means none |
| `import_to_photos` | `true` on macOS, `false` elsewhere | Import each placed day into Photos after a run |
| `photos_folder` | `PhotoPass` | Photos folder that holds one album per day and park |
| `purge_after_import` | `true` | Delete a local day folder once Photos confirms it took every file |
| `layout` | `flat` | Folder structure under `destination`: `flat`, `date/park` or `park/date` |

The three layouts file the same photo as:

```text
flat        2026-09-20 - Disneyland Park/
date/park   2026-09-20/Disneyland Park/
park/date   Disneyland Park/2026-09-20/
```

Photos albums are named `<date> - <park>` whichever layout you choose. Changing `layout` does not move
folders that are already filed.

### `[parks]`

Maps a park name, exactly as it appears in the file name, to an IANA timezone. A timezone the system does
not know is an error. It is a top-level table, not part of `[settings]`:

```toml
[parks]
"Tokyo Disneyland" = "Asia/Tokyo"
```

The "park" is whatever Disney puts in that part of the file name, so photos taken at a resort hotel are
filed under the hotel's name. A name the tool does not know is dated with `default_timezone` and listed in
a warning; add it here if that timezone is wrong.

A park named `Special Events at <place>` takes the timezone of `<place>` unless it is listed here (`DCA`
means Disney California Adventure Park). Its photos are filed under the name of the event, taken from the
location part of the file name, for example `2026-09-20 - Oogie Boogie Bash`. `[parks]` keys and
`[[trip]]` `parks` still use Disney's label, `Special Events at DCA`.

### `[friends.<name>]`

| Key | Default | Meaning |
| --- | --- | --- |
| `share` | `folder` | `folder` or `photos-album` |
| `path` | `<shared_root>/<name>` | Sharing folder; allowed with `share = "folder"` only |
| `album` | the friend's name | Photos album under `Shared`; allowed with `share = "photos-album"` only |

### `[[trip]]`

```toml
[[trip]]
start = "2026-03-12"
end = "2026-03-16"
friends = ["Alex", "Sam"]
i_was_there = true

[[trip]]
start = "2026-04-02"
friends = ["Jordan"]
i_was_there = false

[[trip]]
start = "2026-04-03"
end = "2026-04-04"
parks = ["Epcot"]
ignore = true
```

| Key | Default | Meaning |
| --- | --- | --- |
| `start` | required | First local date, `YYYY-MM-DD` |
| `end` | same as `start` | Last local date |
| `friends` | none | Friends who receive a copy of every photo in the range |
| `i_was_there` | `true` | `false` shares with the friends and then deletes your copy |
| `parks` | all parks | Limit the rule to these parks |
| `ignore` | `false` | Delete everything in the range; may not be combined with `friends` or `i_was_there` |

A day with no rule is undecided and stays in the source folder. Two rules may not overlap, unless both
name `parks` and the lists do not share a park. These are errors too: an `end` before its `start`, and
`i_was_there = false` with no `friends`, which would delete the photos and share them with nobody.

### `[[photo]]`

```toml
[[photo]]
hash = "0f3a9c...full sha256 of the file..."
action = "ignore"
name = "blurry shot at the gate"
```

`hash` is the SHA-256 of the file contents. `action` is `ignore` (delete this photo) or `keep` (never treat
it as stock art). `hash` and `action` are required, and a hash may be listed once. `name` is a free label
for yourself. The review page writes these for you.

## Command reference

Every command takes `--state-dir DIR` and `--verbose`.

```sh
photopass-organizer init
photopass-organizer review [--no-open] [--port PORT]
photopass-organizer organize [--dry-run] [--copy] [--trip RANGE]
photopass-organizer import-photos [--purge] [FOLDER ...]
```

- `init` writes a starter `photopass.toml` into the state directory.
- `review` serves the review page (see [The routine](how-to.md#the-routine)) and runs until you press Done
  or Ctrl-C. It opens the page even when there is nothing new.
- `organize` applies the plan and prints a one-line summary. `--dry-run` prints the plan and changes
  nothing. `--copy` copies instead of moving. `--trip` limits the run to `YYYY-MM-DD` or
  `YYYY-MM-DD..YYYY-MM-DD`. When `import_to_photos` is on, or album friends need photos, it then imports
  into Photos.
- `import-photos` imports day folders into Photos albums named `<date> - <park>`, inside `photos_folder`.
  With no folders given it finds every day folder under `destination`, in any layout, and skips folders
  whose name starts with `_` or `.`. `--purge` deletes each folder once Photos confirms every file was
  imported.

`review` and `organize` first unpack any zip file in `source` whose name is a UUID and whose files all
have PhotoPass names. The files go into a folder of the same name and the zip is deleted. A zip is left
alone, with a warning, when that folder already exists, a file name repeats, or the zip cannot be read.
`organize --dry-run` and `organize --copy` unpack nothing and report what they would unpack.

Exit status is 0 on success, 2 for a configuration error or a bad `--trip` value, and 1 for a file system
error.

## State files

The state directory is `--state-dir`, else `$PHOTOPASS_ORGANIZER_HOME`, else
`~/.config/photopass-organizer`. It holds:

- `photopass.toml`, the configuration. Every save by the review page keeps the previous version as
  `photopass.toml.bak`.
- `ledger.json`, one entry per content hash already placed, shared or deleted. A placed entry holds the
  `path` and `placed_at`; a deleted one holds an empty `path`, `handled_at` and the `reason`. `shared_with`
  lists the friends who have a copy; an entry without that list predates share tracking and counts as
  shared with everyone. Do not delete the file unless you want old photos treated as new.
- `organizer.log`, one line per action, appended on every run except `--dry-run`.

Photos staged for an album friend whose import did not finish wait under `pending-import/` in the same
directory until the next run imports them.

## Platform notes

macOS supports everything. Linux supports everything except the Photos.app features: `import_to_photos`,
`import-photos` and `share = "photos-album"`. On Linux `shared_root` has no default, so give every
folder friend a `path`; a friend configured with `photos-album` is a configuration error. The review page
opens in the default browser on both systems.

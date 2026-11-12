# How photopass-organizer works

This page explains what a PhotoPass download contains and how the tool decides what to do with each file.
For step-by-step instructions, read [How to use photopass-organizer](how-to.md). For every setting and
command, read the [Reference](reference.md).

## What a PhotoPass download looks like

PhotoPass downloads land in `~/Downloads` as a folder named with a UUID, holding files named like this:

```text
2026-03-14 - Epcot - Spaceship Earth_3.jpeg
2026-03-14 - Magic Kingdom Park - Main Street USA_12.jpeg
```

Ride videos arrive loose in `~/Downloads` and are named only with a media id, such as `4821937650.mp4`.
Files with PhotoPass names that sit loose in `~/Downloads` are picked up too, and a copy the browser
renamed with ` 2` or ` (2)` is still recognised.

If your browser leaves the download as `<uuid>.zip`, `review` and `organize` unpack it into a folder of the
same name and delete the zip once every file is out. Only a zip whose files all have PhotoPass names is
touched, and one whose folder already exists or that repeats a file name is left alone with a warning.
`organize --dry-run` and `organize --copy` leave it zipped and say what they would expand.

Three things make these downloads awkward:

- The date in the file name is UTC. A photo taken at 8 pm in Florida is filed under the next day. The
  organizer reads the EXIF capture time and its timezone offset instead; a capture time with no offset is
  taken to be in the park's timezone. Videos use the MP4 creation time, converted with the park's timezone.
  A loose video takes its park from the nearest timed photo taken within three hours. With no photo that
  close it is filed under the park of its day when that day has exactly one park, and otherwise under the
  resort name.
- Every "Select all visible media" download contains the photos from your earlier downloads again, and
  Disney gives each one a different `_N` suffix every time, so the same photo appears under several names
  and a file-name comparison does not find it. Duplicates are recognised by content hash against the ledger
  of photos already dealt with (see "What gets deleted and when"), and by a file-name fingerprint against
  your friends' sharing folders (see "How sharing avoids duplicates").
- Stock art is mixed into the gallery. The tool treats a JPEG as stock art when it carries an embedded ICC
  profile, or when its EXIF date is more than two days from the file-name date. Magic Shots, where Disney
  adds a character or a frame to your own photo, kept the camera's EXIF in the downloads checked so far and
  are handled as ordinary photos. If one is flagged, its "Keep" button on the review page rescues it.
- On-ride photos carry no EXIF at all. A photo with no usable capture time is dated at noon, on the most
  common date among the other photos with the same file-name date and park, or on the file-name date when
  there are none. The file-name fallback is reported as a warning, because it can be a day late.

A UUID-named folder that holds anything other than PhotoPass files is left alone, with a note in the
output. Other folders in `~/Downloads` are never looked at.

## How sharing avoids duplicates

Each friend is shared with one of two methods, a synced folder or a Photos.app album. The how-to shows
how to [set up each one](how-to.md#share-photos-with-a-friend).

### Folder friends

Cloud services evict files to save disk space, so the tool never reads the bytes of a file in a sharing
folder. It matches a PhotoPass file to a file already in a sharing folder by a fingerprint of the date,
park and location in the file name plus the byte size, and ignores the `_N` suffix. Only files directly
in the sharing folder are matched, not files in folders inside it. This relies on an
evicted file still reporting its full size. A file that reports size 0 can never match, so the tool warns
when a sharing folder contains such files, because those photos would be shared again.

What was checked for evicted-file sizes (macOS, 2026-11-11):

| Service | Result |
| --- | --- |
| iCloud Drive | checked, evicted files report full size |
| OneDrive | checked, evicted files report full size |
| Dropbox | not checked |
| Google Drive | not checked |

The Dropbox folder on the test machine held no evicted files and no Google Drive was present. If you use
either, look at the warning after your first run; a warning about size 0 means the fingerprint match does not
work for that service and re-downloads will be shared again.

### Album friends

The tool adds each album friend's photos to the Photos album `Shared/<album>` by itself on every run.
Sharing that album with the friend is the one manual step, done once per friend in Photos.

For album friends the tool cannot look inside Photos, so it relies on its ledger to avoid sharing the same
photo twice. The ledger is checked first, so adding a friend to an old trip and downloading again shares the
photos with the new friend only. An album share is written to the ledger only after Photos confirms the
photo was added to the friend's album; if it could not, the run says `Photos could not add N photos for
<friend>; they are retried the next time that photo is downloaded`. That retry works because a
duplicate is imported again for the album friend, from its placed copy if that still exists and otherwise
from the re-downloaded file. Ledger entries from
before the tool tracked shares count as already shared with everyone. Adding a friend to such a date on the
review page starts tracking them, so the next organize shares the re-downloaded copies with that friend.

## What gets deleted and when

Every file in `~/Downloads` ends up in exactly one of seven outcomes. `organize` writes one line per file
to `organizer.log`; ignored, friend-only and left-alone files carry their reason. `organize --dry-run`
prints the same lines, prefixed "Would", and writes nothing.

| Outcome | Reason | What happens in a move run |
| --- | --- | --- |
| Placed for you | date source (exif, container, paired, neighbours, filename) | Moved into its day folder under `destination` (`<date> - <park>/` in the default layout), and recorded in the ledger |
| Duplicate | same content previously processed | Deleted from the source folder. Any friends still missing a copy get one first |
| Stock art | Disney stock art | Deleted when `stock_art = "delete"`, moved to `_Stock art` when `"keep"` |
| Ignored photo | ignored photo | Deleted. Set by a `[[photo]]` entry with `action = "ignore"` |
| Ignored day | ignored day | Deleted. Set by a `[[trip]]` entry with `ignore = true` |
| Friend-only | friend's trip, not mine | Copied to each friend, then deleted because `i_was_there = false` |
| Left alone | undecided, outside --trip, or no creation time in the MP4 header | Stays in the source folder |

The checks run in that order: stock art first, then an ignored photo, then duplicates, and only then the
rule for the day. So stock art and duplicates are removed on an undecided day too; only new photos wait
for your decision.

A file is a duplicate when its content hash is already in the ledger or in your destination folder, when it
was placed earlier in the same run, or when its fingerprint matches a file in any folder friend's sharing
folder. The ledger remembers every hash that was placed, shared or deleted, so a photo you imported into
Photos and purged from disk is still recognised when you download it again next year.

Stock art is detected when a JPEG carries an embedded ICC profile, or when its EXIF date is more than two
days away from the file-name date. A `[[photo]]` entry with `action = "keep"` exempts a photo from the check.

Nothing is deleted until its shares and its move have all succeeded; if copying to a friend fails, the
copies already made for that photo are removed, the original stays in the source folder and the run
stops there. After a run the tool removes the batch folders it emptied. `--copy` makes the same decisions
and still files copies and updates the ledger, but leaves the source folder untouched.

To recover from a mistaken ignore, or from a friend-only decision you later change to yours, downloading
the photo again is not enough, because its hash is in the ledger and the new copy is deleted as a duplicate.
Remove that photo's hash from `ledger.json` (see [State files](reference.md#state-files)) and download
it again; it is then handled as new under the current rules. If `photopass.toml` still has a `[[photo]]`
entry with `action = "ignore"` for that hash, or an `ignore = true` rule for its day, remove that too, or
the photo is deleted again. The how-to has the
[steps](how-to.md#get-back-a-photo-that-was-deleted-by-mistake).

## Special events

Photos from a ticketed event arrive with a park such as `Special Events at DCA` and the event in the
location part of the name, for example `Oogie boogie bash  a disney halloween party`. They get their own
day on the review page and their own folder, named for the event: `2026-09-20 - Oogie Boogie Bash`. The
event takes the timezone of its host park. In `photopass.toml` its rules still use Disney's label, so
`parks = ["Special Events at DCA"]`.

## The review page

The review page is served only on `127.0.0.1`, on a free port (or the one from `--port`), under a random
secret path, so other machines and other local web pages cannot reach it. Choices save by themselves a
moment after you make them. Every save that changes the file keeps the previous configuration as
`photopass.toml.bak`. A friend you add on the page is written to the file only once a day selects them.
The "Organize" buttons run the same steps as `photopass-organizer organize`, including the Photos import.

Photos that are in the ledger, in your destination folder or in a friend's sharing folder are hidden on
the page, because they are removed as duplicates when you organize. "Show previously processed" lists them.

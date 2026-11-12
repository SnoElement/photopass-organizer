# How to use photopass-organizer

These instructions tell you how to install the tool, set it up and use it. To learn why the tool does
what it does, read [How photopass-organizer works](how-it-works.md). For the full list of settings and
commands, read the [Reference](reference.md).

## Install

Use one of these three commands. Each command installs the tool from its GitHub repository.

With [uv](https://docs.astral.sh/uv/):

```sh
uv tool install git+https://github.com/SnoElement/photopass-organizer
```

With [pipx](https://pipx.pypa.io/):

```sh
pipx install git+https://github.com/SnoElement/photopass-organizer
```

With [Homebrew](https://brew.sh/):

```sh
brew install snoelement/tap/photopass-organizer
```

The `uv` and `pipx` commands need `git` and Python 3.12 or newer. Homebrew installs Python for you. The
tool needs two other packages, Pillow and tomli-w. Each install command gets them for you.

To install one version, add its tag to the address. An example is
`git+https://github.com/SnoElement/photopass-organizer@v1.0.0`. Each version also has a wheel file on the
[releases page](https://github.com/SnoElement/photopass-organizer/releases). `uv tool install` and
`pipx install` accept the address of that file.

## First run

1. Write a starter configuration. The configuration is a text file that holds your settings.

   ```sh
   photopass-organizer init
   ```

   The command creates `~/.config/photopass-organizer/photopass.toml`. If the file is already there, the
   command does not replace it.
2. Open `photopass.toml` in a text editor.
3. Check each setting in the list below.
4. Change the settings that are not correct for you.
5. Save the file.

On macOS the starter file looks like this:

```toml
[settings]
source = "~/Downloads"
destination = "~/Pictures/PhotoPass"
default_timezone = "America/New_York"
stock_art = "delete"
shared_root = "~/Library/Mobile Documents/com~apple~CloudDocs/Shared Photos"
import_to_photos = true
photos_folder = "PhotoPass"
purge_after_import = true
layout = "flat"
```

The settings to check:

- `source` is the folder that the tool reads. Set it to the folder where your browser saves PhotoPass
  downloads. The default is `~/Downloads`, and these instructions use that name.
- `destination` is the folder for your own photos. The tool makes one folder for each day and park there.
- `layout` sets the names of those folders. It is `flat`, `date/park` or `park/date`.
  - `flat` makes `<YYYY-MM-DD> - <Park>`. This is the default.
  - `date/park` makes `<YYYY-MM-DD>/<Park>`.
  - `park/date` makes `<Park>/<YYYY-MM-DD>`.
  - When you change `layout`, the tool does not move the folders that are already there.
  - Photos from a ticketed event use the name of the event, not the park. An example is
    `2026-09-20 - Oogie Boogie Bash`.
- `stock_art` is `delete` or `keep`. Stock art is a picture that Disney made, not a photo of you. `delete`
  removes it. `keep` moves it to `<destination>/_Stock art`.
- `shared_root` is the folder that holds your friends' sharing folders. A sharing folder is a folder that a
  sync service, such as iCloud Drive, shares with one friend. Linux has no default for this setting. On
  Linux, give each friend a `path` (see "Share photos with a friend").
- `import_to_photos` is `true` on macOS and `false` on other systems. When it is `true`, the tool imports
  each finished day into an album in the Photos app.
  - The first run can stop at a permission dialog from Photos. Approve it. The run then continues.
  - The tool imports only the files that it placed in that run. It also imports an older file when you
    share it for the first time with a friend who uses a Photos album.
- `purge_after_import` is `true` or `false`. When it is `true`, the tool deletes the local day folder after
  the import.
  - The tool deletes a folder only when it imported every file in that folder in the same run, and Photos
    confirmed each file.
  - A folder that still holds older files stays on disk.
- `default_timezone` is the timezone for a park that the tool does not know. The tool knows the Disneyland
  and Walt Disney World parks. To add other parks, see "Add a park that the tool does not know".

## The routine

Do these steps each time you have new photos.

1. Download your photos from PhotoPass into `~/Downloads`. You can use "Select all visible media". The
   tool removes the photos that it dealt with before.
   If your browser saves the download as a zip file with a long ID as its name, leave it there. The tool
   unpacks the zip file and then deletes it.
2. Start the review page:

   ```sh
   photopass-organizer review
   ```

   The page opens in your browser. It shows each new photo. The photos are in groups, by trip and by day.
   The page opens when there are no new photos too.
3. Make a choice for each day. Each day has a list of choices. A day starts as "Undecided". The tool does
   not touch an undecided day.
   - "I was there with friends": you keep the photos, and your friends get copies.
   - "I was there solo": you keep the photos.
   - "I was not there": your friends get copies, and the tool deletes your copy.
   - "Ignore date": the tool deletes the photos.
4. If friends get copies, select those friends for that day. The page shows the friends only for the two
   choices that share photos. If you select "I was not there" and no friend, the day stays undecided.
5. If a friend is not in the list, click "+ new friend". Enter the friend's name. Select "Shared folder"
   or "Photos album". Enter the folder path or the album name. Then click "Add".
   The tool writes a new friend to `photopass.toml` only when a day selects that friend. If no day selects
   the friend, "Done" asks you to confirm before it stops.
6. Click a photo to see it larger. Click the large photo, or press Esc, to close it. The arrow keys show
   the next photo and the photo before.
7. To ignore one photo, press `x` in the large view. You can also click the `x` on the small picture.
8. Go to the "Stock art" section at the bottom of the page. It lists the photos that the tool marked as
   stock art. If a photo there is a real photo, click its "Keep" button.
9. Look at the status line. The page saves each choice a moment after you make it. The status line then
   shows "Saved".
10. Click "Organize this trip" on one trip. To do all trips, click "Organize all decided days" at the top
    of the page. The browser shows a summary and asks you to confirm. Click "OK". The tool then moves,
    shares, deletes and imports the photos of the days that have a choice.
    Undecided days stay in `~/Downloads` for the next time.
11. Click "Done" to stop the review page. You can also press Ctrl-C in the terminal.

The page hides the photos that you kept, shared or deleted before. A day that has only such photos is
hidden too. Click "Show previously processed" to see them.

The bar at the side of the page shows totals: what the tool will do, the new photos for each park or
event, and the number of photos and videos. Click a total to see only those photos. Click it again, or
click "Show everything", to see all photos. The list of trips below the totals takes you to a trip.

To change a setting, click "Settings". Change the values, then click "Save settings". The page saves them
to `photopass.toml` and loads the photos again. If a value is not correct, the page tells you and saves
nothing.

Two options change how the review page starts:

- `--no-open` prints the page address. The tool then does not open a browser.
- `--port PORT` sets the port. A port is the number at the end of the address. Without this option, the
  tool selects a free port.

## Work without the review page

1. Write the rules in `photopass.toml`. The [Reference](reference.md#configuration-reference) lists
   each rule.
2. Show the plan. This command changes nothing:

   ```sh
   photopass-organizer organize --dry-run
   ```

3. Apply the plan:

   ```sh
   photopass-organizer organize
   ```

`organize --copy` copies the files and does not change the source folder. `organize --trip` does only the
days that you give. The [Reference](reference.md#command-reference) lists each option.

## Share photos with a friend

The tool can give a friend copies in two ways. Select one way for each friend.

### Use a synced folder

A synced folder is a folder that a sync service keeps the same on your computer and on your friend's
computer. iCloud Drive, Dropbox, OneDrive and Google Drive are sync services.

1. Make a folder for the friend in your sync service.
2. Share that folder with your friend. Use the sharing feature of the sync service. You do this only one
   time.
3. Add the friend to `photopass.toml`:

   ```toml
   [friends.Alex]
   share = "folder"
   path = "~/Library/Mobile Documents/com~apple~CloudDocs/Shared Photos/Alex"
   ```

   You can also add the friend on the review page. Click "+ new friend" and select "Shared folder".

After that, the tool copies the friend's photos into the folder. The sync service sends them to your friend.

If you do not add a `[friends.<name>]` table, the tool uses the folder `<shared_root>/<name>`.

A synced folder is usually in one of these locations:

| Service | Usual path |
| --- | --- |
| iCloud Drive | `~/Library/Mobile Documents/com~apple~CloudDocs/<folder>` |
| Dropbox | `~/Dropbox/<folder>` |
| OneDrive | `~/Library/CloudStorage/OneDrive-Personal/<folder>` |
| Google Drive | `~/Library/CloudStorage/GoogleDrive-<account>/My Drive/<folder>` |

After your first run, look for a warning about files of size 0 in a sharing folder. That warning means
the tool cannot recognise the photos that are already in the folder. The tool then shares those photos
again. See [How sharing avoids duplicates](how-it-works.md#how-sharing-avoids-duplicates).

### Use a Photos album

This way works only on macOS.

1. Add the friend to `photopass.toml`:

   ```toml
   [friends.Alex]
   share = "photos-album"
   album = "Alex"
   ```

   You can also add the friend on the review page. Click "+ new friend" and select "Photos album".
   If you do not set `album`, the tool uses the friend's name.
2. Do "The routine". The tool makes the album `Shared/<album>` in Photos. `Shared` is a folder in Photos.
   The tool makes it when it is necessary.
3. Open the Photos app.
4. Share the album `Shared/<album>` with your friend. You do this only one time.

After that, the tool adds the friend's photos to the album in each run. You do not move photos by hand.

### Add a friend to a day that is already done

1. Download the photos of that day again.
2. Start the review page and click "Show previously processed".
3. Select the new friend for that day.
4. Click "Organize this trip".

The tool gives the new friend a copy of each photo of that day. A friend who has a photo does not get it
again.

## Get back a photo that was deleted by mistake

The ledger is the file where the tool records each photo that it dealt with. If you download a deleted
photo again, the tool finds it in the ledger and deletes it again. Remove the photo from the ledger first.

1. Open `ledger.json` in a text editor. The file is in `~/.config/photopass-organizer`, next to
   `photopass.toml`.
2. Find the entry for the photo. Each entry starts with the hash of the photo. A hash is a long code that
   the tool calculates from the contents of the file.
3. Delete that entry.
4. Save the file.
5. Open `photopass.toml`. If it has a `[[photo]]` entry with `action = "ignore"` and the same hash, delete
   that entry too. If you do not, the tool deletes the photo again.
6. Download the photo from PhotoPass again.
7. Do "The routine" again. The tool now handles the photo as a new photo.

Do the same steps when you change a day from "I was not there" to one of the "I was there" choices.

## Add a park that the tool does not know

The tool shows a warning when it finds a park name that it does not know. It then uses
`default_timezone` for that park. If that timezone is wrong, add the park.

1. Open `photopass.toml` in a text editor.
2. Add a `[parks]` table. Write the park name the same as it is in the file name. Then write the timezone:

   ```toml
   [parks]
   "Tokyo Disneyland" = "Asia/Tokyo"
   ```

3. Save the file.

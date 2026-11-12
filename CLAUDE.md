# Working on photopass-organizer

Orientation for anyone changing this code, with or without an AI assistant. For what the tool does, read
[README.md](README.md). For how it decides things, read [docs/how-it-works.md](docs/how-it-works.md). For
every setting and command, read [docs/reference.md](docs/reference.md).

## Commands

```sh
uv sync                        # install the tool and the dev dependencies
uv run pytest -q -W error      # the test suite, warnings as errors
uv run ruff check .            # lint
uv run ruff format .           # format (CI runs it with --check)
```

CI runs the tests and both ruff checks on macOS and Linux with Python 3.12 and 3.13, on every push.

To try a change by hand, use a scratch state directory so your own photos and settings are not touched:

```sh
uv run photopass-organizer init --state-dir /tmp/pp-state
# edit /tmp/pp-state/photopass.toml: point source and destination at scratch folders,
# and set import_to_photos = false
uv run photopass-organizer review --state-dir /tmp/pp-state
```

`write_jpeg` and `write_mp4` in `tests/conftest.py` make small files with the EXIF and MP4 metadata the
tool reads.

## Do not

- Do not run `review` or `organize` without `--state-dir` while experimenting. Without it they use the
  real configuration, and a move run deletes files from the source folder.
- Do not read the contents of files in a friend's sharing folder. Cloud services evict them, and reading
  one downloads it. Match by name and size, as `shared.py` does.
- Do not put real names, home paths or host names in code, tests or docs. Use Alex, Sam and Jordan.
  `tests/test_scrub.py` checks tracked files against a private list when one exists.

## Map of the code

Everything is in `src/photopass_organizer/`.

| File | What it holds |
| --- | --- |
| `cli.py` | The four commands (`init`, `review`, `organize`, `import-photos`) and their output |
| `config.py` | `photopass.toml`: parsing, validation, defaults and writing it back |
| `media.py` | File-name parsing, EXIF and MP4 times, park timezones, event names, fingerprints, hashing |
| `archives.py` | Unpacking UUID-named zip files of PhotoPass files |
| `organizer.py` | Discover files, date them, plan one action for each file, carry the plan out |
| `ledger.py` | `ledger.json`: every content hash already placed, shared or deleted |
| `shared.py` | Index of the friends' sharing folders, by fingerprint |
| `photos.py` | Photos.app import and friend albums, through `osascript` |
| `review.py` | Pure functions behind the review page: the state it shows, the rules it writes |
| `review_server.py` | The local HTTP server: state, thumbnails, media, save, settings, organize |
| `review_page.py` | The review page: one HTML document with its CSS and JavaScript in a Python string |

The flow of a run is `Organizer.plan()` then `Organizer.execute(plan)`, then `sync_photos` on macOS. The
review page calls the same code; it has no logic of its own for filing or sharing.

## Things the code relies on

- The date in a PhotoPass file name is UTC. The real day comes from EXIF, or from the MP4 header and the
  park's timezone.
- Disney renumbers the `_N` suffix on every download, so the same photo arrives under different names. A
  duplicate is found by content hash, never by name.
- The ledger is what makes a re-download recognisable after the local copy is gone. A change that stops
  recording a hash makes old photos look new.
- An entry in the ledger without a `shared_with` list predates share tracking and counts as shared with
  everyone.
- Nothing is deleted until its copies and its move have succeeded. Keep that order when you change
  `execute`.

## Conventions

- Code, comments and terminal output are ASCII. The review page must be ASCII too; a test checks it.
- The page script lives in a raw Python string. A test runs `node --check` on it when Node is installed,
  so a syntax error in the JavaScript fails the suite.
- Build page content with `textContent` and DOM calls, never `innerHTML`. File names and friend names
  come from outside.
- Terminal lines start with `INFO:`, `SUCCESS:`, `WARNING:` or `ERROR:`. Use `WARNING` only for something
  the user should act on.
- A test that adds a `photos-album` friend must force the macOS check on, as the tests in
  `tests/test_review_server.py` do, or it fails on the Linux runners.
- A new setting needs five things: the `Settings` field, the parser, the writer, the Settings form in
  `review_page.py`, and a row in [docs/reference.md](docs/reference.md).
- [docs/how-to.md](docs/how-to.md) uses short sentences with one action in each step. Keep that style
  when you add to it.
- Add a line to `CHANGELOG.md` for a change a user can see, and update the doc that describes the
  behaviour in the same change.

## Releases

A tag `v*` runs `.github/workflows/release.yml`, which tests, builds and attaches the wheel and sdist to
a GitHub Release. The version is the `version` field in `pyproject.toml`.

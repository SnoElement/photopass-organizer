# Contributing

Bug reports and pull requests are welcome.

## Setup

Clone the repository and install the dependencies with uv:

    git clone https://github.com/SnoElement/photopass-organizer.git
    cd photopass-organizer
    uv sync

[CLAUDE.md](CLAUDE.md) has a map of the code and the rules that are easy to break.

## Checks

Run these before opening a pull request. CI runs the same checks on macOS and Linux with Python 3.12 and 3.13.

    uv run pytest
    uv run ruff check .
    uv run ruff format .

## Conventions

- Code, comments and terminal output stay ASCII.
- Every terminal line starts with a prefix: `INFO:`, `SUCCESS:`, `WARNING:` or `ERROR:`.
- Tests and docs use invented names (Alex, Sam, Jordan) and no real names, home paths or host names.
- Add a line to `CHANGELOG.md` for any user-visible change.

## Pull requests

Make your change on a branch, push it to your fork and open a pull request against `main`. Describe what changed and why, and include a test for new behaviour.

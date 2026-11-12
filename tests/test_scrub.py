import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
NAMES_FILE = (
    Path(
        os.environ.get("PHOTOPASS_ORGANIZER_HOME", "~/.config/photopass-organizer")
    ).expanduser()
    / "private-names.txt"
)
EXCLUDED_PREFIX = "docs/superpowers/"
# Split so this file does not contain the marker it scans for.
HOME_PATH_MARKER = "/" + "Users" + "/"


def _tracked_files() -> list[str]:
    listing = subprocess.run(
        ["git", "ls-files"],
        check=True,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    return [
        name
        for name in listing.stdout.splitlines()
        if not name.startswith(EXCLUDED_PREFIX)
    ]


def test_tracked_files_hold_no_private_names_or_home_paths() -> None:
    if not NAMES_FILE.is_file():
        pytest.skip(f"no private names list at {NAMES_FILE}")
    names = [
        line.strip()
        for line in NAMES_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    patterns = [re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE) for name in names]
    offenders: list[str] = []
    for relative in _tracked_files():
        try:
            text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            for index, pattern in enumerate(patterns):
                if pattern.search(line):
                    offenders.append(f"{relative}:{number} (name #{index + 1})")
            if HOME_PATH_MARKER in line:
                offenders.append(f"{relative}:{number} (home path)")
    assert not offenders, "private names or home paths found:\n" + "\n".join(offenders)

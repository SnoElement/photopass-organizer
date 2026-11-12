import re
import shutil
import subprocess

import pytest

from photopass_organizer.review_page import render_page


def test_page_contains_token_and_api_paths():
    page = render_page("abc")
    for path in (
        "/abc/api/state",
        "/abc/thumb/",
        "/abc/api/save",
        "/abc/api/run",
        "/abc/api/done",
    ):
        assert path in page
    assert "__TOKEN__" not in page


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_page_script_parses(tmp_path):
    scripts = re.findall(r"<script>(.*?)</script>", render_page("abc"), re.DOTALL)
    assert len(scripts) == 1
    script = tmp_path / "page.js"
    script.write_text(scripts[0], encoding="utf-8")
    result = subprocess.run(
        ["node", "--check", str(script)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_page_is_ascii():
    assert render_page("abc").isascii()


def _format_summary(tmp_path, summary, photos):
    page = render_page("abc")
    script = re.findall(r"<script>(.*?)</script>", page, re.DOTALL)[0]
    start = script.index("function formatSummary")
    end = script.index("async function runDecided")
    harness = tmp_path / "format.js"
    harness.write_text(
        "const NEWLINE = String.fromCharCode(10);\n"
        + script[start:end]
        + f"\nconsole.log(formatSummary({summary}, {photos}));\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["node", str(harness)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


SUMMARY = (
    "{placed: 2, shared: 1, deleted: 0, duplicates: 0, stock: 0, ignored: 0,"
    " undecided: 0}"
)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_summary_shows_photos_counts_and_unconfirmed_friend_albums(tmp_path):
    photos = (
        "{imported: 2, purged: 1, added_to_friend_albums: 3, friend_imports: 4,"
        " added_by_friend: {}, failed_by_friend: {Sam: 2}}"
    )
    text = _format_summary(tmp_path, SUMMARY, photos)
    assert (
        "Photos: imported 2, purged 1, added to friend albums 3, friend imports 4"
        in text
    )
    assert (
        "Photos could not add 2 photos for Sam; they are retried the next time that photo is downloaded"
        in text
    )
    quiet = _format_summary(
        tmp_path,
        SUMMARY,
        "{imported: 0, purged: 0, added_to_friend_albums: 0, friend_imports: 0,"
        " added_by_friend: {}, failed_by_friend: {}}",
    )
    assert "could not add" not in quiet


def test_done_button_is_disabled_while_a_run_is_busy():
    page = render_page("abc")
    assert "doneButton.disabled = on;" in page


def test_done_warns_about_new_friends_no_day_selects():
    page = render_page("abc")
    assert "not selected on any day and will not be saved. Finish anyway?" in page
    assert "unsaved_friends" in page

import json
from pathlib import Path

from photopass_organizer.ledger import Ledger


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_missing_ledger_is_empty(tmp_path):
    assert "x" not in Ledger.load(tmp_path / "ledger.json")


def test_record_and_reload(tmp_path):
    path = tmp_path / "nested" / "ledger.json"
    ledger = Ledger.load(path)
    ledger.record_placed("aaa", tmp_path / "Park" / "one.jpg")
    ledger.record_deleted("bbb", "stock art")
    ledger.record_shared("aaa", "Alex")
    ledger.record_shared("ccc", "Alex")
    ledger.save()

    reloaded = Ledger.load(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["aaa"]["path"] == str(tmp_path / "Park" / "one.jpg")
    assert "placed_at" in raw["aaa"]
    assert raw["bbb"]["path"] == ""
    assert raw["bbb"]["reason"] == "stock art"
    assert "handled_at" in raw["bbb"]
    assert raw["ccc"]["path"] == ""
    assert "handled_at" in raw["ccc"]
    assert reloaded.path_for("aaa") == str(tmp_path / "Park" / "one.jpg")
    assert reloaded.path_for("bbb") == "already handled"
    assert reloaded.shared_with("aaa") == {"Alex"}
    assert reloaded.shared_with("bbb") == set()
    assert reloaded.shared_with("ccc") == {"Alex"}
    assert "aaa" in reloaded and "zzz" not in reloaded
    assert path.read_text(encoding="utf-8").startswith('{\n "aaa"')
    assert [p.name for p in path.parent.iterdir()] == ["ledger.json"]


def test_legacy_entry_without_shared_with_is_complete(tmp_path):
    path = tmp_path / "ledger.json"
    _write(
        path, {"old": {"path": "/x/y.jpg", "placed_at": "2026-01-01T00:00:00+00:00"}}
    )
    ledger = Ledger.load(path)
    assert ledger.is_complete("old")
    assert ledger.shared_with("old") == set()
    assert not ledger.is_complete("missing")


def test_entry_with_shared_with_is_not_complete(tmp_path):
    ledger = Ledger.load(tmp_path / "ledger.json")
    ledger.record_shared("h", "Jordan")
    assert not ledger.is_complete("h")


def test_record_shared_backfills_key(tmp_path):
    path = tmp_path / "ledger.json"
    _write(
        path, {"old": {"path": "/x/y.jpg", "placed_at": "2026-01-01T00:00:00+00:00"}}
    )
    ledger = Ledger.load(path)
    ledger.record_shared("old", "Sam")
    ledger.save()
    reloaded = Ledger.load(path)
    assert reloaded.shared_with("old") == {"Sam"}
    assert reloaded.path_for("old") == "/x/y.jpg"


def test_record_shared_is_sorted_and_unique(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = Ledger.load(path)
    for friend in ("Sam", "Alex", "Sam"):
        ledger.record_shared("h", friend)
    ledger.save()
    assert json.loads(path.read_text(encoding="utf-8"))["h"]["shared_with"] == [
        "Alex",
        "Sam",
    ]


def test_placing_or_deleting_keeps_the_friends_already_shared_with(tmp_path):
    ledger = Ledger.load(tmp_path / "ledger.json")
    ledger.record_shared("placed", "Alex")
    ledger.record_placed("placed", tmp_path / "one.jpg")
    ledger.record_shared("deleted", "Sam")
    ledger.record_deleted("deleted", "ignored day")
    assert ledger.shared_with("placed") == {"Alex"}
    assert ledger.path_for("placed") == str(tmp_path / "one.jpg")
    assert ledger.shared_with("deleted") == {"Sam"}
    assert ledger.path_for("deleted") == "already handled"


def test_new_placed_and_deleted_entries_start_with_an_empty_shared_with(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = Ledger.load(path)
    ledger.record_placed("placed", tmp_path / "one.jpg")
    ledger.record_deleted("deleted", "ignored day")
    ledger.save()
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["placed"]["shared_with"] == []
    assert raw["deleted"]["shared_with"] == []
    assert not ledger.is_complete("placed")
    assert not ledger.is_complete("deleted")


def test_replacing_a_legacy_entry_keeps_it_complete(tmp_path):
    path = tmp_path / "ledger.json"
    _write(path, {"old": {"path": "", "handled_at": "2026-01-01T00:00:00+00:00"}})
    ledger = Ledger.load(path)
    ledger.record_placed("old", tmp_path / "one.jpg")
    assert ledger.is_complete("old")
    ledger.record_deleted("old", "ignored day")
    assert ledger.is_complete("old")


def test_reopen_for_sharing_turns_a_legacy_entry_into_a_tracked_one(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text(
        '{"old": {"path": ""}, "new": {"path": "", "shared_with": ["Sam"]}}'
    )
    ledger = Ledger.load(path)
    assert ledger.reopen_for_sharing("old", ["Riley", "Alex"]) is True
    assert ledger.shared_with("old") == {"Alex", "Riley"}
    assert not ledger.is_complete("old")
    assert ledger.reopen_for_sharing("new", ["Alex"]) is False
    assert ledger.shared_with("new") == {"Sam"}
    assert ledger.reopen_for_sharing("missing", ["Alex"]) is False

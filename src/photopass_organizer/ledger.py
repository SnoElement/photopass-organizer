from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

ALREADY_HANDLED = "already handled"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Ledger:
    def __init__(self, path: Path, entries: dict[str, dict]) -> None:
        self._path = path
        self._entries = entries

    @classmethod
    def load(cls, path: Path) -> Ledger:
        if not path.is_file():
            return cls(path, {})
        with path.open("r", encoding="utf-8") as handle:
            return cls(path, json.load(handle))

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(
            dir=self._path.parent, prefix=f".{self._path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(self._entries, handle, indent=1, sort_keys=True)
            os.replace(temp_name, self._path)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise

    def __contains__(self, content_hash: str) -> bool:
        return content_hash in self._entries

    def path_for(self, content_hash: str) -> str:
        return self._entries[content_hash]["path"] or ALREADY_HANDLED

    def shared_with(self, content_hash: str) -> set[str]:
        return set(self._entries.get(content_hash, {}).get("shared_with", ()))

    def is_complete(self, content_hash: str) -> bool:
        entry = self._entries.get(content_hash)
        return entry is not None and "shared_with" not in entry

    def reopen_for_sharing(self, content_hash: str, already: Iterable[str]) -> bool:
        """Start tracking shares for a legacy entry, given the friends who already have it.

        A legacy entry counts as shared with everyone; this makes a friend added later get a copy.
        """
        entry = self._entries.get(content_hash)
        if entry is None or "shared_with" in entry:
            return False
        entry["shared_with"] = sorted(set(already))
        return True

    def _replace(self, content_hash: str, entry: dict) -> None:
        existing = self._entries.get(content_hash)
        if existing is None:
            entry["shared_with"] = []
        elif "shared_with" in existing:
            entry["shared_with"] = existing["shared_with"]
        self._entries[content_hash] = entry

    def record_placed(self, content_hash: str, target: Path) -> None:
        self._replace(content_hash, {"path": str(target), "placed_at": _now()})

    def record_deleted(self, content_hash: str, reason: str) -> None:
        self._replace(
            content_hash, {"path": "", "handled_at": _now(), "reason": reason}
        )

    def record_shared(self, content_hash: str, friend: str) -> None:
        entry = self._entries.setdefault(
            content_hash, {"path": "", "handled_at": _now()}
        )
        entry["shared_with"] = sorted({*entry.get("shared_with", ()), friend})

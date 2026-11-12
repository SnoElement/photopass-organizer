"""Index of the friends' sharing folders, keyed without reading file contents."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .media import fingerprint

log = logging.getLogger(__name__)


@dataclass
class SharedFolderIndex:
    folders: dict[str, Path] = field(default_factory=dict)
    friends: list[str] = field(default_factory=list)
    friends_by_fingerprint: dict[tuple, set[str]] = field(
        default_factory=lambda: defaultdict(set)
    )
    file_count: int = 0
    zero_size_files: dict[str, int] = field(default_factory=dict)

    @classmethod
    def load(cls, folders_by_friend: dict[str, Path]) -> SharedFolderIndex:
        index = cls(folders=dict(folders_by_friend))
        for friend, folder in folders_by_friend.items():
            index.friends.append(friend)
            if not folder.is_dir():
                continue
            zero_size = 0
            for shared_file in folder.iterdir():
                if shared_file.name.startswith(".") or not shared_file.is_file():
                    continue
                index.file_count += 1
                size_bytes = shared_file.stat().st_size
                if size_bytes == 0:
                    zero_size += 1
                    continue
                key = fingerprint(shared_file.name, size_bytes)
                if key is not None:
                    index.friends_by_fingerprint[key].add(friend)
            if zero_size:
                index.zero_size_files[friend] = zero_size
                log.warning(
                    "%d files in sharing folder %s report size 0 and cannot be matched",
                    zero_size,
                    folder,
                )
        return index

    def friends_holding(self, name: str, size_bytes: int) -> set[str]:
        key = fingerprint(name, size_bytes)
        if key is None:
            return set()
        return set(self.friends_by_fingerprint.get(key, ()))

    def folder_for(self, friend: str) -> Path:
        return self.folders[friend]

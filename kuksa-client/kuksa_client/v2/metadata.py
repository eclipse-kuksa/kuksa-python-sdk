# /********************************************************************************
# * Copyright (c) 2026 Contributors to the Eclipse Foundation
# *
# * See the NOTICE file(s) distributed with this work for additional
# * information regarding copyright ownership.
# *
# * This program and the accompanying materials are made available under the
# * terms of the Apache License 2.0 which is available at
# * http://www.apache.org/licenses/LICENSE-2.0
# *
# * SPDX-License-Identifier: Apache-2.0
# ********************************************************************************/

"""
In-memory metadata cache bound to a connection.

The cache maps signal paths to their ``id``, ``data_type`` and ``entry_type``
(and the full :class:`Metadata`). It caches both positively (known signals) and
negatively (paths known not to exist) and is cleared on reconnect.

No TTL is used: VSS metadata is assumed static while a system is running.
"""

from __future__ import annotations

from typing import Dict
from typing import Iterable
from typing import Optional
from typing import Set

from .types import DataType
from .types import EntryType
from .types import Metadata


class MetadataStore:
    def __init__(self):
        self._metadata: Dict[str, Metadata] = {}
        self._missing: Set[str] = set()
        self._id_to_path: Dict[int, str] = {}

    def invalidate(self) -> None:
        """Clear all cached metadata (e.g. on reconnect)."""
        self._metadata.clear()
        self._missing.clear()
        self._id_to_path.clear()

    def has(self, path: str) -> bool:
        return path in self._metadata

    def is_missing(self, path: str) -> bool:
        return path in self._missing

    def get(self, path: str) -> Optional[Metadata]:
        return self._metadata.get(path)

    def add(self, metadata: Metadata) -> None:
        if metadata.path is not None:
            self._metadata[metadata.path] = metadata
            self._missing.discard(metadata.path)
            if metadata.id is not None:
                self._id_to_path[metadata.id] = metadata.path

    def add_many(self, metadatas: Iterable[Metadata]) -> None:
        for metadata in metadatas:
            self.add(metadata)

    def mark_missing(self, path: str) -> None:
        self._missing.add(path)
        self._metadata.pop(path, None)

    def data_type(self, path: str) -> Optional[DataType]:
        metadata = self._metadata.get(path)
        return metadata.data_type if metadata is not None else None

    def entry_type(self, path: str) -> Optional[EntryType]:
        metadata = self._metadata.get(path)
        return metadata.entry_type if metadata is not None else None

    def signal_id(self, path: str) -> Optional[int]:
        metadata = self._metadata.get(path)
        return metadata.id if metadata is not None else None

    def path_for_id(self, signal_id: int) -> Optional[str]:
        return self._id_to_path.get(signal_id)

    def paths(self) -> Iterable[str]:
        return self._metadata.keys()

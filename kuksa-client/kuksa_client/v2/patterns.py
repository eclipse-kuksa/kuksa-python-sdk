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
Client-side wildcard pattern matching.

This pins the databroker's wildcard semantics (see ``wildcard_matching.md`` in
the kuksa-databroker project) so that path expansion never depends on
server-side behaviour:

- ``*``  matches exactly one path segment,
- ``**`` matches zero or more path segments,
- both are valid anywhere in the pattern,
- a plain branch path (no wildcards) matches the branch and everything below it,
- ``**`` combined with consecutive ``*`` segments is not supported.
"""

from __future__ import annotations

import functools
from typing import Sequence
from typing import Tuple

_WILDCARD = "*"


def _is_unsupported(segments: Sequence[str]) -> bool:
    has_double_star = "**" in segments
    has_consecutive_star = any(
        a == "*" and b == "*" for a, b in zip(segments, segments[1:])
    )
    return has_double_star and has_consecutive_star


@functools.lru_cache(maxsize=None)
def _match(
    segments: Tuple[str, ...],
    seg_index: int,
    path: Tuple[str, ...],
    path_index: int,
) -> bool:
    if seg_index == len(segments):
        return path_index == len(path)

    segment = segments[seg_index]
    if segment == "**":
        # Match zero segments, or consume one path segment and stay on '**'.
        return _match(segments, seg_index + 1, path, path_index) or (
            path_index < len(path)
            and _match(segments, seg_index, path, path_index + 1)
        )

    if path_index >= len(path):
        return False

    if segment == "*":
        return _match(segments, seg_index + 1, path, path_index + 1)

    return segment == path[path_index] and _match(
        segments, seg_index + 1, path, path_index + 1
    )


class Matcher:
    """A compiled wildcard pattern."""

    __slots__ = ("segments", "literal", "match_all")

    def __init__(self, pattern: str):
        self.segments = tuple(pattern.split(".")) if pattern else ()
        self.literal = bool(self.segments) and not any(
            _WILDCARD in segment for segment in self.segments
        )
        self.match_all = pattern == ""

    def matches(self, path: str) -> bool:
        if self.match_all:
            return True
        if _is_unsupported(self.segments):
            raise ValueError(
                "Pattern combining '**' with consecutive '*' segments is not supported"
            )
        path_segments = tuple(path.split("."))
        if self.literal:
            pattern = ".".join(self.segments)
            return path == pattern or path.startswith(pattern + ".")
        return _match(self.segments, 0, path_segments, 0)


def compile_pattern(pattern: str) -> Matcher:
    """Compile a wildcard pattern into a reusable matcher."""
    return Matcher(pattern)


def matches(pattern: str, path: str) -> bool:
    """Return whether ``path`` (a concrete signal path) matches ``pattern``."""
    return compile_pattern(pattern).matches(path)


def literal_prefix(pattern: str) -> str:
    """
    Return the longest literal prefix of ``pattern`` (everything before the
    first wildcard), used to bound a ``ListMetadata(root=...)`` call.
    """
    if not pattern:
        return ""
    segments = []
    for segment in pattern.split("."):
        if _WILDCARD in segment:
            break
        segments.append(segment)
    return ".".join(segments)

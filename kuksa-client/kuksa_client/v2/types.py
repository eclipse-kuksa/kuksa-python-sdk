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

from __future__ import annotations

import dataclasses
import datetime
import enum
from typing import Any
from typing import List
from typing import Optional


class DataType(enum.IntEnum):
    """
    VSS data type of a signal.

    The enum values match ``kuksa.val.v2.DataType`` so that the codec can map
    between them without an explicit conversion table for the enum itself.

    ``TIMESTAMP`` and ``TIMESTAMP_ARRAY`` are intentionally absent: the v2
    ``Value`` oneof has no timestamp field, so these types cannot be
    represented as values.
    """

    UNSPECIFIED = 0
    STRING = 1
    BOOLEAN = 2
    INT8 = 3
    INT16 = 4
    INT32 = 5
    INT64 = 6
    UINT8 = 7
    UINT16 = 8
    UINT32 = 9
    UINT64 = 10
    FLOAT = 11
    DOUBLE = 12
    STRING_ARRAY = 20
    BOOLEAN_ARRAY = 21
    INT8_ARRAY = 22
    INT16_ARRAY = 23
    INT32_ARRAY = 24
    INT64_ARRAY = 25
    UINT8_ARRAY = 26
    UINT16_ARRAY = 27
    UINT32_ARRAY = 28
    UINT64_ARRAY = 29
    FLOAT_ARRAY = 30
    DOUBLE_ARRAY = 31


class EntryType(enum.IntEnum):
    UNSPECIFIED = 0
    ATTRIBUTE = 1
    SENSOR = 2
    ACTUATOR = 3


@dataclasses.dataclass
class Datapoint:
    """
    A timestamped value.

    ``value`` is a native Python value (int, float, str, bool, list, ...) or
    ``None`` if the signal exists but has no value yet.
    """

    value: Any = None
    timestamp: Optional[datetime.datetime] = None


@dataclasses.dataclass
class ValueRestriction:
    allowed_values: Optional[List[Any]] = None
    min: Optional[Any] = None
    max: Optional[Any] = None


@dataclasses.dataclass
class Metadata:
    """
    Read-only metadata of a signal, as returned by the databroker's
    ``ListMetadata`` RPC.
    """

    path: Optional[str] = None
    id: Optional[int] = None
    data_type: DataType = DataType.UNSPECIFIED
    entry_type: EntryType = EntryType.UNSPECIFIED
    description: Optional[str] = None
    comment: Optional[str] = None
    deprecation: Optional[str] = None
    unit: Optional[str] = None
    value_restriction: Optional[ValueRestriction] = None
    min_sample_interval: Optional[int] = None


@dataclasses.dataclass
class ServerInfo:
    name: str
    version: str
    commit_hash: Optional[str] = None

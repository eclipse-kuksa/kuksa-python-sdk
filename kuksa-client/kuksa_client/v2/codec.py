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
Single source of truth for converting between native Python values and the
``kuksa.val.v2`` protobuf ``Value`` / ``Datapoint`` messages.

This is the only place in the SDK that knows the ``DataType -> proto field``
mapping. It deliberately does no string casting; values are expected to already
be native Python values of the appropriate type.
"""

from __future__ import annotations

import datetime
from typing import Any
from typing import Dict
from typing import Tuple

from kuksa.val.v2 import types_pb2

from .types import DataType
from .types import Datapoint
from .types import EntryType
from .types import Metadata
from .types import ValueRestriction

# DataType -> (proto Value field name, python scalar type, is_array)
# Protobuf has no int8/int16/uint8/uint16, so those alias to int32/uint32.
_FIELD_MAP: Dict[DataType, Tuple[str, type, bool]] = {
    DataType.STRING: ("string", str, False),
    DataType.BOOLEAN: ("bool", bool, False),
    DataType.INT8: ("int32", int, False),
    DataType.INT16: ("int32", int, False),
    DataType.INT32: ("int32", int, False),
    DataType.INT64: ("int64", int, False),
    DataType.UINT8: ("uint32", int, False),
    DataType.UINT16: ("uint32", int, False),
    DataType.UINT32: ("uint32", int, False),
    DataType.UINT64: ("uint64", int, False),
    DataType.FLOAT: ("float", float, False),
    DataType.DOUBLE: ("double", float, False),
    DataType.STRING_ARRAY: ("string_array", str, True),
    DataType.BOOLEAN_ARRAY: ("bool_array", bool, True),
    DataType.INT8_ARRAY: ("int32_array", int, True),
    DataType.INT16_ARRAY: ("int32_array", int, True),
    DataType.INT32_ARRAY: ("int32_array", int, True),
    DataType.INT64_ARRAY: ("int64_array", int, True),
    DataType.UINT8_ARRAY: ("uint32_array", int, True),
    DataType.UINT16_ARRAY: ("uint32_array", int, True),
    DataType.UINT32_ARRAY: ("uint32_array", int, True),
    DataType.UINT64_ARRAY: ("uint64_array", int, True),
    DataType.FLOAT_ARRAY: ("float_array", float, True),
    DataType.DOUBLE_ARRAY: ("double_array", float, True),
}


def data_type_to_python_type(data_type: DataType) -> type:
    """Return the native Python type a ``DataType`` maps to."""
    try:
        _field, python_type, is_array = _FIELD_MAP[data_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported data type {data_type}") from exc
    if is_array:
        return list
    return python_type


def _validate_scalar(value: Any, python_type: type, data_type: DataType) -> Any:
    if python_type is bool:
        if not isinstance(value, bool):
            raise TypeError(
                f"Expected bool for {data_type.name}, got {type(value).__name__}"
            )
        return value
    if python_type is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(
                f"Expected int for {data_type.name}, got {type(value).__name__}"
            )
        return value
    if python_type is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(
                f"Expected int/float for {data_type.name}, got {type(value).__name__}"
            )
        return float(value)
    if python_type is str:
        if not isinstance(value, str):
            raise TypeError(
                f"Expected str for {data_type.name}, got {type(value).__name__}"
            )
        return value
    raise ValueError(f"Unsupported python type {python_type}")


def to_proto_value(value: Any, data_type: DataType) -> types_pb2.Value:
    """Encode a native Python value into a v2 ``Value`` message."""
    if value is None:
        return types_pb2.Value()
    if data_type == DataType.UNSPECIFIED:
        raise ValueError("Cannot encode a value with UNSPECIFIED data type")
    try:
        field, python_type, is_array = _FIELD_MAP[data_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported data type {data_type}") from exc

    message = types_pb2.Value()
    if is_array:
        if not isinstance(value, (list, tuple)):
            raise TypeError(
                f"Expected list/tuple for {data_type.name}, got {type(value).__name__}"
            )
        array = getattr(message, field)
        for item in value:
            array.values.append(_validate_scalar(item, python_type, data_type))
    else:
        setattr(message, field, _validate_scalar(value, python_type, data_type))
    return message


def from_proto_value(value: types_pb2.Value) -> Any:
    """Decode a v2 ``Value`` message into a native Python value.

    Returns ``None`` if no value is present.
    """
    field = value.WhichOneof("typed_value")
    if field is None:
        return None
    raw = getattr(value, field)
    if field.endswith("_array"):
        return list(raw.values)
    return raw


def to_proto_datapoint(
    datapoint: Datapoint, data_type: DataType
) -> types_pb2.Datapoint:
    """Encode a :class:`Datapoint` into a v2 ``Datapoint`` message."""
    message = types_pb2.Datapoint()
    if datapoint.value is not None:
        message.value.CopyFrom(to_proto_value(datapoint.value, data_type))
    if datapoint.timestamp is not None:
        message.timestamp.FromDatetime(datapoint.timestamp)
    return message


def from_proto_datapoint(message: types_pb2.Datapoint) -> Datapoint:
    """Decode a v2 ``Datapoint`` message into a :class:`Datapoint`."""
    value = from_proto_value(message.value)
    timestamp = None
    if message.HasField("timestamp") and (
        message.timestamp.seconds != 0 or message.timestamp.nanos != 0
    ):
        try:
            timestamp = message.timestamp.ToDatetime(
                tzinfo=datetime.timezone.utc
            )
        except ValueError:
            # Out-of-range timestamps (year > 9999) are not representable.
            timestamp = None
    return Datapoint(value=value, timestamp=timestamp)


def from_proto_metadata(message: types_pb2.Metadata) -> Metadata:
    """Decode a v2 ``Metadata`` message into :class:`Metadata`."""
    value_restriction = None
    allowed_values = None
    minimum = None
    maximum = None

    if message.HasField("allowed_values"):
        allowed_values = from_proto_value(message.allowed_values)
    if message.HasField("min"):
        minimum = from_proto_value(message.min)
    if message.HasField("max"):
        maximum = from_proto_value(message.max)
    if any(v is not None for v in (allowed_values, minimum, maximum)):
        value_restriction = ValueRestriction(
            allowed_values=allowed_values,
            min=minimum,
            max=maximum,
        )

    min_sample_interval = None
    if message.HasField("min_sample_interval"):
        min_sample_interval = message.min_sample_interval.interval_ms

    return Metadata(
        path=message.path or None,
        id=message.id or None,
        data_type=DataType(message.data_type),
        entry_type=EntryType(message.entry_type),
        description=message.description or None,
        comment=message.comment or None,
        deprecation=message.deprecation or None,
        unit=message.unit or None,
        value_restriction=value_restriction,
        min_sample_interval=min_sample_interval,
    )

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
Helpers for turning strings (e.g. from a CSV file, a config file or the CLI)
into the native Python values the :mod:`kuksa_client.v2` clients expect.

Unlike :mod:`kuksa_client.v2.codec`, which deliberately does no string casting,
this module exists exactly for the string-input boundary. Values that are
already native Python values are passed through unchanged.
"""

from __future__ import annotations

from typing import Any
from typing import Mapping

from .types import DataType

_BOOL_TRUE = {"true", "t", "1", "yes", "on"}
_BOOL_FALSE = {"false", "f", "0", "no", "off"}
_INT_TYPES = {
    DataType.INT8,
    DataType.INT16,
    DataType.INT32,
    DataType.INT64,
    DataType.UINT8,
    DataType.UINT16,
    DataType.UINT32,
    DataType.UINT64,
}
_FLOAT_TYPES = {DataType.FLOAT, DataType.DOUBLE}
_INT_ARRAYS = {
    DataType.INT8_ARRAY,
    DataType.INT16_ARRAY,
    DataType.INT32_ARRAY,
    DataType.INT64_ARRAY,
    DataType.UINT8_ARRAY,
    DataType.UINT16_ARRAY,
    DataType.UINT32_ARRAY,
    DataType.UINT64_ARRAY,
}
_FLOAT_ARRAYS = {DataType.FLOAT_ARRAY, DataType.DOUBLE_ARRAY}


def _coerce_bool(text: str) -> bool:
    lowered = text.strip().lower()
    if lowered in _BOOL_TRUE:
        return True
    if lowered in _BOOL_FALSE:
        return False
    raise ValueError(f"Invalid boolean value: {text}")


def _parse_array(text: str, data_type: DataType) -> list:
    stripped = text.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        stripped = stripped[1:-1]
    items = [item.strip() for item in stripped.split(",") if item.strip() != ""]
    if data_type == DataType.STRING_ARRAY:
        def cast(s):
            return s.strip("\"'")
    elif data_type == DataType.BOOLEAN_ARRAY:
        cast = _coerce_bool
    elif data_type in _INT_ARRAYS:
        cast = int
    elif data_type in _FLOAT_ARRAYS:
        cast = float
    else:
        cast = str
    return [cast(item) for item in items]


def coerce_value(value: Any, data_type: DataType) -> Any:
    """
    Coerce ``value`` into the native Python value for ``data_type``.

    Strings are parsed according to ``data_type`` (booleans accept
    ``true``/``false`` and friends, numbers use ``int``/``float``, arrays use a
    comma-separated / JSON-like ``[...]`` syntax). Non-string values are
    returned unchanged so this is safe to apply to mixed input.
    """
    if not isinstance(value, str):
        return value
    if data_type is None or data_type == DataType.UNSPECIFIED:
        return value
    if data_type == DataType.BOOLEAN:
        return _coerce_bool(value)
    if data_type in _FLOAT_TYPES:
        return float(value)
    if data_type in _INT_TYPES:
        return int(value)
    if data_type.name.endswith("_ARRAY"):
        return _parse_array(value, data_type)
    return value


def coerce_values(
    values: Mapping[str, Any], data_types: Mapping[str, DataType]
) -> dict:
    """
    Coerce a ``{path: value}`` mapping using each path's ``DataType``.

    Raises ``ValueError`` if a path has no known data type.
    """
    result = {}
    for path, value in values.items():
        data_type = data_types.get(path)
        if data_type is None:
            raise ValueError(f"No data type for path '{path}'")
        result[path] = coerce_value(value, data_type)
    return result

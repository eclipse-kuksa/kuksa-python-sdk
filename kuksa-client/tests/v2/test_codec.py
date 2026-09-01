# /********************************************************************************
# * Copyright (c) 2026 Contributors to the Eclipse Foundation
# *
# * SPDX-License-Identifier: Apache-2.0
# ********************************************************************************/

import datetime

import pytest

from kuksa_client.v2 import codec
from kuksa_client.v2.types import DataType
from kuksa_client.v2.types import Datapoint


@pytest.mark.parametrize(
    "data_type, value",
    [
        (DataType.STRING, "hello"),
        (DataType.BOOLEAN, True),
        (DataType.INT8, -5),
        (DataType.INT16, -500),
        (DataType.INT32, -70000),
        (DataType.INT64, -9000000000),
        (DataType.UINT8, 200),
        (DataType.UINT16, 60000),
        (DataType.UINT32, 4000000000),
        (DataType.UINT64, 9000000000),
        (DataType.FLOAT, 1.5),
        (DataType.DOUBLE, 1.5),
        (DataType.STRING_ARRAY, ["a", "b"]),
        (DataType.BOOLEAN_ARRAY, [True, False]),
        (DataType.INT8_ARRAY, [-1, 2]),
        (DataType.INT32_ARRAY, [1, -2]),
        (DataType.INT64_ARRAY, [1, -2]),
        (DataType.UINT8_ARRAY, [1, 2]),
        (DataType.UINT32_ARRAY, [1, 2]),
        (DataType.UINT64_ARRAY, [1, 2]),
        (DataType.FLOAT_ARRAY, [1.5, 2.5]),
        (DataType.DOUBLE_ARRAY, [1.5, 2.5]),
    ],
)
def test_value_round_trip(data_type, value):
    message = codec.to_proto_value(value, data_type)
    assert codec.from_proto_value(message) == value


def test_value_none_round_trip():
    message = codec.to_proto_value(None, DataType.STRING)
    assert codec.from_proto_value(message) is None


def test_datapoint_round_trip():
    timestamp = datetime.datetime(2024, 1, 17, 10, 2, 27, tzinfo=datetime.timezone.utc)
    dp = Datapoint(value=42.0, timestamp=timestamp)
    message = codec.to_proto_datapoint(dp, DataType.FLOAT)
    decoded = codec.from_proto_datapoint(message)
    assert decoded.value == 42.0
    assert decoded.timestamp == timestamp


def test_datapoint_no_value():
    message = codec.to_proto_datapoint(Datapoint(value=None), DataType.FLOAT)
    decoded = codec.from_proto_datapoint(message)
    assert decoded.value is None
    assert decoded.timestamp is None


def test_unspecified_data_type_raises():
    with pytest.raises(ValueError):
        codec.to_proto_value(1, DataType.UNSPECIFIED)


def test_type_mismatch_raises():
    with pytest.raises(TypeError):
        codec.to_proto_value(1, DataType.STRING)
    with pytest.raises(TypeError):
        codec.to_proto_value("x", DataType.INT32)
    with pytest.raises(TypeError):
        codec.to_proto_value(True, DataType.INT32)
    with pytest.raises(TypeError):
        codec.to_proto_value("x", DataType.INT32_ARRAY)


def test_python_type_map():
    assert codec.data_type_to_python_type(DataType.FLOAT) is float
    assert codec.data_type_to_python_type(DataType.STRING) is str
    assert codec.data_type_to_python_type(DataType.BOOLEAN) is bool
    assert codec.data_type_to_python_type(DataType.INT32_ARRAY) is list


def test_metadata_from_proto():
    from kuksa.val.v2 import types_pb2

    message = types_pb2.Metadata(
        path="Vehicle.Speed",
        id=42,
        data_type=types_pb2.DATA_TYPE_FLOAT,
        entry_type=types_pb2.ENTRY_TYPE_SENSOR,
        description="Vehicle speed.",
        unit="km/h",
        min=types_pb2.Value(float=0.0),
        max=types_pb2.Value(float=300.0),
    )
    metadata = codec.from_proto_metadata(message)
    assert metadata.path == "Vehicle.Speed"
    assert metadata.id == 42
    assert metadata.data_type == DataType.FLOAT
    assert metadata.unit == "km/h"
    assert metadata.value_restriction.min == 0.0
    assert metadata.value_restriction.max == 300.0

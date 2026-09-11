# /********************************************************************************
# * Copyright (c) 2026 Contributors to the Eclipse Foundation
# *
# * SPDX-License-Identifier: Apache-2.0
# ********************************************************************************/

import pytest

from kuksa_client.v2 import DataType
from kuksa_client.v2 import KuksaClient
from kuksa_client.v2 import coerce_value
from kuksa_client.v2 import coerce_values
from kuksa_client.v2.aio import KuksaClient as AioKuksaClient


@pytest.mark.parametrize(
    "text,expected",
    [
        ("true", True),
        ("TRUE", True),
        ("t", True),
        ("1", True),
        ("yes", True),
        ("on", True),
        ("false", False),
        ("FALSE", False),
        ("f", False),
        ("0", False),
        ("no", False),
        ("off", False),
        (" false ", False),
    ],
)
def test_coerce_bool(text, expected):
    assert coerce_value(text, DataType.BOOLEAN) is expected


def test_coerce_bool_invalid():
    with pytest.raises(ValueError):
        coerce_value("not-a-bool", DataType.BOOLEAN)


@pytest.mark.parametrize(
    "data_type", [DataType.INT8, DataType.INT32, DataType.INT64, DataType.UINT32]
)
def test_coerce_int(data_type):
    assert coerce_value("42", data_type) == 42


@pytest.mark.parametrize("data_type", [DataType.FLOAT, DataType.DOUBLE])
def test_coerce_float(data_type):
    assert coerce_value("42.5", data_type) == 42.5


def test_coerce_string():
    assert coerce_value("hello", DataType.STRING) == "hello"


def test_coerce_unspecified_passthrough():
    assert coerce_value("hello", DataType.UNSPECIFIED) == "hello"
    assert coerce_value("hello", None) == "hello"


def test_coerce_non_string_passthrough():
    assert coerce_value(42, DataType.FLOAT) == 42
    assert coerce_value(True, DataType.BOOLEAN) is True
    assert coerce_value([1, 2], DataType.INT32_ARRAY) == [1, 2]


def test_coerce_int_array():
    assert coerce_value("[1,2,3]", DataType.INT32_ARRAY) == [1, 2, 3]
    assert coerce_value("1,2,3", DataType.INT32_ARRAY) == [1, 2, 3]


def test_coerce_float_array():
    assert coerce_value("[1.5, 2.5]", DataType.FLOAT_ARRAY) == [1.5, 2.5]


def test_coerce_bool_array():
    assert coerce_value("[true,false]", DataType.BOOLEAN_ARRAY) == [True, False]


def test_coerce_string_array():
    assert coerce_value("['a','b']", DataType.STRING_ARRAY) == ["a", "b"]
    assert coerce_value('["a","b"]', DataType.STRING_ARRAY) == ["a", "b"]


def test_coerce_values():
    data_types = {
        "Vehicle.Speed": DataType.FLOAT,
        "Vehicle.ADAS.ABS.IsActive": DataType.BOOLEAN,
        "Vehicle.OBD.DTCList": DataType.STRING_ARRAY,
    }
    result = coerce_values(
        {
            "Vehicle.Speed": "42.5",
            "Vehicle.ADAS.ABS.IsActive": "true",
            "Vehicle.OBD.DTCList": "['a','b']",
        },
        data_types,
    )
    assert result == {
        "Vehicle.Speed": 42.5,
        "Vehicle.ADAS.ABS.IsActive": True,
        "Vehicle.OBD.DTCList": ["a", "b"],
    }


def test_coerce_values_missing_type():
    with pytest.raises(ValueError):
        coerce_values({"Vehicle.Speed": "42"}, {})


def test_sync_client_coerce_updates():
    client = KuksaClient(ensure_startup_connection=False)
    client._resolve_data_types = lambda paths: {
        path: DataType.BOOLEAN for path in paths
    }
    assert client.coerce_updates({"Vehicle.ParkingBrake.IsEngaged": "false"}) == {
        "Vehicle.ParkingBrake.IsEngaged": False
    }


@pytest.mark.asyncio
async def test_async_client_coerce_updates():
    client = AioKuksaClient(ensure_startup_connection=False)

    async def resolve(paths):
        return {path: DataType.BOOLEAN for path in paths}

    client._resolve_data_types = resolve
    assert await client.coerce_updates({"Vehicle.ParkingBrake.IsEngaged": "false"}) == {
        "Vehicle.ParkingBrake.IsEngaged": False
    }

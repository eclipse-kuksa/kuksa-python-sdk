# /********************************************************************************
# * Copyright (c) 2026 Contributors to the Eclipse Foundation
# *
# * SPDX-License-Identifier: Apache-2.0
# ********************************************************************************/

import pytest
import pytest_asyncio

from kuksa_client.v2 import DataType
from kuksa_client.v2 import Datapoint
from kuksa_client.v2 import EntryType
from kuksa_client.v2 import NotFound
from kuksa_client.v2.aio import KuksaClient


@pytest_asyncio.fixture
async def client(server):
    async with KuksaClient("127.0.0.1", server) as client:
        yield client


@pytest.mark.asyncio
async def test_get_missing_raises_not_found(client):
    with pytest.raises(NotFound):
        await client.get("Vehicle.DoesNotExist")


@pytest.mark.asyncio
async def test_get_no_value_returns_none(client):
    datapoint = await client.get("Vehicle.Speed")
    assert datapoint.value is None


@pytest.mark.asyncio
async def test_set_and_get_round_trip(client):
    await client.set({"Vehicle.Speed": 42.0})
    datapoint = await client.get("Vehicle.Speed")
    assert datapoint.value == 42.0


@pytest.mark.asyncio
async def test_set_with_datapoint(client):
    await client.set({"Vehicle.Speed": Datapoint(43.0)})
    assert (await client.get("Vehicle.Speed")).value == 43.0


@pytest.mark.asyncio
async def test_set_with_explicit_data_type(client):
    await client.set({"Vehicle.Speed": 44.0}, data_type=DataType.FLOAT)
    assert (await client.get("Vehicle.Speed")).value == 44.0


@pytest.mark.asyncio
async def test_get_many(client):
    await client.set({"Vehicle.Speed": 1.0, "Vehicle.ADAS.ABS.IsActive": True})
    values = await client.get(["Vehicle.Speed", "Vehicle.ADAS.ABS.IsActive"])
    assert values["Vehicle.Speed"].value == 1.0
    assert values["Vehicle.ADAS.ABS.IsActive"].value is True


@pytest.mark.asyncio
async def test_get_many_all_or_nothing(client):
    with pytest.raises(NotFound):
        await client.get(["Vehicle.Speed", "Vehicle.DoesNotExist"])


@pytest.mark.asyncio
async def test_get_metadata(client):
    metadata = await client.get_metadata("Vehicle.Speed")
    assert metadata.data_type == DataType.FLOAT
    assert metadata.entry_type == EntryType.SENSOR


@pytest.mark.asyncio
async def test_list_metadata_pattern(client):
    metadatas = await client.list_metadata("Vehicle.Cabin.Sunroof.*")
    paths = {m.path for m in metadatas}
    assert paths == {"Vehicle.Cabin.Sunroof.Position", "Vehicle.Cabin.Sunroof.Switch"}


@pytest.mark.asyncio
async def test_expand_by_entry_type(client):
    sensors = await client.expand("Vehicle.**", entry_type=EntryType.SENSOR)
    assert sensors == ["Vehicle.ADAS.ABS.IsActive", "Vehicle.Speed"]


@pytest.mark.asyncio
async def test_missing_signals(client):
    missing = await client.missing_signals(["Vehicle.Speed", "Vehicle.DoesNotExist"])
    assert missing == {"Vehicle.DoesNotExist"}


@pytest.mark.asyncio
async def test_subscribe(client):
    await client.set({"Vehicle.Speed": 10.0})
    iterator = client.subscribe(["Vehicle.Speed"])
    first = await iterator.__anext__()
    assert first["Vehicle.Speed"].value == 10.0

    await client.set({"Vehicle.Speed": 20.0})
    second = await iterator.__anext__()
    assert second["Vehicle.Speed"].value == 20.0
